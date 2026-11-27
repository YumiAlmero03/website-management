from __future__ import annotations

import math
from datetime import timedelta
from urllib.parse import urlparse

from app.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now
from app.models.website import Website
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.article_repo import ArticleRepositoryProtocol
from app.repositories.brand_repo import BrandRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.website import (
    ALLOWED_BASELINE_MODES,
    ALLOWED_DISCOVERY_METHODS,
    ALLOWED_WEBSITE_STATUSES,
    ALLOWED_WEBSITE_TYPES,
    WebsiteConnectivityResponse,
    WebsiteCreateRequest,
    WebsiteDiscoverResponse,
    WebsiteListResponse,
    WebsiteResponse,
    WebsiteUpdateRequest,
)
from app.services.scanner.discovery import WebsiteAutoDiscovery
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.security import SafeHttpFetcher
from app.services.scanner.url_normalizer import normalize_domain, validate_url_patterns


def _validate_optional_http_url(url: str | None, *, field_name: str) -> str | None:
    if url is None:
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValidationAppError(f"{field_name} must be a valid http(s) URL.")
    if parsed.username or parsed.password:
        raise ValidationAppError(f"{field_name} must not contain embedded credentials.")
    return cleaned


class WebsiteService:
    def __init__(
        self,
        *,
        settings: Settings,
        website_repo: WebsiteRepositoryProtocol,
        brand_repo: BrandRepositoryProtocol,
        article_repo: ArticleRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        fetcher: SafeHttpFetcher,
    ) -> None:
        self.settings = settings
        self.website_repo = website_repo
        self.brand_repo = brand_repo
        self.article_repo = article_repo
        self.activity_repo = activity_repo
        self.fetcher = fetcher

    def _to_response(self, site: Website) -> WebsiteResponse:
        now = utc_now()
        brand = self.brand_repo.get_by_id(site.brand_id)
        return WebsiteResponse(
            id=site.id,
            brand_id=site.brand_id,
            brand_name=brand.name if brand else None,
            name=site.name,
            domain=site.domain,
            website_type=site.website_type,
            discovery_method=site.discovery_method,
            rss_url=site.rss_url,
            sitemap_url=site.sitemap_url,
            llms_url=site.llms_url,
            api_endpoint=site.api_endpoint,
            article_url_patterns=list(site.article_url_patterns or []),
            excluded_url_patterns=list(site.excluded_url_patterns or []),
            scan_interval_minutes=site.scan_interval_minutes,
            auto_scan=site.auto_scan,
            auto_generate=site.auto_generate,
            initial_scan_completed=site.initial_scan_completed,
            baseline_mode=site.baseline_mode,
            baseline_after_date=ensure_utc(site.baseline_after_date),
            baseline_limit=site.baseline_limit,
            last_scanned_at=ensure_utc(site.last_scanned_at),
            last_successful_scan_at=ensure_utc(site.last_successful_scan_at),
            next_scan_at=ensure_utc(site.next_scan_at),
            status=site.status,
            article_count=self.article_repo.count_by_website(site.id),
            created_at=ensure_utc(site.created_at) or now,
            updated_at=ensure_utc(site.updated_at) or now,
        )

    def list_websites(
        self,
        *,
        page: int,
        page_size: int,
        brand_id: int | None = None,
        status: str | None = None,
        website_type: str | None = None,
        search: str | None = None,
    ) -> WebsiteListResponse:
        rows, total = self.website_repo.list_paginated(
            page=page,
            page_size=page_size,
            brand_id=brand_id,
            status=status,
            website_type=website_type,
            search=search,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return WebsiteListResponse(
            items=[self._to_response(row) for row in rows],
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
            ),
        )

    def get_website(self, website_id: int) -> WebsiteResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        return self._to_response(site)

    def create_website(
        self,
        payload: WebsiteCreateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteResponse:
        if self.brand_repo.get_by_id(payload.brand_id) is None:
            raise NotFoundError(f"Brand #{payload.brand_id} not found.")

        try:
            domain = normalize_domain(payload.domain)
            include_patterns = validate_url_patterns(payload.article_url_patterns)
            exclude_patterns = validate_url_patterns(payload.excluded_url_patterns)
        except ValueError as exc:
            raise ValidationAppError(str(exc)) from exc

        self._validate_enums(
            website_type=payload.website_type,
            discovery_method=payload.discovery_method,
            baseline_mode=payload.baseline_mode,
            status=payload.status,
        )

        if self.website_repo.get_by_brand_and_domain(payload.brand_id, domain) is not None:
            raise ConflictError(f"Domain '{domain}' is already registered under this brand.")

        next_scan_at = (
            (utc_now() + timedelta(minutes=payload.scan_interval_minutes)).replace(tzinfo=None)
            if payload.auto_scan and payload.status == "active"
            else None
        )

        site = self.website_repo.create(
            {
                "brand_id": payload.brand_id,
                "name": payload.name.strip(),
                "domain": domain,
                "website_type": payload.website_type,
                "discovery_method": payload.discovery_method,
                "rss_url": _validate_optional_http_url(payload.rss_url, field_name="rss_url"),
                "sitemap_url": _validate_optional_http_url(
                    payload.sitemap_url, field_name="sitemap_url"
                ),
                "llms_url": _validate_optional_http_url(payload.llms_url, field_name="llms_url"),
                "api_endpoint": _validate_optional_http_url(
                    payload.api_endpoint, field_name="api_endpoint"
                ),
                "article_url_patterns": include_patterns,
                "excluded_url_patterns": exclude_patterns,
                "scan_interval_minutes": payload.scan_interval_minutes,
                "auto_scan": payload.auto_scan,
                "auto_generate": payload.auto_generate,
                "baseline_mode": payload.baseline_mode,
                "baseline_after_date": (
                    payload.baseline_after_date.replace(tzinfo=None)
                    if payload.baseline_after_date
                    else None
                ),
                "baseline_limit": payload.baseline_limit,
                "next_scan_at": next_scan_at,
                "status": payload.status,
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.created",
            level="info",
            message=f"Registered website '{site.name}' ({site.domain}).",
            metadata={"website_id": site.id, "brand_id": site.brand_id, "domain": site.domain},
            ip_address=ip_address,
        )
        return self._to_response(site)

    def update_website(
        self,
        website_id: int,
        payload: WebsiteUpdateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteResponse:
        existing = self.website_repo.get_by_id(website_id)
        if existing is None:
            raise NotFoundError(f"Website #{website_id} not found.")

        raw = payload.model_dump(exclude_unset=True)
        updates: dict[str, object] = {}

        target_brand_id = int(raw.get("brand_id", existing.brand_id))
        if "brand_id" in raw:
            if self.brand_repo.get_by_id(target_brand_id) is None:
                raise NotFoundError(f"Brand #{target_brand_id} not found.")
            updates["brand_id"] = target_brand_id

        target_domain = existing.domain
        if "domain" in raw and raw["domain"] is not None:
            try:
                target_domain = normalize_domain(raw["domain"])
            except ValueError as exc:
                raise ValidationAppError(str(exc)) from exc
            updates["domain"] = target_domain

        conflict = self.website_repo.get_by_brand_and_domain(target_brand_id, target_domain)
        if conflict is not None and conflict.id != website_id:
            raise ConflictError(f"Domain '{target_domain}' is already registered under this brand.")

        self._validate_enums(
            website_type=raw.get("website_type"),
            discovery_method=raw.get("discovery_method"),
            baseline_mode=raw.get("baseline_mode"),
            status=raw.get("status"),
        )

        if "name" in raw and raw["name"] is not None:
            updates["name"] = raw["name"].strip()
        for url_field in ("rss_url", "sitemap_url", "llms_url", "api_endpoint"):
            if url_field in raw:
                updates[url_field] = _validate_optional_http_url(
                    raw[url_field], field_name=url_field
                )
        try:
            if "article_url_patterns" in raw:
                updates["article_url_patterns"] = validate_url_patterns(raw["article_url_patterns"])
            if "excluded_url_patterns" in raw:
                updates["excluded_url_patterns"] = validate_url_patterns(
                    raw["excluded_url_patterns"]
                )
        except ValueError as exc:
            raise ValidationAppError(str(exc)) from exc

        for simple_field in (
            "website_type",
            "discovery_method",
            "scan_interval_minutes",
            "auto_scan",
            "auto_generate",
            "baseline_mode",
            "baseline_limit",
            "status",
        ):
            if simple_field in raw:
                updates[simple_field] = raw[simple_field]

        if "baseline_after_date" in raw:
            val = raw["baseline_after_date"]
            updates["baseline_after_date"] = val.replace(tzinfo=None) if val else None

        updated = self.website_repo.update(website_id, updates)
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.updated",
            level="info",
            message=f"Updated website '{updated.name}' ({updated.domain}).",
            metadata={"website_id": updated.id, "updated_fields": sorted(updates.keys())},
            ip_address=ip_address,
        )
        return self._to_response(updated)

    def delete_website(
        self,
        website_id: int,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> None:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")

        article_count = self.article_repo.count_by_website(website_id)
        if article_count > 0:
            raise ConflictError(
                f"Cannot delete website '{site.name}' because {article_count} "
                "discovered article(s) are stored in the Content Library. "
                "Set status to 'paused' or 'archived' instead."
            )

        self.website_repo.delete(website_id)
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.deleted",
            level="warning",
            message=f"Deleted website '{site.name}' ({site.domain}).",
            metadata={"website_id": website_id, "domain": site.domain},
            ip_address=ip_address,
        )

    def test_connectivity(self, website_id: int) -> WebsiteConnectivityResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        robots = RobotsPolicyChecker(
            fetcher=self.fetcher,
            user_agent=self.settings.scanner_user_agent,
            respect_robots=self.settings.scanner_respect_robots_txt,
        )
        discovery = WebsiteAutoDiscovery(fetcher=self.fetcher, robots=robots)
        result = discovery.test_connectivity(site.domain)
        return WebsiteConnectivityResponse(
            reachable=result.reachable,
            status_code=result.status_code,
            final_url=result.final_url,
            title=result.title,
            detected_website_type=result.detected_website_type,
            error=result.error,
        )

    def discover_sources(
        self,
        website_id: int,
        *,
        apply_detected: bool,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteDiscoverResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        robots = RobotsPolicyChecker(
            fetcher=self.fetcher,
            user_agent=self.settings.scanner_user_agent,
            respect_robots=self.settings.scanner_respect_robots_txt,
        )
        discovery = WebsiteAutoDiscovery(fetcher=self.fetcher, robots=robots)
        result = discovery.discover_sources(site.domain)

        if apply_detected:
            updates: dict[str, object] = {}
            if result.rss_urls and not site.rss_url:
                updates["rss_url"] = result.rss_urls[0]
            if result.sitemap_urls and not site.sitemap_url:
                updates["sitemap_url"] = result.sitemap_urls[0]
            if result.llms_urls and not site.llms_url:
                updates["llms_url"] = result.llms_urls[0]
            if result.wordpress_api_url and not site.api_endpoint:
                updates["api_endpoint"] = result.wordpress_api_url
            if updates:
                self.website_repo.update(site.id, updates)
                self.activity_repo.create(
                    user_id=user_id,
                    actor_type="admin",
                    category="websites",
                    action="website.sources_discovered",
                    level="info",
                    message=f"Auto-discovered sources for '{site.name}' ({site.domain}).",
                    metadata={"website_id": site.id, "applied": sorted(updates.keys())},
                    ip_address=ip_address,
                )

        return WebsiteDiscoverResponse(
            reachable=result.reachable,
            homepage_url=result.homepage_url,
            rss_urls=result.rss_urls,
            sitemap_urls=result.sitemap_urls,
            llms_urls=result.llms_urls,
            wordpress_api_url=result.wordpress_api_url,
            recommended_method=result.recommended_method,
            notes=result.notes,
        )

    @staticmethod
    def _validate_enums(
        *,
        website_type: str | None,
        discovery_method: str | None,
        baseline_mode: str | None,
        status: str | None,
    ) -> None:
        if website_type is not None and website_type not in ALLOWED_WEBSITE_TYPES:
            raise ValidationAppError(
                f"Invalid website_type '{website_type}'. "
                f"Allowed: {', '.join(ALLOWED_WEBSITE_TYPES)}."
            )
        if discovery_method is not None and discovery_method not in ALLOWED_DISCOVERY_METHODS:
            raise ValidationAppError(
                f"Invalid discovery_method '{discovery_method}'. "
                f"Allowed: {', '.join(ALLOWED_DISCOVERY_METHODS)}."
            )
        if baseline_mode is not None and baseline_mode not in ALLOWED_BASELINE_MODES:
            raise ValidationAppError(
                f"Invalid baseline_mode '{baseline_mode}'. "
                f"Allowed: {', '.join(ALLOWED_BASELINE_MODES)}."
            )
        if status is not None and status not in ALLOWED_WEBSITE_STATUSES:
            raise ValidationAppError(
                f"Invalid status '{status}'. Allowed: {', '.join(ALLOWED_WEBSITE_STATUSES)}."
            )
