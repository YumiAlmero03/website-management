from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.health import DatabaseHealthInfo, SystemResourcesInfo
from app.schemas.logs import ActivityLogItem
from app.schemas.website import ScanLogResponse


class PhaseModuleStatus(BaseModel):
    key: str
    label: str
    route: str
    phase: int
    status: str  # "active" | "not_implemented"
    summary: str


class Phase1Counts(BaseModel):
    active_sessions: int
    configured_settings: int
    activity_events_total: int


class Phase2Metrics(BaseModel):
    active_websites: int
    total_categories: int
    total_contents: int
    total_extracted: int
    homepage_count: int
    page_count: int
    game_page_count: int = 0
    blog_post_count: int
    blog_index_count: int
    other_count: int
    pending_extractions: int
    failed_extractions: int
    contents_discovered_today: int
    updated_contents: int
    completed_scans: int
    failed_scans: int
    incomplete_scans: int
    websites_due_for_scan: int
    pending_content_approvals: int = 0
    approved_keywords_count: int = 0


class Phase4PublishingMetrics(BaseModel):
    drafts_awaiting_review: int = 0
    approved_posts: int = 0
    scheduled_posts: int = 0
    published_today: int = 0
    published_this_month: int = 0
    failed_publications: int = 0
    verification_required: int = 0
    accounts_requiring_attention: int = 0
    expiring_credentials: int = 0


class DashboardSummaryResponse(BaseModel):
    generated_at: datetime
    timezone: str
    current_phase: int
    filtered_website_id: int | None = None
    filtered_category_id: int | None = None
    database: DatabaseHealthInfo
    resources: SystemResourcesInfo
    phase1_counts: Phase1Counts
    phase2_metrics: Phase2Metrics
    phase4_metrics: Phase4PublishingMetrics = Field(default_factory=Phase4PublishingMetrics)
    recent_scans: list[ScanLogResponse] = Field(default_factory=list)
    modules: list[PhaseModuleStatus]
    recent_activities: list[ActivityLogItem]
