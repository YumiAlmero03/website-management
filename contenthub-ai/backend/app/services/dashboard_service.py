from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.models.base import ensure_utc, utc_now
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.category_repo import WebsiteCategoryRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.scan_log_repo import ScanLogRepositoryProtocol
from app.repositories.session_repo import SessionRepositoryProtocol
from app.repositories.settings_repo import SettingsRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    Phase1Counts,
    Phase2Metrics,
    PhaseModuleStatus,
)
from app.schemas.logs import ActivityLogItem
from app.schemas.website import ScanLogResponse
from app.services.monitoring.health_service import HealthService
from app.services.settings_service import SettingsService

ROADMAP_MODULES: tuple[PhaseModuleStatus, ...] = (
    PhaseModuleStatus(
        key="websites",
        label="Websites & Scanner",
        route="/websites",
        phase=2,
        status="active",
        summary=(
            "Website-centric brand profiles, multi-source discovery, "
            "deterministic URL classification, and resumable batched scanning."
        ),
    ),
    PhaseModuleStatus(
        key="content_library",
        label="Content Library",
        route="/content-library",
        phase=2,
        status="active",
        summary=(
            "Universal content repository covering homepages, pages, blog posts, "
            "blog indexes, revisions, and extraction failure diagnostics."
        ),
    ),
    PhaseModuleStatus(
        key="ai_management",
        label="Gemini AI Engine",
        route="/ai-management",
        phase=3,
        status="not_implemented",
        summary="Token optimization, response cache, quota guard, and prompt templates.",
    ),
    PhaseModuleStatus(
        key="social_media",
        label="Social Media",
        route="/social-media",
        phase=4,
        status="not_implemented",
        summary="Caption generation, approval queue, UTM builder, and publishing.",
    ),
    PhaseModuleStatus(
        key="connected_accounts",
        label="Connected Accounts",
        route="/connected-accounts",
        phase=4,
        status="not_implemented",
        summary="Official publisher adapters (WordPress, Facebook, Blogger, Manual).",
    ),
    PhaseModuleStatus(
        key="publishing_calendar",
        label="Publishing Calendar",
        route="/publishing-calendar",
        phase=4,
        status="not_implemented",
        summary="FullCalendar Standard monthly/weekly/daily scheduling.",
    ),
    PhaseModuleStatus(
        key="editorial_planner",
        label="Editorial Planner",
        route="/editorial-planner",
        phase=5,
        status="not_implemented",
        summary="Keyword research, Search Console gaps, topic clusters, and plans.",
    ),
    PhaseModuleStatus(
        key="articles",
        label="Article Editor",
        route="/articles",
        phase=5,
        status="not_implemented",
        summary="Tiptap rich-text editor with non-blocking SEO guideline warnings.",
    ),
    PhaseModuleStatus(
        key="automation",
        label="Automation Engine",
        route="/automation",
        phase=6,
        status="not_implemented",
        summary="MySQL persistent job queue, retries, and background worker.",
    ),
    PhaseModuleStatus(
        key="analytics",
        label="Analytics",
        route="/analytics",
        phase=6,
        status="not_implemented",
        summary="Measured publishing metrics, Gemini usage, and Search Console reports.",
    ),
)


class DashboardService:
    """Aggregates system health, website inventory, content breakdowns, and recent scans."""

    def __init__(
        self,
        *,
        settings: Settings,
        health_service: HealthService,
        settings_service: SettingsService,
        session_repo: SessionRepositoryProtocol,
        settings_repo: SettingsRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        category_repo: WebsiteCategoryRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        scan_log_repo: ScanLogRepositoryProtocol,
    ) -> None:
        self.settings = settings
        self.health_service = health_service
        self.settings_service = settings_service
        self.session_repo = session_repo
        self.settings_repo = settings_repo
        self.activity_repo = activity_repo
        self.category_repo = category_repo
        self.website_repo = website_repo
        self.content_repo = content_repo
        self.scan_log_repo = scan_log_repo

    def get_summary(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> DashboardSummaryResponse:
        now = utc_now()
        effective = self.settings_service.get_effective_map()
        tz_name = str(effective.get("app.timezone", self.settings.app_timezone))

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = UTC
        local_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        utc_day_start = local_start.astimezone(UTC)

        db_health = self.health_service.get_database_health()
        resources = self.health_service.get_system_resources(effective_settings=effective)

        active_sessions = self.session_repo.count_active(now=now)
        configured_settings = self.settings_repo.count_all()
        recent_rows, total_activities = self.activity_repo.list_paginated(page=1, page_size=8)

        total_categories = self.category_repo.count_all(include_archived=False)
        active_websites = self.website_repo.count_all(
            website_id=website_id,
            category_id=category_id,
            status="active",
        )
        content_stats = self.content_repo.get_stats(
            website_id=website_id,
            category_id=category_id,
            discovered_since=utc_day_start,
        )
        completed_scans = self.scan_log_repo.count_by_status(
            "completed", website_id=website_id, category_id=category_id
        ) + self.scan_log_repo.count_by_status(
            "partially_completed", website_id=website_id, category_id=category_id
        )
        failed_scans = self.scan_log_repo.count_by_status(
            "failed", website_id=website_id, category_id=category_id
        )
        incomplete_scans = self.scan_log_repo.count_by_status(
            "incomplete", website_id=website_id, category_id=category_id
        ) + self.scan_log_repo.count_by_status(
            "paused", website_id=website_id, category_id=category_id
        )
        websites_due = self.website_repo.count_due(
            now=now, website_id=website_id, category_id=category_id
        )

        recent_scan_rows = self.scan_log_repo.list_recent(
            limit=6,
            website_id=website_id,
            category_id=category_id,
        )
        recent_scans = []
        for scan in recent_scan_rows:
            site = self.website_repo.get_by_id(scan.website_id)
            recent_scans.append(
                ScanLogResponse(
                    id=scan.id,
                    website_id=scan.website_id,
                    website_name=site.name if site else None,
                    scan_method=scan.scan_method,
                    scan_mode=scan.scan_mode,
                    trigger_type=scan.trigger_type,
                    urls_found=scan.urls_found,
                    articles_processed=scan.articles_processed,
                    urls_pending_extraction=scan.urls_pending_extraction,
                    new_articles=scan.new_articles,
                    updated_articles=scan.updated_articles,
                    unchanged_articles=scan.unchanged_articles,
                    skipped_articles=scan.skipped_articles,
                    failed_articles=scan.failed_articles,
                    excluded_count=scan.excluded_count,
                    homepage_count=scan.homepage_count,
                    page_count=scan.page_count,
                    blog_post_count=scan.blog_post_count,
                    other_count=scan.other_count,
                    current_source=scan.current_source,
                    current_url=scan.current_url,
                    discovered_sitemaps=list(scan.discovered_sitemaps_json or []),
                    sources_completed=list(scan.sources_completed_json or []),
                    sources_failed=list(scan.sources_failed_json or []),
                    status=scan.status,
                    error_message=scan.error_message,
                    duration_ms=scan.duration_ms,
                    started_at=ensure_utc(scan.started_at),
                    completed_at=ensure_utc(scan.completed_at),
                    created_at=ensure_utc(scan.created_at) or now,
                )
            )

        recent_items = [
            ActivityLogItem(
                id=row.id,
                user_id=row.user_id,
                actor_type=row.actor_type,
                category=row.category,
                action=row.action,
                level=row.level,
                message=row.message,
                metadata=row.metadata_json,
                ip_address=row.ip_address,
                created_at=ensure_utc(row.created_at) or now,
            )
            for row in recent_rows
        ]

        return DashboardSummaryResponse(
            generated_at=now,
            timezone=tz_name,
            current_phase=2,
            filtered_website_id=website_id,
            filtered_category_id=category_id,
            database=db_health,
            resources=resources,
            phase1_counts=Phase1Counts(
                active_sessions=active_sessions,
                configured_settings=configured_settings,
                activity_events_total=total_activities,
            ),
            phase2_metrics=Phase2Metrics(
                active_websites=active_websites,
                total_categories=total_categories,
                total_contents=content_stats["total_discovered"],
                total_extracted=content_stats["total_extracted"],
                homepage_count=content_stats["homepage_count"],
                page_count=content_stats["page_count"],
                blog_post_count=content_stats["blog_post_count"],
                blog_index_count=content_stats["blog_index_count"],
                other_count=content_stats["other_count"],
                pending_extractions=content_stats["pending_count"],
                failed_extractions=content_stats["failed_count"],
                contents_discovered_today=content_stats["discovered_today_count"],
                updated_contents=content_stats["updated_count"],
                completed_scans=completed_scans,
                failed_scans=failed_scans,
                incomplete_scans=incomplete_scans,
                websites_due_for_scan=websites_due,
            ),
            recent_scans=recent_scans,
            modules=list(ROADMAP_MODULES),
            recent_activities=recent_items,
        )
