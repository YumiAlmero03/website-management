from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import redact_text
from app.core.security import decrypt_secret, encrypt_secret, hash_token
from app.models.base import ensure_utc, utc_now_naive
from app.models.platform import Platform
from app.models.publishing import SocialProfileConnection
from app.models.social_profile import SocialProfile
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.publishing_repo import PublishingRepositoryProtocol
from app.repositories.social_profile_repo import SocialProfileRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.publishing import (
    ConnectAccountRequest,
    ConnectAccountResponse,
    DisconnectAccountRequest,
    OAuthCompleteRequest,
    SelectTargetRequest,
    SocialProfileConnectionResponse,
    TargetResourceResponse,
)
from app.services.publishers.exceptions import PublisherError
from app.services.publishers.registry import PublisherAdapterRegistry
from app.services.social_profile_service import CREDENTIAL_COLUMN_MAP

EXPIRING_SOON_DAYS = 7


class PublishingConnectionService:
    """Manages OAuth PKCE sessions, Fernet credentials, verification, and refresh."""

    def __init__(
        self,
        *,
        settings: Settings,
        social_profile_repo: SocialProfileRepositoryProtocol,
        publishing_repo: PublishingRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        adapter_registry: PublisherAdapterRegistry,
    ) -> None:
        self.settings = settings
        self.profile_repo = social_profile_repo
        self.pub_repo = publishing_repo
        self.website_repo = website_repo
        self.activity_repo = activity_repo
        self.registry = adapter_registry

    def _load_profile_and_platform(
        self, profile_id: int
    ) -> tuple[SocialProfile, Platform]:
        profile = self.profile_repo.get_by_id(profile_id)
        if profile is None:
            raise NotFoundError(f"Social profile #{profile_id} not found.")
        platform = self.profile_repo.get_platform_by_id(profile.platform_id)
        if platform is None:
            raise NotFoundError(f"Platform #{profile.platform_id} not found.")
        return profile, platform

    def _decrypt_profile_credentials(
        self, profile: SocialProfile
    ) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for field_name, col in CREDENTIAL_COLUMN_MAP.items():
            ciphertext = getattr(profile, col, None)
            if ciphertext:
                out[field_name] = decrypt_secret(ciphertext, self.settings.app_encryption_key)
            else:
                out[field_name] = None
        return out

    def _validate_redirect_uri(self, raw_uri: str | None) -> str:
        default_cb = (
            f"{self.settings.app_url.rstrip('/')}/connected-accounts?oauth_callback=1"
        )
        candidate = (raw_uri or default_cb).strip()
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValidationAppError("OAuth redirect URI must be a valid http/https URL.")
        host = (parsed.hostname or "").lower()
        app_host = (urlparse(self.settings.app_url).hostname or "").lower()
        allowed_hosts = {app_host, "127.0.0.1", "localhost"} | (
            self.settings.oauth_allowed_redirect_host_set
        )
        if host not in allowed_hosts:
            raise ValidationAppError(
                f"Untrusted OAuth redirect host '{host}'. Register host via APP_URL or "
                "OAUTH_ALLOWED_REDIRECT_HOSTS."
            )
        return candidate

    def _build_default_connection_data(
        self, profile: SocialProfile, platform: Platform
    ) -> dict[str, Any]:
        caps = dict(platform.capabilities_json or {})
        is_manual = (
            profile.publishing_method == "manual" or platform.platform_key == "custom_social"
        )
        has_token = bool(profile.encrypted_access_token or profile.encrypted_api_key)
        status_val = (
            "configured"
            if is_manual
            else ("configured" if has_token else "not_connected")
        )
        elig_val = "manual_only" if is_manual else ("unverified" if has_token else "unknown")
        return {
            "auth_type": "manual" if is_manual else str(caps.get("auth_flow") or "credentials"),
            "connection_status": status_val,
            "account_type": "manual" if is_manual else None,
            "external_account_id": profile.external_account_id,
            "profile_url": profile.profile_url,
            "available_targets_json": [],
            "granted_scopes_json": list(profile.granted_permissions_json or []),
            "required_scopes_json": list(caps.get("required_scopes") or []),
            "missing_scopes_json": [],
            "eligibility_status": elig_val,
            "eligibility_notes": caps.get("limitations_summary"),
            "api_version": caps.get("api_version"),
            "token_expires_at": profile.token_expires_at,
            "metadata_json": {},
        }

    def get_or_init_connection(
        self,
        profile: SocialProfile,
        platform: Platform,
    ) -> SocialProfileConnection:
        existing = self.pub_repo.get_connection_by_profile_id(profile.id)
        if existing is not None:
            return existing
        return self.pub_repo.upsert_connection(
            social_profile_id=profile.id,
            website_id=profile.website_id,
            platform_id=platform.id,
            data=self._build_default_connection_data(profile, platform),
        )

    def to_response(
        self,
        profile: SocialProfile,
        platform: Platform,
        conn: SocialProfileConnection,
    ) -> SocialProfileConnectionResponse:
        now = utc_now_naive()
        expires_soon = bool(
            conn.token_expires_at is not None
            and now < conn.token_expires_at <= now + timedelta(days=EXPIRING_SOON_DAYS)
        )
        effective_status = conn.connection_status
        if (
            conn.token_expires_at is not None
            and conn.token_expires_at <= now
            and conn.connection_status in {"connected", "expiring_soon", "configured"}
            and profile.publishing_method == "api"
        ):
            effective_status = "expired"
        elif expires_soon and conn.connection_status == "connected":
            effective_status = "expiring_soon"

        latest_rec = self.pub_repo.get_latest_for_profile(profile.id)
        last_pub = profile.last_published_at or (latest_rec.published_at if latest_rec else None)

        targets = [
            TargetResourceResponse(
                target_id=str(item.get("target_id") or ""),
                name=str(item.get("name") or item.get("target_id") or ""),
                account_type=str(item.get("account_type") or ""),
                profile_url=item.get("profile_url"),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in (conn.available_targets_json or [])
            if isinstance(item, dict) and item.get("target_id")
        ]
        return SocialProfileConnectionResponse(
            social_profile_id=profile.id,
            website_id=profile.website_id,
            platform_id=platform.id,
            platform_key=platform.platform_key,
            platform_display_name=platform.display_name,
            auth_type=conn.auth_type,
            connection_status=effective_status,
            account_type=conn.account_type,
            external_account_id=conn.external_account_id or profile.external_account_id,
            external_username=conn.external_username,
            external_display_name=conn.external_display_name,
            profile_url=conn.profile_url or profile.profile_url,
            target_resource_id=conn.target_resource_id,
            target_resource_name=conn.target_resource_name,
            available_targets=targets,
            granted_scopes=list(conn.granted_scopes_json or []),
            required_scopes=list(conn.required_scopes_json or []),
            missing_scopes=list(conn.missing_scopes_json or []),
            eligibility_status=conn.eligibility_status,
            eligibility_notes=conn.eligibility_notes,
            access_tier=conn.access_tier,
            allow_paid_publishing=bool(conn.allow_paid_publishing),
            api_version=conn.api_version,
            token_expires_at=ensure_utc(conn.token_expires_at),
            refresh_token_expires_at=ensure_utc(conn.refresh_token_expires_at),
            expires_soon=expires_soon,
            last_tested_at=ensure_utc(conn.last_tested_at),
            last_refreshed_at=ensure_utc(conn.last_refreshed_at),
            last_verified_at=ensure_utc(conn.last_verified_at),
            last_published_at=ensure_utc(last_pub),
            last_error_code=conn.last_error_code,
            last_error_message=conn.last_error_message,
            metadata=dict(conn.metadata_json or {}),
            capabilities=dict(platform.capabilities_json or {}),
        )

    def get_connection_status(self, profile_id: int) -> SocialProfileConnectionResponse:
        profile, platform = self._load_profile_and_platform(profile_id)
        conn = self.get_or_init_connection(profile, platform)
        return self.to_response(profile, platform, conn)

    def _store_encrypted_credentials(
        self,
        profile: SocialProfile,
        updates_dict: dict[str, str | None],
        *,
        token_expires_at: Any = None,
    ) -> SocialProfile:
        prof_updates: dict[str, Any] = {}
        for field_name, col in CREDENTIAL_COLUMN_MAP.items():
            if field_name in updates_dict:
                val = updates_dict[field_name]
                if val is not None and val.strip():
                    prof_updates[col] = encrypt_secret(
                        val.strip(), self.settings.app_encryption_key
                    )
        if token_expires_at is not None:
            prof_updates["token_expires_at"] = token_expires_at.replace(tzinfo=None)
        if prof_updates:
            prof_updates["credentials_updated_at"] = utc_now_naive()
            prof_updates["credential_status"] = "configured"
            updated = self.profile_repo.update(profile.id, prof_updates)
            assert updated is not None
            return updated
        return profile

    def connect_account(
        self,
        profile_id: int,
        payload: ConnectAccountRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> ConnectAccountResponse:
        profile, platform = self._load_profile_and_platform(profile_id)
        conn = self.get_or_init_connection(profile, platform)
        adapter = self.registry.get(
            platform.platform_key,
            publishing_method=profile.publishing_method,
        )

        # Store any supplied app/token credentials encrypted right away
        cred_patch: dict[str, str | None] = {}
        for fname in (
            "app_id",
            "app_secret",
            "api_key",
            "api_secret",
            "access_token",
            "refresh_token",
        ):
            val = getattr(payload, fname, None)
            if val is not None and val.strip():
                cred_patch[fname] = val.strip()
        if cred_patch or payload.token_expires_at is not None:
            profile = self._store_encrypted_credentials(
                profile, cred_patch, token_expires_at=payload.token_expires_at
            )

        prof_extra: dict[str, Any] = {}
        if payload.external_account_id is not None:
            prof_extra["external_account_id"] = payload.external_account_id.strip() or None
        if payload.mode == "manual" or platform.platform_key == "custom_social":
            prof_extra["publishing_method"] = "manual"
            prof_extra["publishing_eligibility_status"] = "manual_only"
            if prof_extra:
                profile = self.profile_repo.update(profile.id, prof_extra) or profile
            updated_conn = self.pub_repo.upsert_connection(
                social_profile_id=profile.id,
                website_id=profile.website_id,
                platform_id=platform.id,
                data={
                    "auth_type": "manual",
                    "connection_status": "configured",
                    "account_type": "manual",
                    "eligibility_status": "manual_only",
                    "eligibility_notes": (
                        "Manual publishing active; no external API credentials required."
                    ),
                    "last_verified_at": utc_now_naive(),
                    "last_error_code": None,
                    "last_error_message": None,
                },
            )
            return ConnectAccountResponse(
                action="manual_ready",
                connection=self.to_response(profile, platform, updated_conn),
            )

        if payload.mode == "oauth":
            if not adapter.capabilities.supports_oauth:
                raise ValidationAppError(
                    f"{platform.display_name} does not support OAuth 2.0 connection."
                )
            redirect_uri = self._validate_redirect_uri(payload.redirect_uri)
            raw_state = secrets.token_urlsafe(32)
            decrypted = self._decrypt_profile_credentials(profile)
            try:
                oauth_start = adapter.build_oauth_authorize_url(
                    credentials=decrypted,
                    redirect_uri=redirect_uri,
                    state=raw_state,
                    scopes=payload.scopes or None,
                )
            except PublisherError as exc:
                raise ValidationAppError(exc.message, code=exc.code) from exc

            expires_at = utc_now_naive() + timedelta(minutes=15)
            enc_verifier = (
                encrypt_secret(oauth_start.code_verifier, self.settings.app_encryption_key)
                if oauth_start.code_verifier
                else None
            )
            self.pub_repo.create_oauth_state(
                {
                    "state_hash": hash_token(raw_state),
                    "website_id": profile.website_id,
                    "social_profile_id": profile.id,
                    "platform_key": platform.platform_key,
                    "redirect_uri": redirect_uri,
                    "encrypted_code_verifier": enc_verifier,
                    "requested_scopes_json": list(oauth_start.requested_scopes),
                    "status": "pending",
                    "initiated_by": user_id,
                    "expires_at": expires_at,
                }
            )
            self.profile_repo.update(profile.id, {"publishing_method": "api"})
            self.activity_repo.create(
                user_id=user_id,
                actor_type="admin",
                category="social_profiles",
                action="social_profile.oauth_started",
                level="info",
                message=(
                    f"Initiated {platform.display_name} OAuth flow "
                    f"for '{profile.profile_name}'."
                ),
                metadata={"social_profile_id": profile.id, "platform": platform.platform_key},
                ip_address=ip_address,
            )
            return ConnectAccountResponse(
                action="oauth_redirect",
                authorization_url=oauth_start.authorization_url,
                state_preview=raw_state[:8] + "...",
                expires_at=ensure_utc(expires_at),
                connection=self.to_response(profile, platform, conn),
            )

        # Direct administrator-supplied credentials/tokens path
        prof_extra["publishing_method"] = "api"
        profile = self.profile_repo.update(profile.id, prof_extra) or profile
        conn_patch: dict[str, Any] = {}
        if payload.allow_paid_publishing is not None:
            conn_patch["allow_paid_publishing"] = payload.allow_paid_publishing
        if payload.target_resource_id is not None:
            conn_patch["target_resource_id"] = payload.target_resource_id.strip() or None
        if payload.target_resource_name is not None:
            conn_patch["target_resource_name"] = payload.target_resource_name.strip() or None
        if conn_patch:
            conn = self.pub_repo.upsert_connection(
                social_profile_id=profile.id,
                website_id=profile.website_id,
                platform_id=platform.id,
                data=conn_patch,
            )
        verified_resp = self.verify_connection(
            profile.id, user_id=user_id, ip_address=ip_address
        )
        return ConnectAccountResponse(action="connected", connection=verified_resp)

    def complete_oauth_callback(
        self,
        profile_id: int,
        payload: OAuthCompleteRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialProfileConnectionResponse:
        profile, platform = self._load_profile_and_platform(profile_id)
        state_row = self.pub_repo.get_oauth_state_by_hash(hash_token(payload.state))
        if (
            state_row is None
            or state_row.social_profile_id != profile.id
            or state_row.website_id != profile.website_id
        ):
            raise ValidationAppError("Invalid OAuth state token.", code="OAUTH_STATE_INVALID")
        if state_row.status != "pending":
            raise ConflictError(
                f"OAuth state already {state_row.status}. Restart connection flow."
            )
        if state_row.expires_at <= utc_now_naive():
            self.pub_repo.update_oauth_state(state_row.id, {"status": "expired"})
            raise ValidationAppError(
                "OAuth authorization session expired. Restart Connect Account.",
                code="OAUTH_STATE_EXPIRED",
            )
        if payload.error:
            err_msg = redact_text(payload.error_description or payload.error)
            self.pub_repo.update_oauth_state(
                state_row.id, {"status": "failed", "consumed_at": utc_now_naive()}
            )
            conn = self.pub_repo.upsert_connection(
                social_profile_id=profile.id,
                website_id=profile.website_id,
                platform_id=platform.id,
                data={
                    "connection_status": "error",
                    "last_error_code": payload.error[:64],
                    "last_error_message": err_msg[:500],
                },
            )
            return self.to_response(profile, platform, conn)

        if not payload.code or not payload.code.strip():
            raise ValidationAppError("OAuth authorization code is missing.")

        adapter = self.registry.get(platform.platform_key, publishing_method="api")
        decrypted = self._decrypt_profile_credentials(profile)
        verifier = (
            decrypt_secret(state_row.encrypted_code_verifier, self.settings.app_encryption_key)
            if state_row.encrypted_code_verifier
            else None
        )
        try:
            cb_res = adapter.exchange_oauth_code(
                credentials=decrypted,
                code=payload.code.strip(),
                redirect_uri=state_row.redirect_uri,
                code_verifier=verifier,
            )
        except PublisherError as exc:
            self.pub_repo.update_oauth_state(state_row.id, {"status": "failed"})
            self.pub_repo.upsert_connection(
                social_profile_id=profile.id,
                website_id=profile.website_id,
                platform_id=platform.id,
                data={
                    "connection_status": "error",
                    "last_error_code": exc.code[:64],
                    "last_error_message": exc.message[:500],
                },
            )
            raise ValidationAppError(exc.message, code=exc.code) from exc

        self.pub_repo.update_oauth_state(
            state_row.id,
            {"status": "consumed", "consumed_at": utc_now_naive()},
        )
        profile = self._store_encrypted_credentials(
            profile,
            {
                "access_token": cb_res.access_token,
                "refresh_token": cb_res.refresh_token,
            },
            token_expires_at=cb_res.token_expires_at,
        )
        now = utc_now_naive()
        prof_update: dict[str, Any] = {
            "publishing_method": "api",
            "credential_status": "verified",
            "granted_permissions_json": list(cb_res.granted_scopes),
            "last_verified_at": now,
            "last_connection_error": None,
        }
        if cb_res.external_account_id:
            prof_update["external_account_id"] = cb_res.external_account_id
        if cb_res.profile_url:
            prof_update["profile_url"] = cb_res.profile_url
        profile = self.profile_repo.update(profile.id, prof_update) or profile

        safe_targets = [
            {
                "target_id": t.target_id,
                "name": t.name,
                "account_type": t.account_type,
                "profile_url": t.profile_url,
                "metadata": dict(t.metadata),
            }
            for t in cb_res.available_targets
        ]
        conn_status = (
            "connected"
            if (cb_res.target_resource_id or not adapter.capabilities.supports_target_selection)
            else "configured"
        )
        existing_conn = self.pub_repo.get_connection_by_profile_id(profile.id)
        needs_paid_opt_in = adapter.capabilities.requires_paid_api_ack and not (
            existing_conn.allow_paid_publishing if existing_conn else False
        )
        elig_status = (
            "manual_only"
            if needs_paid_opt_in
            else ("eligible" if conn_status == "connected" else "unverified")
        )
        elig_notes = (
            "Paid pay-per-use API acknowledgment disabled — enable Paid API "
            "or use Manual Publishing."
            if needs_paid_opt_in
            else (
                "OAuth verified."
                if conn_status == "connected"
                else "OAuth completed; select a target resource to finalize connection."
            )
        )
        conn = self.pub_repo.upsert_connection(
            social_profile_id=profile.id,
            website_id=profile.website_id,
            platform_id=platform.id,
            data={
                "auth_type": adapter.capabilities.platform_key,
                "connection_status": conn_status,
                "account_type": cb_res.account_type,
                "external_account_id": cb_res.external_account_id,
                "external_username": cb_res.external_username,
                "external_display_name": cb_res.external_display_name,
                "profile_url": cb_res.profile_url,
                "target_resource_id": cb_res.target_resource_id,
                "target_resource_name": cb_res.target_resource_name,
                "available_targets_json": safe_targets,
                "granted_scopes_json": list(cb_res.granted_scopes),
                "required_scopes_json": list(adapter.capabilities.required_scopes),
                "missing_scopes_json": [],
                "eligibility_status": elig_status,
                "eligibility_notes": elig_notes,
                "access_tier": cb_res.access_tier,
                "api_version": adapter.api_version,
                "token_expires_at": cb_res.token_expires_at,
                "refresh_token_expires_at": cb_res.refresh_token_expires_at,
                "last_verified_at": now,
                "last_tested_at": now,
                "last_error_code": None,
                "last_error_message": None,
                "metadata_json": dict(cb_res.metadata),
            },
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_profiles",
            action="social_profile.oauth_connected",
            level="info",
            message=f"Connected {platform.display_name} OAuth for '{profile.profile_name}'.",
            metadata={"social_profile_id": profile.id, "target": cb_res.target_resource_id},
            ip_address=ip_address,
        )
        return self.to_response(profile, platform, conn)

    def select_target(
        self,
        profile_id: int,
        payload: SelectTargetRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialProfileConnectionResponse:
        profile, platform = self._load_profile_and_platform(profile_id)
        conn = self.get_or_init_connection(profile, platform)
        chosen_id = payload.target_resource_id.strip()
        chosen_name = (payload.target_resource_name or "").strip() or None
        chosen_url = conn.profile_url
        for t in conn.available_targets_json or []:
            if isinstance(t, dict) and str(t.get("target_id")) == chosen_id:
                chosen_name = chosen_name or t.get("name")
                chosen_url = t.get("profile_url") or chosen_url
                break

        # If Facebook Page selected with user token stored in encrypted_refresh_token, exchange
        # safely via /me/accounts for that Page's dedicated Page Access Token.
        if platform.platform_key == "facebook" and profile.encrypted_refresh_token:
            user_token = decrypt_secret(
                profile.encrypted_refresh_token, self.settings.app_encryption_key
            )
            adapter = self.registry.get("facebook", publishing_method="api")
            pages_resp = adapter.http.request(
                "GET",
                f"https://graph.facebook.com/{adapter.api_version}/me/accounts",
                params={"fields": "id,name,link,access_token", "access_token": user_token},
            )
            if pages_resp.status_code == 200:
                for page in pages_resp.json().get("data") or []:
                    if str(page.get("id")) == chosen_id and page.get("access_token"):
                        profile = self._store_encrypted_credentials(
                            profile,
                            {"access_token": str(page["access_token"])},
                        )
                        chosen_name = chosen_name or page.get("name")
                        chosen_url = page.get("link") or chosen_url
                        break

        self.profile_repo.update(
            profile.id,
            {
                "external_account_id": chosen_id,
                "profile_url": chosen_url,
            },
        )
        self.pub_repo.upsert_connection(
            social_profile_id=profile.id,
            website_id=profile.website_id,
            platform_id=platform.id,
            data={
                "target_resource_id": chosen_id,
                "target_resource_name": chosen_name or chosen_id,
                "external_account_id": chosen_id,
                "profile_url": chosen_url,
                "connection_status": "connected",
            },
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_profiles",
            action="social_profile.target_selected",
            level="info",
            message=f"Selected target '{chosen_name or chosen_id}' for '{profile.profile_name}'.",
            metadata={"social_profile_id": profile.id, "target_resource_id": chosen_id},
            ip_address=ip_address,
        )
        return self.verify_connection(profile.id, user_id=user_id, ip_address=ip_address)

    def verify_connection(
        self,
        profile_id: int,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialProfileConnectionResponse:
        profile, platform = self._load_profile_and_platform(profile_id)
        conn = self.get_or_init_connection(profile, platform)
        adapter = self.registry.get(
            platform.platform_key, publishing_method=profile.publishing_method
        )
        decrypted = self._decrypt_profile_credentials(profile)
        now = utc_now_naive()
        try:
            res = adapter.verify_connection(
                credentials=decrypted,
                external_account_id=profile.external_account_id,
                target_resource_id=conn.target_resource_id,
                metadata={
                    **dict(conn.metadata_json or {}),
                    "allow_paid_publishing": conn.allow_paid_publishing,
                },
            )
        except PublisherError as exc:
            err_status = (
                "expired"
                if exc.error_category == "expired_credentials"
                else (
                    "missing_permissions"
                    if exc.error_category == "missing_permissions"
                    else (
                        "restricted"
                        if exc.error_category in {"unsupported_account", "policy_restriction"}
                        else "error"
                    )
                )
            )
            self.profile_repo.update(
                profile.id,
                {
                    "credential_status": err_status,
                    "publishing_eligibility_status": (
                        "restricted"
                        if exc.error_category in {"unsupported_account", "policy_restriction"}
                        else "unverified"
                    ),
                    "publishing_eligibility_reason": exc.message,
                    "last_connection_error": exc.message,
                },
            )
            updated_conn = self.pub_repo.upsert_connection(
                social_profile_id=profile.id,
                website_id=profile.website_id,
                platform_id=platform.id,
                data={
                    "connection_status": err_status,
                    "last_tested_at": now,
                    "last_error_code": exc.code[:64],
                    "last_error_message": exc.message[:500],
                },
            )
            self.activity_repo.create(
                user_id=user_id,
                actor_type="admin",
                category="social_profiles",
                action="social_profile.verify_failed",
                level="warning",
                message=f"Verification failed for '{profile.profile_name}': {exc.message}",
                metadata={"social_profile_id": profile.id, "error_code": exc.code},
                ip_address=ip_address,
            )
            return self.to_response(profile, platform, updated_conn)

        safe_targets = [
            {
                "target_id": t.target_id,
                "name": t.name,
                "account_type": t.account_type,
                "profile_url": t.profile_url,
                "metadata": dict(t.metadata),
            }
            for t in res.available_targets
        ]
        prof_updates: dict[str, Any] = {
            "credential_status": "verified" if res.connected else "configured",
            "granted_permissions_json": res.granted_scopes,
            "publishing_eligibility_status": res.eligibility_status,
            "publishing_eligibility_reason": res.eligibility_notes,
            "last_verified_at": now,
            "last_connection_error": None,
        }
        if res.external_account_id:
            prof_updates["external_account_id"] = res.external_account_id
        if res.profile_url:
            prof_updates["profile_url"] = res.profile_url
        if res.token_expires_at is not None:
            prof_updates["token_expires_at"] = res.token_expires_at
        profile = self.profile_repo.update(profile.id, prof_updates) or profile

        conn_data: dict[str, Any] = {
            "connection_status": res.connection_status,
            "account_type": res.account_type or conn.account_type,
            "external_account_id": res.external_account_id or conn.external_account_id,
            "external_username": res.external_username or conn.external_username,
            "external_display_name": res.external_display_name or conn.external_display_name,
            "profile_url": res.profile_url or conn.profile_url,
            "target_resource_id": res.target_resource_id or conn.target_resource_id,
            "target_resource_name": res.target_resource_name or conn.target_resource_name,
            "granted_scopes_json": res.granted_scopes,
            "required_scopes_json": list(adapter.capabilities.required_scopes),
            "missing_scopes_json": res.missing_scopes,
            "eligibility_status": res.eligibility_status,
            "eligibility_notes": res.eligibility_notes,
            "access_tier": res.access_tier or conn.access_tier,
            "api_version": adapter.api_version,
            "last_tested_at": now,
            "last_verified_at": now if res.connected else conn.last_verified_at,
            "last_error_code": res.error_code,
            "last_error_message": res.error_message,
            "metadata_json": {**dict(conn.metadata_json or {}), **dict(res.metadata)},
        }
        if safe_targets:
            conn_data["available_targets_json"] = safe_targets
        if res.token_expires_at is not None:
            conn_data["token_expires_at"] = res.token_expires_at

        updated_conn = self.pub_repo.upsert_connection(
            social_profile_id=profile.id,
            website_id=profile.website_id,
            platform_id=platform.id,
            data=conn_data,
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_profiles",
            action="social_profile.verified",
            level="info",
            message=(
                f"Verified {platform.display_name} profile '{profile.profile_name}' "
                f"({res.connection_status})."
            ),
            metadata={"social_profile_id": profile.id, "eligibility": res.eligibility_status},
            ip_address=ip_address,
        )
        return self.to_response(profile, platform, updated_conn)

    def refresh_connection(
        self,
        profile_id: int,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialProfileConnectionResponse:
        profile, platform = self._load_profile_and_platform(profile_id)
        if profile.publishing_method == "manual" or platform.platform_key == "custom_social":
            return self.verify_connection(profile.id, user_id=user_id, ip_address=ip_address)
        adapter = self.registry.get(platform.platform_key, publishing_method="api")
        decrypted = self._decrypt_profile_credentials(profile)
        try:
            refreshed = adapter.refresh_credentials(credentials=decrypted)
        except PublisherError as exc:
            self.pub_repo.upsert_connection(
                social_profile_id=profile.id,
                website_id=profile.website_id,
                platform_id=platform.id,
                data={
                    "connection_status": "expired"
                    if exc.error_category == "expired_credentials"
                    else "error",
                    "last_error_code": exc.code[:64],
                    "last_error_message": exc.message[:500],
                },
            )
            raise ValidationAppError(exc.message, code=exc.code) from exc

        profile = self._store_encrypted_credentials(
            profile,
            {
                "access_token": refreshed.access_token,
                "refresh_token": refreshed.refresh_token,
            },
            token_expires_at=refreshed.token_expires_at,
        )
        self.pub_repo.upsert_connection(
            social_profile_id=profile.id,
            website_id=profile.website_id,
            platform_id=platform.id,
            data={
                "token_expires_at": refreshed.token_expires_at,
                "last_refreshed_at": utc_now_naive(),
                "last_error_code": None,
                "last_error_message": None,
            },
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_profiles",
            action="social_profile.refreshed",
            level="info",
            message=f"Refreshed credentials for '{profile.profile_name}'.",
            metadata={"social_profile_id": profile.id},
            ip_address=ip_address,
        )
        return self.verify_connection(profile.id, user_id=user_id, ip_address=ip_address)

    def disconnect_account(
        self,
        profile_id: int,
        payload: DisconnectAccountRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialProfileConnectionResponse:
        profile, platform = self._load_profile_and_platform(profile_id)
        updates: dict[str, Any] = {
            "granted_permissions_json": [],
            "last_connection_error": None,
        }
        if payload.clear_credentials:
            for col in CREDENTIAL_COLUMN_MAP.values():
                updates[col] = None
            updates["token_expires_at"] = None
            updates["credential_status"] = "not_configured"
        if payload.switch_to_manual:
            updates["publishing_method"] = "manual"
            updates["publishing_eligibility_status"] = "manual_only"
        else:
            updates["publishing_eligibility_status"] = "unknown"

        profile = self.profile_repo.update(profile.id, updates) or profile
        conn = self.pub_repo.upsert_connection(
            social_profile_id=profile.id,
            website_id=profile.website_id,
            platform_id=platform.id,
            data={
                "connection_status": "configured" if payload.switch_to_manual else "disconnected",
                "eligibility_status": "manual_only" if payload.switch_to_manual else "unknown",
                "eligibility_notes": (
                    "Switched to Manual Publishing."
                    if payload.switch_to_manual
                    else "Account disconnected by administrator."
                ),
                "target_resource_id": None,
                "target_resource_name": None,
                "available_targets_json": [],
                "granted_scopes_json": [],
                "missing_scopes_json": [],
                "token_expires_at": None if payload.clear_credentials else profile.token_expires_at,
                "refresh_token_expires_at": None,
                "last_error_code": None,
                "last_error_message": None,
            },
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_profiles",
            action="social_profile.disconnected",
            level="warning",
            message=f"Disconnected external account from '{profile.profile_name}'.",
            metadata={
                "social_profile_id": profile.id,
                "cleared_credentials": payload.clear_credentials,
            },
            ip_address=ip_address,
        )
        return self.to_response(profile, platform, conn)

    def set_paid_publishing(
        self,
        profile_id: int,
        *,
        allow_paid_publishing: bool,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialProfileConnectionResponse:
        profile, platform = self._load_profile_and_platform(profile_id)
        conn = self.get_or_init_connection(profile, platform)
        adapter = self.registry.get(platform.platform_key, publishing_method="api")
        paid_eligibility = (
            "manual_only"
            if (adapter.capabilities.requires_paid_api_ack and not allow_paid_publishing)
            else conn.eligibility_status
        )
        conn = self.pub_repo.upsert_connection(
            social_profile_id=profile.id,
            website_id=profile.website_id,
            platform_id=platform.id,
            data={
                "allow_paid_publishing": allow_paid_publishing,
                "eligibility_status": paid_eligibility,
            },
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_profiles",
            action="social_profile.paid_policy_updated",
            level="warning" if allow_paid_publishing else "info",
            message=(
                f"{'Enabled' if allow_paid_publishing else 'Disabled'} paid API publishing opt-in "
                f"for '{profile.profile_name}'."
            ),
            metadata={"social_profile_id": profile.id, "allow_paid": allow_paid_publishing},
            ip_address=ip_address,
        )
        if profile.encrypted_access_token or profile.encrypted_api_key:
            return self.verify_connection(profile.id, user_id=user_id, ip_address=ip_address)
        return self.to_response(profile, platform, conn)
