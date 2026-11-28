from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import PaginationMeta


class SocialPostRevisionResponse(BaseModel):
    id: int
    social_post_id: int
    version_number: int
    title: str | None = None
    caption: str
    assembled_content: str
    hashtags: list[str] = Field(default_factory=list)
    cta_text: str | None = None
    generation_model: str | None = None
    change_type: str
    edited_by: int | None = None
    notes: str | None = None
    created_at: datetime


class SocialPostResponse(BaseModel):
    id: int
    website_id: int
    website_name: str | None = None
    website_content_id: int | None = None
    source_title: str | None = None
    source_content_type: str | None = None
    focus_keyphrase: str | None = None
    social_profile_id: int
    social_profile_name: str | None = None
    publishing_method: str | None = None
    platform_id: int
    platform_key: str | None = None
    platform_display_name: str | None = None
    featured_media_id: int | None = None
    featured_image_url: str | None = None
    media_count: int = 0
    ai_generation_job_id: int | None = None
    ai_provider_id: int | None = None
    generation_model: str | None = None
    prompt_template_id: int | None = None
    title: str | None = None
    caption: str
    assembled_content: str
    hashtags: list[str] = Field(default_factory=list)
    cta_text: str | None = None
    source_url: str | None = None
    language: str
    character_count: int
    character_limit: int | None = None
    validation_warnings: list[str] = Field(default_factory=list)
    status: str
    publishing_status: str = "unscheduled"
    approved_revision_id: int | None = None
    alternative_captions: list[str] = Field(default_factory=list)
    utm_params: dict[str, str] = Field(default_factory=dict)
    target_url_with_utm: str | None = None
    scheduled_for: datetime | None = None
    display_timezone: str | None = None
    published_at: datetime | None = None
    external_post_id: str | None = None
    published_url: str | None = None
    verification_status: str = "unverified"
    last_publish_error: str | None = None
    last_publish_attempt_at: datetime | None = None
    is_manually_edited: bool
    current_version: int
    error_message: str | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    rejected_by: int | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    generated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SocialPostTestDraftRequest(BaseModel):
    caption: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16000)
    ]


class SocialPostUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    caption: str | None = Field(default=None, min_length=1, max_length=65000)
    alternative_captions: list[str] | None = None
    hashtags: list[str] | None = None
    cta_text: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=1000)
    utm_params: dict[str, str] | None = None
    featured_media_id: int | None = Field(default=None, ge=1)
    clear_featured_media: bool = False
    status: str | None = Field(default=None, max_length=32)


class SocialPostRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class SocialPostRegenerateRequest(BaseModel):
    provider_id: int | None = Field(default=None, ge=1)
    context_mode: str = Field(default="optimized", max_length=32)
    force: bool = True


class SocialPostStatsResponse(BaseModel):
    total_drafts: int = 0
    drafts: int = 0
    pending_review: int = 0
    approved: int = 0
    rejected: int = 0
    generation_failed: int = 0
    archived: int = 0
    scheduled: int = 0
    publishing: int = 0
    published: int = 0
    manually_published: int = 0
    failed_publishing: int = 0
    verification_required: int = 0


class SocialPostListResponse(BaseModel):
    items: list[SocialPostResponse]
    meta: PaginationMeta
    stats: SocialPostStatsResponse = Field(default_factory=SocialPostStatsResponse)
