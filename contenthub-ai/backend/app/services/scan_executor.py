from __future__ import annotations

import math
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from app.config import BACKEND_ROOT, Settings
from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.website import Website
from app.models.website_scan_log import WebsiteScanLog
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.article_repo import ArticleRepositoryProtocol
from app.repositories.brand_repo import BrandRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.scan_log_repo import ScanLogRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.website import ScanLogListResponse, ScanLogResponse
from app.services.content.duplicate import find_near_duplicate
from app.services.content.extractor import ContentExtractionEngine
from app.services.content.media import MediaAssetProcessor, MediaValidationError
from app.services.content.revisions import create_revision_snapshot, has_content_changed
from app.services.monitoring.health_service import HealthService
from app.services.scanner.base import DiscoveredCandidate
from app.services.scanner.exceptions import DiscoveryError, ScannerError
from app.services.scanner.manager import WebsiteDiscoveryManager
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.security import SafeHttpFetcher
from app.services.settings_service import SettingsService

ScanDispatcher = Callable[[int], None]


def default_subprocess_dispatcher(scan_id: int) -> None:
    """Spawn a detached non-blocking Python worker subprocess to execute a single scan."""
    subprocess.Popen(
        [sys.executable, "-m", "app.cli", "run-scan", "--scan-id", str(scan_id)],
        cwd=str(BACKEND_ROOT),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@dataclass
class ScheduledScanRunSummary:
    paused_by_resource_guardian: bool
    guardian_status: str
    guardian_reasons: list[str]
    stale_recovered: int
    due_websites_found: int
    scans_executed: int
    scans_succeeded: int
    scans_failed: int
    skipped_locked: int


class ScanExecutorService:
    """Durable MySQL-backed Phase 2 website scan orchestrator with Resource Guardian checks."""

    def __init__(
        self,
        *,
        settings: Settings,
        website_repo: WebsiteRepositoryProtocol,
        brand_repo: BrandRepositoryProtocol,
        article_repo: ArticleRepositoryProtocol,
        scan_log_repo: ScanLogRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        health_service: HealthService,
        settings_service: SettingsService,
        fetcher: SafeHttpFetcher,
        dispatcher: ScanDispatcher | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.website_repo = website_repo
        self.brand_repo = brand_repo
        self.article_repo = article_repo
        self.scan_log_repo = scan_log_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo
        self.health_service = health_service
        self.settings_service = settings_service
        self.fetcher = fetcher
        self.dispatcher = dispatcher or default_subprocess_dispatcher
        self.sleep_fn = sleep_fn
        self.extractor = ContentExtractionEngine(settings=settings)
        self.media_processor = MediaAssetProcessor(
            settings=settings,
            fetcher=fetcher,
            media_repo=media_repo,
        )

    def _to_response(self, scan: WebsiteScanLog) -> ScanLogResponse:
        now = utc_now()
        site = self.website_repo.get_by_id(scan.website_id)
        return ScanLogResponse(
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

    def get_scan(self, scan_id: int) -> ScanLogResponse:
        scan = self.scan_log_repo.get_by_id(scan_id)
        if scan is None:
            raise NotFoundError(f"Scan #{scan_id} not found.")
        return self._to_response(scan)

    def list_website_scans(
        self,
        website_id: int,
        *,
        page: int,
        page_size: int,
    ) -> ScanLogListResponse:
        if self.website_repo.get_by_id(website_id) is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        rows, total = self.scan_log_repo.list_for_website(
            website_id, page=page, page_size=page_size
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return ScanLogListResponse(
            items=[self._to_response(row) for row in rows],
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
        trigger_type: str = "manual",
        user_id: int | None = None,
        ip_address: str | None = None,
        dispatch: bool = True,
    ) -> ScanLogResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")

        # Recover stale scans before checking active lock.
        recovered = self.scan_log_repo.recover_stale_scans(
            stale_minutes=self.settings.scanner_stale_timeout_minutes,
            website_id=website_id,
        )
        if recovered:
            self.activity_repo.create(
                user_id=user_id,
                actor_type="system",
                category="scanner",
                action="scanner.stale_recovered",
                level="warning",
                message=f"Recovered {len(recovered)} stale scan(s) for website '{site.name}'.",
                metadata={"website_id": website_id, "recovered_ids": [r.id for r in recovered]},
                ip_address=ip_address,
            )

        active = self.scan_log_repo.get_active_for_website(website_id)
        if active is not None:
            raise ConflictError(
                f"Website '{site.name}' already has an active scan "
                f"(#{active.id}, status={active.status})."
            )

        # Resource Guardian guard before dispatching scan work.
        effective_settings = self.settings_service.get_effective_map()
        resources = self.health_service.get_system_resources(effective_settings=effective_settings)
        if resources.guardian_status == "critical" or (
            trigger_type == "scheduled" and resources.guardian_status == "warning"
        ):
            reason_summary = "; ".join(resources.guardian_reasons) or resources.guardian_status
            self.activity_repo.create(
                user_id=user_id,
                actor_type="admin" if user_id else "scheduler",
                category="scanner",
                action="scanner.resource_paused",
                level="warning",
                message=(
                    f"Resource Guardian deferred {trigger_type} scan for '{site.name}' "
                    f"({resources.guardian_status}): {reason_summary}"
                ),
                metadata={
                    "website_id": website_id,
                    "guardian_status": resources.guardian_status,
                    "cpu_percent": resources.cpu_percent,
                    "ram_percent": resources.ram_percent,
                },
                ip_address=ip_address,
            )
            raise ServiceUnavailableError(
                f"Resource Guardian delayed scanning ({resources.guardian_status}): "
                f"{reason_summary}",
                code="RESOURCE_GUARDIAN_PAUSED",
            )

        scan = self.scan_log_repo.create(
            website_id=site.id,
            scan_method=site.discovery_method or "auto",
            trigger_type=trigger_type,
            status="pending",
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin" if user_id else "scheduler",
            category="scanner",
            action="scanner.enqueued",
            level="info",
            message=f"Queued {trigger_type} scan #{scan.id} for '{site.name}' ({site.domain}).",
            metadata={"website_id": site.id, "scan_id": scan.id, "trigger_type": trigger_type},
            ip_address=ip_address,
        )

        if dispatch:
            self.dispatcher(scan.id)

        return self._to_response(scan)

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
            raise ConflictError(
                f"Scan #{scan_id} is currently {previous.status} and cannot be retried."
            )
        return self.enqueue_scan(
            previous.website_id,
            trigger_type="retry",
            user_id=user_id,
            ip_address=ip_address,
            dispatch=dispatch,
        )

    def execute_scan(self, scan_id: int) -> ScanLogResponse:
        """Claim and execute a pending scan synchronously (invoked by detached CLI worker)."""
        claimed = self.scan_log_repo.claim_pending(scan_id)
        if claimed is None:
            existing = self.scan_log_repo.get_by_id(scan_id)
            if existing is None:
                raise NotFoundError(f"Scan #{scan_id} not found.")
            return self._to_response(existing)

        site = self.website_repo.get_by_id(claimed.website_id)
        if site is None:
            failed = self.scan_log_repo.update(
                claimed.id,
                {
                    "status": "failed",
                    "error_message": "Website no longer exists.",
                    "completed_at": utc_now_naive(),
                },
            )
            assert failed is not None
            return self._to_response(failed)

        started_perf = time.perf_counter()
        brand = self.brand_repo.get_by_id(site.brand_id)
        default_language = brand.primary_language if brand else "en"
        is_baseline_run = not site.initial_scan_completed

        robots = RobotsPolicyChecker(
            fetcher=self.fetcher,
            user_agent=self.settings.scanner_user_agent,
            respect_robots=self.settings.scanner_respect_robots_txt,
        )
        manager = WebsiteDiscoveryManager(
            settings=self.settings,
            fetcher=self.fetcher,
            robots=robots,
        )

        try:
            discovery = manager.discover_for_website(
                site,
                max_urls=self.settings.scanner_max_urls_per_scan,
            )
        except (DiscoveryError, ScannerError) as exc:
            return self._finalize_failure(site, claimed, started_perf, str(exc))

        if discovery.not_modified:
            return self._finalize_success(
                site=site,
                scan=claimed,
                started_perf=started_perf,
                method_used=discovery.method_used,
                urls_found=0,
                articles_processed=0,
                new_articles=0,
                updated_articles=0,
                unchanged_articles=0,
                skipped_articles=0,
                failed_articles=0,
                etag=discovery.etag,
                last_modified=discovery.last_modified,
                error_message=None,
            )

        candidates, baseline_skipped = self._apply_baseline_policy(
            site=site,
            candidates=discovery.candidates,
            is_baseline_run=is_baseline_run,
        )

        urls_found = discovery.total_discovered or len(discovery.candidates)
        skipped_articles = discovery.skipped_count + baseline_skipped
        articles_processed = 0
        new_articles = 0
        updated_articles = 0
        unchanged_articles = 0
        failed_articles = 0
        errors: list[str] = []

        self.scan_log_repo.update(
            claimed.id,
            {
                "scan_method": discovery.method_used,
                "urls_found": urls_found,
                "skipped_articles": skipped_articles,
                "heartbeat_at": utc_now_naive(),
            },
        )

        crawl_delay = max(
            self.settings.scanner_crawl_delay_seconds,
            robots.get_crawl_delay(f"https://{site.domain}/") or 0.0,
        )
        existing_recent = self.article_repo.list_recent_for_website(site.id, limit=50)

        for idx, candidate in enumerate(candidates):
            if idx > 0 and crawl_delay > 0:
                self.sleep_fn(min(crawl_delay, 5.0))

            try:
                outcome = self._process_candidate(
                    site=site,
                    candidate=candidate,
                    default_language=default_language,
                    is_baseline_run=is_baseline_run,
                    existing_recent=existing_recent,
                )
                articles_processed += 1
                if outcome == "new":
                    new_articles += 1
                elif outcome == "updated":
                    updated_articles += 1
                elif outcome == "unchanged":
                    unchanged_articles += 1
                elif outcome == "skipped":
                    skipped_articles += 1
            except Exception as exc:
                failed_articles += 1
                errors.append(f"{candidate.normalized_url}: {exc}")

            self.scan_log_repo.update(
                claimed.id,
                {
                    "articles_processed": articles_processed,
                    "new_articles": new_articles,
                    "updated_articles": updated_articles,
                    "unchanged_articles": unchanged_articles,
                    "skipped_articles": skipped_articles,
                    "failed_articles": failed_articles,
                    "heartbeat_at": utc_now_naive(),
                },
            )

        error_summary = "; ".join(errors[:5]) if errors else None
        return self._finalize_success(
            site=site,
            scan=claimed,
            started_perf=started_perf,
            method_used=discovery.method_used,
            urls_found=urls_found,
            articles_processed=articles_processed,
            new_articles=new_articles,
            updated_articles=updated_articles,
            unchanged_articles=unchanged_articles,
            skipped_articles=skipped_articles,
            failed_articles=failed_articles,
            etag=discovery.etag,
            last_modified=discovery.last_modified,
            error_message=error_summary,
        )

    def _apply_baseline_policy(
        self,
        *,
        site: Website,
        candidates: list[DiscoveredCandidate],
        is_baseline_run: bool,
    ) -> tuple[list[DiscoveredCandidate], int]:
        if not is_baseline_run:
            return candidates, 0

        mode = (site.baseline_mode or "import_existing").strip().lower()
        if mode == "after_date" and site.baseline_after_date is not None:
            cutoff = ensure_utc(site.baseline_after_date)
            kept = [
                item
                for item in candidates
                if item.published_at is None or (cutoff is not None and item.published_at >= cutoff)
            ]
            return kept, len(candidates) - len(kept)

        if mode == "latest_n" and site.baseline_limit:
            ordered = sorted(
                candidates,
                key=lambda item: item.published_at.timestamp() if item.published_at else 0.0,
                reverse=True,
            )
            kept = ordered[: site.baseline_limit]
            return kept, len(candidates) - len(kept)

        return candidates, 0

    def _process_candidate(
        self,
        *,
        site: Website,
        candidate: DiscoveredCandidate,
        default_language: str,
        is_baseline_run: bool,
        existing_recent: list,
    ) -> str:
        # In new_only baseline mode, record lightweight URL markers without full extraction.
        if is_baseline_run and site.baseline_mode == "new_only":
            from app.services.content.duplicate import compute_content_hash
            from app.services.scanner.url_normalizer import hash_url

            url_hash = hash_url(candidate.normalized_url)
            existing = self.article_repo.get_by_website_and_url_hash(site.id, url_hash)
            if existing is not None:
                self.article_repo.update(existing.id, {"last_checked_at": utc_now_naive()})
                return "unchanged"
            title = (candidate.title or candidate.normalized_url)[:500]
            created = self.article_repo.create(
                {
                    "website_id": site.id,
                    "title": title,
                    "canonical_url": candidate.normalized_url,
                    "url_hash": url_hash,
                    "content_hash": compute_content_hash(title, ""),
                    "word_count": 0,
                    "status": "discovered",
                    "is_historical_baseline": True,
                    "language": default_language,
                    "published_at": candidate.published_at.replace(tzinfo=None)
                    if candidate.published_at
                    else None,
                }
            )
            existing_recent.insert(0, created)
            return "new"

        if candidate.raw_markdown:
            extracted = self.extractor.extract_from_markdown(
                candidate.raw_markdown,
                page_url=candidate.normalized_url,
                candidate=candidate,
                default_language=default_language,
            )
        else:
            raw_html = candidate.raw_html
            page_url = candidate.normalized_url
            if not raw_html or len(raw_html.strip()) < 150:
                response = self.fetcher.fetch(
                    candidate.normalized_url,
                    accept="text/html,application/xhtml+xml,text/markdown;q=0.9,*/*;q=0.5",
                )
                if response.status_code != 200:
                    raise ScannerError(f"HTTP {response.status_code}")
                page_url = response.final_url
                content_type = response.headers.get("content-type", "").lower()
                if "markdown" in content_type or page_url.lower().endswith(".md"):
                    extracted = self.extractor.extract_from_markdown(
                        response.text,
                        page_url=page_url,
                        candidate=candidate,
                        default_language=default_language,
                    )
                else:
                    extracted = self.extractor.extract_from_html(
                        response.text,
                        page_url=page_url,
                        domain=site.domain,
                        candidate=candidate,
                        default_language=default_language,
                    )
            else:
                extracted = self.extractor.extract_from_html(
                    raw_html,
                    page_url=page_url,
                    domain=site.domain,
                    candidate=candidate,
                    default_language=default_language,
                )

        existing = self.article_repo.get_by_website_and_url_hash(site.id, extracted.url_hash)
        now_naive = utc_now_naive()

        if existing is not None:
            if not has_content_changed(existing, extracted.content_hash):
                self.article_repo.update(existing.id, {"last_checked_at": now_naive})
                return "unchanged"

            create_revision_snapshot(self.article_repo, existing)
            featured_media_id = existing.featured_media_id
            if extracted.featured_image_url:
                try:
                    media = self.media_processor.process_featured_image(
                        source_url=extracted.featured_image_url,
                        brand_id=site.brand_id,
                        alt_text=extracted.featured_image_alt or extracted.title,
                    )
                    if media is not None:
                        featured_media_id = media.id
                except (MediaValidationError, ScannerError):
                    pass

            self.article_repo.update(
                existing.id,
                {
                    "featured_media_id": featured_media_id,
                    "title": extracted.title,
                    "canonical_url": extracted.canonical_url,
                    "author": extracted.author,
                    "meta_description": extracted.meta_description,
                    "original_content": extracted.original_content,
                    "markdown_content": extracted.markdown_content,
                    "optimized_context": extracted.optimized_context,
                    "keywords": extracted.keywords,
                    "categories": extracted.categories,
                    "tags": extracted.tags,
                    "language": extracted.language,
                    "content_hash": extracted.content_hash,
                    "word_count": extracted.word_count,
                    "status": "updated",
                    "published_at": extracted.published_at.replace(tzinfo=None)
                    if extracted.published_at
                    else existing.published_at,
                    "source_updated_at": extracted.source_updated_at.replace(tzinfo=None)
                    if extracted.source_updated_at
                    else now_naive,
                    "last_checked_at": now_naive,
                },
            )
            return "updated"

        # New article
        featured_media_id = None
        if extracted.featured_image_url:
            try:
                media = self.media_processor.process_featured_image(
                    source_url=extracted.featured_image_url,
                    brand_id=site.brand_id,
                    alt_text=extracted.featured_image_alt or extracted.title,
                )
                if media is not None:
                    featured_media_id = media.id
            except (MediaValidationError, ScannerError):
                pass

        near_dup = find_near_duplicate(
            title=extracted.title,
            markdown_content=extracted.markdown_content,
            existing_articles=existing_recent,
            threshold=self.settings.content_near_duplicate_threshold,
        )

        created = self.article_repo.create(
            {
                "website_id": site.id,
                "featured_media_id": featured_media_id,
                "title": extracted.title,
                "canonical_url": extracted.canonical_url,
                "url_hash": extracted.url_hash,
                "author": extracted.author,
                "meta_description": extracted.meta_description,
                "original_content": extracted.original_content,
                "markdown_content": extracted.markdown_content,
                "optimized_context": extracted.optimized_context,
                "keywords": extracted.keywords,
                "categories": extracted.categories,
                "tags": extracted.tags,
                "language": extracted.language,
                "content_hash": extracted.content_hash,
                "word_count": extracted.word_count,
                "status": "optimized" if extracted.optimized_context else "extracted",
                "is_historical_baseline": is_baseline_run,
                "near_duplicate_of_id": near_dup[0] if near_dup else None,
                "near_duplicate_score": near_dup[1] if near_dup else None,
                "published_at": extracted.published_at.replace(tzinfo=None)
                if extracted.published_at
                else None,
                "source_updated_at": extracted.source_updated_at.replace(tzinfo=None)
                if extracted.source_updated_at
                else None,
                "discovered_at": now_naive,
                "last_checked_at": now_naive,
            }
        )
        existing_recent.insert(0, created)
        return "new"

    def _finalize_success(
        self,
        *,
        site: Website,
        scan: WebsiteScanLog,
        started_perf: float,
        method_used: str,
        urls_found: int,
        articles_processed: int,
        new_articles: int,
        updated_articles: int,
        unchanged_articles: int,
        skipped_articles: int,
        failed_articles: int,
        etag: str | None,
        last_modified: str | None,
        error_message: str | None,
    ) -> ScanLogResponse:
        now_naive = utc_now_naive()
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        final_status = (
            "partially_completed"
            if failed_articles > 0 and articles_processed > 0
            else ("failed" if failed_articles > 0 and articles_processed == 0 else "completed")
        )

        updated_scan = self.scan_log_repo.update(
            scan.id,
            {
                "scan_method": method_used,
                "urls_found": urls_found,
                "articles_processed": articles_processed,
                "new_articles": new_articles,
                "updated_articles": updated_articles,
                "unchanged_articles": unchanged_articles,
                "skipped_articles": skipped_articles,
                "failed_articles": failed_articles,
                "status": final_status,
                "error_message": error_message,
                "duration_ms": duration_ms,
                "completed_at": now_naive,
                "heartbeat_at": now_naive,
            },
        )
        assert updated_scan is not None

        next_scan = (
            now_naive + timedelta(minutes=site.scan_interval_minutes)
            if site.auto_scan and site.status == "active"
            else None
        )
        website_updates: dict[str, object] = {
            "last_scanned_at": now_naive,
            "next_scan_at": next_scan,
            "last_etag": etag,
            "last_modified_header": last_modified,
        }
        if final_status in {"completed", "partially_completed"}:
            website_updates["last_successful_scan_at"] = now_naive
            website_updates["initial_scan_completed"] = True
        self.website_repo.update(site.id, website_updates)

        self.activity_repo.create(
            user_id=None,
            actor_type="scanner",
            category="scanner",
            action=f"scanner.{final_status}",
            level="warning" if final_status != "completed" else "info",
            message=(
                f"Scan #{scan.id} for '{site.name}' finished ({final_status}): "
                f"{new_articles} new, {updated_articles} updated, {unchanged_articles} unchanged, "
                f"{failed_articles} failed."
            ),
            metadata={
                "website_id": site.id,
                "scan_id": scan.id,
                "method": method_used,
                "new_articles": new_articles,
                "updated_articles": updated_articles,
                "failed_articles": failed_articles,
            },
        )
        return self._to_response(updated_scan)

    def _finalize_failure(
        self,
        site: Website,
        scan: WebsiteScanLog,
        started_perf: float,
        error_message: str,
    ) -> ScanLogResponse:
        now_naive = utc_now_naive()
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        failed = self.scan_log_repo.update(
            scan.id,
            {
                "status": "failed",
                "error_message": error_message[:2000],
                "duration_ms": duration_ms,
                "completed_at": now_naive,
                "heartbeat_at": now_naive,
            },
        )
        assert failed is not None
        next_scan = (
            now_naive + timedelta(minutes=site.scan_interval_minutes)
            if site.auto_scan and site.status == "active"
            else None
        )
        self.website_repo.update(
            site.id,
            {"last_scanned_at": now_naive, "next_scan_at": next_scan},
        )
        self.activity_repo.create(
            user_id=None,
            actor_type="scanner",
            category="scanner",
            action="scanner.failed",
            level="error",
            message=f"Scan #{scan.id} for '{site.name}' failed: {error_message[:300]}",
            metadata={"website_id": site.id, "scan_id": scan.id},
        )
        return self._to_response(failed)

    def run_due_scheduled_scans(self) -> ScheduledScanRunSummary:
        """Process all due auto_scan websites sequentially (invoked by aaPanel Cron CLI)."""
        recovered = self.scan_log_repo.recover_stale_scans(
            stale_minutes=self.settings.scanner_stale_timeout_minutes
        )
        effective_settings = self.settings_service.get_effective_map()
        resources = self.health_service.get_system_resources(effective_settings=effective_settings)
        if resources.guardian_status in {"warning", "critical"}:
            reason_text = "; ".join(resources.guardian_reasons) or resources.guardian_status
            self.activity_repo.create(
                user_id=None,
                actor_type="scheduler",
                category="scanner",
                action="scheduler.resource_paused",
                level="warning",
                message=(
                    f"Resource Guardian paused scheduled website scans "
                    f"({resources.guardian_status}): {reason_text}"
                ),
                metadata={
                    "guardian_status": resources.guardian_status,
                    "cpu_percent": resources.cpu_percent,
                    "ram_percent": resources.ram_percent,
                },
            )
            return ScheduledScanRunSummary(
                paused_by_resource_guardian=True,
                guardian_status=resources.guardian_status,
                guardian_reasons=list(resources.guardian_reasons),
                stale_recovered=len(recovered),
                due_websites_found=0,
                scans_executed=0,
                scans_succeeded=0,
                scans_failed=0,
                skipped_locked=0,
            )

        due_sites = self.website_repo.list_due_for_scan(now=utc_now())
        executed = 0
        succeeded = 0
        failed = 0
        skipped_locked = 0

        for site in due_sites:
            if self.scan_log_repo.get_active_for_website(site.id) is not None:
                skipped_locked += 1
                continue
            scan = self.scan_log_repo.create(
                website_id=site.id,
                scan_method=site.discovery_method or "auto",
                trigger_type="scheduled",
                status="pending",
            )
            result = self.execute_scan(scan.id)
            executed += 1
            if result.status in {"completed", "partially_completed"}:
                succeeded += 1
            else:
                failed += 1

        return ScheduledScanRunSummary(
            paused_by_resource_guardian=False,
            guardian_status=resources.guardian_status,
            guardian_reasons=list(resources.guardian_reasons),
            stale_recovered=len(recovered),
            due_websites_found=len(due_sites),
            scans_executed=executed,
            scans_succeeded=succeeded,
            scans_failed=failed,
            skipped_locked=skipped_locked,
        )
