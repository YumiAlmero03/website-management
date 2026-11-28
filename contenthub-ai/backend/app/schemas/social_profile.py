from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

ALLOWED_PUBLISHING_METHODS: tuple[str, ...] = ("manual", "api")
ALLOWED_PREFERRED_LENGTHS: tuple[str, ...] = ("short", "medium", "long")


class PlatformResponse(BaseModel):
    id: int
    platform_key: str
    display_name: str
    category: str
    default_max_chars: int | None = None
    url_counts_as_chars: int | None = None
    supports_hashtags: bool = True
    supports_cta: bool = True
    supports_source_url: bool = True
    supports_title: bool = False
    supports_media: bool = True
    supports_free_auto_publish: bool = False
    credential_fields: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    sort_order: int = 100


class SocialProfileCredentialsInput(BaseModel):
    api_key: str | None = Field(default=None, max_length=1000)
    api_secret: str | None = Field(default=None, max_length=1000)
    access_token: str | None = Field(default=None, max_length=4000)
    refresh_token: str | None = Field(default=None, max_length=4000)
    app_id: str | None = Field(default=None, max_length=500)
    app_secret: str | None = Field(default=None, max_length=1000)
    token_expires_at: datetime | None = None
    clear_fields: list[str] = Field(default_factory=list)


class CredentialFieldMaskResponse(BaseModel):
    field: str
    configured: bool
    masked_value: str | None = None


class SocialProfileCreateRequest(BaseModel):
    platform_key: str = Field(min_length=2, max_length=64)
    profile_name: str = Field(min_length=2, max_length=150)
    profile_url: str | None = Field(default=None, max_length=500)
    external_account_id: str | None = Field(default=None, max_length=255)
    profile_image_url: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    publishing_method: str = Field(default="manual", max_length=24)
    generation_enabled: bool = True
    automatic_generation_enabled: bool = False
    # External auto-publishing remains disabled by default
    auto_publish_enabled: bool = False
    publishing_enabled: bool = True
    display_timezone: str | None = Field(default=None, max_length=64)
    preferred_publishing_days: list[str] = Field(default_factory=list)
    preferred_publishing_times: list[str] = Field(default_factory=list)
    daily_publishing_limit: int | None = Field(default=None, ge=1, le=200)
    min_interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    require_approval_before_publish: bool = True
    default_media_required: bool = False
    custom_language: str | None = Field(default=None, max_length=32)
    writing_tone: str | None = Field(default=None, max_length=120)
    platform_ai_instructions: str | None = Field(default=None, max_length=5000)
    default_hashtags: list[str] = Field(default_factory=list)
    default_cta: str | None = Field(default=None, max_length=255)
    preferred_length: str | None = Field(default="medium", max_length=32)
    character_limit: int | None = Field(default=None, ge=40, le=65000)
    include_source_url: bool = True
    include_hashtags: bool = True
    include_emojis: bool = True
    content_restrictions: str | None = Field(default=None, max_length=4000)
    credentials: SocialProfileCredentialsInput | None = None


class SocialProfileUpdateRequest(BaseModel):
    profile_name: str | None = Field(default=None, min_length=2, max_length=150)
    profile_url: str | None = Field(default=None, max_length=500)
    external_account_id: str | None = Field(default=None, max_length=255)
    profile_image_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    publishing_method: str | None = Field(default=None, max_length=24)
    generation_enabled: bool | None = None
    automatic_generation_enabled: bool | None = None
    auto_publish_enabled: bool | None = None
    publishing_enabled: bool | None = None
    display_timezone: str | None = Field(default=None, max_length=64)
    clear_display_timezone: bool = False
    preferred_publishing_days: list[str] | None = None
    preferred_publishing_times: list[str] | None = None
    daily_publishing_limit: int | None = Field(default=None, ge=1, le=200)
    clear_daily_publishing_limit: bool = False
    min_interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    clear_min_interval_minutes: bool = False
    require_approval_before_publish: bool | None = None
    default_media_required: bool | None = None
    custom_language: str | None = Field(default=None, max_length=32)
    clear_custom_language: bool = False
    writing_tone: str | None = Field(default=None, max_length=120)
    platform_ai_instructions: str | None = Field(default=None, max_length=5000)
    default_hashtags: list[str] | None = None
    default_cta: str | None = Field(default=None, max_length=255)
    preferred_length: str | None = Field(default=None, max_length=32)
    character_limit: int | None = Field(default=None, ge=40, le=65000)
    clear_character_limit: bool = False
    include_source_url: bool | None = None
    include_hashtags: bool | None = None
    include_emojis: bool | None = None
    content_restrictions: str | None = Field(default=None, max_length=4000)
    credentials: SocialProfileCredentialsInput | None = None


class SocialProfileResponse(BaseModel):
    id: int
    website_id: int
    website_name: str | None = None
    platform_id: int
    platform_key: str
    platform_display_name: str
    profile_name: str
    profile_url: str | None = None
    external_account_id: str | None = None
    profile_image_url: str | None = None
    is_active: bool
    publishing_method: str
    credential_status: str
    generation_enabled: bool
    automatic_generation_enabled: bool
    auto_publish_enabled: bool = False
    auto_publish_available: bool = False
    publishing_enabled: bool = True
    display_timezone: str | None = None
    effective_timezone: str = "Asia/Manila"
    preferred_publishing_days: list[str] = Field(default_factory=list)
    preferred_publishing_times: list[str] = Field(default_factory=list)
    daily_publishing_limit: int | None = None
    min_interval_minutes: int | None = None
    require_approval_before_publish: bool = True
    default_media_required: bool = False
    connection_status: str = "not_connected"
    granted_permissions: list[str] = Field(default_factory=list)
    missing_permissions: list[str] = Field(default_factory=list)
    publishing_eligibility_status: str = "unknown"
    publishing_eligibility_reason: str | None = None
    target_resource_id: str | None = None
    target_resource_name: str | None = None
    allow_paid_publishing: bool = False
    last_verified_at: datetime | None = None
    last_published_at: datetime | None = None
    last_connection_error: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    custom_language: str | None = None
    effective_language: str = "en"
    writing_tone: str | None = None
    platform_ai_instructions: str | None = None
    default_hashtags: list[str] = Field(default_factory=list)
    default_cta: str | None = None
    preferred_length: str | None = None
    character_limit: int | None = None
    effective_character_limit: int | None = None
    include_source_url: bool = True
    include_hashtags: bool = True
    include_emojis: bool = True
    content_restrictions: str | None = None
    credential_masks: list[CredentialFieldMaskResponse] = Field(default_factory=list)
    has_credentials: bool = False
    allowed_credential_fields: list[str] = Field(default_factory=list)
    token_expires_at: datetime | None = None
    credentials_updated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
