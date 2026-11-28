from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import PaginationMeta


class TargetResourceResponse(BaseModel):
    target_id: str
    name: str
    account_type: str
    profile_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SocialProfileConnectionResponse(BaseModel):
    social_profile_id: int
    website_id: int
    platform_id: int
    platform_key: str
    platform_display_name: str
    auth_type: str
    connection_status: str
    account_type: str | None = None
    external_account_id: str | None = None
    external_username: str | None = None
    external_display_name: str | None = None
    profile_url: str | None = None
    target_resource_id: str | None = None
    target_resource_name: str | None = None
    available_targets: list[TargetResourceResponse] = Field(default_factory=list)
    granted_scopes: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    missing_scopes: list[str] = Field(default_factory=list)
    eligibility_status: str = "unknown"
    eligibility_notes: str | None = None
    access_tier: str | None = None
    allow_paid_publishing: bool = False
    api_version: str | None = None
    token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    expires_soon: bool = False
    last_tested_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_verified_at: datetime | None = None
    last_published_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class ConnectAccountRequest(BaseModel):
    mode: str = Field(default="credentials", max_length=32)  # "oauth" | "credentials" | "manual"
    redirect_uri: str | None = Field(default=None, max_length=500)
    scopes: list[str] = Field(default_factory=list)
    app_id: str | None = Field(default=None, max_length=500)
    app_secret: str | None = Field(default=None, max_length=1000)
    api_key: str | None = Field(default=None, max_length=1000)
    api_secret: str | None = Field(default=None, max_length=1000)
    access_token: str | None = Field(default=None, max_length=4000)
    refresh_token: str | None = Field(default=None, max_length=4000)
    token_expires_at: datetime | None = None
    external_account_id: str | None = Field(default=None, max_length=255)
    target_resource_id: str | None = Field(default=None, max_length=255)
    target_resource_name: str | None = Field(default=None, max_length=255)
    allow_paid_publishing: bool | None = None


class ConnectAccountResponse(BaseModel):
    action: str  # "oauth_redirect" | "connected" | "manual_ready"
    authorization_url: str | None = None
    state_preview: str | None = None
    expires_at: datetime | None = None
    connection: SocialProfileConnectionResponse


class OAuthCompleteRequest(BaseModel):
    state: str = Field(min_length=8, max_length=512)
    code: str | None = Field(default=None, max_length=2048)
    error: str | None = Field(default=None, max_length=255)
    error_description: str | None = Field(default=None, max_length=500)


class SelectTargetRequest(BaseModel):
    target_resource_id: str = Field(min_length=1, max_length=255)
    target_resource_name: str | None = Field(default=None, max_length=255)


class DisconnectAccountRequest(BaseModel):
    clear_credentials: bool = True
    switch_to_manual: bool = False


class SocialPostMediaAttachmentResponse(BaseModel):
    id: int
    social_post_id: int
    media_asset_id: int
    sort_order: int
    role: str
    alt_text: str | None = None
    file_name: str | None = None
    preview_url: str | None = None
    public_url: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    is_prepared: bool = False
    prepared_mime_type: str | None = None
    prepared_width: int | None = None
    prepared_height: int | None = None
    prepared_file_size: int | None = None


class SocialPostMediaUpdateItem(BaseModel):
    media_asset_id: int = Field(ge=1)
    sort_order: int = Field(default=0, ge=0, le=20)
    role: str = Field(default="primary", max_length=24)
    alt_text: str | None = Field(default=None, max_length=255)


class SocialPostMediaUpdateRequest(BaseModel):
    attachments: list[SocialPostMediaUpdateItem] = Field(default_factory=list, max_length=10)


class PreflightCheckItemResponse(BaseModel):
    name: str
    passed: bool
    detail: str


class PublishingPreflightResponse(BaseModel):
    social_post_id: int
    ready: bool
    platform_key: str
    publishing_method: str
    destination_name: str
    destination_target: str | None = None
    assembled_content: str
    character_count: int
    character_limit: int | None = None
    checks: list[PreflightCheckItemResponse] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    media: list[SocialPostMediaAttachmentResponse] = Field(default_factory=list)


class PublishNowRequest(BaseModel):
    confirm: bool = False
    confirm_paid_api: bool = False


class SchedulePostRequest(BaseModel):
    scheduled_at: datetime
    display_timezone: str | None = Field(default=None, max_length=64)
    confirm_paid_api: bool = False


class CancelScheduleRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class MarkPublishedRequest(BaseModel):
    published_url: str = Field(min_length=8, max_length=1000)
    external_post_id: str | None = Field(default=None, max_length=255)
    published_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)


class ReconcileJobRequest(BaseModel):
    # Supported resolutions: auto | confirm_published | confirm_missing
    resolution: str = Field(default="auto", max_length=32)
    external_post_id: str | None = Field(default=None, max_length=255)
    published_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=500)


class PublishingJobResponse(BaseModel):
    id: int
    job_uuid: str
    idempotency_key: str
    website_id: int
    website_name: str | None = None
    social_profile_id: int | None = None
    profile_name: str | None = None
    social_post_id: int
    publishing_schedule_id: int | None = None
    approved_revision_id: int | None = None
    platform_key: str
    publishing_method: str
    status: str
    priority: int
    scheduled_at: datetime | None = None
    available_at: datetime
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None = None
    worker_id: str | None = None
    heartbeat_at: datetime | None = None
    requires_verification: bool = False
    external_post_id: str | None = None
    published_url: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    paused_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PublishingJobListResponse(BaseModel):
    items: list[PublishingJobResponse]
    meta: PaginationMeta


class PublishingLogResponse(BaseModel):
    id: int
    publishing_job_id: int | None = None
    website_id: int
    social_profile_id: int | None = None
    social_post_id: int | None = None
    platform_key: str
    attempt_number: int
    action: str
    outcome: str
    http_status: int | None = None
    external_post_id: str | None = None
    published_url: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    response_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PublicationRecordResponse(BaseModel):
    id: int
    website_id: int
    website_name: str
    social_profile_id: int | None = None
    profile_name: str
    platform_id: int
    platform_key: str
    platform_display_name: str
    social_post_id: int | None = None
    website_content_id: int | None = None
    source_title: str | None = None
    approved_revision_id: int | None = None
    approved_version_number: int | None = None
    publishing_job_id: int | None = None
    publishing_method: str
    verification_status: str
    outcome: str
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    external_post_id: str | None = None
    published_url: str | None = None
    caption_snapshot: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    source_url: str | None = None
    attempt_count: int
    last_http_status: int | None = None
    error_summary: str | None = None
    created_at: datetime


class PublishingHistoryListResponse(BaseModel):
    items: list[PublicationRecordResponse]
    meta: PaginationMeta


class CalendarEventResponse(BaseModel):
    id: str
    schedule_id: int | None = None
    social_post_id: int
    website_id: int
    website_name: str | None = None
    social_profile_id: int
    profile_name: str | None = None
    platform_key: str
    platform_display_name: str | None = None
    title: str
    caption_preview: str
    publishing_method: str
    publishing_status: str
    start_utc: datetime
    display_timezone: str
    local_iso: str
    published_url: str | None = None
    last_error: str | None = None
    color: str


class CalendarResponse(BaseModel):
    timezone: str
    events: list[CalendarEventResponse]


class PublishingStatisticsResponse(BaseModel):
    timezone: str
    drafts_awaiting_review: int = 0
    approved_posts: int = 0
    scheduled_posts: int = 0
    published_today: int = 0
    published_this_month: int = 0
    failed_publications: int = 0
    verification_required: int = 0
    accounts_requiring_attention: int = 0
    expiring_credentials: int = 0
    upcoming_scheduled: list[CalendarEventResponse] = Field(default_factory=list)
