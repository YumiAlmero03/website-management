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
    total_brands: int
    active_websites: int
    total_articles: int
    articles_discovered_today: int
    updated_articles: int
    completed_scans: int
    failed_scans: int
    websites_due_for_scan: int


class DashboardSummaryResponse(BaseModel):
    generated_at: datetime
    timezone: str
    current_phase: int
    filtered_brand_id: int | None = None
    filtered_website_id: int | None = None
    database: DatabaseHealthInfo
    resources: SystemResourcesInfo
    phase1_counts: Phase1Counts
    phase2_metrics: Phase2Metrics
    recent_scans: list[ScanLogResponse] = Field(default_factory=list)
    modules: list[PhaseModuleStatus]
    recent_activities: list[ActivityLogItem]
