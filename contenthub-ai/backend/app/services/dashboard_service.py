from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.models.base import ensure_utc, utc_now
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.article_repo import ArticleRepositoryProtocol
from app.repositories.brand_repo import BrandRepositoryProtocol
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
        key="brands",
        label="Brands",
        route="/brands",
        phase=2,
        status="active",
        summary="Multi-brand language, tone, keyword, hashtag, and CTA profiles.",
    ),
    PhaseModuleStatus(
        key="websites",
        label="Websites & Scanner",
        route="/websites",
        phase=2,
        status="active",
        summary="SSRF-safe discovery via REST, WordPress, RSS, Sitemap, llms.txt, and HTML.",
    ),
    PhaseModuleStatus(
        key="content_library",
        label="Content Library",
        route="/content-library",
        phase=2,
        status="active",
        summary="Extracted Markdown articles, optimized context, hashes, and revisions.",
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
    def __init__(
        self,
        *,
        settings: Settings,
        health_service: HealthService,
        settings_service: SettingsService,
        session_repo: SessionRepositoryProtocol,
        settings_repo: SettingsRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        brand_repo: BrandRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        article_repo: ArticleRepositoryProtocol,
        scan_log_repo: ScanLogRepositoryProtocol,
    ) -> None:
        self.settings = settings
        self.health_service = health_service
        self.settings_service = settings_service
        self.session_repo = session_repo
        self.settings_repo = settings_repo
        self.activity_repo = activity_repo
        self.brand_repo = brand_repo
        self.website_repo = website_repo
        self.article_repo = article_repo
        self.scan_log_repo = scan_log_repo

    def get_summary(
        self,
        *,
        brand_id: int | None = None,
        website_id: int | None = None,
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

        total_brands = (
            1
            if brand_id is not None and self.brand_repo.get_by_id(brand_id) is not None
            else (0 if brand_id is not None else self.brand_repo.count_all())
        )
        active_websites = self.website_repo.count_all(
            brand_id=brand_id,
            website_id=website_id,
            status="active",
        )
        total_articles = self.article_repo.count_all(brand_id=brand_id, website_id=website_id)
        articles_today = self.article_repo.count_all(
            brand_id=brand_id,
            website_id=website_id,
            discovered_since=utc_day_start,
        )
        updated_articles = self.article_repo.count_all(
            brand_id=brand_id,
            website_id=website_id,
            status="updated",
        )
        completed_scans = self.scan_log_repo.count_by_status(
            "completed", brand_id=brand_id, website_id=website_id
        ) + self.scan_log_repo.count_by_status(
            "partially_completed", brand_id=brand_id, website_id=website_id
        )
        failed_scans = self.scan_log_repo.count_by_status(
            "failed", brand_id=brand_id, website_id=website_id
        )
        websites_due = self.website_repo.count_due(
            now=now, brand_id=brand_id, website_id=website_id
        )

        recent_scan_rows = self.scan_log_repo.list_recent(
            limit=6,
            brand_id=brand_id,
            website_id=website_id,
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
                    trigger_type=scan.trigger_type,
                    urls_found=scan.urls_found,
                    articles_processed=scan.articles_processed,
                    new_articles=scan.new_articles,
                    updated_articles=scan.updated_articles,
                    unchanged_articles=scan.unchanged_articles,
                    skipped_articles=scan.skipped_articles,
                    failed_articles=scan.failed_articles,
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
            filtered_brand_id=brand_id,
            filtered_website_id=website_id,
            database=db_health,
            resources=resources,
            phase1_counts=Phase1Counts(
                active_sessions=active_sessions,
                configured_settings=configured_settings,
                activity_events_total=total_activities,
            ),
            phase2_metrics=Phase2Metrics(
                total_brands=total_brands,
                active_websites=active_websites,
                total_articles=total_articles,
                articles_discovered_today=articles_today,
                updated_articles=updated_articles,
                completed_scans=completed_scans,
                failed_scans=failed_scans,
                websites_due_for_scan=websites_due,
            ),
            recent_scans=recent_scans,
            modules=list(ROADMAP_MODULES),
            recent_activities=recent_items,
        )
