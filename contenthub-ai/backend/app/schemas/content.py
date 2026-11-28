from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import PaginationMeta
from app.schemas.keyword_approval import (
    ContentApprovalItemResponse,
    ContentKeywordResponse,
)
from app.schemas.media import MediaAssetResponse


class ContentRevisionResponse(BaseModel):
    id: int
    content_id: int
    revision_number: int
    content_type: str | None = None
    title: str
    meta_description: str | None = None
    markdown_content: str | None = None
    content_hash: str
    created_at: datetime


class ContentStatsResponse(BaseModel):
    total_discovered: int = 0
    total_extracted: int = 0
    homepage_count: int = 0
    page_count: int = 0
    game_page_count: int = 0
    blog_post_count: int = 0
    blog_index_count: int = 0
    other_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    updated_count: int = 0
    excluded_count: int = 0
    discovered_today_count: int = 0


class ContentListItemResponse(BaseModel):
    id: int
    website_id: int
    website_name: str | None = None
    website_domain: str | None = None
    website_category_name: str | None = None
    featured_media_id: int | None = None
    featured_image_url: str | None = None
    content_type: str
    classification_method: str
    manual_classification_override: bool = False
    is_excluded: bool = False
    url: str
    canonical_url: str
    title: str
    author: str | None = None
    meta_description: str | None = None
    h1_text: str | None = None
    language: str | None = None
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    discovery_sources: list[str] = Field(default_factory=list)
    word_count: int
    http_status: int | None = None
    extraction_status: str
    extraction_error: str | None = None
    status: str
    is_historical_baseline: bool = False
    near_duplicate_of_id: int | None = None
    near_duplicate_score: float | None = None
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    first_discovered_at: datetime
    last_discovered_at: datetime
    last_checked_at: datetime
    approval_status: str | None = None
    keyword_approval_status: str | None = None
    focus_keyphrase: str | None = None
    secondary_keywords: list[str] = Field(default_factory=list)
    cannibalization_count: int = 0
    google_index_status: str = "uninspected"
    google_index_verified_at: datetime | None = None
    google_index_last_attempt_at: datetime | None = None
    google_index_coverage_state: str | None = None
    google_index_verdict: str | None = None


class ContentDetailResponse(ContentListItemResponse):
    url_hash: str
    content_hash: str
    original_content: str | None = None
    extracted_content: str | None = None
    markdown_content: str | None = None
    optimized_context: str | None = None
    structured_data_json: dict[str, Any] | None = None
    featured_media: MediaAssetResponse | None = None
    revision_count: int = 0
    keyword_mapping: ContentKeywordResponse | None = None
    content_approval: ContentApprovalItemResponse | None = None
    created_at: datetime
    updated_at: datetime


class ContentListResponse(BaseModel):
    items: list[ContentListItemResponse]
    meta: PaginationMeta
    stats: ContentStatsResponse = Field(default_factory=ContentStatsResponse)


class ContentUpdateRequest(BaseModel):
    content_type: str | None = Field(default=None, max_length=32)
    manual_classification_override: bool | None = None
    is_excluded: bool | None = None
    status: str | None = Field(default=None, max_length=32)
    categories: list[str] | None = None
    tags: list[str] | None = None
    language: str | None = Field(default=None, max_length=32)
