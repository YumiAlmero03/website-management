from __future__ import annotations

import contextlib
import math
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    from app.services.ai.generation_service import AiGenerationService
    from app.services.content_approval_service import ContentApprovalService

from app.config import BACKEND_ROOT, Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.website import Website
from app.models.website_content import WebsiteContent
from app.models.website_scan_item import WebsiteScanItem
from app.models.website_scan_log import WebsiteScanLog
from app.models.website_url_rule import WebsiteUrlRule
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.scan_log_repo import RESUMABLE_SCAN_STATUSES, ScanLogRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.repositories.website_source_repo import WebsiteSourceConfigRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.website import (
    ALLOWED_SCAN_MODES,
    ScanItemListResponse,
    ScanItemResponse,
    ScanLogListResponse,
    ScanLogResponse,
)
from app.services.content.duplicate import find_near_duplicate
from app.services.content.extractor import ContentExtractionEngine
from app.services.content.media import MediaAssetProcessor, MediaValidationError
from app.services.content.revisions import create_revision_snapshot, has_content_changed
from app.services.monitoring.health_service import HealthService
from app.services.scanner.base import DiscoveredCandidate, EndpointFetchRecord
from app.services.scanner.classifier import classify_url
from app.services.scanner.exceptions import DiscoveryError, ScannerError
from app.services.scanner.manager import (
    AggregatedDiscoveryOutput,
    SourceEndpointState,
    WebsiteDiscoveryManager,
)
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.url_normalizer import hash_url, matches_url_patterns
from app.services.settings_service import SettingsService

ScanDispatcher = Callable[[int], None]


def _is_email_protection_url(url: str) -> bool:
    return unquote(urlsplit(url).path).lower().rstrip("/") == "/cdn-cgi/l/email-protection"


def default_subprocess_dispatcher(scan_id: int) -> None:
    """Spawn a detached worker process via `python -m app.cli run-scan --scan-id <id>`."""
    cfg = Settings()
    log_file = None
    with contextlib.suppress(OSError):
        log_dir = cfg.resolved_storage_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = (log_dir / "scanner-worker.log").open("ab")

    try:
        subprocess.Popen(
            [sys.executable, "-m", "app.cli", "run-scan", "--scan-id", str(scan_id)],
            cwd=str(BACKEND_ROOT),
            stdout=log_file if log_file is not None else subprocess.DEVNULL,
            stderr=log_file if log_file is not None else subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        if log_file is not None:
            with contextlib.suppress(OSError):
                log_file.close()


@dataclass(frozen=True)
class ScheduledRunSummary:
    guardian_status: str
    paused_by_resource_guardian: bool
    stale_recovered: int
    due_websites_found: int
    scans_executed: int
    scans_succeeded: int
    scans_failed: int
    skipped_locked: int


class ScanExecutorService:
    """Orchestrates aggregated discovery, resumable batched extraction, and scheduled scans."""

    def __init__(
        self,
        *,
        settings: Settings,
        website_repo: WebsiteRepositoryProtocol,
        source_config_repo: WebsiteSourceConfigRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        scan_log_repo: ScanLogRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        health_service: HealthService,
        settings_service: SettingsService,
        fetcher: SafeHttpFetcher,
        dispatcher: ScanDispatcher | None = None,
        ai_generation_service: AiGenerationService | None = None,
        approval_service: ContentApprovalService | None = None,
    ) -> None:
        self.settings = settings
        self.website_repo = website_repo
        self.source_config_repo = source_config_repo
        self.content_repo = content_repo
        self.scan_log_repo = scan_log_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo
        self.health_service = health_service
        self.settings_service = settings_service
        self.fetcher = fetcher
        self.dispatcher = dispatcher or default_subprocess_dispatcher
        self.ai_generation_service = ai_generation_service
        self.approval_service = approval_service

    def _to_scan_response(
        self, row: WebsiteScanLog, *, site_name: str | None = None
    ) -> ScanLogResponse:
        now = utc_now()
        if site_name is None:
            site = self.website_repo.get_by_id(row.website_id)
            site_name = site.name if site else None
        return ScanLogResponse(
            id=row.id,
            website_id=row.website_id,
            website_name=site_name,
            scan_method=row.scan_method,
            scan_mode=row.scan_mode,
            trigger_type=row.trigger_type,
            urls_found=row.urls_found,
            articles_processed=row.articles_processed,
            urls_pending_extraction=row.urls_pending_extraction,
            new_articles=row.new_articles,
            updated_articles=row.updated_articles,
            unchanged_articles=row.unchanged_articles,
            skipped_articles=row.skipped_articles,
            failed_articles=row.failed_articles,
            excluded_count=row.excluded_count,
            homepage_count=row.homepage_count,
            page_count=row.page_count,
            blog_post_count=row.blog_post_count,
            other_count=row.other_count,
            current_source=row.current_source,
            current_url=row.current_url,
            discovered_sitemaps=list(row.discovered_sitemaps_json or []),
            sources_completed=list(row.sources_completed_json or []),
            sources_failed=list(row.sources_failed_json or []),
            status=row.status,
            error_message=row.error_message,
            duration_ms=row.duration_ms,
            started_at=ensure_utc(row.started_at),
            completed_at=ensure_utc(row.completed_at),
            created_at=ensure_utc(row.created_at) or now,
        )

    @staticmethod
    def _to_scan_item_response(row: WebsiteScanItem) -> ScanItemResponse:
        now = utc_now()
        return ScanItemResponse(
            id=row.id,
            scan_log_id=row.scan_log_id,
            website_id=row.website_id,
            content_id=row.content_id,
            url=row.url,
            normalized_url=row.normalized_url,
            content_type=row.content_type,
            discovery_sources=list(row.discovery_sources or []),
            discovered_title=row.discovered_title,
            status=row.status,
            http_status=row.http_status,
            failure_reason=row.failure_reason,
            error_detail=row.error_detail,
            processed_at=ensure_utc(row.processed_at),
            created_at=ensure_utc(row.created_at) or now,
        )

    def get_scan(self, scan_id: int) -> ScanLogResponse:
        row = self.scan_log_repo.get_by_id(scan_id)
        if row is None:
            raise NotFoundError(f"Scan #{scan_id} not found.")
        return self._to_scan_response(row)

    def list_website_scans(
        self, website_id: int, *, page: int, page_size: int
    ) -> ScanLogListResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        rows, total = self.scan_log_repo.list_for_website(
            website_id, page=page, page_size=page_size
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return ScanLogListResponse(
            items=[self._to_scan_response(row, site_name=site.name) for row in rows],
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
            ),
        )

    def list_scan_items(
        self,
        scan_id: int,
        *,
        status: str | None = None,
        failures_or_excluded_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> ScanItemListResponse:
        if self.scan_log_repo.get_by_id(scan_id) is None:
            raise NotFoundError(f"Scan #{scan_id} not found.")
        rows, total = self.scan_log_repo.list_scan_items(
            scan_id,
            status=status,
            failures_or_excluded_only=failures_or_excluded_only,
            page=page,
            page_size=page_size,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return ScanItemListResponse(
            items=[self._to_scan_item_response(row) for row in rows],
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
            ),
        )

    def enqueue_scan(
        self,
        website_id: int,
        *,
        scan_mode: str = "full",
        trigger_type: str = "manual",
        max_urls_override: int | None = None,
        batch_size_override: int | None = None,
        user_id: int | None = None,
        ip_address: str | None = None,
        dispatch: bool = True,
    ) -> ScanLogResponse:
        if scan_mode not in ALLOWED_SCAN_MODES:
            raise ValidationAppError(
                f"Invalid scan_mode '{scan_mode}'. Allowed: {', '.join(ALLOWED_SCAN_MODES)}."
            )

        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        if site.status == "archived":
            raise ValidationAppError("Archived websites cannot be scanned.")

        self.scan_log_repo.recover_stale_scans(
            stale_minutes=self.settings.scanner_stale_timeout_minutes,
            website_id=site.id,
        )
        if self.scan_log_repo.get_active_for_website(site.id) is not None:
            raise ConflictError(f"A scan is already active for website '{site.name}'.")

        scan = self.scan_log_repo.create(
            website_id=site.id,
            scan_method=site.discovery_method,
            scan_mode=scan_mode,
            trigger_type=trigger_type,
            status="pending",
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin" if user_id else "scheduler",
            category="scans",
            action="scan.queued",
            level="info",
            message=f"Queued {scan_mode} ({trigger_type}) scan #{scan.id} for '{site.name}'.",
            metadata={
                "scan_id": scan.id,
                "website_id": site.id,
                "scan_mode": scan_mode,
                "max_urls_override": max_urls_override,
                "batch_size_override": batch_size_override,
            },
            ip_address=ip_address,
        )
        if dispatch:
            try:
                self.dispatcher(scan.id)
            except Exception as exc:
                self.scan_log_repo.update(
                    scan.id,
                    {
                        "status": "failed",
                        "completed_at": utc_now_naive(),
                        "error_message": f"Failed to dispatch scan worker: {exc}"[:500],
                    },
                )
                raise
        return self._to_scan_response(scan, site_name=site.name)

    def retry_scan(
        self,
        scan_id: int,
        *,
        user_id: int,
        ip_address: str | None,
        dispatch: bool = True,
    ) -> ScanLogResponse:
        previous = self.scan_log_repo.get_by_id(scan_id)
        if previous is None:
            raise NotFoundError(f"Scan #{scan_id} not found.")
        if previous.status in {"pending", "processing"}:
            raise ConflictError(f"Scan #{scan_id} is currently active.")
        mode = (
            "resume"
            if previous.status in RESUMABLE_SCAN_STATUSES and previous.urls_pending_extraction > 0
            else "retry_failed"
        )
        return self.enqueue_scan(
            previous.website_id,
            scan_mode=mode,
            trigger_type="retry",
            user_id=user_id,
            ip_address=ip_address,
            dispatch=dispatch,
        )

    def _guardian_status(self) -> tuple[str, bool]:
        effective = self.settings_service.get_effective_map()
        resources = self.health_service.get_system_resources(effective_settings=effective)
        return resources.guardian_status, resources.guardian_status == "critical"

    def run_due_scheduled_scans(self) -> ScheduledRunSummary:
        now = utc_now_naive()
        recovered = self.scan_log_repo.recover_stale_scans(
            stale_minutes=self.settings.scanner_stale_timeout_minutes
        )
        guardian_status, is_critical = self._guardian_status()
        if is_critical:
            self.activity_repo.create(
                user_id=None,
                actor_type="scheduler",
                category="scans",
                action="scan.deferred_by_resource_guardian",
                level="warning",
                message="Scheduled website scans deferred due to critical CPU/RAM load.",
                metadata={"guardian_status": guardian_status, "stale_recovered": len(recovered)},
                ip_address=None,
            )
            return ScheduledRunSummary(
                guardian_status=guardian_status,
                paused_by_resource_guardian=True,
                stale_recovered=len(recovered),
                due_websites_found=0,
                scans_executed=0,
                scans_succeeded=0,
                scans_failed=0,
                skipped_locked=0,
            )

        due_sites = self.website_repo.list_due_for_scan(now=now)
        executed = 0
        succeeded = 0
        failed = 0
        skipped_locked = 0

        for site in due_sites:
            if self.scan_log_repo.get_active_for_website(site.id) is not None:
                skipped_locked += 1
                continue

            # If a previous scan left pending URLs, resume it cleanly; otherwise check new content.
            incomplete = self.scan_log_repo.get_latest_incomplete_for_website(site.id)
            mode = (
                "resume"
                if incomplete is not None and incomplete.urls_pending_extraction > 0
                else ("incremental" if site.initial_scan_completed else "full")
            )
            scan = self.scan_log_repo.create(
                website_id=site.id,
                scan_method=site.discovery_method,
                scan_mode=mode,
                trigger_type="scheduled",
                status="pending",
            )
            result = self.execute_scan(scan.id)
            executed += 1
            if result.status in {"completed", "partially_completed", "incomplete"}:
                succeeded += 1
            else:
                failed += 1

        return ScheduledRunSummary(
            guardian_status=guardian_status,
            paused_by_resource_guardian=False,
            stale_recovered=len(recovered),
            due_websites_found=len(due_sites),
            scans_executed=executed,
            scans_succeeded=succeeded,
            scans_failed=failed,
            skipped_locked=skipped_locked,
        )

    def execute_scan(
        self,
        scan_id: int,
        *,
        max_urls_override: int | None = None,
        batch_size_override: int | None = None,
    ) -> ScanLogResponse:
        started_monotonic = time.monotonic()
        claimed = self.scan_log_repo.claim_pending(scan_id)
        if claimed is None:
            existing = self.scan_log_repo.get_by_id(scan_id)
            if existing is None:
                raise NotFoundError(f"Scan #{scan_id} not found.")
            return self._to_scan_response(existing)

        site = self.website_repo.get_by_id(claimed.website_id)
        if site is None:
            self._finalize_failed(
                scan_id=scan_id,
                started_monotonic=started_monotonic,
                error_message=f"Website #{claimed.website_id} no longer exists.",
            )
            return self.get_scan(scan_id)

        guardian_status, is_critical = self._guardian_status()
        if is_critical:
            pending_count = len(self.content_repo.list_pending_for_website(site.id, limit=20_000))
            paused = self.scan_log_repo.update(
                scan_id,
                {
                    "status": "paused",
                    "urls_pending_extraction": pending_count,
                    "error_message": (
                        f"Scan deferred by Resource Guardian (status={guardian_status})."
                    ),
                    "completed_at": utc_now_naive(),
                    "duration_ms": int((time.monotonic() - started_monotonic) * 1000),
                },
            )
            assert paused is not None
            return self._to_scan_response(paused, site_name=site.name)

        run_limit = max(
            1,
            max_urls_override
            or site.crawl_max_urls_per_run
            or self.settings.scanner_default_crawl_max_urls_per_run,
        )
        batch_size = max(
            1,
            min(
                run_limit,
                batch_size_override
                or site.crawl_batch_size
                or self.settings.scanner_default_crawl_batch_size,
            ),
        )
        discovery_max_urls = max(self.settings.scanner_max_discovery_urls, run_limit)
        url_rules = self.source_config_repo.list_rules(site.id, enabled_only=True)
        scan_mode = claimed.scan_mode or "full"

        robots = RobotsPolicyChecker(
            fetcher=self.fetcher,
            user_agent=self.settings.scanner_user_agent,
            respect_robots=self.settings.scanner_respect_robots_txt,
        )

        # Map inline adapter payloads (Markdown or WP REST content) by URL hash.
        inline_candidates: dict[str, DiscoveredCandidate] = {}
        new_content_ids: set[int] = set()
        discovery_output: AggregatedDiscoveryOutput | None = None

        try:
            if scan_mode in {"full", "incremental", "discover_only"}:
                saved_sources = self.source_config_repo.list_sources(site.id)
                source_states = [
                    SourceEndpointState(
                        endpoint_url=s.endpoint_url,
                        source_type=s.source_type,
                        is_enabled=s.is_enabled,
                        etag=s.etag,
                        last_modified_header=s.last_modified_header,
                    )
                    for s in saved_sources
                ]
                manager = WebsiteDiscoveryManager(
                    settings=self.settings,
                    fetcher=self.fetcher,
                    robots=robots,
                )

                def _on_source_start(source_type: str, endpoint: str) -> None:
                    self.scan_log_repo.update(
                        scan_id,
                        {
                            "current_source": source_type,
                            "current_url": endpoint[:1000],
                            "heartbeat_at": utc_now_naive(),
                        },
                    )

                discovery_output = manager.discover_for_website(
                    site,
                    url_rules=url_rules,
                    source_states=source_states,
                    max_urls=discovery_max_urls,
                    scan_mode=("incremental" if scan_mode == "incremental" else "full"),
                    probe_missing_sources=True,
                    on_source_start=_on_source_start,
                )
                self._persist_source_records(site.id, discovery_output.endpoint_records)
                self._queue_discovered_candidates(
                    scan_id=scan_id,
                    site=site,
                    output=discovery_output,
                    url_rules=url_rules,
                    robots=robots,
                    scan_mode=scan_mode,
                    inline_candidates=inline_candidates,
                    new_content_ids=new_content_ids,
                )
                self._sync_progress_counts(scan_id=scan_id, site_id=site.id)
                self.scan_log_repo.update(
                    scan_id,
                    {
                        "scan_method": discovery_output.method_used[:64],
                        "discovered_sitemaps_json": discovery_output.discovered_sitemaps[:50],
                        "sources_completed_json": discovery_output.sources_completed[:50],
                        "sources_failed_json": discovery_output.sources_failed[:50],
                        "heartbeat_at": utc_now_naive(),
                    },
                )
            elif scan_mode == "resume":
                self._queue_pending_for_resume(
                    scan_id=scan_id,
                    site=site,
                    url_rules=url_rules,
                )
                self._sync_progress_counts(scan_id=scan_id, site_id=site.id)
            elif scan_mode == "retry_failed":
                self._queue_failed_for_retry(
                    scan_id=scan_id,
                    site=site,
                    url_rules=url_rules,
                    limit=run_limit,
                )
                self._sync_progress_counts(scan_id=scan_id, site_id=site.id)
        except DiscoveryError as exc:
            self._finalize_failed(
                scan_id=scan_id,
                started_monotonic=started_monotonic,
                error_message=str(exc),
            )
            return self.get_scan(scan_id)
        except Exception as exc:
            self._finalize_failed(
                scan_id=scan_id,
                started_monotonic=started_monotonic,
                error_message=f"Unexpected discovery failure: {exc}",
            )
            return self.get_scan(scan_id)

        paused_mid_run = False
        try:
            if scan_mode != "discover_only":
                paused_mid_run = self._extract_pending_in_batches(
                    scan_id=scan_id,
                    site=site,
                    url_rules=url_rules,
                    robots=robots,
                    batch_size=batch_size,
                    run_limit=run_limit,
                    inline_candidates=inline_candidates,
                    new_content_ids=new_content_ids,
                )

            return self._finalize_scan_log(
                scan_id=scan_id,
                site=site,
                scan_mode=scan_mode,
                started_monotonic=started_monotonic,
                discovery_output=discovery_output,
                paused_mid_run=paused_mid_run,
            )
        finally:
            if hasattr(self.fetcher, "close"):
                with contextlib.suppress(Exception):
                    self.fetcher.close()

    def _persist_source_records(self, website_id: int, records: list[EndpointFetchRecord]) -> None:
        now = utc_now_naive()
        parent_ids: dict[str, int] = {}
        for rec in records:
            parent_id = (
                parent_ids.get(rec.parent_endpoint_url or "") if rec.parent_endpoint_url else None
            )
            src = self.source_config_repo.upsert_source(
                website_id=website_id,
                source_type=rec.source_type,
                endpoint_url=rec.endpoint_url,
                parent_source_id=parent_id,
            )
            parent_ids[rec.endpoint_url] = src.id
            updates: dict[str, Any] = {
                "last_checked_at": now,
                "last_status_code": rec.status_code,
                "last_error": rec.error[:500] if rec.error else None,
            }
            if rec.etag:
                updates["etag"] = rec.etag[:255]
            if rec.last_modified:
                updates["last_modified_header"] = rec.last_modified[:120]
            if not rec.error:
                updates["last_success_at"] = now
                if not rec.not_modified:
                    updates["last_urls_found"] = rec.urls_found
            self.source_config_repo.update_source(src.id, updates)

    def _queue_discovered_candidates(
        self,
        *,
        scan_id: int,
        site: Website,
        output: AggregatedDiscoveryOutput,
        url_rules: list[WebsiteUrlRule],
        robots: RobotsPolicyChecker,
        scan_mode: str,
        inline_candidates: dict[str, DiscoveredCandidate],
        new_content_ids: set[int],
    ) -> None:
        now = utc_now_naive()

        # First record explicitly excluded candidates (matched excluded_url_patterns)
        for ex in output.excluded_candidates:
            url_hash = hash_url(ex.normalized_url)
            decision = classify_url(
                ex.normalized_url,
                domain=site.domain,
                custom_rules=url_rules,
                jsonld_types=ex.jsonld_types,
                og_type=ex.og_type,
                source_methods=ex.discovery_sources,
            )
            self.scan_log_repo.upsert_scan_item(
                scan_log_id=scan_id,
                website_id=site.id,
                url=ex.url,
                normalized_url=ex.normalized_url,
                url_hash=url_hash,
                content_type=decision.content_type,
                discovery_sources=ex.discovery_sources,
                discovered_title=ex.title,
                status="excluded",
                failure_reason="excluded_url_pattern",
                error_detail=ex.exclusion_reason or "Matched website excluded URL pattern.",
            )

        candidates = list(output.candidates)
        candidates = self._apply_initial_baseline(site=site, candidates=candidates)

        for cand in candidates:
            norm_url = cand.normalized_url
            url_hash = hash_url(norm_url)
            inline_candidates[url_hash] = cand
            existing = self.content_repo.get_by_website_and_url_hash(site.id, url_hash)

            if _is_email_protection_url(cand.url):
                if existing and not existing.is_excluded:
                    self.content_repo.update(
                        existing.id, {"is_excluded": True, "status": "excluded"}
                    )
                self.scan_log_repo.upsert_scan_item(
                    scan_log_id=scan_id,
                    website_id=site.id,
                    url=cand.url,
                    normalized_url=norm_url,
                    url_hash=url_hash,
                    content_type="page",
                    discovery_sources=cand.discovery_sources,
                    discovered_title=cand.title,
                    status="excluded",
                    failure_reason="ignored_email_protection",
                    error_detail="Ignored Cloudflare email-protection link.",
                )
                continue

            if existing is not None and existing.is_excluded:
                self.scan_log_repo.upsert_scan_item(
                    scan_log_id=scan_id,
                    website_id=site.id,
                    url=cand.url,
                    normalized_url=norm_url,
                    url_hash=url_hash,
                    content_type=existing.content_type,
                    discovery_sources=cand.discovery_sources,
                    discovered_title=cand.title or existing.title,
                    status="excluded",
                    content_id=existing.id,
                    failure_reason="manually_excluded",
                    error_detail="Marked excluded by administrator in Content Library.",
                )
                continue

            if not robots.is_allowed(cand.url):
                self.scan_log_repo.upsert_scan_item(
                    scan_log_id=scan_id,
                    website_id=site.id,
                    url=cand.url,
                    normalized_url=norm_url,
                    url_hash=url_hash,
                    content_type=(
                        existing.content_type if existing else (cand.content_type or "page")
                    ),
                    discovery_sources=cand.discovery_sources,
                    discovered_title=cand.title,
                    status="excluded",
                    content_id=existing.id if existing else None,
                    failure_reason="robots_txt_disallowed",
                    error_detail="Blocked by site robots.txt crawl policy.",
                )
                continue

            override_type = (
                existing.content_type
                if existing and existing.manual_classification_override
                else None
            )
            decision = classify_url(
                norm_url,
                domain=site.domain,
                custom_rules=url_rules,
                jsonld_types=cand.jsonld_types,
                og_type=cand.og_type,
                source_methods=cand.discovery_sources,
                manual_override_type=override_type,
            )

            merged_sources = list(existing.discovery_sources or []) if existing else []
            for src in cand.discovery_sources:
                if src not in merged_sources:
                    merged_sources.append(src)

            if existing is None:
                content_row = None
                item_status = "pending"
            else:
                updates: dict[str, Any] = {
                    "discovery_sources": merged_sources,
                    "last_discovered_at": now,
                }
                if not existing.manual_classification_override:
                    updates["content_type"] = decision.content_type
                    updates["classification_method"] = decision.classification_method
                if cand.title and (not existing.title or existing.title == existing.canonical_url):
                    updates["title"] = cand.title[:500]
                content_row = self.content_repo.update(existing.id, updates) or existing

                # Skip re-fetch in incremental mode if extracted item was not modified in feed.
                if (
                    scan_mode == "incremental"
                    and existing.extraction_status == "extracted"
                    and not (
                        cand.modified_at
                        and existing.source_updated_at
                        and cand.modified_at.replace(tzinfo=None) > existing.source_updated_at
                    )
                ):
                    item_status = "unchanged"
                else:
                    item_status = "pending"

            if self.approval_service is not None and content_row is not None:
                with contextlib.suppress(Exception):
                    self.approval_service.sync_discovered_content(content=content_row, website=site)

            self.scan_log_repo.upsert_scan_item(
                scan_log_id=scan_id,
                website_id=site.id,
                url=cand.url,
                normalized_url=norm_url,
                url_hash=url_hash,
                content_type=content_row.content_type if content_row else decision.content_type,
                discovery_sources=merged_sources,
                discovered_title=cand.title,
                discovered_published_at=(
                    cand.published_at.replace(tzinfo=None) if cand.published_at else None
                ),
                discovered_modified_at=(
                    cand.modified_at.replace(tzinfo=None) if cand.modified_at else None
                ),
                status=item_status,
                content_id=content_row.id if content_row else None,
            )

    def _queue_pending_for_resume(
        self,
        *,
        scan_id: int,
        site: Website,
        url_rules: list[WebsiteUrlRule],
    ) -> None:
        pending_contents = self.content_repo.list_pending_for_website(
            site.id, limit=self.settings.scanner_max_discovery_urls
        )
        seen_hashes: set[str] = set()
        for row in pending_contents:
            seen_hashes.add(row.url_hash)
            self.scan_log_repo.upsert_scan_item(
                scan_log_id=scan_id,
                website_id=site.id,
                url=row.url,
                normalized_url=row.canonical_url,
                url_hash=row.url_hash,
                content_type=row.content_type,
                discovery_sources=list(row.discovery_sources or []),
                discovered_title=row.title,
                status="pending",
                content_id=row.id,
            )

        # Also pull any still-pending scan items from an earlier incomplete scan without duplicates
        prev = self.scan_log_repo.get_latest_incomplete_for_website(site.id)
        if prev is not None and prev.id != scan_id:
            prev_items = self.scan_log_repo.list_pending_scan_items(
                prev.id, limit=self.settings.scanner_max_discovery_urls
            )
            for pitem in prev_items:
                if pitem.url_hash in seen_hashes:
                    continue
                if not matches_url_patterns(
                    pitem.normalized_url,
                    exclude_patterns=list(site.excluded_url_patterns or []),
                    apply_default_excludes=False,
                ):
                    continue
                decision = classify_url(
                    pitem.normalized_url, domain=site.domain, custom_rules=url_rules
                )
                self.scan_log_repo.upsert_scan_item(
                    scan_log_id=scan_id,
                    website_id=site.id,
                    url=pitem.url,
                    normalized_url=pitem.normalized_url,
                    url_hash=pitem.url_hash,
                    content_type=pitem.content_type or decision.content_type,
                    discovery_sources=list(pitem.discovery_sources or []),
                    discovered_title=pitem.discovered_title,
                    status="pending",
                    content_id=pitem.content_id,
                )

    def _queue_failed_for_retry(
        self,
        *,
        scan_id: int,
        site: Website,
        url_rules: list[WebsiteUrlRule],
        limit: int,
    ) -> None:
        failed_contents = self.content_repo.list_failed_for_website(site.id, limit=limit)
        for row in failed_contents:
            content_type = row.content_type
            if not row.manual_classification_override:
                content_type = classify_url(
                    row.canonical_url, domain=site.domain, custom_rules=url_rules
                ).content_type
            self.scan_log_repo.upsert_scan_item(
                scan_log_id=scan_id,
                website_id=site.id,
                url=row.url,
                normalized_url=row.canonical_url,
                url_hash=row.url_hash,
                content_type=content_type,
                discovery_sources=list(row.discovery_sources or []),
                discovered_title=row.title,
                status="pending",
                content_id=row.id,
            )

    def _extract_pending_in_batches(
        self,
        *,
        scan_id: int,
        site: Website,
        url_rules: list[WebsiteUrlRule],
        robots: RobotsPolicyChecker,
        batch_size: int,
        run_limit: int,
        inline_candidates: dict[str, DiscoveredCandidate],
        new_content_ids: set[int],
    ) -> bool:
        extractor = ContentExtractionEngine(settings=self.settings)
        media_processor = MediaAssetProcessor(
            settings=self.settings,
            fetcher=self.fetcher,
            media_repo=self.media_repo,
        )

        processed_this_run = 0
        batch_index = 0
        paused_by_guardian = False

        while processed_this_run < run_limit:
            if batch_index > 0:
                _, is_critical = self._guardian_status()
                if is_critical:
                    paused_by_guardian = True
                    break

            remaining_budget = run_limit - processed_this_run
            batch = self.scan_log_repo.list_pending_scan_items(
                scan_id, limit=min(batch_size, remaining_budget)
            )
            if not batch:
                break

            batch_index += 1
            processed_in_batch = 0
            for item in batch:
                self.scan_log_repo.update(
                    scan_id,
                    {
                        "current_source": (
                            (item.discovery_sources or ["extractor"])[0]
                            if item.discovery_sources
                            else "extractor"
                        ),
                        "current_url": item.url[:1000],
                        "heartbeat_at": utc_now_naive(),
                    },
                )
                cand = inline_candidates.get(item.url_hash)
                self._process_single_scan_item(
                    site=site,
                    item=item,
                    cand=cand,
                    url_rules=url_rules,
                    robots=robots,
                    extractor=extractor,
                    media_processor=media_processor,
                    new_content_ids=new_content_ids,
                )
                processed_this_run += 1
                processed_in_batch += 1
                if processed_in_batch % 5 == 0:
                    self._sync_progress_counts(scan_id=scan_id, site_id=site.id)

            if processed_in_batch % 5 != 0:
                self._sync_progress_counts(scan_id=scan_id, site_id=site.id)

        return paused_by_guardian

    def _process_single_scan_item(
        self,
        *,
        site: Website,
        item: WebsiteScanItem,
        cand: DiscoveredCandidate | None,
        url_rules: list[WebsiteUrlRule],
        robots: RobotsPolicyChecker,
        extractor: ContentExtractionEngine,
        media_processor: MediaAssetProcessor,
        new_content_ids: set[int],
    ) -> None:
        now_naive = utc_now_naive()
        existing = (
            self.content_repo.get_by_id(item.content_id)
            if item.content_id is not None
            else self.content_repo.get_by_website_and_url_hash(site.id, item.url_hash)
        )
        if _is_email_protection_url(item.url):
            if existing and not existing.is_excluded:
                self.content_repo.update(existing.id, {"is_excluded": True, "status": "excluded"})
            self.scan_log_repo.update_scan_item(
                item.id,
                {
                    "content_id": None,
                    "status": "excluded",
                    "failure_reason": "ignored_email_protection",
                    "error_detail": "Ignored Cloudflare email-protection link.",
                    "processed_at": now_naive,
                },
            )
            return
        was_new = (
            existing is None
            or existing.id in new_content_ids
            or existing.extraction_status != "extracted"
        )
        manual_override_type = (
            existing.content_type if existing and existing.manual_classification_override else None
        )

        if not robots.is_allowed(item.url):
            self._record_item_failure_or_exclusion(
                site=site,
                item=item,
                existing=existing,
                item_status="excluded",
                http_status=None,
                failure_reason="robots_txt_disallowed",
                error_detail="URL blocked by site robots.txt crawl policy.",
                now_naive=now_naive,
            )
            return

        extracted = None
        response_status: int | None = None

        # Only skip network fetch when adapter supplied complete Markdown or full WP blog_post HTML
        if cand and cand.raw_markdown and not cand.raw_html:
            extracted = extractor.extract_from_markdown(
                cand.raw_markdown,
                page_url=item.url,
                domain=site.domain,
                candidate=cand,
                url_rules=url_rules,
                manual_override_type=manual_override_type,
                default_language=site.primary_language,
            )
            response_status = 200
        elif (
            cand
            and cand.raw_html
            and cand.source_method == "wordpress"
            and len(cand.raw_html) >= 200
        ):
            extracted = extractor.extract_from_html(
                cand.raw_html,
                page_url=item.url,
                domain=site.domain,
                candidate=cand,
                url_rules=url_rules,
                manual_override_type=manual_override_type,
                default_language=site.primary_language,
            )
            response_status = 200
        else:
            try:
                response = self.fetcher.fetch(item.url, stop_on_redirect=True)
                response_status = response.status_code
            except ScannerError as exc:
                self._record_item_failure_or_exclusion(
                    site=site,
                    item=item,
                    existing=existing,
                    item_status="failed",
                    http_status=None,
                    failure_reason="fetch_error",
                    error_detail=str(exc),
                    now_naive=now_naive,
                )
                return

            if response.status_code in {301, 302, 303, 307, 308}:
                if existing:
                    self.content_repo.update(
                        existing.id, {"is_excluded": True, "status": "excluded"}
                    )
                self.scan_log_repo.update_scan_item(
                    item.id,
                    {
                        "content_id": None,
                        "status": "excluded",
                        "http_status": response.status_code,
                        "failure_reason": "ignored_redirect",
                        "error_detail": "Ignored redirect URL.",
                        "processed_at": now_naive,
                    },
                )
                return

            if response.status_code != 200:
                self._record_item_failure_or_exclusion(
                    site=site,
                    item=item,
                    existing=existing,
                    item_status="failed",
                    http_status=response.status_code,
                    failure_reason=f"http_{response.status_code}",
                    error_detail=f"Origin returned HTTP {response.status_code} for {item.url}.",
                    now_naive=now_naive,
                )
                return

            try:
                extracted = extractor.extract_from_html(
                    response.text,
                    page_url=item.url,
                    domain=site.domain,
                    candidate=cand,
                    url_rules=url_rules,
                    manual_override_type=manual_override_type,
                    default_language=site.primary_language,
                )
            except Exception as exc:
                self._record_item_failure_or_exclusion(
                    site=site,
                    item=item,
                    existing=existing,
                    item_status="failed",
                    http_status=response.status_code,
                    failure_reason="extraction_error",
                    error_detail=f"Extraction failed: {exc}",
                    now_naive=now_naive,
                )
                return

        featured_media_id = existing.featured_media_id if existing else None
        if extracted.featured_image_url:
            try:
                asset = media_processor.process_featured_image(
                    source_url=extracted.featured_image_url,
                    website_id=site.id,
                    alt_text=extracted.featured_image_alt or extracted.title,
                )
                if asset is not None:
                    featured_media_id = asset.id
            except (MediaValidationError, ScannerError):
                pass

        changed = bool(
            existing is not None
            and existing.extraction_status == "extracted"
            and has_content_changed(existing, extracted.content_hash)
        )
        if changed and existing is not None:
            create_revision_snapshot(self.content_repo, existing)

        recent = self.content_repo.list_recent_for_website(site.id, limit=50)
        dup_match = find_near_duplicate(
            title=extracted.title,
            markdown_content=extracted.markdown_content,
            existing_contents=recent,
            exclude_content_id=existing.id if existing else None,
        )

        # Always preserve discovered url_hash so lookup stays deterministic across updates.
        merged_sources = list(existing.discovery_sources or []) if existing else []
        for src in item.discovery_sources or []:
            if src not in merged_sources:
                merged_sources.append(src)

        payload: dict[str, Any] = {
            "website_id": site.id,
            "featured_media_id": featured_media_id,
            "content_type": extracted.content_type,
            "classification_method": extracted.classification_method,
            "manual_classification_override": (
                existing.manual_classification_override if existing else False
            ),
            "is_excluded": False,
            "title": extracted.title,
            "url": item.url[:1000],
            "canonical_url": extracted.canonical_url[:1000],
            "url_hash": item.url_hash,
            "h1_text": extracted.h1_text[:500] if extracted.h1_text else None,
            "author": extracted.author[:255] if extracted.author else None,
            "meta_description": extracted.meta_description,
            "original_content": extracted.original_content,
            "extracted_content": extracted.extracted_content,
            "markdown_content": extracted.markdown_content,
            "optimized_context": extracted.optimized_context,
            "structured_data_json": extracted.structured_data_json,
            "keywords": extracted.keywords,
            "categories": extracted.categories,
            "tags": extracted.tags,
            "discovery_sources": merged_sources,
            "language": extracted.language,
            "content_hash": extracted.content_hash,
            "word_count": extracted.word_count,
            "http_status": response_status,
            "extraction_status": "extracted",
            "extraction_error": None,
            "status": "updated" if changed else "extracted",
            "near_duplicate_of_id": dup_match[0] if dup_match else None,
            "near_duplicate_score": dup_match[1] if dup_match else None,
            "published_at": (
                extracted.published_at.replace(tzinfo=None)
                if extracted.published_at
                else (existing.published_at if existing else None)
            ),
            "source_updated_at": (
                extracted.source_updated_at.replace(tzinfo=None)
                if extracted.source_updated_at
                else (existing.source_updated_at if existing else None)
            ),
            "last_discovered_at": now_naive,
            "last_checked_at": now_naive,
        }

        if existing is None:
            payload["first_discovered_at"] = now_naive
            payload["is_historical_baseline"] = not site.initial_scan_completed
            content_row = self.content_repo.create(payload)
        else:
            content_row = self.content_repo.update(existing.id, payload) or existing

        final_item_status = "new" if was_new else ("updated" if changed else "unchanged")
        self.scan_log_repo.update_scan_item(
            item.id,
            {
                "content_id": content_row.id,
                "content_type": content_row.content_type,
                "status": final_item_status,
                "http_status": response_status,
                "failure_reason": None,
                "error_detail": None,
                "processed_at": now_naive,
            },
        )
        # Never auto-approve or auto-trigger AI generation from scan extraction.
        # Eligible items enter Pending Review / Needs Re-review safely.
        if self.approval_service is not None:
            with contextlib.suppress(Exception):
                self.approval_service.sync_extracted_content(
                    content=content_row,
                    website=site,
                    extracted_headings=extracted.headings,
                    extracted_images=extracted.images,
                    featured_image_url=extracted.featured_image_url,
                    featured_image_alt=extracted.featured_image_alt,
                    changed=changed,
                )

    def _record_item_failure_or_exclusion(
        self,
        *,
        site: Website,
        item: WebsiteScanItem,
        existing: WebsiteContent | None,
        item_status: str,
        http_status: int | None,
        failure_reason: str,
        error_detail: str,
        now_naive: datetime,
    ) -> None:
        content_id = existing.id if existing else None
        if item_status == "failed":
            if existing is None:
                created = self.content_repo.create(
                    {
                        "website_id": site.id,
                        "content_type": item.content_type or "page",
                        "classification_method": "default",
                        "title": (item.discovered_title or item.normalized_url)[:500],
                        "url": item.url[:1000],
                        "canonical_url": item.normalized_url[:1000],
                        "url_hash": item.url_hash,
                        "discovery_sources": list(item.discovery_sources or []),
                        "language": site.primary_language,
                        "content_hash": item.url_hash,
                        "word_count": 0,
                        "http_status": http_status,
                        "extraction_status": "failed",
                        "extraction_error": error_detail[:500],
                        "status": "failed",
                        "first_discovered_at": now_naive,
                        "last_discovered_at": now_naive,
                        "last_checked_at": now_naive,
                    }
                )
                content_id = created.id
            else:
                self.content_repo.update(
                    existing.id,
                    {
                        "http_status": http_status,
                        "extraction_status": "failed",
                        "extraction_error": error_detail[:500],
                        "status": "failed",
                        "last_checked_at": now_naive,
                    },
                )

        self.scan_log_repo.update_scan_item(
            item.id,
            {
                "content_id": content_id,
                "status": item_status,
                "http_status": http_status,
                "failure_reason": failure_reason[:120],
                "error_detail": error_detail[:500],
                "processed_at": now_naive,
            },
        )

    def _apply_initial_baseline(
        self, *, site: Website, candidates: list[DiscoveredCandidate]
    ) -> list[DiscoveredCandidate]:
        if site.initial_scan_completed:
            return candidates
        mode = site.baseline_mode
        if mode == "after_date" and site.baseline_after_date is not None:
            cutoff = site.baseline_after_date.replace(tzinfo=None)
            return [
                c
                for c in candidates
                if c.published_at is None or c.published_at.replace(tzinfo=None) >= cutoff
            ]
        if mode == "latest_n" and site.baseline_limit is not None:
            sorted_c = sorted(
                candidates,
                key=lambda c: c.published_at.timestamp() if c.published_at else 0.0,
                reverse=True,
            )
            return sorted_c[: site.baseline_limit]
        return candidates

    def _sync_progress_counts(self, *, scan_id: int, site_id: int) -> dict[str, int]:
        counts = self.scan_log_repo.count_scan_items_by_status(scan_id)
        new_cnt = counts.get("new", 0)
        upd_cnt = counts.get("updated", 0)
        unch_cnt = counts.get("unchanged", 0)
        fail_cnt = counts.get("failed", 0)
        excl_cnt = counts.get("excluded", 0)
        pend_cnt = counts.get("pending", 0)
        total_found = sum(counts.values())
        processed_cnt = new_cnt + upd_cnt + unch_cnt

        content_stats = self.content_repo.get_stats(website_id=site_id)

        self.scan_log_repo.update(
            scan_id,
            {
                "urls_found": total_found,
                "articles_processed": processed_cnt,
                "urls_pending_extraction": pend_cnt,
                "new_articles": new_cnt,
                "updated_articles": upd_cnt,
                "unchanged_articles": unch_cnt,
                "skipped_articles": excl_cnt,
                "failed_articles": fail_cnt,
                "excluded_count": excl_cnt,
                "homepage_count": content_stats["homepage_count"],
                "page_count": content_stats["page_count"],
                "blog_post_count": content_stats["blog_post_count"],
                "other_count": (
                    content_stats["blog_index_count"]
                    + content_stats.get("game_page_count", 0)
                    + content_stats["other_count"]
                ),
                "heartbeat_at": utc_now_naive(),
            },
        )
        return counts

    def _finalize_scan_log(
        self,
        *,
        scan_id: int,
        site: Website,
        scan_mode: str,
        started_monotonic: float,
        discovery_output: AggregatedDiscoveryOutput | None,
        paused_mid_run: bool,
    ) -> ScanLogResponse:
        now_naive = utc_now_naive()
        counts = self._sync_progress_counts(scan_id=scan_id, site_id=site.id)
        total_found = sum(counts.values())
        pend_cnt = counts.get("pending", 0)
        fail_cnt = counts.get("failed", 0)
        processed_cnt = counts.get("new", 0) + counts.get("updated", 0) + counts.get("unchanged", 0)
        sources_failed = list(discovery_output.sources_failed) if discovery_output else []
        sources_ok = list(discovery_output.sources_completed) if discovery_output else []

        if paused_mid_run:
            final_status = "paused"
            err_msg = (
                f"Scan paused by Resource Guardian with {pend_cnt} URLs still pending extraction."
            )
        elif pend_cnt > 0:
            final_status = "incomplete"
            err_msg = (
                f"Discovered {total_found} URLs; extracted {processed_cnt} so far "
                f"({pend_cnt} remaining pending extraction)."
            )
        elif total_found == 0 and sources_failed and not sources_ok:
            final_status = "failed"
            err_msg = "; ".join(str(s.get("error") or "") for s in sources_failed[:3])[:500]
        elif fail_cnt > 0 or sources_failed:
            final_status = (
                "partially_completed" if processed_cnt > 0 or total_found > 0 else "failed"
            )
            err_msg = f"{fail_cnt} URL(s) failed extraction." if fail_cnt else None
        else:
            final_status = "completed"
            err_msg = None

        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        updated_scan = self.scan_log_repo.update(
            scan_id,
            {
                "status": final_status,
                "current_source": None,
                "current_url": None,
                "error_message": err_msg,
                "duration_ms": duration_ms,
                "completed_at": now_naive,
                "heartbeat_at": now_naive,
            },
        )
        assert updated_scan is not None

        site_updates: dict[str, Any] = {
            "last_scanned_at": now_naive,
            "next_scan_at": (
                now_naive + timedelta(minutes=site.scan_interval_minutes)
                if site.auto_scan and site.status == "active"
                else None
            ),
        }
        if final_status in {"completed", "partially_completed", "incomplete"}:
            site_updates["last_successful_scan_at"] = now_naive
            if pend_cnt == 0 and scan_mode != "discover_only":
                site_updates["initial_scan_completed"] = True
        self.website_repo.update(site.id, site_updates)

        self.activity_repo.create(
            user_id=None,
            actor_type="scheduler",
            category="scans",
            action=f"scan.{final_status}",
            level="warning"
            if final_status in {"failed", "partially_completed", "incomplete", "paused"}
            else "info",
            message=(
                f"Scan #{scan_id} ({scan_mode}) for '{site.name}' finished with status "
                f"'{final_status}' ({processed_cnt} processed, "
                f"{pend_cnt} pending, {fail_cnt} failed)."
            ),
            metadata={
                "scan_id": scan_id,
                "website_id": site.id,
                "urls_found": total_found,
                "processed": processed_cnt,
                "pending": pend_cnt,
                "failed": fail_cnt,
            },
            ip_address=None,
        )
        return self._to_scan_response(updated_scan, site_name=site.name)

    def _finalize_failed(
        self, *, scan_id: int, started_monotonic: float, error_message: str
    ) -> None:
        self.scan_log_repo.update(
            scan_id,
            {
                "status": "failed",
                "current_source": None,
                "current_url": None,
                "error_message": error_message[:500],
                "duration_ms": int((time.monotonic() - started_monotonic) * 1000),
                "completed_at": utc_now_naive(),
                "heartbeat_at": utc_now_naive(),
            },
        )
