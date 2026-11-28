from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import PaginationMeta

ApprovalStatusType = Literal[
    "awaiting_extraction",
    "pending_review",
    "approved",
    "rejected",
    "needs_rereview",
]

APPROVAL_ELIGIBLE_CONTENT_TYPES: tuple[str, ...] = (
    "homepage",
    "page",
    "game_page",
    "blog_post",
)


class ImageAltSuggestionItem(BaseModel):
    image_url: str | None = Field(default=None, max_length=2048)
    current_alt: str | None = Field(default=None, max_length=300)
    suggested_alt: str = Field(..., min_length=1, max_length=300)
    context: str | None = Field(default=None, max_length=160)


class CannibalizationMatchResponse(BaseModel):
    content_id: int
    title: str
    canonical_url: str
    content_type: str
    focus_keyphrase: str
    approval_status: str
    similarity_score: float
    severity: Literal["high", "medium"]
    reason: str


class ContentKeywordResponse(BaseModel):
    id: int
    website_id: int
    website_content_id: int
    focus_keyphrase: str
    secondary_keywords: list[str]
    anchor_text_variations: list[str]
    image_alt_suggestions: list[ImageAltSuggestionItem]
    approval_status: ApprovalStatusType | str
    suggestion_source: str
    keyword_generation_method: str = "python"
    keyword_generation_status: str = "pending"
    keyword_evidence: list[dict[str, Any]] = Field(default_factory=list)
    keyword_scores: dict[str, Any] = Field(default_factory=dict)
    keyword_model: str | None = None
    keyword_input_hash: str | None = None
    keyword_generated_at: datetime | None = None
    game_name: str | None = None
    provider_name: str | None = None
    is_admin_locked: bool
    version: int
    cannibalization_warnings: list[CannibalizationMatchResponse] = Field(default_factory=list)
    last_reviewed_at: datetime | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ContentKeywordRevisionResponse(BaseModel):
    id: int
    content_keyword_id: int
    revision_number: int
    focus_keyphrase: str
    secondary_keywords: list[str]
    anchor_text_variations: list[str]
    image_alt_suggestions: list[ImageAltSuggestionItem]
    approval_status: str
    suggestion_source: str
    change_note: str | None = None
    changed_by: int | None = None
    created_at: datetime


class ContentApprovalHistoryResponse(BaseModel):
    id: int
    content_approval_id: int
    from_status: str | None = None
    to_status: str
    content_type: str | None = None
    focus_keyphrase: str | None = None
    action: str
    note: str | None = None
    acted_by: int | None = None
    created_at: datetime


class ContentApprovalItemResponse(BaseModel):
    approval_id: int | None = None
    website_id: int
    website_name: str | None = None
    website_domain: str | None = None
    content_id: int
    title: str
    url: str
    canonical_url: str
    content_type: str
    extraction_status: str
    extraction_error: str | None = None
    is_historical_baseline: bool
    is_excluded: bool
    word_count: int
    meta_description: str | None = None
    meta_title: str | None = None
    h1_text: str | None = None
    language: str | None = None
    optimized_context_preview: str | None = None
    featured_image_url: str | None = None
    published_at: datetime | None = None
    first_discovered_at: datetime | None = None
    last_discovered_at: datetime | None = None
    status: ApprovalStatusType | str
    classified_content_type: str
    review_note: str | None = None
    rejection_reason: str | None = None
    auto_generation_triggered_at: datetime | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    keyword_mapping: ContentKeywordResponse | None = None
    cannibalization_warnings: list[CannibalizationMatchResponse] = Field(default_factory=list)
    updated_at: datetime
    created_at: datetime


class ContentApprovalDetailResponse(ContentApprovalItemResponse):
    markdown_content: str | None = None
    extracted_content: str | None = None
    yake_keywords: list[str] = Field(default_factory=list)
    keyword_revisions: list[ContentKeywordRevisionResponse] = Field(default_factory=list)
    approval_history: list[ContentApprovalHistoryResponse] = Field(default_factory=list)


class ContentApprovalStatsResponse(BaseModel):
    total_eligible: int = 0
    awaiting_extraction: int = 0
    pending_review: int = 0
    needs_rereview: int = 0
    approved: int = 0
    rejected: int = 0
    cannibalization_flagged: int = 0


class ContentApprovalListResponse(BaseModel):
    items: list[ContentApprovalItemResponse]
    meta: PaginationMeta
    stats: ContentApprovalStatsResponse


class KeywordMappingUpdateRequest(BaseModel):
    focus_keyphrase: str = Field(..., min_length=2, max_length=255)
    secondary_keywords: list[str] = Field(default_factory=list, max_length=25)
    anchor_text_variations: list[str] = Field(default_factory=list, max_length=20)
    image_alt_suggestions: list[ImageAltSuggestionItem] = Field(default_factory=list, max_length=20)
    content_type: str | None = Field(default=None, max_length=32)
    change_note: str | None = Field(default=None, max_length=500)


class ApproveContentRequest(BaseModel):
    """Supports inline keyword and content-type edits in the exact approval action."""

    focus_keyphrase: str | None = Field(default=None, max_length=255)
    secondary_keywords: list[str] | None = Field(default=None, max_length=25)
    anchor_text_variations: list[str] | None = Field(default=None, max_length=20)
    image_alt_suggestions: list[ImageAltSuggestionItem] | None = Field(default=None, max_length=20)
    content_type: str | None = Field(default=None, max_length=32)
    review_note: str | None = Field(default=None, max_length=500)
    trigger_auto_generation: bool = True


class ApproveContentResultResponse(BaseModel):
    item: ContentApprovalDetailResponse
    auto_generation_job_id: int | None = None
    auto_generation_note: str | None = None
    cannibalization_warnings: list[CannibalizationMatchResponse] = Field(default_factory=list)


class BulkApproveItemOverride(BaseModel):
    content_id: int = Field(..., ge=1)
    focus_keyphrase: str | None = Field(default=None, max_length=255)
    secondary_keywords: list[str] | None = Field(default=None, max_length=25)
    anchor_text_variations: list[str] | None = Field(default=None, max_length=20)
    image_alt_suggestions: list[ImageAltSuggestionItem] | None = Field(default=None, max_length=20)
    content_type: str | None = Field(default=None, max_length=32)


class BulkApproveRequest(BaseModel):
    content_ids: list[int] = Field(..., min_length=1, max_length=100)
    overrides: list[BulkApproveItemOverride] = Field(default_factory=list)
    review_note: str | None = Field(default=None, max_length=500)
    trigger_auto_generation: bool = True


class BulkApproveResultResponse(BaseModel):
    approved_content_ids: list[int]
    skipped_items: list[dict[str, str | int]]
    auto_generation_job_ids: list[int]
    total_approved: int
    total_skipped: int


class RejectContentRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ReopenReviewRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class AiKeywordRefineRequest(BaseModel):
    provider_id: int | None = Field(default=None, ge=1)
    apply_immediately: bool = False


class AiKeywordSuggestionPreviewResponse(BaseModel):
    content_id: int
    focus_keyphrase: str
    secondary_keywords: list[str]
    anchor_text_variations: list[str]
    image_alt_suggestions: list[ImageAltSuggestionItem]
    suggestion_source: str
    provider_name: str | None = None
    applied: bool = False


class ApprovedKeywordMapEntryResponse(BaseModel):
    website_id: int
    website_name: str | None = None
    content_id: int
    canonical_url: str
    title: str
    content_type: str
    focus_keyphrase: str
    secondary_keywords: list[str]
    anchor_text_variations: list[str]
    image_alt_suggestions: list[ImageAltSuggestionItem]
    approval_status: str
    keyword_version: int
    last_reviewed_at: datetime | None = None
    cannibalization_warnings: list[CannibalizationMatchResponse] = Field(default_factory=list)


class KeywordMapListResponse(BaseModel):
    items: list[ApprovedKeywordMapEntryResponse]
    meta: PaginationMeta
    total_cannibalization_conflicts: int = 0
