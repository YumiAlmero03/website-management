from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

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


class LinkedInRestAdapter(BasePublisherAdapter):
    """Official LinkedIn REST Posts & Images API (/rest/posts, /rest/images)."""

    allowed_hosts = frozenset({"www.linkedin.com", "api.linkedin.com"})
    capabilities = PublisherCapabilities(
        platform_key="linkedin",
        display_name="LinkedIn",
        priority_tier=2,
        supports_official_api=True,
        supports_manual_fallback=True,
        supports_oauth=True,
        supports_pkce=False,
        supports_refresh=True,
        supports_target_selection=True,
        supports_text_post=True,
        supports_link_post=True,
        supports_image_post=True,
        supports_native_schedule=False,
        supports_reconcile=True,
        requires_media=False,
        requires_external_media_url=False,
        requires_paid_api_ack=False,
        required_scopes=("openid", "profile", "w_member_social"),
        api_version="202610",
        limitations_summary=(
            "w_member_social allows member profile posts via self-serve Share on LinkedIn. "
            "Company Page posting (w_organization_social) requires "
            "Community Management API approval."
        ),
        rate_limit_summary="24-hour UTC member and application rate limits.",
    )

    def _headers(
        self,
        token: str,
        *,
        content_type: str | None = "application/json",
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Linkedin-Version": self.api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def validate_credentials(self, credentials: dict[str, str | None]) -> None:
        if not (credentials.get("access_token") or "").strip():
            raise PublisherError(
                "LinkedIn OAuth 2.0 Access Token is required for API publishing.",
                error_category="invalid_credentials",
                code="LI_TOKEN_MISSING",
            )

    def build_oauth_authorize_url(
        self,
        *,
        credentials: dict[str, str | None],
        redirect_uri: str,
        state: str,
        scopes: list[str] | None = None,
    ) -> OAuthStartResult:
        client_id = (credentials.get("app_id") or "").strip()
        if not client_id:
            raise PublisherError(
                "LinkedIn Client ID (App ID field) is required to start OAuth.",
                error_category="invalid_credentials",
                code="LI_CLIENT_ID_MISSING",
            )
        chosen = tuple(scopes or self.capabilities.required_scopes)
        params = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": " ".join(chosen),
            }
        )
        return OAuthStartResult(
            authorization_url=f"https://www.linkedin.com/oauth/v2/authorization?{params}",
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
        client_id = (credentials.get("app_id") or "").strip()
        client_secret = (credentials.get("app_secret") or "").strip()
        if not client_id or not client_secret:
            raise PublisherError(
                "LinkedIn Client ID and Client Secret are required for OAuth exchange.",
                error_category="invalid_credentials",
                code="LI_CLIENT_CREDS_MISSING",
            )
        resp = self.http.request(
            "POST",
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        tdata = resp.json()
        token = str(tdata.get("access_token") or "").strip()
        refresh_tok = str(tdata.get("refresh_token") or "").strip() or None
        expires_at = utc_now_naive() + timedelta(seconds=int(tdata.get("expires_in") or 5184000))
        ref_exp = (
            utc_now_naive() + timedelta(seconds=int(tdata["refresh_token_expires_in"]))
            if tdata.get("refresh_token_expires_in")
            else None
        )
        granted = str(tdata.get("scope") or "").replace(",", " ").split()
        targets, person_info = self._discover_authors(token)
        selected = targets[0] if targets else None
        return OAuthCallbackResult(
            access_token=token,
            refresh_token=refresh_tok,
            token_expires_at=expires_at,
            refresh_token_expires_at=ref_exp,
            granted_scopes=granted or list(self.capabilities.required_scopes),
            external_account_id=selected.target_id if selected else person_info.get("sub"),
            external_display_name=selected.name if selected else person_info.get("name"),
            account_type="linkedin_member",
            target_resource_id=selected.target_id if selected else None,
            target_resource_name=selected.name if selected else None,
            available_targets=targets,
        )

    def refresh_credentials(
        self, *, credentials: dict[str, str | None]
    ) -> OAuthTokenRefreshResult:
        client_id = (credentials.get("app_id") or "").strip()
        client_secret = (credentials.get("app_secret") or "").strip()
        refresh_tok = (credentials.get("refresh_token") or "").strip()
        if not client_id or not client_secret or not refresh_tok:
            raise PublisherError(
                "Client ID, Client Secret, and Refresh Token are required for LinkedIn refresh.",
                error_category="expired_credentials",
                code="LI_REFRESH_MISSING",
            )
        resp = self.http.request(
            "POST",
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_tok,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        tdata = resp.json()
        return OAuthTokenRefreshResult(
            access_token=str(tdata.get("access_token") or "").strip(),
            refresh_token=str(tdata.get("refresh_token") or refresh_tok).strip(),
            token_expires_at=utc_now_naive()
            + timedelta(seconds=int(tdata.get("expires_in") or 5184000)),
        )

    def _discover_authors(self, token: str) -> tuple[list[TargetResourceOption], dict[str, Any]]:
        me_resp = self.http.request(
            "GET",
            "https://api.linkedin.com/v2/userinfo",
            headers=self._headers(token, content_type=None),
        )
        if me_resp.status_code != 200:
            raise classify_http_failure(me_resp)
        me = me_resp.json()
        targets: list[TargetResourceOption] = []
        sub = str(me.get("sub") or "").strip()
        if sub:
            person_urn = sub if sub.startswith("urn:li:") else f"urn:li:person:{sub}"
            targets.append(
                TargetResourceOption(
                    target_id=person_urn,
                    name=str(me.get("name") or person_urn),
                    account_type="linkedin_member",
                    profile_url="https://www.linkedin.com/feed/",
                )
            )
        # Optionally check organization admin targets if permitted
        acl_resp = self.http.request(
            "GET",
            "https://api.linkedin.com/rest/organizationAcls",
            headers=self._headers(token, content_type=None),
            params={"q": "roleAssignee", "state": "APPROVED"},
        )
        if acl_resp.status_code == 200:
            for item in acl_resp.json().get("elements") or []:
                org_urn = item.get("organization")
                if org_urn and str(item.get("role")) in {
                    "ADMINISTRATOR",
                    "CONTENT_ADMIN",
                    "DIRECT_SPONSORED_CONTENT_POSTER",
                }:
                    targets.append(
                        TargetResourceOption(
                            target_id=str(org_urn),
                            name=str(org_urn),
                            account_type="linkedin_organization",
                        )
                    )
        return targets, me

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
        targets, me = self._discover_authors(token)
        wanted = (target_resource_id or external_account_id or "").strip()
        chosen = next((t for t in targets if t.target_id == wanted), None) or (
            targets[0] if targets else None
        )
        return AccountVerifyResult(
            connected=chosen is not None,
            connection_status="connected" if chosen else "configured",
            eligibility_status="eligible" if chosen else "unknown",
            eligibility_notes=(
                f"Verified LinkedIn author '{chosen.name}' ({chosen.target_id})."
                if chosen
                else "No LinkedIn author URN resolved."
            ),
            account_type=chosen.account_type if chosen else "linkedin_member",
            external_account_id=chosen.target_id if chosen else me.get("sub"),
            external_display_name=chosen.name if chosen else me.get("name"),
            profile_url="https://www.linkedin.com/feed/",
            target_resource_id=chosen.target_id if chosen else None,
            target_resource_name=chosen.name if chosen else None,
            available_targets=targets,
            granted_scopes=list(self.capabilities.required_scopes),
        )

    def _upload_image(
        self,
        *,
        token: str,
        owner_urn: str,
        media_bytes: bytes,
        alt: str | None,
    ) -> str:
        init_resp = self.http.request(
            "POST",
            "https://api.linkedin.com/rest/images?action=initializeUpload",
            headers=self._headers(token),
            json={"initializeUploadRequest": {"owner": owner_urn}},
        )
        if init_resp.status_code not in (200, 201):
            raise classify_http_failure(init_resp)
        val = (init_resp.json() or {}).get("value") or {}
        upload_url = str(val.get("uploadUrl") or "").strip()
        image_urn = str(val.get("image") or "").strip()
        if not upload_url or not image_urn:
            raise PublisherError(
                "LinkedIn image initializeUpload returned missing uploadUrl or image URN.",
                error_category="invalid_media",
                code="LI_UPLOAD_INIT_INVALID",
            )
        put_resp = self.http.request(
            "PUT",
            upload_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            content=media_bytes,
        )
        if put_resp.status_code not in (200, 201, 204):
            raise classify_http_failure(put_resp)
        return image_urn

    def publish_post(self, request: PublishRequest) -> PublishResult:
        self.validate_credentials(request.credentials)
        token = (request.credentials.get("access_token") or "").strip()
        author_urn = (request.target_resource_id or request.external_account_id or "").strip()
        if not author_urn.startswith("urn:li:"):
            raise PublisherError(
                "Valid LinkedIn author URN (urn:li:person:... or "
                "urn:li:organization:...) required.",
                error_category="unsupported_account",
                code="LI_AUTHOR_URN_MISSING",
            )

        post_body: dict[str, Any] = {
            "author": author_urn,
            "commentary": request.assembled_content[:3000],
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if request.media:
            primary = request.media[0]
            if primary.file_path:
                root = Settings().resolved_storage_root.resolve()
                fpath = (root / primary.file_path).resolve()
                if str(fpath).startswith(str(root)) and fpath.is_file():
                    image_urn = self._upload_image(
                        token=token,
                        owner_urn=author_urn,
                        media_bytes=fpath.read_bytes(),
                        alt=primary.alt_text,
                    )
                    media_obj: dict[str, Any] = {"id": image_urn}
                    if primary.alt_text:
                        media_obj["altText"] = primary.alt_text[:300]
                    post_body["content"] = {"media": media_obj}
        elif request.source_url:
            post_body["content"] = {
                "article": {
                    "source": request.source_url,
                    "title": (request.title or "Latest Update")[:200],
                }
            }

        resp = self.http.request(
            "POST",
            "https://api.linkedin.com/rest/posts",
            headers=self._headers(token),
            json=post_body,
            is_publish_mutation=True,
        )
        if resp.status_code not in (200, 201):
            raise classify_http_failure(resp, is_publish_mutation=True)
        post_urn = resp.headers.get("x-restli-id") or (
            resp.json().get("id") if resp.content else None
        )
        ext_id = str(post_urn).strip() if post_urn else None
        pub_url = f"https://www.linkedin.com/feed/update/{ext_id}/" if ext_id else None
        return PublishResult(
            external_post_id=ext_id,
            published_url=pub_url,
            http_status=resp.status_code,
            verification_status="api_verified",
            response_summary={"x_restli_id": ext_id},
        )

    def reconcile_publication(
        self, *, request: PublishRequest, external_post_id: str | None = None
    ) -> ReconcileResult:
        token = (request.credentials.get("access_token") or "").strip()
        if not token or not external_post_id:
            return ReconcileResult(
                exists=False,
                indeterminate=True,
                note=(
                    "LinkedIn post URN not returned before timeout; verify manually "
                    "in LinkedIn feed."
                ),
            )
        resp = self.http.request(
            "GET",
            f"https://api.linkedin.com/rest/posts/{external_post_id}",
            headers=self._headers(token, content_type=None),
        )
        if resp.status_code == 200:
            return ReconcileResult(
                exists=True,
                external_post_id=external_post_id,
                published_url=f"https://www.linkedin.com/feed/update/{external_post_id}/",
            )
        return ReconcileResult(exists=False, indeterminate=resp.status_code != 404)
