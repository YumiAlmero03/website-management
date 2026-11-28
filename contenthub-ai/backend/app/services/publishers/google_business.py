from __future__ import annotations

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
    generate_pkce_pair,
)
from app.services.publishers.exceptions import PublisherError

GBP_CTA_MAP: dict[str, str] = {
    "book": "BOOK",
    "order": "ORDER",
    "shop": "SHOP",
    "sign up": "SIGN_UP",
    "signup": "SIGN_UP",
    "call": "CALL",
    "learn more": "LEARN_MORE",
}


class GoogleBusinessProfileAdapter(BasePublisherAdapter):
    """Official Google Business Profile API (v1 accounts/locations + v4 localPosts)."""

    allowed_hosts = frozenset(
        {
            "accounts.google.com",
            "oauth2.googleapis.com",
            "mybusinessaccountmanagement.googleapis.com",
            "mybusinessbusinessinformation.googleapis.com",
            "mybusiness.googleapis.com",
        }
    )
    capabilities = PublisherCapabilities(
        platform_key="google_business_profile",
        display_name="Google Business Profile",
        priority_tier=1,
        supports_official_api=True,
        supports_manual_fallback=True,
        supports_oauth=True,
        supports_pkce=True,
        supports_refresh=True,
        supports_target_selection=True,
        supports_text_post=True,
        supports_link_post=True,
        supports_image_post=True,
        supports_native_schedule=False,
        supports_reconcile=True,
        requires_media=False,
        requires_external_media_url=True,
        requires_paid_api_ack=False,
        required_scopes=("https://www.googleapis.com/auth/business.manage",),
        api_version="v4",
        limitations_summary=(
            "Strictly gated: requires Google-approved Business Profile API access (300 QPM quota; "
            "unapproved projects get 0 QPM), an active verified profile (>=60 days), and strict "
            "policy eligibility (regulated/gambling brands may be ineligible)."
        ),
        rate_limit_summary="300 QPM when Google-approved; 0 QPM until approved.",
    )

    def validate_credentials(self, credentials: dict[str, str | None]) -> None:
        if not (credentials.get("access_token") or "").strip():
            raise PublisherError(
                "Google Business Profile OAuth access token is required.",
                error_category="invalid_credentials",
                code="GBP_TOKEN_MISSING",
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
                "Google OAuth Client ID (App ID field) is required.",
                error_category="invalid_credentials",
                code="GBP_CLIENT_ID_MISSING",
            )
        verifier, challenge = generate_pkce_pair()
        chosen = tuple(scopes or self.capabilities.required_scopes)
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(chosen),
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return OAuthStartResult(
            authorization_url=f"https://accounts.google.com/o/oauth2/v2/auth?{params}",
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
        client_id = (credentials.get("app_id") or "").strip()
        client_secret = (credentials.get("app_secret") or "").strip()
        if not client_id or not client_secret:
            raise PublisherError(
                "Google Client ID and Client Secret are required for OAuth exchange.",
                error_category="invalid_credentials",
                code="GBP_CLIENT_SECRET_MISSING",
            )
        form: dict[str, str] = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if code_verifier:
            form["code_verifier"] = code_verifier
        resp = self.http.request("POST", "https://oauth2.googleapis.com/token", data=form)
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        tdata = resp.json()
        access_token = str(tdata.get("access_token") or "").strip()
        refresh_token = str(tdata.get("refresh_token") or "").strip() or None
        exp_sec = int(tdata.get("expires_in") or 3600)
        targets = self._discover_locations(access_token)
        selected = targets[0] if len(targets) == 1 else None
        return OAuthCallbackResult(
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=utc_now_naive() + timedelta(seconds=exp_sec),
            granted_scopes=str(tdata.get("scope") or "").split() or list(
                self.capabilities.required_scopes
            ),
            external_account_id=selected.target_id if selected else None,
            external_display_name=selected.name if selected else None,
            profile_url=selected.profile_url if selected else None,
            account_type="gbp_location",
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
                "Client ID, Client Secret, and Refresh Token are required for Google refresh.",
                error_category="expired_credentials",
                code="GBP_REFRESH_MISSING",
            )
        resp = self.http.request(
            "POST",
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_tok,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        tdata = resp.json()
        return OAuthTokenRefreshResult(
            access_token=str(tdata.get("access_token") or "").strip(),
            refresh_token=refresh_tok,
            token_expires_at=(
                utc_now_naive() + timedelta(seconds=int(tdata.get("expires_in") or 3600))
            ),
        )

    def _discover_locations(self, access_token: str) -> list[TargetResourceOption]:
        headers = {"Authorization": f"Bearer {access_token}"}
        acct_resp = self.http.request(
            "GET",
            "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
            headers=headers,
        )
        if acct_resp.status_code != 200:
            raise classify_http_failure(acct_resp)
        targets: list[TargetResourceOption] = []
        for acct in acct_resp.json().get("accounts") or []:
            acct_name = acct.get("name")
            if not acct_name:
                continue
            loc_resp = self.http.request(
                "GET",
                f"https://mybusinessbusinessinformation.googleapis.com/v1/{acct_name}/locations",
                headers=headers,
                params={"readMask": "name,title,websiteUri,metadata"},
            )
            if loc_resp.status_code != 200:
                continue
            for loc in loc_resp.json().get("locations") or []:
                loc_name = str(loc.get("name") or "")
                # Combine accounts/{id}/locations/{loc_id} for v4 localPosts calls
                full_parent = (
                    loc_name if loc_name.startswith("accounts/") else f"{acct_name}/{loc_name}"
                )
                targets.append(
                    TargetResourceOption(
                        target_id=full_parent,
                        name=str(loc.get("title") or full_parent),
                        account_type="gbp_location",
                        profile_url=loc.get("websiteUri"),
                        metadata={"account": acct_name},
                    )
                )
        return targets

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
        targets = self._discover_locations(token)
        selected_id = (target_resource_id or external_account_id or "").strip()
        chosen = next((t for t in targets if t.target_id == selected_id), None)
        if chosen is None and len(targets) == 1:
            chosen = targets[0]

        if not targets:
            return AccountVerifyResult(
                connected=False,
                connection_status="restricted",
                eligibility_status="requires_review",
                eligibility_notes=(
                    "No eligible GBP locations found or API quota is still 0 QPM "
                    "awaiting Google approval."
                ),
                account_type="gbp_location",
            )

        return AccountVerifyResult(
            connected=chosen is not None,
            connection_status="connected" if chosen else "configured",
            eligibility_status="eligible" if chosen else "unknown",
            eligibility_notes=(
                f"Verified GBP location '{chosen.name}'."
                if chosen
                else "Select an approved Google Business Profile location target."
            ),
            account_type="gbp_location",
            external_account_id=chosen.target_id if chosen else None,
            external_display_name=chosen.name if chosen else None,
            profile_url=chosen.profile_url if chosen else None,
            target_resource_id=chosen.target_id if chosen else None,
            target_resource_name=chosen.name if chosen else None,
            available_targets=targets,
            granted_scopes=list(self.capabilities.required_scopes),
            access_tier="approved_basic",
        )

    def publish_post(self, request: PublishRequest) -> PublishResult:
        self.validate_credentials(request.credentials)
        token = (request.credentials.get("access_token") or "").strip()
        location_parent = (request.target_resource_id or request.external_account_id or "").strip()
        if not location_parent or "locations/" not in location_parent:
            raise PublisherError(
                "Valid GBP location resource (accounts/*/locations/*) is required.",
                error_category="unsupported_account",
                code="GBP_LOCATION_MISSING",
            )

        body: dict[str, Any] = {
            "languageCode": "en",
            "topicType": "STANDARD",
            "summary": request.assembled_content[:1500],
        }
        if request.source_url:
            cta_key = (request.cta_text or "").strip().lower()
            action_type = next(
                (v for k, v in GBP_CTA_MAP.items() if k in cta_key),
                "LEARN_MORE",
            )
            body["callToAction"] = {"actionType": action_type, "url": request.source_url}
        if request.media and (request.media[0].public_url or request.media[0].source_url):
            body["media"] = [
                {
                    "mediaFormat": "PHOTO",
                    "sourceUrl": request.media[0].public_url or request.media[0].source_url,
                }
            ]

        resp = self.http.request(
            "POST",
            f"https://mybusiness.googleapis.com/v4/{location_parent}/localPosts",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            is_publish_mutation=True,
        )
        if resp.status_code not in (200, 201):
            raise classify_http_failure(resp, is_publish_mutation=True)
        res = resp.json()
        return PublishResult(
            external_post_id=str(res.get("name") or "") or None,
            published_url=res.get("searchUrl"),
            http_status=resp.status_code,
            verification_status="api_verified",
            response_summary={"name": res.get("name"), "state": res.get("state")},
        )

    def reconcile_publication(
        self,
        *,
        request: PublishRequest,
        external_post_id: str | None = None,
    ) -> ReconcileResult:
        token = (request.credentials.get("access_token") or "").strip()
        parent = (request.target_resource_id or request.external_account_id or "").strip()
        if not token or not parent:
            return ReconcileResult(exists=False, indeterminate=True)
        resp = self.http.request(
            "GET",
            f"https://mybusiness.googleapis.com/v4/{parent}/localPosts",
            headers={"Authorization": f"Bearer {token}"},
            params={"pageSize": 10},
        )
        if resp.status_code != 200:
            return ReconcileResult(exists=False, indeterminate=True)
        needle = request.caption.strip()[:100]
        for row in resp.json().get("localPosts") or []:
            if needle and needle in str(row.get("summary") or ""):
                return ReconcileResult(
                    exists=True,
                    external_post_id=row.get("name"),
                    published_url=row.get("searchUrl"),
                    note="Confirmed GBP localPost exists after timeout.",
                )
        return ReconcileResult(
            exists=False,
            indeterminate=False,
            note="Not found in recent localPosts.",
        )
