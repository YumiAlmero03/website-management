from __future__ import annotations

import time
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

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


class InstagramGraphAdapter(BasePublisherAdapter):
    """Official Instagram Graph API (v27.0) adapter for Business and Creator accounts."""

    allowed_hosts = frozenset({"graph.facebook.com", "www.facebook.com"})
    capabilities = PublisherCapabilities(
        platform_key="instagram",
        display_name="Instagram",
        priority_tier=1,
        supports_official_api=True,
        supports_manual_fallback=True,
        supports_oauth=True,
        supports_pkce=False,
        supports_refresh=True,
        supports_target_selection=True,
        supports_text_post=False,
        supports_link_post=False,
        supports_image_post=True,
        supports_native_schedule=False,
        supports_reconcile=True,
        requires_media=True,
        requires_external_media_url=True,
        requires_paid_api_ack=False,
        required_scopes=(
            "instagram_basic",
            "instagram_content_publish",
            "pages_read_engagement",
        ),
        api_version="v27.0",
        limitations_summary=(
            "Business or Creator accounts linked to a Facebook Page only (Personal accounts "
            "unsupported). Feed posts require compliant JPEG media at a public HTTPS URL; caption "
            "links are non-clickable."
        ),
        rate_limit_summary="Dynamic 24h content_publishing_limit (typically 50-100 posts/day).",
    )

    def validate_credentials(self, credentials: dict[str, str | None]) -> None:
        token = (credentials.get("access_token") or "").strip()
        if not token:
            raise PublisherError(
                "Instagram / Meta Access Token is required for API publishing.",
                error_category="invalid_credentials",
                code="IG_TOKEN_MISSING",
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
                "Meta App ID is required before starting Instagram Graph OAuth.",
                error_category="invalid_credentials",
                code="IG_APP_ID_MISSING",
            )
        chosen = tuple(scopes or self.capabilities.required_scopes)
        params = urlencode(
            {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "response_type": "code",
                "scope": ",".join(chosen),
            }
        )
        return OAuthStartResult(
            authorization_url=f"https://www.facebook.com/{self.api_version}/dialog/oauth?{params}",
            state=state,
            requested_scopes=chosen,
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
                "Meta App ID and App Secret are required for Instagram OAuth exchange.",
                error_category="invalid_credentials",
                code="IG_APP_CREDENTIALS_MISSING",
            )
        resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        token = str(resp.json().get("access_token") or "").strip()
        expires_at = utc_now_naive() + timedelta(hours=2)

        long_resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": token,
            },
        )
        if long_resp.status_code == 200:
            ldata = long_resp.json()
            token = str(ldata.get("access_token") or token).strip()
            expires_at = utc_now_naive() + timedelta(
                seconds=int(ldata.get("expires_in") or 5184000)
            )

        acct_resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/me/accounts",
            params={
                "fields": (
                    "id,name,instagram_business_account{id,username,name,profile_picture_url}"
                ),
                "access_token": token,
            },
        )
        if acct_resp.status_code != 200:
            raise classify_http_failure(acct_resp)

        targets: list[TargetResourceOption] = []
        for page in acct_resp.json().get("data") or []:
            ig = page.get("instagram_business_account") if isinstance(page, dict) else None
            if not isinstance(ig, dict) or not ig.get("id"):
                continue
            uname = str(ig.get("username") or ig["id"])
            targets.append(
                TargetResourceOption(
                    target_id=str(ig["id"]),
                    name=f"@{uname}" if not uname.startswith("@") else uname,
                    account_type="instagram_professional",
                    profile_url=f"https://www.instagram.com/{uname.lstrip('@')}/",
                    metadata={
                        "linked_page_id": page.get("id"),
                        "linked_page_name": page.get("name"),
                    },
                )
            )
        selected = targets[0] if len(targets) == 1 else None
        return OAuthCallbackResult(
            access_token=token,
            refresh_token=token,
            token_expires_at=expires_at,
            granted_scopes=list(self.capabilities.required_scopes),
            external_account_id=selected.target_id if selected else None,
            external_username=selected.name if selected else None,
            profile_url=selected.profile_url if selected else None,
            account_type="instagram_professional",
            target_resource_id=selected.target_id if selected else None,
            target_resource_name=selected.name if selected else None,
            available_targets=targets,
        )

    def refresh_credentials(
        self, *, credentials: dict[str, str | None]
    ) -> OAuthTokenRefreshResult:
        app_id = (credentials.get("app_id") or "").strip()
        app_secret = (credentials.get("app_secret") or "").strip()
        token = (credentials.get("access_token") or "").strip()
        if not app_id or not app_secret or not token:
            raise PublisherError(
                "App ID, App Secret, and Access Token required to refresh Instagram Graph token.",
                error_category="expired_credentials",
                code="IG_REFRESH_CREDS_MISSING",
            )
        resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": token,
            },
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        data = resp.json()
        new_tok = str(data.get("access_token") or "").strip()
        return OAuthTokenRefreshResult(
            access_token=new_tok,
            refresh_token=new_tok,
            token_expires_at=utc_now_naive()
            + timedelta(seconds=int(data.get("expires_in") or 5184000)),
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
        ig_id = (target_resource_id or external_account_id or "").strip()
        if not ig_id:
            raise PublisherError(
                "Instagram Professional User ID (ig_user_id) is required to verify.",
                error_category="unsupported_account",
                code="IG_ACCOUNT_ID_MISSING",
            )

        info_resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/{ig_id}",
            params={"fields": "id,username,name,account_type", "access_token": token},
        )
        if info_resp.status_code != 200:
            raise classify_http_failure(info_resp)
        info = info_resp.json()
        acct_type = str(info.get("account_type") or "BUSINESS").upper()
        if acct_type == "PERSONAL":
            raise PublisherError(
                "Personal Instagram accounts cannot publish via API. "
                "Convert to Business or Creator.",
                error_category="unsupported_account",
                code="IG_PERSONAL_UNSUPPORTED",
            )

        quota_info: dict[str, Any] = {}
        limit_resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/{ig_id}/content_publishing_limit",
            params={"fields": "config,quota_usage", "access_token": token},
        )
        if limit_resp.status_code == 200:
            ldata = (limit_resp.json().get("data") or [{}])[0]
            if isinstance(ldata, dict):
                quota_info = ldata

        username = str(info.get("username") or ig_id)
        return AccountVerifyResult(
            connected=True,
            connection_status="connected",
            eligibility_status="eligible",
            eligibility_notes=(
                f"Verified Instagram {acct_type.title()} account @{username} linked to Meta App."
            ),
            account_type=f"instagram_{acct_type.lower()}",
            external_account_id=str(info.get("id") or ig_id),
            external_username=username,
            external_display_name=info.get("name") or username,
            profile_url=f"https://www.instagram.com/{username.lstrip('@')}/",
            target_resource_id=str(info.get("id") or ig_id),
            target_resource_name=f"@{username}",
            granted_scopes=list(self.capabilities.required_scopes),
            metadata={"publishing_limit": quota_info},
        )

    def publish_post(self, request: PublishRequest) -> PublishResult:
        self.validate_credentials(request.credentials)
        token = (request.credentials.get("access_token") or "").strip()
        ig_id = (request.target_resource_id or request.external_account_id or "").strip()
        if not ig_id:
            raise PublisherError(
                "Instagram Professional User ID is required before publishing.",
                error_category="unsupported_account",
                code="IG_ACCOUNT_ID_MISSING",
            )
        if not request.media:
            raise PublisherError(
                "Instagram requires an image or video attachment for feed posts.",
                error_category="invalid_media",
                code="IG_MEDIA_REQUIRED",
            )
        media_urls = [m.public_url or m.source_url for m in request.media]
        if any(not url for url in media_urls):
            raise PublisherError(
                "Instagram API requires publicly accessible HTTPS media URLs.",
                error_category="invalid_media",
                code="IG_PUBLIC_MEDIA_URL_REQUIRED",
            )

        if len(request.media) == 1:
            primary = request.media[0]
            container_payload: dict[str, Any] = {
                "image_url": primary.public_url or primary.source_url,
                "caption": request.assembled_content,
                "access_token": token,
            }
            if primary.alt_text:
                container_payload["alt_text"] = primary.alt_text[:250]
            creation_id = self._create_and_wait_container(
                ig_id=ig_id,
                payload=container_payload,
                token=token,
            )
        else:
            children_ids: list[str] = []
            for m in request.media[:10]:
                child_id = self._create_and_wait_container(
                    ig_id=ig_id,
                    payload={
                        "image_url": m.public_url or m.source_url,
                        "is_carousel_item": "true",
                        "access_token": token,
                    },
                    token=token,
                )
                children_ids.append(child_id)
            creation_id = self._create_and_wait_container(
                ig_id=ig_id,
                payload={
                    "media_type": "CAROUSEL",
                    "children": ",".join(children_ids),
                    "caption": request.assembled_content,
                    "access_token": token,
                },
                token=token,
            )

        pub_resp = self.http.request(
            "POST",
            f"https://graph.facebook.com/{self.api_version}/{ig_id}/media_publish",
            data={"creation_id": creation_id, "access_token": token},
            is_publish_mutation=True,
        )
        if pub_resp.status_code not in (200, 201):
            raise classify_http_failure(pub_resp, is_publish_mutation=True)
        media_id = str(pub_resp.json().get("id") or "").strip() or None
        permalink = self._fetch_permalink(media_id=media_id, token=token)
        return PublishResult(
            external_post_id=media_id,
            published_url=permalink,
            http_status=pub_resp.status_code,
            verification_status="api_verified",
            response_summary={
                "media_id": media_id,
                "creation_id": creation_id,
                "permalink": permalink,
            },
        )

    def _create_and_wait_container(
        self, *, ig_id: str, payload: dict[str, Any], token: str
    ) -> str:
        c_resp = self.http.request(
            "POST",
            f"https://graph.facebook.com/{self.api_version}/{ig_id}/media",
            data=payload,
        )
        if c_resp.status_code not in (200, 201):
            raise classify_http_failure(c_resp)
        creation_id = str(c_resp.json().get("id") or "").strip()
        if not creation_id:
            raise PublisherError(
                "Instagram container creation did not return a creation_id.",
                error_category="invalid_media",
                code="IG_CONTAINER_FAILED",
            )
        for _ in range(5):
            st_resp = self.http.request(
                "GET",
                f"https://graph.facebook.com/{self.api_version}/{creation_id}",
                params={"fields": "status_code,status", "access_token": token},
            )
            if st_resp.status_code == 200:
                code = str(st_resp.json().get("status_code") or "FINISHED").upper()
                if code == "FINISHED":
                    return creation_id
                if code in {"ERROR", "EXPIRED"}:
                    status_msg = st_resp.json().get("status")
                    raise PublisherError(
                        f"Instagram media processing failed ({code}: {status_msg}).",
                        error_category="invalid_media",
                        code=f"IG_MEDIA_{code}",
                    )
            time.sleep(0.2)
        return creation_id

    def _fetch_permalink(self, *, media_id: str | None, token: str) -> str | None:
        if not media_id:
            return None
        try:
            resp = self.http.request(
                "GET",
                f"https://graph.facebook.com/{self.api_version}/{media_id}",
                params={"fields": "permalink", "access_token": token},
            )
            if resp.status_code == 200:
                link = resp.json().get("permalink")
                if isinstance(link, str) and link.strip():
                    return link.strip()
        except PublisherError:
            pass
        return None

    def reconcile_publication(
        self,
        *,
        request: PublishRequest,
        external_post_id: str | None = None,
    ) -> ReconcileResult:
        token = (request.credentials.get("access_token") or "").strip()
        ig_id = (request.target_resource_id or request.external_account_id or "").strip()
        if not token or not ig_id:
            return ReconcileResult(exists=False, indeterminate=True)
        resp = self.http.request(
            "GET",
            f"https://graph.facebook.com/{self.api_version}/{ig_id}/media",
            params={"fields": "id,caption,permalink", "limit": 10, "access_token": token},
        )
        if resp.status_code != 200:
            return ReconcileResult(exists=False, indeterminate=True)
        needle = request.caption.strip()[:100]
        for row in resp.json().get("data") or []:
            if needle and needle in str(row.get("caption") or ""):
                return ReconcileResult(
                    exists=True,
                    external_post_id=str(row.get("id") or ""),
                    published_url=row.get("permalink"),
                    note="Confirmed Instagram media in recent feed items.",
                )
        return ReconcileResult(
            exists=False,
            indeterminate=False,
            note="Not found in recent IG media.",
        )
