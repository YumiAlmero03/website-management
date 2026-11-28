from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.models.base import utc_now_naive
from app.services.publishers.base import (
    AccountVerifyResult,
    BasePublisherAdapter,
    OAuthCallbackResult,
    OAuthStartResult,
    OAuthTokenRefreshResult,
    PublisherCapabilities,
    PublishRequest,
    PublishResult,
    ReconcileResult,
    TargetResourceOption,
    classify_http_failure,
)
from app.services.publishers.exceptions import PublisherError


class FacebookPagesAdapter(BasePublisherAdapter):
    """Official Meta Graph API (v27.0) adapter for Facebook Pages only."""

    allowed_hosts = frozenset({"graph.facebook.com", "www.facebook.com"})
    capabilities = PublisherCapabilities(
        platform_key="facebook",
        display_name="Facebook",
        priority_tier=1,
        supports_official_api=True,
        supports_manual_fallback=True,
        supports_oauth=True,
        supports_pkce=False,
        supports_refresh=True,
        supports_target_selection=True,
        supports_text_post=True,
        supports_link_post=True,
        supports_image_post=True,
        supports_native_schedule=True,
        supports_reconcile=True,
        requires_media=False,
        requires_external_media_url=False,
        requires_paid_api_ack=False,
        required_scopes=("pages_manage_posts", "pages_read_engagement", "pages_show_list"),
        api_version="v27.0",
        limitations_summary=(
            "Facebook Pages only (personal profiles unsupported). Page Access Token via "
            "/me/accounts required. App Review needed outside Admin/Developer/Tester roles."
        ),
        rate_limit_summary="Meta Business Use Case Graph API quota; ~25-100 Page posts/day.",
    )

    def validate_credentials(self, credentials: dict[str, str | None]) -> None:
        token = (credentials.get("access_token") or "").strip()
        if not token:
            raise PublisherError(
                "Facebook Page Access Token is required for API publishing.",
                error_category="invalid_credentials",
                code="FB_TOKEN_MISSING",
            )

    def build_oauth_authorize_url(
        self,
        *,
        credentials: dict[str, str | None],
        redirect_uri: str,
        state: str,
        scopes: list[str] | None = None,
    ) -> OAuthStartResult:
        app_id = (credentials.get("app_id") or "").strip()
        if not app_id:
            raise PublisherError(
                "Meta App ID is required before starting Facebook OAuth.",
                error_category="invalid_credentials",
                code="FB_APP_ID_MISSING",
            )
        chosen_scopes = tuple(scopes or self.capabilities.required_scopes)
        params = urlencode(
            {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "response_type": "code",
                "scope": ",".join(chosen_scopes),
            }
        )
        return OAuthStartResult(
            authorization_url=f"https://www.facebook.com/{self.api_version}/dialog/oauth?{params}",
            state=state,
            requested_scopes=chosen_scopes,
        )

    def exchange_oauth_code(
        self,
        *,
        credentials: dict[str, str | None],
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> OAuthCallbackResult:
        app_id = (credentials.get("app_id") or "").strip()
        app_secret = (credentials.get("app_secret") or "").strip()
        if not app_id or not app_secret:
            raise PublisherError(
                "Meta App ID and App Secret are required to exchange OAuth code.",
                error_category="invalid_credentials",
                code="FB_APP_CREDENTIALS_MISSING",
            )

        token_resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if token_resp.status_code != 200:
            raise classify_http_failure(token_resp)
        short_token = str(token_resp.json().get("access_token") or "").strip()
        if not short_token:
            raise PublisherError(
                "Meta OAuth exchange returned empty access token.",
                error_category="invalid_credentials",
                code="FB_EMPTY_TOKEN",
            )

        # Exchange for ~60-day long-lived user token, then list Pages (/me/accounts)
        long_resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            },
        )
        user_token = short_token
        expires_at = utc_now_naive() + timedelta(hours=2)
        if long_resp.status_code == 200:
            long_json = long_resp.json()
            user_token = str(long_json.get("access_token") or short_token).strip()
            exp_sec = int(long_json.get("expires_in") or 5184000)
            expires_at = utc_now_naive() + timedelta(seconds=exp_sec)

        accounts_resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/me/accounts",
            params={
                "fields": "id,name,category,link,tasks,access_token",
                "access_token": user_token,
            },
        )
        if accounts_resp.status_code != 200:
            raise classify_http_failure(accounts_resp)
        pages_raw = accounts_resp.json().get("data") or []
        targets: list[TargetResourceOption] = []
        for page in pages_raw:
            if not isinstance(page, dict) or not page.get("id"):
                continue
            targets.append(
                TargetResourceOption(
                    target_id=str(page["id"]),
                    name=str(page.get("name") or page["id"]),
                    account_type="facebook_page",
                    profile_url=page.get("link"),
                    access_token_override=page.get("access_token"),
                    metadata={
                        "category": page.get("category"),
                        "tasks": page.get("tasks") or [],
                    },
                )
            )
        selected = targets[0] if len(targets) == 1 else None
        effective_token = (
            selected.access_token_override
            if selected and selected.access_token_override
            else user_token
        )
        return OAuthCallbackResult(
            access_token=effective_token,
            refresh_token=user_token,
            token_expires_at=None if selected else expires_at,
            granted_scopes=list(self.capabilities.required_scopes),
            external_account_id=selected.target_id if selected else None,
            external_display_name=selected.name if selected else None,
            profile_url=selected.profile_url if selected else None,
            account_type="facebook_page",
            target_resource_id=selected.target_id if selected else None,
            target_resource_name=selected.name if selected else None,
            available_targets=targets,
            access_tier="dev_mode_or_approved",
        )

    def refresh_credentials(
        self, *, credentials: dict[str, str | None]
    ) -> OAuthTokenRefreshResult:
        app_id = (credentials.get("app_id") or "").strip()
        app_secret = (credentials.get("app_secret") or "").strip()
        exchange_token = (
            credentials.get("refresh_token") or credentials.get("access_token") or ""
        ).strip()
        if not app_id or not app_secret or not exchange_token:
            raise PublisherError(
                "App ID, App Secret, and an active Meta token are required to refresh.",
                error_category="expired_credentials",
                code="FB_REFRESH_CREDS_MISSING",
            )
        resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": exchange_token,
            },
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        payload = resp.json()
        new_token = str(payload.get("access_token") or "").strip()
        if not new_token:
            raise PublisherError(
                "Meta token refresh returned empty token.",
                error_category="expired_credentials",
                code="FB_REFRESH_EMPTY",
            )
        exp_sec = int(payload.get("expires_in") or 5184000)
        return OAuthTokenRefreshResult(
            access_token=new_token,
            refresh_token=new_token,
            token_expires_at=utc_now_naive() + timedelta(seconds=exp_sec),
        )

    def verify_connection(
        self,
        *,
        credentials: dict[str, str | None],
        external_account_id: str | None = None,
        target_resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AccountVerifyResult:
        self.validate_credentials(credentials)
        token = (credentials.get("access_token") or "").strip()
        page_id = (target_resource_id or external_account_id or "me").strip()

        page_resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/{page_id}",
            params={
                "fields": "id,name,link,category,fan_count",
                "access_token": token,
            },
        )
        if page_resp.status_code != 200:
            raise classify_http_failure(page_resp)
        page_data = page_resp.json()
        resolved_id = str(page_data.get("id") or page_id)
        resolved_name = str(page_data.get("name") or resolved_id)
        profile_url = page_data.get("link") or f"https://www.facebook.com/{resolved_id}"

        # Reject personal profiles explicitly if category absent on /me user node
        is_user_node = "category" not in page_data and page_id == "me"
        if is_user_node:
            raise PublisherError(
                "Token belongs to a personal Facebook user rather than a Facebook Page. "
                "Select a managed Facebook Page or use Manual Publishing.",
                error_category="unsupported_account",
                code="FB_PERSONAL_PROFILE_UNSUPPORTED",
            )

        granted_scopes: list[str] = []
        missing_scopes: list[str] = []
        expires_at: Any = None
        app_id = (credentials.get("app_id") or "").strip()
        app_secret = (credentials.get("app_secret") or "").strip()
        if app_id and app_secret:
            dbg = self.http.request(
                "GET",
                f"https://graph.facebook.com/{self.api_version}/debug_token",
                params={
                    "input_token": token,
                    "access_token": f"{app_id}|{app_secret}",
                },
            )
            if dbg.status_code == 200:
                ddata = (dbg.json() or {}).get("data") or {}
                if not ddata.get("is_valid", True):
                    raise PublisherError(
                        "Facebook Page token failed validation (is_valid=false).",
                        error_category="expired_credentials",
                        code="FB_TOKEN_INVALID",
                    )
                granted_scopes = [str(s) for s in (ddata.get("scopes") or [])]
                missing_scopes = [
                    req
                    for req in ("pages_manage_posts", "pages_read_engagement")
                    if req not in granted_scopes
                ]
                exp_ts = int(ddata.get("expires_at") or 0)
                if exp_ts > 0:
                    expires_at = utc_now_naive()
                    from datetime import UTC, datetime

                    expires_at = datetime.fromtimestamp(exp_ts, tz=UTC).replace(tzinfo=None)

        status_val = "missing_permissions" if missing_scopes else "connected"
        elig_val = "restricted" if missing_scopes else "eligible"
        return AccountVerifyResult(
            connected=not missing_scopes,
            connection_status=status_val,
            eligibility_status=elig_val,
            eligibility_notes=(
                "Missing permissions: " + ", ".join(missing_scopes)
                if missing_scopes
                else (
                    f"Verified Facebook Page '{resolved_name}' "
                    f"({page_data.get('category') or 'Page'})."
                )
            ),
            account_type="facebook_page",
            external_account_id=resolved_id,
            external_display_name=resolved_name,
            profile_url=profile_url,
            target_resource_id=resolved_id,
            target_resource_name=resolved_name,
            granted_scopes=granted_scopes,
            missing_scopes=missing_scopes,
            token_expires_at=expires_at,
            metadata={"category": page_data.get("category")},
        )

    def publish_post(self, request: PublishRequest) -> PublishResult:
        self.validate_credentials(request.credentials)
        token = (request.credentials.get("access_token") or "").strip()
        page_id = (request.target_resource_id or request.external_account_id or "").strip()
        if not page_id:
            raise PublisherError(
                "Facebook Page ID is required before publishing.",
                error_category="unsupported_account",
                code="FB_PAGE_ID_MISSING",
            )

        message = request.assembled_content.strip()
        if request.media:
            primary = request.media[0]
            endpoint = f"https://graph.facebook.com/{self.api_version}/{page_id}/photos"
            data = {"caption": message, "access_token": token, "published": "true"}
            files: dict[str, Any] | None = None
            if primary.file_path:
                root = Settings().resolved_storage_root.resolve()
                fpath = (root / primary.file_path).resolve()
                if str(fpath).startswith(str(root)) and fpath.is_file():
                    files = {
                        "source": (
                            Path(primary.file_path).name,
                            fpath.read_bytes(),
                            primary.mime_type or "image/jpeg",
                        )
                    }
            if files is None:
                media_url = primary.public_url or primary.source_url
                if not media_url:
                    raise PublisherError(
                        "Facebook photo post requires a local image or reachable URL.",
                        error_category="invalid_media",
                        code="FB_MEDIA_UNAVAILABLE",
                    )
                data["url"] = media_url
            resp = self.http.request(
                "POST",
                endpoint,
                data=data,
                files=files,
                is_publish_mutation=True,
            )
        else:
            endpoint = f"https://graph.facebook.com/{self.api_version}/{page_id}/feed"
            payload: dict[str, Any] = {
                "message": message,
                "access_token": token,
                "published": True,
            }
            if request.source_url:
                payload["link"] = request.source_url
            resp = self.http.request(
                "POST",
                endpoint,
                json=payload,
                is_publish_mutation=True,
            )

        if resp.status_code not in (200, 201):
            raise classify_http_failure(resp, is_publish_mutation=True)

        res_json = resp.json() if resp.content else {}
        ext_id = str(res_json.get("post_id") or res_json.get("id") or "").strip() or None
        pub_url = self._fetch_permalink(ext_id=ext_id, page_id=page_id, token=token)
        return PublishResult(
            external_post_id=ext_id,
            published_url=pub_url,
            http_status=resp.status_code,
            verification_status="api_verified",
            response_summary={"id": ext_id, "permalink_url": pub_url},
        )

    def _fetch_permalink(
        self, *, ext_id: str | None, page_id: str, token: str
    ) -> str | None:
        if not ext_id:
            return None
        try:
            resp = self.http.request(
                "GET",
                f"https://graph.facebook.com/{self.api_version}/{ext_id}",
                params={"fields": "permalink_url", "access_token": token},
            )
            if resp.status_code == 200:
                link = resp.json().get("permalink_url")
                if isinstance(link, str) and link.strip():
                    return link.strip()
        except PublisherError:
            pass
        return f"https://www.facebook.com/{page_id}"

    def reconcile_publication(
        self,
        *,
        request: PublishRequest,
        external_post_id: str | None = None,
    ) -> ReconcileResult:
        token = (request.credentials.get("access_token") or "").strip()
        page_id = (request.target_resource_id or request.external_account_id or "").strip()
        if not token or not page_id:
            return ReconcileResult(
                exists=False, indeterminate=True, note="Missing Page credentials to reconcile."
            )
        if external_post_id:
            resp = self.http.request(
                "GET",
                f"https://graph.facebook.com/{self.api_version}/{external_post_id}",
                params={"fields": "id,permalink_url", "access_token": token},
            )
            if resp.status_code == 200:
                data = resp.json()
                return ReconcileResult(
                    exists=True,
                    external_post_id=str(data.get("id") or external_post_id),
                    published_url=data.get("permalink_url"),
                    note="Confirmed post exists via Graph API.",
                )
        feed_resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/{page_id}/published_posts",
            params={"fields": "id,message,permalink_url", "limit": 10, "access_token": token},
        )
        if feed_resp.status_code != 200:
            return ReconcileResult(
                exists=False,
                indeterminate=True,
                note=f"Graph reconciliation HTTP {feed_resp.status_code}.",
            )
        needle = request.caption.strip()[:120]
        for row in feed_resp.json().get("data") or []:
            msg = str(row.get("message") or "")
            if needle and needle in msg:
                return ReconcileResult(
                    exists=True,
                    external_post_id=str(row.get("id") or ""),
                    published_url=row.get("permalink_url"),
                    note="Matched recent Page post after timeout.",
                )
        return ReconcileResult(
            exists=False,
            indeterminate=False,
            note="Not found in recent Facebook Page posts; safe to retry if intended.",
        )


def make_httpx_transport_for_test(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)
