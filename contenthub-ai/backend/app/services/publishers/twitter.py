from __future__ import annotations

import base64
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
    classify_http_failure,
    generate_pkce_pair,
)
from app.services.publishers.exceptions import PublisherError


class TwitterApiAdapter(BasePublisherAdapter):
    """Official X / Twitter API v2 (OAuth 2.0 PKCE) gated on explicit paid authorization."""

    allowed_hosts = frozenset({"x.com", "api.x.com", "api.twitter.com"})
    capabilities = PublisherCapabilities(
        platform_key="twitter",
        display_name="X / Twitter",
        priority_tier=3,
        supports_official_api=True,
        supports_manual_fallback=True,
        supports_oauth=True,
        supports_pkce=True,
        supports_refresh=True,
        supports_target_selection=False,
        supports_text_post=True,
        supports_link_post=True,
        supports_image_post=False,
        supports_native_schedule=False,
        supports_reconcile=True,
        requires_media=False,
        requires_external_media_url=False,
        requires_paid_api_ack=True,
        required_scopes=("tweet.write", "tweet.read", "users.read", "offline.access"),
        api_version="v2",
        limitations_summary=(
            "X discontinued free developer posting; posting incurs pay-per-use credits "
            "(~$0.015 text / ~$0.200 w/ URL) or a paid plan. Explicit admin opt-in is required "
            "before API calls; otherwise use Manual Publishing."
        ),
        rate_limit_summary=(
            "Pay-per-use credits required; ~100 user writes/15m on authorized accounts."
        ),
    )

    def _basic_auth(self, client_id: str, client_secret: str) -> str | None:
        if not client_secret:
            return None
        raw = f"{client_id}:{client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def validate_credentials(self, credentials: dict[str, str | None]) -> None:
        if not (credentials.get("access_token") or "").strip():
            raise PublisherError(
                "X OAuth 2.0 User Access Token is required for API publishing.",
                error_category="invalid_credentials",
                code="X_TOKEN_MISSING",
            )

    def build_oauth_authorize_url(
        self,
        *,
        credentials: dict[str, str | None],
        redirect_uri: str,
        state: str,
        scopes: list[str] | None = None,
    ) -> OAuthStartResult:
        client_id = (credentials.get("app_id") or credentials.get("api_key") or "").strip()
        if not client_id:
            raise PublisherError(
                "X OAuth 2.0 Client ID (App ID field) is required to start PKCE flow.",
                error_category="invalid_credentials",
                code="X_CLIENT_ID_MISSING",
            )
        verifier, challenge = generate_pkce_pair()
        chosen = tuple(scopes or self.capabilities.required_scopes)
        params = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(chosen),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return OAuthStartResult(
            authorization_url=f"https://x.com/i/oauth2/authorize?{params}",
            state=state,
            code_verifier=verifier,
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
        client_id = (credentials.get("app_id") or credentials.get("api_key") or "").strip()
        client_secret = (
            credentials.get("app_secret") or credentials.get("api_secret") or ""
        ).strip()
        if not client_id or not code_verifier:
            raise PublisherError(
                "X Client ID and PKCE code_verifier are required to exchange OAuth code.",
                error_category="invalid_credentials",
                code="X_PKCE_MISSING",
            )
        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
        basic = self._basic_auth(client_id, client_secret)
        if basic:
            headers["Authorization"] = basic
        data = {
            "code": code,
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        resp = self.http.request(
            "POST", "https://api.x.com/2/oauth2/token", headers=headers, data=data
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        tdata = resp.json()
        access_tok = str(tdata.get("access_token") or "").strip()
        refresh_tok = str(tdata.get("refresh_token") or "").strip() or None
        exp_sec = int(tdata.get("expires_in") or 7200)
        username = None
        ext_id = None
        display = None
        me = self.http.request(
            "GET",
            "https://api.x.com/2/users/me",
            headers={"Authorization": f"Bearer {access_tok}"},
        )
        if me.status_code == 200:
            udata = (me.json() or {}).get("data") or {}
            ext_id = str(udata.get("id") or "") or None
            username = udata.get("username")
            display = udata.get("name") or username
        return OAuthCallbackResult(
            access_token=access_tok,
            refresh_token=refresh_tok,
            token_expires_at=utc_now_naive() + timedelta(seconds=exp_sec),
            granted_scopes=str(tdata.get("scope") or "").split()
            or list(self.capabilities.required_scopes),
            external_account_id=ext_id,
            external_username=username,
            external_display_name=display,
            profile_url=f"https://x.com/{username}" if username else None,
            account_type="x_account",
            target_resource_id=ext_id,
            target_resource_name=f"@{username}" if username else ext_id,
            access_tier="pay_per_use",
        )

    def refresh_credentials(
        self, *, credentials: dict[str, str | None]
    ) -> OAuthTokenRefreshResult:
        client_id = (credentials.get("app_id") or credentials.get("api_key") or "").strip()
        client_secret = (
            credentials.get("app_secret") or credentials.get("api_secret") or ""
        ).strip()
        refresh_tok = (credentials.get("refresh_token") or "").strip()
        if not client_id or not refresh_tok:
            raise PublisherError(
                "X Client ID and Refresh Token (offline.access) are required to refresh.",
                error_category="expired_credentials",
                code="X_REFRESH_MISSING",
            )
        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
        basic = self._basic_auth(client_id, client_secret)
        if basic:
            headers["Authorization"] = basic
        resp = self.http.request(
            "POST",
            "https://api.x.com/2/oauth2/token",
            headers=headers,
            data={
                "refresh_token": refresh_tok,
                "grant_type": "refresh_token",
                "client_id": client_id,
            },
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        tdata = resp.json()
        return OAuthTokenRefreshResult(
            access_token=str(tdata.get("access_token") or "").strip(),
            refresh_token=str(tdata.get("refresh_token") or refresh_tok).strip(),
            token_expires_at=(
                utc_now_naive() + timedelta(seconds=int(tdata.get("expires_in") or 7200))
            ),
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
        me_resp = self.http.request(
            "GET",
            "https://api.x.com/2/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        if me_resp.status_code != 200:
            raise classify_http_failure(me_resp)
        udata = (me_resp.json() or {}).get("data") or {}
        uid = str(udata.get("id") or external_account_id or "")
        uname = str(udata.get("username") or uid)
        paid_allowed = bool((metadata or {}).get("allow_paid_publishing"))
        return AccountVerifyResult(
            connected=True,
            connection_status="connected",
            eligibility_status="eligible" if paid_allowed else "manual_only",
            eligibility_notes=(
                f"Verified X @{uname}. Paid API posting explicitly enabled."
                if paid_allowed
                else (
                    f"Verified X @{uname}. Paid pay-per-use API acknowledgment disabled — use "
                    "Manual Publishing or confirm paid API authorization."
                )
            ),
            account_type="x_account",
            external_account_id=uid,
            external_username=uname,
            external_display_name=udata.get("name") or uname,
            profile_url=f"https://x.com/{uname}",
            target_resource_id=uid,
            target_resource_name=f"@{uname}",
            granted_scopes=list(self.capabilities.required_scopes),
            access_tier="pay_per_use",
        )

    def publish_post(self, request: PublishRequest) -> PublishResult:
        self.validate_credentials(request.credentials)
        if not bool((request.metadata or {}).get("allow_paid_publishing")):
            raise PublisherError(
                "X API posting requires explicit Paid API opt-in (pay-per-use ~$0.015-$0.20/post). "
                "Enable paid API authorization on this connection or publish manually.",
                error_category="policy_restriction",
                code="X_PAID_OPT_IN_REQUIRED",
            )
        token = (request.credentials.get("access_token") or "").strip()
        resp = self.http.request(
            "POST",
            "https://api.x.com/2/tweets",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"text": request.assembled_content[:280]},
            is_publish_mutation=True,
        )
        if resp.status_code not in (200, 201):
            raise classify_http_failure(resp, is_publish_mutation=True)
        tdata = (resp.json() or {}).get("data") or {}
        tid = str(tdata.get("id") or "").strip() or None
        pub_url = f"https://x.com/i/web/status/{tid}" if tid else None
        return PublishResult(
            external_post_id=tid,
            published_url=pub_url,
            http_status=resp.status_code,
            verification_status="api_verified",
            response_summary={"id": tid},
        )

    def reconcile_publication(
        self, *, request: PublishRequest, external_post_id: str | None = None
    ) -> ReconcileResult:
        token = (request.credentials.get("access_token") or "").strip()
        uid = (request.target_resource_id or request.external_account_id or "").strip()
        if not token or not uid:
            return ReconcileResult(exists=False, indeterminate=True)
        resp = self.http.request(
            "GET",
            f"https://api.x.com/2/users/{uid}/tweets",
            headers={"Authorization": f"Bearer {token}"},
            params={"max_results": 10},
        )
        if resp.status_code != 200:
            return ReconcileResult(exists=False, indeterminate=True)
        needle = request.caption.strip()[:60]
        for row in resp.json().get("data") or []:
            if needle and needle in str(row.get("text") or ""):
                tid = str(row.get("id") or "")
                return ReconcileResult(
                    exists=True,
                    external_post_id=tid,
                    published_url=f"https://x.com/i/web/status/{tid}" if tid else None,
                )
        return ReconcileResult(exists=False, indeterminate=False)
