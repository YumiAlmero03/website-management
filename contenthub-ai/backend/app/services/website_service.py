from __future__ import annotations

import json
import math
import re
from datetime import timedelta
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.security import encrypt_secret
from app.models.base import ensure_utc, utc_now
from app.models.website import Website
from app.models.website_discovery_source import WebsiteDiscoverySource
from app.models.website_url_rule import WebsiteUrlRule
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.category_repo import WebsiteCategoryRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.keyword_approval_repo import KeywordApprovalRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.repositories.website_source_repo import WebsiteSourceConfigRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.website import (
    ALLOWED_BASELINE_MODES,
    ALLOWED_DISCOVERY_METHODS,
    ALLOWED_WEBSITE_STATUSES,
    ALLOWED_WEBSITE_TYPES,
    ContentBreakdownCounts,
    WebsiteConnectivityResponse,
    WebsiteCreateRequest,
    WebsiteDiscoverResponse,
    WebsiteDiscoverySourceResponse,
    WebsiteDiscoverySourceUpdateRequest,
    WebsiteListResponse,
    WebsiteResponse,
    WebsiteUpdateRequest,
    WebsiteUrlRuleCreateRequest,
    WebsiteUrlRuleResponse,
    WebsiteUrlRuleUpdateRequest,
)
from app.services.category_service import slugify_label
from app.services.content.media import MediaValidationError, validate_image_bytes
from app.services.scanner.classifier import RULE_TARGET_TYPES
from app.services.scanner.discovery import WebsiteAutoDiscovery
from app.services.scanner.exceptions import ScannerError
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.security import SafeHttpFetcher, validate_outbound_url
from app.services.scanner.url_normalizer import normalize_domain, validate_url_patterns

ALLOWED_RULE_MATCH_MODES: tuple[str, ...] = ("prefix", "glob", "exact", "regex")
MAX_GSC_SERVICE_ACCOUNT_BYTES = 64 * 1024
GOOGLE_OAUTH_TOKEN_URI = "https://oauth2.googleapis.com/token"


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


def _validate_logo_value(logo_url: str | None) -> str | None:
    if logo_url is None:
        return None
    cleaned = logo_url.strip()
    if not cleaned:
        return None
    if cleaned.startswith("/"):
        return cleaned[:500]
    return _validate_optional_http_url(cleaned, field_name="logo_url")


def _clean_string_list(values: list[str] | None, *, max_len: int = 120) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        item = str(raw).strip()[:max_len]
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


class WebsiteService:
    """Website-centric management service owning brand identity, sources, URL rules, and media."""

    def __init__(
        self,
        *,
        settings: Settings,
        website_repo: WebsiteRepositoryProtocol,
        category_repo: WebsiteCategoryRepositoryProtocol,
        source_config_repo: WebsiteSourceConfigRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        keyword_approval_repo: KeywordApprovalRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        fetcher: SafeHttpFetcher,
    ) -> None:
        self.settings = settings
        self.website_repo = website_repo
        self.category_repo = category_repo
        self.source_config_repo = source_config_repo
        self.content_repo = content_repo
        self.keyword_approval_repo = keyword_approval_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo
        self.fetcher = fetcher

    def _to_response(self, site: Website) -> WebsiteResponse:
        now = utc_now()
        cat = self.category_repo.get_by_id(site.category_id) if site.category_id else None
        raw_stats = self.content_repo.get_stats(website_id=site.id)
        breakdown = ContentBreakdownCounts(
            total_discovered=raw_stats["total_discovered"],
            total_extracted=raw_stats["total_extracted"],
            homepage=raw_stats["homepage_count"],
            page=raw_stats["page_count"],
            game_page=raw_stats.get("game_page_count", 0),
            blog_index=raw_stats["blog_index_count"],
            blog_post=raw_stats["blog_post_count"],
            category=raw_stats.get("category_count", 0),
            tag=raw_stats.get("tag_count", 0),
            archive=raw_stats.get("archive_count", 0),
            custom=raw_stats.get("custom_count", 0),
            pending=raw_stats["pending_count"],
            failed=raw_stats["failed_count"],
            updated=raw_stats["updated_count"],
            excluded=raw_stats["excluded_count"],
        )
        return WebsiteResponse(
            id=site.id,
            category_id=site.category_id,
            category_name=cat.name if cat else None,
            name=site.name,
            brand_name=site.brand_name,
            brand_slug=site.brand_slug,
            logo_url=site.logo_url,
            brand_description=site.brand_description,
            target_audience=site.target_audience,
            target_country=site.target_country,
            primary_language=site.primary_language,
            secondary_languages=list(site.secondary_languages or []),
            tone=site.tone,
            target_keywords=list(site.target_keywords or []),
            keyword_bank=list(site.keyword_bank or []),
            restricted_keywords=list(site.restricted_keywords or []),
            default_hashtags=list(site.default_hashtags or []),
            default_cta=site.default_cta,
            writing_guidelines=site.writing_guidelines,
            ai_instructions=site.ai_instructions,
            domain=site.domain,
            website_type=site.website_type,
            discovery_method=site.discovery_method,
            single_source_only=site.single_source_only,
            rss_url=site.rss_url,
            sitemap_url=site.sitemap_url,
            llms_url=site.llms_url,
            api_endpoint=site.api_endpoint,
            gsc_property_url=site.gsc_property_url,
            gsc_property_verified_at=ensure_utc(site.gsc_property_verified_at),
            gsc_service_account_configured=bool(site.encrypted_gsc_service_account_json),
            article_url_patterns=list(site.article_url_patterns or []),
            excluded_url_patterns=list(site.excluded_url_patterns or []),
            scan_interval_minutes=site.scan_interval_minutes,
            crawl_batch_size=site.crawl_batch_size,
            crawl_max_urls_per_run=site.crawl_max_urls_per_run,
            auto_scan=site.auto_scan,
            auto_generate=site.auto_generate,
            auto_generate_require_published_at=site.auto_generate_require_published_at,
            auto_generate_context_mode=site.auto_generate_context_mode,
            initial_scan_completed=site.initial_scan_completed,
            baseline_mode=site.baseline_mode,
            baseline_after_date=ensure_utc(site.baseline_after_date),
            baseline_limit=site.baseline_limit,
            last_scanned_at=ensure_utc(site.last_scanned_at),
            last_successful_scan_at=ensure_utc(site.last_successful_scan_at),
            next_scan_at=ensure_utc(site.next_scan_at),
            status=site.status,
            article_count=raw_stats["total_discovered"],
            content_counts=breakdown,
            created_at=ensure_utc(site.created_at) or now,
            updated_at=ensure_utc(site.updated_at) or now,
        )

    @staticmethod
    def _to_source_response(src: WebsiteDiscoverySource) -> WebsiteDiscoverySourceResponse:
        now = utc_now()
        return WebsiteDiscoverySourceResponse(
            id=src.id,
            website_id=src.website_id,
            parent_source_id=src.parent_source_id,
            source_type=src.source_type,
            endpoint_url=src.endpoint_url,
            is_enabled=src.is_enabled,
            etag=src.etag,
            last_modified_header=src.last_modified_header,
            last_status_code=src.last_status_code,
            last_urls_found=src.last_urls_found,
            last_checked_at=ensure_utc(src.last_checked_at),
            last_success_at=ensure_utc(src.last_success_at),
            last_error=src.last_error,
            created_at=ensure_utc(src.created_at) or now,
            updated_at=ensure_utc(src.updated_at) or now,
        )

    @staticmethod
    def _to_rule_response(rule: WebsiteUrlRule) -> WebsiteUrlRuleResponse:
        now = utc_now()
        return WebsiteUrlRuleResponse(
            id=rule.id,
            website_id=rule.website_id,
            pattern=rule.pattern,
            target_content_type=rule.target_content_type,
            match_mode=rule.match_mode,
            priority=rule.priority,
            is_enabled=rule.is_enabled,
            notes=rule.notes,
            created_at=ensure_utc(rule.created_at) or now,
            updated_at=ensure_utc(rule.updated_at) or now,
        )

    def _sync_configured_sources(self, site: Website) -> None:
        origin = f"https://{site.domain}"
        self.source_config_repo.upsert_source(
            website_id=site.id,
            source_type="homepage",
            endpoint_url=f"{origin}/",
            is_enabled=True,
        )
        mapping = [
            ("rss", site.rss_url),
            ("sitemap", site.sitemap_url),
            ("llms_txt", site.llms_url),
            (
                "wordpress" if site.website_type == "wordpress" else "rest_api",
                site.api_endpoint,
            ),
        ]
        for source_type, url in mapping:
            if url:
                self.source_config_repo.upsert_source(
                    website_id=site.id,
                    source_type=source_type,
                    endpoint_url=url,
                    is_enabled=True,
                )

    def list_websites(
        self,
        *,
        page: int,
        page_size: int,
        category_id: int | None = None,
        status: str | None = None,
        website_type: str | None = None,
        search: str | None = None,
    ) -> WebsiteListResponse:
        rows, total = self.website_repo.list_paginated(
            page=page,
            page_size=page_size,
            category_id=category_id,
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

    def get_keyword_bank(self, website_id: int) -> list[str]:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")

        keywords: dict[str, str] = {}

        def add(raw: str | None) -> None:
            phrase = " ".join(raw.split()) if raw else ""
            if phrase:
                keywords.setdefault(phrase.casefold(), phrase)

        for keyword in site.keyword_bank or []:
            add(keyword)
        sources = self.keyword_approval_repo.list_content_keyword_sources(website_id)
        for focus, secondary, _ in sources:
            add(focus)
            for keyword in secondary or []:
                add(keyword)
        for _, _, extracted in sources:
            for keyword in extracted or []:
                add(keyword)
        return [keywords[key] for key in sorted(keywords)]

    def create_website(
        self,
        payload: WebsiteCreateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteResponse:
        if (
            payload.category_id is not None
            and self.category_repo.get_by_id(payload.category_id) is None
        ):
            raise NotFoundError(f"Website category #{payload.category_id} not found.")

        try:
            domain = normalize_domain(payload.domain)
            validate_outbound_url(
                f"https://{domain}/",
                trusted_internal_hosts=self.settings.trusted_internal_host_set,
                resolver=self.fetcher.resolver,
                resolve_dns=False,
            )
            include_patterns = validate_url_patterns(payload.article_url_patterns)
            exclude_patterns = validate_url_patterns(payload.excluded_url_patterns)
        except (ValueError, ScannerError) as exc:
            raise ValidationAppError(str(exc)) from exc

        self._validate_enums(
            website_type=payload.website_type,
            discovery_method=payload.discovery_method,
            baseline_mode=payload.baseline_mode,
            status=payload.status,
        )

        if self.website_repo.get_by_domain(domain) is not None:
            raise ConflictError(f"Domain '{domain}' is already registered.")

        site_name = payload.name.strip()
        brand_name = (payload.brand_name or site_name).strip()
        brand_slug = slugify_label(brand_name) or slugify_label(domain)

        next_scan_at = (
            (utc_now() + timedelta(minutes=payload.scan_interval_minutes)).replace(tzinfo=None)
            if payload.auto_scan and payload.status == "active"
            else None
        )

        site = self.website_repo.create(
            {
                "category_id": payload.category_id,
                "name": site_name,
                "brand_name": brand_name,
                "brand_slug": brand_slug,
                "logo_url": _validate_logo_value(payload.logo_url),
                "brand_description": (
                    payload.brand_description.strip() if payload.brand_description else None
                ),
                "target_audience": (
                    payload.target_audience.strip() if payload.target_audience else None
                ),
                "target_country": (
                    payload.target_country.strip() if payload.target_country else None
                ),
                "primary_language": payload.primary_language.strip()[:32] or "en",
                "secondary_languages": _clean_string_list(payload.secondary_languages, max_len=32),
                "tone": payload.tone.strip() if payload.tone else None,
                "target_keywords": _clean_string_list(payload.target_keywords),
                "keyword_bank": _clean_string_list(payload.keyword_bank),
                "restricted_keywords": _clean_string_list(payload.restricted_keywords),
                "default_hashtags": _clean_string_list(payload.default_hashtags),
                "default_cta": payload.default_cta.strip() if payload.default_cta else None,
                "writing_guidelines": (
                    payload.writing_guidelines.strip() if payload.writing_guidelines else None
                ),
                "ai_instructions": (
                    payload.ai_instructions.strip() if payload.ai_instructions else None
                ),
                "domain": domain,
                "website_type": payload.website_type,
                "discovery_method": payload.discovery_method,
                "single_source_only": payload.single_source_only,
                "rss_url": _validate_optional_http_url(payload.rss_url, field_name="rss_url"),
                "sitemap_url": _validate_optional_http_url(
                    payload.sitemap_url, field_name="sitemap_url"
                ),
                "llms_url": _validate_optional_http_url(payload.llms_url, field_name="llms_url"),
                "api_endpoint": _validate_optional_http_url(
                    payload.api_endpoint, field_name="api_endpoint"
                ),
                "gsc_property_url": (
                    payload.gsc_property_url.strip()
                    if payload.gsc_property_url and payload.gsc_property_url.strip()
                    else None
                ),
                "article_url_patterns": include_patterns,
                "excluded_url_patterns": exclude_patterns,
                "scan_interval_minutes": payload.scan_interval_minutes,
                "crawl_batch_size": payload.crawl_batch_size,
                "crawl_max_urls_per_run": payload.crawl_max_urls_per_run,
                "auto_scan": payload.auto_scan,
                "auto_generate": payload.auto_generate,
                "auto_generate_require_published_at": payload.auto_generate_require_published_at,
                "auto_generate_context_mode": (
                    payload.auto_generate_context_mode
                    if payload.auto_generate_context_mode in {"metadata_only", "optimized", "full"}
                    else "optimized"
                ),
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
        self._sync_configured_sources(site)
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.created",
            level="info",
            message=f"Registered website '{site.name}' ({site.domain}).",
            metadata={
                "website_id": site.id,
                "category_id": site.category_id,
                "brand_name": site.brand_name,
                "domain": site.domain,
            },
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

        if raw.get("clear_category"):
            updates["category_id"] = None
        elif "category_id" in raw:
            cat_id = raw["category_id"]
            if cat_id is not None and self.category_repo.get_by_id(int(cat_id)) is None:
                raise NotFoundError(f"Website category #{cat_id} not found.")
            updates["category_id"] = cat_id

        if "domain" in raw and raw["domain"] is not None:
            try:
                target_domain = normalize_domain(raw["domain"])
                validate_outbound_url(
                    f"https://{target_domain}/",
                    trusted_internal_hosts=self.settings.trusted_internal_host_set,
                    resolver=self.fetcher.resolver,
                    resolve_dns=False,
                )
            except (ValueError, ScannerError) as exc:
                raise ValidationAppError(str(exc)) from exc
            conflict = self.website_repo.get_by_domain(target_domain)
            if conflict is not None and conflict.id != website_id:
                raise ConflictError(f"Domain '{target_domain}' is already registered.")
            updates["domain"] = target_domain

        self._validate_enums(
            website_type=raw.get("website_type"),
            discovery_method=raw.get("discovery_method"),
            baseline_mode=raw.get("baseline_mode"),
            status=raw.get("status"),
        )

        if "name" in raw and raw["name"] is not None:
            updates["name"] = raw["name"].strip()
        if "brand_name" in raw:
            bname = (raw["brand_name"] or existing.name).strip()
            updates["brand_name"] = bname
            updates["brand_slug"] = slugify_label(bname)
        if "logo_url" in raw:
            updates["logo_url"] = _validate_logo_value(raw["logo_url"])

        for text_field in (
            "brand_description",
            "target_audience",
            "target_country",
            "primary_language",
            "tone",
            "default_cta",
            "writing_guidelines",
            "ai_instructions",
        ):
            if text_field in raw:
                val = raw[text_field]
                if text_field == "primary_language" and val:
                    updates[text_field] = str(val).strip()[:32]
                else:
                    updates[text_field] = (
                        str(val).strip() if isinstance(val, str) and val.strip() else None
                    )

        for list_field in (
            "secondary_languages",
            "target_keywords",
            "keyword_bank",
            "restricted_keywords",
            "default_hashtags",
        ):
            if list_field in raw and raw[list_field] is not None:
                max_len = 32 if list_field == "secondary_languages" else 120
                updates[list_field] = _clean_string_list(raw[list_field], max_len=max_len)

        if "gsc_property_url" in raw:
            value = str(raw["gsc_property_url"] or "").strip()
            property_url = value or None
            updates["gsc_property_url"] = property_url
            if property_url != existing.gsc_property_url:
                updates["gsc_property_verified_at"] = None

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
            "single_source_only",
            "scan_interval_minutes",
            "crawl_batch_size",
            "crawl_max_urls_per_run",
            "auto_scan",
            "auto_generate",
            "auto_generate_require_published_at",
            "baseline_mode",
            "baseline_limit",
            "status",
        ):
            if simple_field in raw and raw[simple_field] is not None:
                updates[simple_field] = raw[simple_field]

        if "auto_generate_context_mode" in raw and raw["auto_generate_context_mode"] is not None:
            mode = str(raw["auto_generate_context_mode"]).strip().lower()
            if mode not in {"metadata_only", "optimized", "full"}:
                raise ValidationAppError(
                    "auto_generate_context_mode must be 'metadata_only', 'optimized', or 'full'."
                )
            updates["auto_generate_context_mode"] = mode

        if "baseline_after_date" in raw:
            val = raw["baseline_after_date"]
            updates["baseline_after_date"] = val.replace(tzinfo=None) if val else None

        updated = self.website_repo.update(website_id, updates)
        assert updated is not None
        self._sync_configured_sources(updated)

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

    def upload_logo(
        self,
        website_id: int,
        *,
        filename: str,
        file_bytes: bytes,
        content_type: str | None,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")

        try:
            mime_type, width, height, checksum = validate_image_bytes(
                file_bytes,
                max_file_bytes=self.settings.media_max_file_bytes,
                max_dimension_px=self.settings.media_max_dimension_px,
                declared_mime=content_type,
            )
        except MediaValidationError as exc:
            raise ValidationAppError(str(exc)) from exc

        ext_map = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        ext = ext_map[mime_type]
        safe_name = f"logo_{website_id}_{checksum[:16]}.{ext}"
        images_dir = self.settings.resolved_storage_root / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        dest_file = (images_dir / safe_name).resolve()
        if not str(dest_file).startswith(str(images_dir.resolve())):
            raise ValidationAppError("Invalid resolved logo file path.")
        dest_file.write_bytes(file_bytes)

        asset = self.media_repo.create(
            website_id=site.id,
            file_name=safe_name,
            file_path=f"images/{safe_name}",
            source_url=None,
            mime_type=mime_type,
            file_size=len(file_bytes),
            width=width,
            height=height,
            alt_text=f"{site.brand_name} logo",
            checksum=checksum,
        )
        updated = self.website_repo.update(site.id, {"logo_url": f"/api/v1/media/{asset.id}/file"})
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.logo_uploaded",
            level="info",
            message=f"Uploaded brand logo for '{site.name}'.",
            metadata={"website_id": site.id, "media_id": asset.id, "filename": filename[:120]},
            ip_address=ip_address,
        )
        return self._to_response(updated)

    def upload_google_index_service_account(
        self,
        website_id: int,
        *,
        filename: str,
        file_bytes: bytes,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        if not filename.lower().endswith(".json"):
            raise ValidationAppError("Upload a Google service-account .json file.")
        if not file_bytes or len(file_bytes) > MAX_GSC_SERVICE_ACCOUNT_BYTES:
            raise ValidationAppError("Service-account JSON must be between 1 byte and 64 KB.")
        try:
            raw_json = file_bytes.decode("utf-8")
            account = json.loads(raw_json)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationAppError("The uploaded file is not valid UTF-8 JSON.") from exc
        if not isinstance(account, dict) or account.get("type") != "service_account":
            raise ValidationAppError("Upload a Google Cloud service-account JSON key.")

        private_key_data = account.get("private_key")
        client_email = account.get("client_email")
        token_uri = account.get("token_uri", GOOGLE_OAUTH_TOKEN_URI)
        if (
            not isinstance(private_key_data, str)
            or not private_key_data.strip()
            or not isinstance(client_email, str)
            or not client_email.strip()
            or token_uri != GOOGLE_OAUTH_TOKEN_URI
        ):
            raise ValidationAppError("The service-account JSON is missing required Google fields.")
        try:
            private_key = serialization.load_pem_private_key(
                private_key_data.encode("utf-8"),
                password=None,
            )
        except (TypeError, ValueError) as exc:
            raise ValidationAppError("The service-account private key is invalid.") from exc
        if not isinstance(private_key, RSAPrivateKey):
            raise ValidationAppError("The service-account key must be an RSA private key.")

        ciphertext = encrypt_secret(raw_json, self.settings.app_encryption_key)
        updated = self.website_repo.update(
            website_id,
            {
                "encrypted_gsc_service_account_json": ciphertext,
                "gsc_property_verified_at": None,
            },
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.google_index_credentials_uploaded",
            level="info",
            message=f"Updated Google indexing credentials for '{updated.name}'.",
            metadata={"website_id": updated.id},
            ip_address=ip_address,
        )
        return self._to_response(updated)

    def clear_google_index_service_account(
        self,
        website_id: int,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        updated = self.website_repo.update(
            website_id,
            {
                "encrypted_gsc_service_account_json": None,
                "gsc_property_verified_at": None,
            },
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.google_index_credentials_cleared",
            level="info",
            message=f"Removed Google indexing credentials for '{updated.name}'.",
            metadata={"website_id": updated.id},
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

        content_count = self.content_repo.count_by_website(website_id)
        if content_count > 0:
            raise ConflictError(
                f"Cannot delete website '{site.name}' because {content_count} "
                "discovered content item(s) are stored in the Content Library. "
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
            if result.detected_website_type and result.detected_website_type != site.website_type:
                updates["website_type"] = result.detected_website_type
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

            for rss_url in result.rss_urls:
                self.source_config_repo.upsert_source(
                    website_id=site.id,
                    source_type="rss",
                    endpoint_url=rss_url,
                    is_enabled=True,
                )
            for sitemap_url in result.sitemap_urls:
                self.source_config_repo.upsert_source(
                    website_id=site.id,
                    source_type="sitemap",
                    endpoint_url=sitemap_url,
                    is_enabled=True,
                )
            for llms_url in result.llms_urls:
                self.source_config_repo.upsert_source(
                    website_id=site.id,
                    source_type="llms_txt",
                    endpoint_url=llms_url,
                    is_enabled=True,
                )
            if result.wordpress_api_url:
                self.source_config_repo.upsert_source(
                    website_id=site.id,
                    source_type="wordpress",
                    endpoint_url=result.wordpress_api_url,
                    is_enabled=True,
                )
            self.activity_repo.create(
                user_id=user_id,
                actor_type="admin",
                category="websites",
                action="website.sources_discovered",
                level="info",
                message=f"Auto-discovered sources for '{site.name}' ({site.domain}).",
                metadata={
                    "website_id": site.id,
                    "applied": sorted(updates.keys()),
                    "sitemaps_found": len(result.sitemap_urls),
                    "rss_found": len(result.rss_urls),
                },
                ip_address=ip_address,
            )

        return WebsiteDiscoverResponse(
            reachable=result.reachable,
            homepage_url=result.homepage_url,
            detected_website_type=result.detected_website_type,
            rss_urls=result.rss_urls,
            sitemap_urls=result.sitemap_urls,
            llms_urls=result.llms_urls,
            wordpress_api_url=result.wordpress_api_url,
            recommended_method=result.recommended_method,
            notes=result.notes,
        )

    def list_sources(self, website_id: int) -> list[WebsiteDiscoverySourceResponse]:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        rows = self.source_config_repo.list_sources(website_id)
        return [self._to_source_response(row) for row in rows]

    def update_source(
        self,
        website_id: int,
        source_id: int,
        payload: WebsiteDiscoverySourceUpdateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteDiscoverySourceResponse:
        source = self.source_config_repo.get_source(source_id)
        if source is None or source.website_id != website_id:
            raise NotFoundError(
                f"Discovery source #{source_id} not found for website #{website_id}."
            )
        updated = self.source_config_repo.update_source(
            source_id, {"is_enabled": payload.is_enabled}
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.source_toggled",
            level="info",
            message=(
                f"{'Enabled' if payload.is_enabled else 'Disabled'} {updated.source_type} "
                f"source ({updated.endpoint_url})."
            ),
            metadata={"website_id": website_id, "source_id": source_id},
            ip_address=ip_address,
        )
        return self._to_source_response(updated)

    def list_rules(self, website_id: int) -> list[WebsiteUrlRuleResponse]:
        if self.website_repo.get_by_id(website_id) is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        return [self._to_rule_response(r) for r in self.source_config_repo.list_rules(website_id)]

    def create_rule(
        self,
        website_id: int,
        payload: WebsiteUrlRuleCreateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteUrlRuleResponse:
        if self.website_repo.get_by_id(website_id) is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        self._validate_rule_fields(
            pattern=payload.pattern,
            target_content_type=payload.target_content_type,
            match_mode=payload.match_mode,
        )
        created = self.source_config_repo.create_rule(
            {
                "website_id": website_id,
                "pattern": payload.pattern.strip(),
                "target_content_type": payload.target_content_type.strip(),
                "match_mode": payload.match_mode.strip(),
                "priority": payload.priority,
                "is_enabled": payload.is_enabled,
                "notes": payload.notes.strip() if payload.notes else None,
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.rule_created",
            level="info",
            message=(
                f"Added URL classification rule '{created.pattern}' -> "
                f"'{created.target_content_type}'."
            ),
            metadata={"website_id": website_id, "rule_id": created.id},
            ip_address=ip_address,
        )
        return self._to_rule_response(created)

    def update_rule(
        self,
        website_id: int,
        rule_id: int,
        payload: WebsiteUrlRuleUpdateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> WebsiteUrlRuleResponse:
        existing = self.source_config_repo.get_rule(rule_id)
        if existing is None or existing.website_id != website_id:
            raise NotFoundError(f"URL rule #{rule_id} not found for website #{website_id}.")

        raw = payload.model_dump(exclude_unset=True)
        self._validate_rule_fields(
            pattern=raw.get("pattern", existing.pattern),
            target_content_type=raw.get("target_content_type", existing.target_content_type),
            match_mode=raw.get("match_mode", existing.match_mode),
        )
        updates: dict[str, object] = {}
        for key in (
            "pattern",
            "target_content_type",
            "match_mode",
            "priority",
            "is_enabled",
            "notes",
        ):
            if key in raw:
                val = raw[key]
                updates[key] = val.strip() if isinstance(val, str) else val
        updated = self.source_config_repo.update_rule(rule_id, updates)
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.rule_updated",
            level="info",
            message=f"Updated URL classification rule #{rule_id}.",
            metadata={"website_id": website_id, "rule_id": rule_id},
            ip_address=ip_address,
        )
        return self._to_rule_response(updated)

    def delete_rule(
        self,
        website_id: int,
        rule_id: int,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> None:
        existing = self.source_config_repo.get_rule(rule_id)
        if existing is None or existing.website_id != website_id:
            raise NotFoundError(f"URL rule #{rule_id} not found for website #{website_id}.")
        self.source_config_repo.delete_rule(rule_id)
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="websites",
            action="website.rule_deleted",
            level="warning",
            message=f"Deleted URL classification rule '{existing.pattern}'.",
            metadata={"website_id": website_id, "rule_id": rule_id},
            ip_address=ip_address,
        )

    @staticmethod
    def _validate_rule_fields(
        *,
        pattern: str | None,
        target_content_type: str | None,
        match_mode: str | None,
    ) -> None:
        if target_content_type not in RULE_TARGET_TYPES:
            raise ValidationAppError(
                f"Invalid target_content_type '{target_content_type}'. "
                f"Allowed: {', '.join(RULE_TARGET_TYPES)}."
            )
        if match_mode not in ALLOWED_RULE_MATCH_MODES:
            raise ValidationAppError(
                f"Invalid match_mode '{match_mode}'. "
                f"Allowed: {', '.join(ALLOWED_RULE_MATCH_MODES)}."
            )
        if not pattern or not pattern.strip():
            raise ValidationAppError("URL rule pattern must not be empty.")
        if match_mode == "regex":
            try:
                re.compile(pattern.strip())
            except re.error as exc:
                raise ValidationAppError(f"Invalid regular expression pattern: {exc}") from exc

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
