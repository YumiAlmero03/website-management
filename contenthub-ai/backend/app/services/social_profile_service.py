from __future__ import annotations

import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.security import decrypt_secret, encrypt_secret, mask_secret_hint
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.platform import Platform
from app.models.social_profile import SocialProfile
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.publishing_repo import PublishingRepositoryProtocol
from app.repositories.social_profile_repo import SocialProfileRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.social_profile import (
    ALLOWED_PREFERRED_LENGTHS,
    ALLOWED_PUBLISHING_METHODS,
    CredentialFieldMaskResponse,
    PlatformResponse,
    SocialProfileCreateRequest,
    SocialProfileCredentialsInput,
    SocialProfileResponse,
    SocialProfileUpdateRequest,
)

CREDENTIAL_COLUMN_MAP: dict[str, str] = {
    "api_key": "encrypted_api_key",
    "api_secret": "encrypted_api_secret",
    "access_token": "encrypted_access_token",
    "refresh_token": "encrypted_refresh_token",
    "app_id": "encrypted_app_id",
    "app_secret": "encrypted_app_secret",
}
ALLOWED_PUBLISHING_DAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIME_HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _normalize_days(days: list[str] | None) -> list[str]:
    if not days:
        return []
    out: list[str] = []
    for raw in days:
        val = str(raw).strip().lower()[:3]
        if val not in ALLOWED_PUBLISHING_DAYS:
            raise ValidationAppError(
                f"Invalid preferred publishing day '{raw}'. Use mon..sun."
            )
        if val not in out:
            out.append(val)
    return out


def _normalize_times(times: list[str] | None) -> list[str]:
    if not times:
        return []
    out: list[str] = []
    for raw in times:
        val = str(raw).strip()
        if not TIME_HHMM_RE.match(val):
            raise ValidationAppError(
                f"Invalid preferred publishing time '{raw}'. Use 24h HH:MM format."
            )
        if val not in out:
            out.append(val)
    return out


class SocialProfileService:
    """Manages website-owned social destination profiles and Fernet-encrypted credentials."""

    def __init__(
        self,
        *,
        settings: Settings,
        social_profile_repo: SocialProfileRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        publishing_repo: PublishingRepositoryProtocol | None = None,
    ) -> None:
        self.settings = settings
        self.repo = social_profile_repo
        self.website_repo = website_repo
        self.activity_repo = activity_repo
        self.pub_repo = publishing_repo

    @staticmethod
    def _to_platform_response(p: Platform) -> PlatformResponse:
        return PlatformResponse(
            id=p.id,
            platform_key=p.platform_key,
            display_name=p.display_name,
            category=p.category,
            default_max_chars=p.default_max_chars,
            url_counts_as_chars=p.url_counts_as_chars,
            supports_hashtags=p.supports_hashtags,
            supports_cta=p.supports_cta,
            supports_source_url=p.supports_source_url,
            supports_title=p.supports_title,
            supports_media=p.supports_media,
            supports_free_auto_publish=p.supports_free_auto_publish,
            credential_fields=list(p.credential_fields_json or []),
            capabilities=dict(p.capabilities_json or {}),
            is_enabled=p.is_enabled,
            sort_order=p.sort_order,
        )

    def _mask_credentials(
        self, profile: SocialProfile, platform: Platform
    ) -> tuple[list[CredentialFieldMaskResponse], bool]:
        allowed = list(platform.credential_fields_json or [])
        masks: list[CredentialFieldMaskResponse] = []
        any_set = False
        for field_name in allowed:
            col = CREDENTIAL_COLUMN_MAP.get(field_name)
            if not col:
                continue
            ciphertext = getattr(profile, col, None)
            if not ciphertext:
                masks.append(
                    CredentialFieldMaskResponse(
                        field=field_name, configured=False, masked_value=None
                    )
                )
                continue
            any_set = True
            masked: str | None = "••••••••"
            try:
                plain = decrypt_secret(ciphertext, self.settings.app_encryption_key)
                masked = mask_secret_hint(plain) or "••••••••"
            except Exception:
                masked = "••••••••"
            masks.append(
                CredentialFieldMaskResponse(field=field_name, configured=True, masked_value=masked)
            )
        return masks, any_set

    def _to_response(self, profile: SocialProfile) -> SocialProfileResponse:
        now = utc_now()
        platform = self.repo.get_platform_by_id(profile.platform_id)
        if platform is None:
            raise NotFoundError(f"Platform #{profile.platform_id} not found.")
        site = self.website_repo.get_by_id(profile.website_id)
        masks, has_creds = self._mask_credentials(profile, platform)
        effective_lang = profile.custom_language or (site.primary_language if site else "en")
        effective_limit = (
            profile.character_limit
            if profile.character_limit is not None
            else platform.default_max_chars
        )
        conn = self.pub_repo.get_connection_by_profile_id(profile.id) if self.pub_repo else None
        latest_pub = (
            self.pub_repo.get_latest_for_profile(profile.id) if self.pub_repo else None
        )
        last_published = profile.last_published_at or (
            latest_pub.published_at if latest_pub else None
        )
        default_conn_status = (
            "configured"
            if profile.publishing_method == "manual" or has_creds
            else "not_connected"
        )
        conn_status = conn.connection_status if conn else default_conn_status
        elig_status = (
            conn.eligibility_status
            if conn
            else (
                "manual_only"
                if profile.publishing_method == "manual"
                else profile.publishing_eligibility_status
            )
        )

        return SocialProfileResponse(
            id=profile.id,
            website_id=profile.website_id,
            website_name=site.name if site else None,
            platform_id=profile.platform_id,
            platform_key=platform.platform_key,
            platform_display_name=platform.display_name,
            profile_name=profile.profile_name,
            profile_url=conn.profile_url if conn and conn.profile_url else profile.profile_url,
            external_account_id=(
                conn.external_account_id
                if conn and conn.external_account_id
                else profile.external_account_id
            ),
            profile_image_url=profile.profile_image_url,
            is_active=profile.is_active,
            publishing_method=profile.publishing_method,
            credential_status=profile.credential_status,
            generation_enabled=profile.generation_enabled,
            automatic_generation_enabled=profile.automatic_generation_enabled,
            auto_publish_enabled=False,
            auto_publish_available=False,
            publishing_enabled=profile.publishing_enabled,
            display_timezone=profile.display_timezone,
            effective_timezone=profile.display_timezone or self.settings.app_timezone,
            preferred_publishing_days=list(profile.preferred_publishing_days or []),
            preferred_publishing_times=list(profile.preferred_publishing_times or []),
            daily_publishing_limit=profile.daily_publishing_limit,
            min_interval_minutes=profile.min_interval_minutes,
            require_approval_before_publish=profile.require_approval_before_publish,
            default_media_required=profile.default_media_required,
            connection_status=conn_status,
            granted_permissions=list(
                (conn.granted_scopes_json if conn else None)
                or profile.granted_permissions_json
                or []
            ),
            missing_permissions=list(conn.missing_scopes_json or []) if conn else [],
            publishing_eligibility_status=elig_status,
            publishing_eligibility_reason=(
                conn.eligibility_notes if conn else profile.publishing_eligibility_reason
            ),
            target_resource_id=conn.target_resource_id if conn else None,
            target_resource_name=conn.target_resource_name if conn else None,
            allow_paid_publishing=bool(conn.allow_paid_publishing) if conn else False,
            last_verified_at=ensure_utc(
                conn.last_verified_at
                if conn and conn.last_verified_at
                else profile.last_verified_at
            ),
            last_published_at=ensure_utc(last_published),
            last_connection_error=(
                conn.last_error_message
                if conn and conn.last_error_message
                else profile.last_connection_error
            ),
            capabilities=dict(platform.capabilities_json or {}),
            custom_language=profile.custom_language,
            effective_language=effective_lang,
            writing_tone=profile.writing_tone,
            platform_ai_instructions=profile.platform_ai_instructions,
            default_hashtags=list(profile.default_hashtags or []),
            default_cta=profile.default_cta,
            preferred_length=profile.preferred_length,
            character_limit=profile.character_limit,
            effective_character_limit=effective_limit,
            include_source_url=profile.include_source_url,
            include_hashtags=profile.include_hashtags,
            include_emojis=profile.include_emojis,
            content_restrictions=profile.content_restrictions,
            credential_masks=masks,
            has_credentials=has_creds,
            allowed_credential_fields=list(platform.credential_fields_json or []),
            token_expires_at=ensure_utc(profile.token_expires_at),
            credentials_updated_at=ensure_utc(profile.credentials_updated_at),
            created_at=ensure_utc(profile.created_at) or now,
            updated_at=ensure_utc(profile.updated_at) or now,
        )

    def _apply_credentials(
        self,
        *,
        creds: SocialProfileCredentialsInput,
        platform: Platform,
        existing: SocialProfile | None,
        updates: dict[str, Any],
    ) -> None:
        allowed_fields = set(platform.credential_fields_json or [])
        clear_set = {f.strip() for f in creds.clear_fields if f.strip()}
        changed = False

        for field_name, col in CREDENTIAL_COLUMN_MAP.items():
            if field_name not in allowed_fields:
                continue
            if field_name in clear_set:
                updates[col] = None
                changed = True
                continue
            raw_val = getattr(creds, field_name, None)
            if raw_val is not None and raw_val.strip():
                updates[col] = encrypt_secret(raw_val.strip(), self.settings.app_encryption_key)
                changed = True

        if creds.token_expires_at is not None:
            updates["token_expires_at"] = creds.token_expires_at.replace(tzinfo=None)
            changed = True

        # Recompute credential_status accurately (never implies verified live connection)
        resulting_cols = []
        for field_name in allowed_fields:
            col = CREDENTIAL_COLUMN_MAP.get(field_name)
            if not col:
                continue
            val = updates.get(col, getattr(existing, col, None) if existing else None)
            if val:
                resulting_cols.append(col)

        if resulting_cols:
            updates["credential_status"] = "configured"
        else:
            updates["credential_status"] = "not_configured"
        if changed:
            updates["credentials_updated_at"] = utc_now_naive()

    def list_platforms(self) -> list[PlatformResponse]:
        return [self._to_platform_response(p) for p in self.repo.list_platforms(enabled_only=True)]

    def list_for_website(self, website_id: int) -> list[SocialProfileResponse]:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        return [self._to_response(row) for row in self.repo.list_for_website(website_id)]

    def list_all(self, *, website_id: int | None = None) -> list[SocialProfileResponse]:
        return [self._to_response(row) for row in self.repo.list_all(website_id=website_id)]

    def get_profile(self, profile_id: int) -> SocialProfileResponse:
        row = self.repo.get_by_id(profile_id)
        if row is None:
            raise NotFoundError(f"Social profile #{profile_id} not found.")
        return self._to_response(row)

    def create_profile(
        self,
        website_id: int,
        payload: SocialProfileCreateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialProfileResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        platform = self.repo.get_platform_by_key(payload.platform_key)
        if platform is None:
            raise ValidationAppError(f"Unsupported social platform '{payload.platform_key}'.")

        pub_method = payload.publishing_method.strip().lower()
        if pub_method not in ALLOWED_PUBLISHING_METHODS:
            raise ValidationAppError("Publishing method must be 'manual' or 'api'.")
        if payload.auto_publish_enabled:
            raise ValidationAppError(
                "Automatic external publishing is disabled in Phase 3 and remains out of scope."
            )
        if payload.preferred_length and payload.preferred_length not in ALLOWED_PREFERRED_LENGTHS:
            raise ValidationAppError("Preferred length must be 'short', 'medium', or 'long'.")
        if payload.display_timezone:
            try:
                ZoneInfo(payload.display_timezone.strip())
            except ZoneInfoNotFoundError as exc:
                raise ValidationAppError(
                    f"Invalid IANA display_timezone '{payload.display_timezone}'."
                ) from exc
        pref_days = _normalize_days(payload.preferred_publishing_days)
        pref_times = _normalize_times(payload.preferred_publishing_times)

        data: dict[str, Any] = {
            "website_id": website_id,
            "platform_id": platform.id,
            "profile_name": payload.profile_name.strip(),
            "profile_url": payload.profile_url.strip() if payload.profile_url else None,
            "external_account_id": (
                payload.external_account_id.strip() if payload.external_account_id else None
            ),
            "profile_image_url": (
                payload.profile_image_url.strip() if payload.profile_image_url else None
            ),
            "is_active": payload.is_active,
            "publishing_method": pub_method,
            "credential_status": "not_configured",
            "generation_enabled": payload.generation_enabled,
            "automatic_generation_enabled": payload.automatic_generation_enabled,
            "auto_publish_enabled": False,
            "publishing_enabled": payload.publishing_enabled,
            "display_timezone": (
                payload.display_timezone.strip() if payload.display_timezone else None
            ),
            "preferred_publishing_days": pref_days,
            "preferred_publishing_times": pref_times,
            "daily_publishing_limit": payload.daily_publishing_limit,
            "min_interval_minutes": payload.min_interval_minutes,
            "require_approval_before_publish": payload.require_approval_before_publish,
            "default_media_required": payload.default_media_required,
            "publishing_eligibility_status": "manual_only" if pub_method == "manual" else "unknown",
            "custom_language": payload.custom_language.strip() if payload.custom_language else None,
            "writing_tone": payload.writing_tone.strip() if payload.writing_tone else None,
            "platform_ai_instructions": (
                payload.platform_ai_instructions.strip()
                if payload.platform_ai_instructions
                else None
            ),
            "default_hashtags": [h.strip() for h in payload.default_hashtags if h.strip()],
            "default_cta": payload.default_cta.strip() if payload.default_cta else None,
            "preferred_length": payload.preferred_length or "medium",
            "character_limit": payload.character_limit,
            "include_source_url": payload.include_source_url,
            "include_hashtags": payload.include_hashtags,
            "include_emojis": payload.include_emojis,
            "content_restrictions": (
                payload.content_restrictions.strip() if payload.content_restrictions else None
            ),
        }

        if payload.credentials is not None:
            self._apply_credentials(
                creds=payload.credentials, platform=platform, existing=None, updates=data
            )

        created = self.repo.create(data)
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_profiles",
            action="social_profile.created",
            level="info",
            message=(
                f"Configured {platform.display_name} profile '{created.profile_name}' "
                f"for '{site.name}' ({created.publishing_method})."
            ),
            metadata={
                "website_id": website_id,
                "social_profile_id": created.id,
                "platform": platform.platform_key,
                "has_credentials": created.credential_status == "configured",
            },
            ip_address=ip_address,
        )
        return self._to_response(created)

    def update_profile(
        self,
        profile_id: int,
        payload: SocialProfileUpdateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialProfileResponse:
        existing = self.repo.get_by_id(profile_id)
        if existing is None:
            raise NotFoundError(f"Social profile #{profile_id} not found.")
        platform = self.repo.get_platform_by_id(existing.platform_id)
        if platform is None:
            raise NotFoundError(f"Platform #{existing.platform_id} not found.")

        if payload.auto_publish_enabled:
            raise ValidationAppError(
                "Automatic external publishing is disabled in Phase 3 and remains out of scope."
            )

        updates: dict[str, Any] = {}
        if payload.profile_name is not None:
            updates["profile_name"] = payload.profile_name.strip()
        if payload.profile_url is not None:
            updates["profile_url"] = payload.profile_url.strip() or None
        if payload.external_account_id is not None:
            updates["external_account_id"] = payload.external_account_id.strip() or None
        if payload.profile_image_url is not None:
            updates["profile_image_url"] = payload.profile_image_url.strip() or None
        if payload.is_active is not None:
            updates["is_active"] = payload.is_active
        if payload.publishing_method is not None:
            pm = payload.publishing_method.strip().lower()
            if pm not in ALLOWED_PUBLISHING_METHODS:
                raise ValidationAppError("Publishing method must be 'manual' or 'api'.")
            updates["publishing_method"] = pm
        if payload.generation_enabled is not None:
            updates["generation_enabled"] = payload.generation_enabled
        if payload.automatic_generation_enabled is not None:
            updates["automatic_generation_enabled"] = payload.automatic_generation_enabled
        updates["auto_publish_enabled"] = False
        if payload.publishing_enabled is not None:
            updates["publishing_enabled"] = payload.publishing_enabled
        if payload.clear_display_timezone:
            updates["display_timezone"] = None
        elif payload.display_timezone is not None:
            tz_val = payload.display_timezone.strip()
            if tz_val:
                try:
                    ZoneInfo(tz_val)
                except ZoneInfoNotFoundError as exc:
                    raise ValidationAppError(f"Invalid IANA timezone '{tz_val}'.") from exc
                updates["display_timezone"] = tz_val
            else:
                updates["display_timezone"] = None
        if payload.preferred_publishing_days is not None:
            updates["preferred_publishing_days"] = _normalize_days(
                payload.preferred_publishing_days
            )
        if payload.preferred_publishing_times is not None:
            updates["preferred_publishing_times"] = _normalize_times(
                payload.preferred_publishing_times
            )
        if payload.clear_daily_publishing_limit:
            updates["daily_publishing_limit"] = None
        elif payload.daily_publishing_limit is not None:
            updates["daily_publishing_limit"] = payload.daily_publishing_limit
        if payload.clear_min_interval_minutes:
            updates["min_interval_minutes"] = None
        elif payload.min_interval_minutes is not None:
            updates["min_interval_minutes"] = payload.min_interval_minutes
        if payload.require_approval_before_publish is not None:
            updates["require_approval_before_publish"] = payload.require_approval_before_publish
        if payload.default_media_required is not None:
            updates["default_media_required"] = payload.default_media_required
        if payload.clear_custom_language:
            updates["custom_language"] = None
        elif payload.custom_language is not None:
            updates["custom_language"] = payload.custom_language.strip() or None
        if payload.writing_tone is not None:
            updates["writing_tone"] = payload.writing_tone.strip() or None
        if payload.platform_ai_instructions is not None:
            updates["platform_ai_instructions"] = payload.platform_ai_instructions.strip() or None
        if payload.default_hashtags is not None:
            updates["default_hashtags"] = [h.strip() for h in payload.default_hashtags if h.strip()]
        if payload.default_cta is not None:
            updates["default_cta"] = payload.default_cta.strip() or None
        if payload.preferred_length is not None:
            if payload.preferred_length not in ALLOWED_PREFERRED_LENGTHS:
                raise ValidationAppError("Preferred length must be 'short', 'medium', or 'long'.")
            updates["preferred_length"] = payload.preferred_length
        if payload.clear_character_limit:
            updates["character_limit"] = None
        elif payload.character_limit is not None:
            updates["character_limit"] = payload.character_limit
        if payload.include_source_url is not None:
            updates["include_source_url"] = payload.include_source_url
        if payload.include_hashtags is not None:
            updates["include_hashtags"] = payload.include_hashtags
        if payload.include_emojis is not None:
            updates["include_emojis"] = payload.include_emojis
        if payload.content_restrictions is not None:
            updates["content_restrictions"] = payload.content_restrictions.strip() or None

        if payload.credentials is not None:
            self._apply_credentials(
                creds=payload.credentials,
                platform=platform,
                existing=existing,
                updates=updates,
            )

        updated = self.repo.update(profile_id, updates)
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_profiles",
            action="social_profile.updated",
            level="info",
            message=f"Updated {platform.display_name} profile '{updated.profile_name}'.",
            metadata={
                "website_id": updated.website_id,
                "social_profile_id": updated.id,
                "credential_status": updated.credential_status,
            },
            ip_address=ip_address,
        )
        return self._to_response(updated)

    def delete_profile(
        self,
        profile_id: int,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> None:
        existing = self.repo.get_by_id(profile_id)
        if existing is None:
            raise NotFoundError(f"Social profile #{profile_id} not found.")
        ok = self.repo.delete(profile_id)
        if not ok:
            raise NotFoundError(f"Social profile #{profile_id} not found.")
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_profiles",
            action="social_profile.deleted",
            level="warning",
            message=f"Deleted social profile '{existing.profile_name}' (#{profile_id}).",
            metadata={"website_id": existing.website_id, "social_profile_id": profile_id},
            ip_address=ip_address,
        )
