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
    classify_http_failure,
)
from app.services.publishers.exceptions import PublisherError


class ThreadsAdapter(BasePublisherAdapter):
    """Official Meta Threads API (graph.threads.net) 2-step container adapter."""

    allowed_hosts = frozenset({"threads.net", "www.threads.net", "graph.threads.net"})
    capabilities = PublisherCapabilities(
        platform_key="threads",
        display_name="Threads",
        priority_tier=2,
        supports_official_api=True,
        supports_manual_fallback=True,
        supports_oauth=True,
        supports_pkce=False,
        supports_refresh=True,
        supports_target_selection=False,
        supports_text_post=True,
        supports_link_post=True,
        supports_image_post=True,
        supports_native_schedule=False,
        supports_reconcile=True,
        requires_media=False,
        requires_external_media_url=True,
        requires_paid_api_ack=False,
        required_scopes=("threads_basic", "threads_content_publish"),
        api_version="v1.0",
        limitations_summary=(
            "Requires Threads Tester role in Dev Mode or Meta App Review. Image/video posts "
            "require publicly accessible HTTPS URLs; max 500 characters."
        ),
        rate_limit_summary="250 API posts / 24h rolling window via threads_publishing_limit.",
    )

    def validate_credentials(self, credentials: dict[str, str | None]) -> None:
        if not (credentials.get("access_token") or "").strip():
            raise PublisherError(
                "Threads Access Token is required for API publishing.",
                error_category="invalid_credentials",
                code="THREADS_TOKEN_MISSING",
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
                "Threads App ID is required before starting OAuth.",
                error_category="invalid_credentials",
                code="THREADS_APP_ID_MISSING",
            )
        chosen = tuple(scopes or self.capabilities.required_scopes)
        params = urlencode(
            {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "scope": ",".join(chosen),
                "response_type": "code",
                "state": state,
            }
        )
        return OAuthStartResult(
            authorization_url=f"https://threads.net/oauth/authorize?{params}",
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
                "Threads App ID and App Secret are required for OAuth exchange.",
                error_category="invalid_credentials",
                code="THREADS_APP_SECRET_MISSING",
            )
        short_resp = self.http.request(
            "POST",
            "https://graph.threads.net/oauth/access_token",
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if short_resp.status_code != 200:
            raise classify_http_failure(short_resp)
        short_data = short_resp.json()
        token = str(short_data.get("access_token") or "").strip()
        user_id = str(short_data.get("user_id") or "") or None
        expires_at = utc_now_naive() + timedelta(hours=1)

        long_resp = self.http.request(
            "GET",
            "https://graph.threads.net/access_token",
            params={
                "grant_type": "th_exchange_token",
                "client_secret": app_secret,
                "access_token": token,
            },
        )
        if long_resp.status_code == 200:
            ldata = long_resp.json()
            token = str(ldata.get("access_token") or token).strip()
            expires_at = utc_now_naive() + timedelta(
                seconds=int(ldata.get("expires_in") or 5184000)
            )

        me_resp = self.http.request(
            "GET",
            f"https://graph.threads.net/{self.api_version}/me",
            params={
                "fields": "id,username,name,threads_profile_picture_url",
                "access_token": token,
            },
        )
        username = None
        display_name = None
        if me_resp.status_code == 200:
            me = me_resp.json()
            user_id = str(me.get("id") or user_id or "") or None
            username = me.get("username")
            display_name = me.get("name") or username

        profile_url = f"https://www.threads.net/@{username}" if username else None
        return OAuthCallbackResult(
            access_token=token,
            refresh_token=token,
            token_expires_at=expires_at,
            granted_scopes=list(self.capabilities.required_scopes),
            external_account_id=user_id,
            external_username=username,
            external_display_name=display_name,
            profile_url=profile_url,
            account_type="threads_profile",
            target_resource_id=user_id,
            target_resource_name=f"@{username}" if username else user_id,
        )

    def refresh_credentials(
        self, *, credentials: dict[str, str | None]
    ) -> OAuthTokenRefreshResult:
        token = (credentials.get("access_token") or "").strip()
        if not token:
            raise PublisherError(
                "Long-lived Threads token required to refresh.",
                error_category="expired_credentials",
                code="THREADS_TOKEN_MISSING",
            )
        resp = self.http.request(
            "GET",
            "https://graph.threads.net/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": token},
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
        me_resp = self.http.request(
            "GET",
            f"https://graph.threads.net/{self.api_version}/me",
            params={"fields": "id,username,name", "access_token": token},
        )
        if me_resp.status_code != 200:
            raise classify_http_failure(me_resp)
        me = me_resp.json()
        uid = str(me.get("id") or target_resource_id or external_account_id or "me")
        uname = str(me.get("username") or uid)
        limit_resp = self.http.request(
            "GET",
            f"https://graph.threads.net/{self.api_version}/{uid}/threads_publishing_limit",
            params={"fields": "quota_usage,config", "access_token": token},
        )
        quota_meta = limit_resp.json() if limit_resp.status_code == 200 else {}
        return AccountVerifyResult(
            connected=True,
            connection_status="connected",
            eligibility_status="eligible",
            eligibility_notes=f"Verified Threads profile @{uname}.",
            account_type="threads_profile",
            external_account_id=uid,
            external_username=uname,
            external_display_name=me.get("name") or uname,
            profile_url=f"https://www.threads.net/@{uname.lstrip('@')}",
            target_resource_id=uid,
            target_resource_name=f"@{uname}",
            granted_scopes=list(self.capabilities.required_scopes),
            metadata={"publishing_limit": quota_meta},
        )

    def publish_post(self, request: PublishRequest) -> PublishResult:
        self.validate_credentials(request.credentials)
        token = (request.credentials.get("access_token") or "").strip()
        uid = (request.target_resource_id or request.external_account_id or "me").strip()

        container_data: dict[str, Any] = {
            "text": request.assembled_content[:500],
            "access_token": token,
        }
        if request.media and (request.media[0].public_url or request.media[0].source_url):
            container_data["media_type"] = "IMAGE"
            container_data["image_url"] = request.media[0].public_url or request.media[0].source_url
            if request.media[0].alt_text:
                container_data["alt_text"] = request.media[0].alt_text[:500]
        else:
            container_data["media_type"] = "TEXT"

        c_resp = self.http.request(
            "POST",
            f"https://graph.threads.net/{self.api_version}/{uid}/threads",
            data=container_data,
        )
        if c_resp.status_code not in (200, 201):
            raise classify_http_failure(c_resp)
        creation_id = str(c_resp.json().get("id") or "").strip()

        # Brief container readiness check for image uploads
        if container_data["media_type"] == "IMAGE" and creation_id:
            for _ in range(3):
                st = self.http.request(
                    "GET",
                    f"https://graph.threads.net/{self.api_version}/{creation_id}",
                    params={"fields": "status,error_message", "access_token": token},
                )
                if st.status_code == 200 and st.json().get("status") == "FINISHED":
                    break
                time.sleep(0.2)

        p_resp = self.http.request(
            "POST",
            f"https://graph.threads.net/{self.api_version}/{uid}/threads_publish",
            data={"creation_id": creation_id, "access_token": token},
            is_publish_mutation=True,
        )
        if p_resp.status_code not in (200, 201):
            raise classify_http_failure(p_resp, is_publish_mutation=True)
        thread_id = str(p_resp.json().get("id") or "").strip() or None
        permalink = None
        if thread_id:
            try:
                g = self.http.request(
                    "GET",
                    f"https://graph.threads.net/{self.api_version}/{thread_id}",
                    params={"fields": "permalink", "access_token": token},
                )
                if g.status_code == 200:
                    permalink = g.json().get("permalink")
            except PublisherError:
                pass
        return PublishResult(
            external_post_id=thread_id,
            published_url=permalink,
            http_status=p_resp.status_code,
            verification_status="api_verified",
            response_summary={"id": thread_id, "permalink": permalink},
        )

    def reconcile_publication(
        self, *, request: PublishRequest, external_post_id: str | None = None
    ) -> ReconcileResult:
        token = (request.credentials.get("access_token") or "").strip()
        uid = (request.target_resource_id or request.external_account_id or "me").strip()
        if not token:
            return ReconcileResult(exists=False, indeterminate=True)
        resp = self.http.request(
            "GET",
            f"https://graph.threads.net/{self.api_version}/{uid}/threads",
            params={"fields": "id,text,permalink", "limit": 10, "access_token": token},
        )
        if resp.status_code != 200:
            return ReconcileResult(exists=False, indeterminate=True)
        needle = request.caption.strip()[:100]
        for row in resp.json().get("data") or []:
            if needle and needle in str(row.get("text") or ""):
                return ReconcileResult(
                    exists=True,
                    external_post_id=str(row.get("id") or ""),
                    published_url=row.get("permalink"),
                    note="Confirmed Threads post exists after timeout.",
                )
        return ReconcileResult(exists=False, indeterminate=False)
