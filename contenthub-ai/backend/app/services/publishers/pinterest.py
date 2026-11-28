from __future__ import annotations

import base64
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
    generate_pkce_pair,
)
from app.services.publishers.exceptions import PublisherError


class PinterestApiAdapter(BasePublisherAdapter):
    """Official Pinterest API v5 (/v5/pins, /v5/boards) adapter with PKCE & board check."""

    allowed_hosts = frozenset({"www.pinterest.com", "api.pinterest.com"})
    capabilities = PublisherCapabilities(
        platform_key="pinterest",
        display_name="Pinterest",
        priority_tier=2,
        supports_official_api=True,
        supports_manual_fallback=True,
        supports_oauth=True,
        supports_pkce=True,
        supports_refresh=True,
        supports_target_selection=True,
        supports_text_post=False,
        supports_link_post=True,
        supports_image_post=True,
        supports_native_schedule=False,
        supports_reconcile=True,
        requires_media=True,
        requires_external_media_url=False,
        requires_paid_api_ack=False,
        required_scopes=("boards:read", "pins:read", "pins:write"),
        api_version="v5",
        limitations_summary=(
            "Requires a target board_id and an image attachment (text-only pins unsupported). "
            "Trial access creates sandbox-only hidden Pins; Standard access requires demo review."
        ),
        rate_limit_summary="Trial: ~300 org_write/day; Standard: ~100/min.",
    )

    def _basic_auth_header(self, client_id: str, client_secret: str) -> str:
        raw = f"{client_id}:{client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def validate_credentials(self, credentials: dict[str, str | None]) -> None:
        if not (credentials.get("access_token") or "").strip():
            raise PublisherError(
                "Pinterest API v5 Access Token is required for API publishing.",
                error_category="invalid_credentials",
                code="PIN_TOKEN_MISSING",
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
                "Pinterest App ID is required before starting OAuth.",
                error_category="invalid_credentials",
                code="PIN_APP_ID_MISSING",
            )
        verifier, challenge = generate_pkce_pair()
        chosen = tuple(scopes or self.capabilities.required_scopes)
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": ",".join(chosen),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return OAuthStartResult(
            authorization_url=f"https://www.pinterest.com/oauth/?{params}",
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
                "Pinterest App ID and App Secret are required for OAuth exchange.",
                error_category="invalid_credentials",
                code="PIN_CREDS_MISSING",
            )
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        resp = self.http.request(
            "POST",
            "https://api.pinterest.com/v5/oauth/token",
            headers={"Authorization": self._basic_auth_header(client_id, client_secret)},
            data=data,
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        tdata = resp.json()
        access_tok = str(tdata.get("access_token") or "").strip()
        refresh_tok = str(tdata.get("refresh_token") or "").strip() or None
        exp_sec = int(tdata.get("expires_in") or 2592000)
        ref_exp = (
            utc_now_naive() + timedelta(seconds=int(tdata["refresh_token_expires_in"]))
            if tdata.get("refresh_token_expires_in")
            else None
        )
        boards = self._list_boards(access_tok)
        selected = boards[0] if len(boards) == 1 else None
        return OAuthCallbackResult(
            access_token=access_tok,
            refresh_token=refresh_tok,
            token_expires_at=utc_now_naive() + timedelta(seconds=exp_sec),
            refresh_token_expires_at=ref_exp,
            granted_scopes=str(tdata.get("scope") or "").replace(",", " ").split()
            or list(self.capabilities.required_scopes),
            account_type="pinterest_business",
            target_resource_id=selected.target_id if selected else None,
            target_resource_name=selected.name if selected else None,
            available_targets=boards,
            access_tier="trial_or_standard",
        )

    def refresh_credentials(
        self, *, credentials: dict[str, str | None]
    ) -> OAuthTokenRefreshResult:
        client_id = (credentials.get("app_id") or "").strip()
        client_secret = (credentials.get("app_secret") or "").strip()
        refresh_tok = (credentials.get("refresh_token") or "").strip()
        if not client_id or not client_secret or not refresh_tok:
            raise PublisherError(
                "App ID, App Secret, and Refresh Token are required for Pinterest refresh.",
                error_category="expired_credentials",
                code="PIN_REFRESH_MISSING",
            )
        resp = self.http.request(
            "POST",
            "https://api.pinterest.com/v5/oauth/token",
            headers={"Authorization": self._basic_auth_header(client_id, client_secret)},
            data={"grant_type": "refresh_token", "refresh_token": refresh_tok},
        )
        if resp.status_code != 200:
            raise classify_http_failure(resp)
        tdata = resp.json()
        return OAuthTokenRefreshResult(
            access_token=str(tdata.get("access_token") or "").strip(),
            refresh_token=str(tdata.get("refresh_token") or refresh_tok).strip(),
            token_expires_at=utc_now_naive()
            + timedelta(seconds=int(tdata.get("expires_in") or 2592000)),
        )

    def _list_boards(self, token: str) -> list[TargetResourceOption]:
        resp = self.http.request(
            "GET",
            "https://api.pinterest.com/v5/boards",
            headers={"Authorization": f"Bearer {token}"},
            params={"page_size": 25},
        )
        if resp.status_code != 200:
            return []
        out: list[TargetResourceOption] = []
        for b in resp.json().get("items") or []:
            if b.get("id"):
                out.append(
                    TargetResourceOption(
                        target_id=str(b["id"]),
                        name=str(b.get("name") or b["id"]),
                        account_type="pinterest_board",
                    )
                )
        return out

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
            "https://api.pinterest.com/v5/user_account",
            headers={"Authorization": f"Bearer {token}"},
        )
        if me_resp.status_code != 200:
            raise classify_http_failure(me_resp)
        me = me_resp.json()
        boards = self._list_boards(token)
        wanted = (target_resource_id or external_account_id or "").strip()
        chosen = next((b for b in boards if b.target_id == wanted), None) or (
            boards[0] if len(boards) == 1 else None
        )
        username = str(me.get("username") or "pinterest")
        return AccountVerifyResult(
            connected=chosen is not None,
            connection_status="connected" if chosen else "configured",
            eligibility_status="eligible" if chosen else "unknown",
            eligibility_notes=(
                f"Verified Pinterest @{username} (board: {chosen.name}). "
                "Note: Trial apps publish to sandbox."
                if chosen
                else "Connected Pinterest account; select a destination board_id."
            ),
            account_type=str(me.get("account_type") or "pinterest_business"),
            external_account_id=str(me.get("id") or username),
            external_username=username,
            external_display_name=me.get("business_name") or username,
            profile_url=f"https://www.pinterest.com/{username}/",
            target_resource_id=chosen.target_id if chosen else None,
            target_resource_name=chosen.name if chosen else None,
            available_targets=boards,
            granted_scopes=list(self.capabilities.required_scopes),
            access_tier="trial_or_standard",
        )

    def publish_post(self, request: PublishRequest) -> PublishResult:
        self.validate_credentials(request.credentials)
        token = (request.credentials.get("access_token") or "").strip()
        board_id = (request.target_resource_id or request.external_account_id or "").strip()
        if not board_id:
            raise PublisherError(
                "Pinterest destination board_id is required.",
                error_category="unsupported_account",
                code="PIN_BOARD_REQUIRED",
            )
        if not request.media:
            raise PublisherError(
                "Pinterest API requires an image attachment for Pins.",
                error_category="invalid_media",
                code="PIN_MEDIA_REQUIRED",
            )
        primary = request.media[0]
        media_source: dict[str, Any] | None = None
        if primary.public_url or primary.source_url:
            media_source = {
                "source_type": "image_url",
                "url": primary.public_url or primary.source_url,
            }
        elif primary.file_path:
            root = Settings().resolved_storage_root.resolve()
            fpath = (root / primary.file_path).resolve()
            if str(fpath).startswith(str(root)) and fpath.is_file():
                media_source = {
                    "source_type": "image_base64",
                    "content_type": primary.mime_type or "image/jpeg",
                    "data": base64.b64encode(fpath.read_bytes()).decode("ascii"),
                }
        if not media_source:
            raise PublisherError(
                "Could not prepare image_url or image_base64 media_source for Pinterest Pin.",
                error_category="invalid_media",
                code="PIN_MEDIA_UNAVAILABLE",
            )

        payload: dict[str, Any] = {
            "board_id": board_id,
            "description": request.assembled_content[:500],
            "media_source": media_source,
        }
        if request.title:
            payload["title"] = request.title[:100]
        if request.source_url:
            payload["link"] = request.source_url
        if primary.alt_text:
            payload["alt_text"] = primary.alt_text[:500]

        resp = self.http.request(
            "POST",
            "https://api.pinterest.com/v5/pins",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            is_publish_mutation=True,
        )
        if resp.status_code not in (200, 201):
            raise classify_http_failure(resp, is_publish_mutation=True)
        res = resp.json()
        pin_id = str(res.get("id") or "").strip() or None
        pub_url = f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else None
        return PublishResult(
            external_post_id=pin_id,
            published_url=pub_url,
            http_status=resp.status_code,
            verification_status="api_verified",
            response_summary={"id": pin_id, "board_id": board_id},
        )

    def reconcile_publication(
        self, *, request: PublishRequest, external_post_id: str | None = None
    ) -> ReconcileResult:
        token = (request.credentials.get("access_token") or "").strip()
        board_id = (request.target_resource_id or request.external_account_id or "").strip()
        if not token or not board_id:
            return ReconcileResult(exists=False, indeterminate=True)
        resp = self.http.request(
            "GET",
            f"https://api.pinterest.com/v5/boards/{board_id}/pins",
            headers={"Authorization": f"Bearer {token}"},
            params={"page_size": 10},
        )
        if resp.status_code != 200:
            return ReconcileResult(exists=False, indeterminate=True)
        needle = request.caption.strip()[:100]
        for row in resp.json().get("items") or []:
            if needle and needle in str(row.get("description") or ""):
                pid = str(row.get("id") or "")
                return ReconcileResult(
                    exists=True,
                    external_post_id=pid,
                    published_url=f"https://www.pinterest.com/pin/{pid}/" if pid else None,
                )
        return ReconcileResult(exists=False, indeterminate=False)
