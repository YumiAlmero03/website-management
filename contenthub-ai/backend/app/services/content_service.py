from __future__ import annotations

import contextlib
import math
from datetime import datetime
from typing import TYPE_CHECKING

from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now
from app.models.content_keyword import ContentKeyword
from app.models.website_content import WebsiteContent
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.category_repo import WebsiteCategoryRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.keyword_approval_repo import KeywordApprovalRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.repositories.website_source_repo import WebsiteSourceConfigRepositoryProtocol

if TYPE_CHECKING:
    from app.services.content_approval_service import ContentApprovalService
from app.schemas.common import PaginationMeta
from app.schemas.content import (
    ContentDetailResponse,
    ContentListItemResponse,
    ContentListResponse,
    ContentRevisionResponse,
    ContentStatsResponse,
    ContentUpdateRequest,
)
from app.schemas.keyword_approval import APPROVAL_ELIGIBLE_CONTENT_TYPES
from app.services.content.duplicate import find_near_duplicate
from app.services.content.extractor import ContentExtractionEngine
from app.services.content.media import MediaAssetProcessor, MediaValidationError
from app.services.content.revisions import create_revision_snapshot, has_content_changed
from app.services.media_service import MediaService
from app.services.scanner.classifier import CONTENT_TYPES
from app.services.scanner.exceptions import ScannerError
from app.services.scanner.robots import RobotsPolicyChecker
from app.services.scanner.security import SafeHttpFetcher

ALLOWED_CONTENT_STATUSES: tuple[str, ...] = (
    "discovered",
    "extracted",
    "optimized",
    "updated",
    "failed",
    "excluded",
    "archived",
)

TAB_TO_FILTERS: dict[str, dict[str, object]] = {
    "all": {"include_excluded": False},
    "homepage": {"content_type": "homepage", "include_excluded": False},
    "pages": {"content_type": "page", "include_excluded": False},
    "game_pages": {"content_type": "game_page", "include_excluded": False},
    "blog_posts": {"content_type": "blog_post", "include_excluded": False},
    "blog_indexes": {"content_type": "blog_index", "include_excluded": False},
    "other": {"content_types": ["category", "tag", "archive", "custom"], "include_excluded": False},
    "failed": {"extraction_status": "failed", "include_excluded": False},
    "excluded": {"status": "excluded", "include_excluded": True},
}


class ContentService:
    """Universal Content Library service managing all discovered pages, posts, and failures."""

    def __init__(
        self,
        *,
        settings: Settings,
        content_repo: ContentRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        category_repo: WebsiteCategoryRepositoryProtocol,
        source_config_repo: WebsiteSourceConfigRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        fetcher: SafeHttpFetcher,
        keyword_approval_repo: KeywordApprovalRepositoryProtocol | None = None,
        approval_service: ContentApprovalService | None = None,
    ) -> None:
        self.settings = settings
        self.content_repo = content_repo
        self.website_repo = website_repo
        self.category_repo = category_repo
        self.source_config_repo = source_config_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo
        self.fetcher = fetcher
        self.keyword_approval_repo = keyword_approval_repo
        self.approval_service = approval_service
        self.extractor = ContentExtractionEngine(settings=settings)
        self.media_processor = MediaAssetProcessor(
            settings=settings,
            fetcher=fetcher,
            media_repo=media_repo,
        )

    def _stats_response(
        self, *, website_id: int | None = None, category_id: int | None = None
    ) -> ContentStatsResponse:
        raw = self.content_repo.get_stats(website_id=website_id, category_id=category_id)
        return ContentStatsResponse(**raw)

    def _resolve_website_meta(self, website_id: int) -> tuple[str | None, str | None, str | None]:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            return None, None, None
        cat = self.category_repo.get_by_id(site.category_id) if site.category_id else None
        return site.name, site.domain, (cat.name if cat else None)

    def _to_list_item(
        self,
        row: WebsiteContent,
        *,
        sibling_cache: dict[int, list[tuple[ContentKeyword, WebsiteContent]]] | None = None,
        website_meta: tuple[str | None, str | None, str | None] | None = None,
    ) -> ContentListItemResponse:
        now = utc_now()
        if website_meta is None:
            website_meta = self._resolve_website_meta(row.website_id)
        site_name, site_domain, cat_name = website_meta
        media = self.media_repo.get_by_id(row.featured_media_id) if row.featured_media_id else None
        featured_url = None
        if media is not None:
            featured_url = f"/api/v1/media/{media.id}/file" if media.file_path else media.source_url

        approval = (
            self.keyword_approval_repo.get_approval_by_content_id(row.id)
            if self.keyword_approval_repo is not None
            else None
        )
        kw = (
            self.keyword_approval_repo.get_keyword_by_content_id(row.id)
            if self.keyword_approval_repo is not None
            else None
        )
        cannibal_count = 0
        if (
            self.approval_service is not None
            and kw is not None
            and kw.focus_keyphrase
            and not row.is_excluded
        ):
            from app.services.content.keyword_suggester import detect_cannibalization_warnings

            if sibling_cache is None:
                sibling_cache = {}
            if row.website_id not in sibling_cache:
                sibling_cache[row.website_id] = (
                    self.approval_service.reuse_service._load_website_keyword_pairs(row.website_id)
                )
            siblings = sibling_cache[row.website_id]
            cannibal_count = len(
                detect_cannibalization_warnings(
                    content_id=row.id,
                    focus_keyphrase=kw.focus_keyphrase,
                    sibling_records=siblings,
                )
            )
        return ContentListItemResponse(
            id=row.id,
            website_id=row.website_id,
            website_name=site_name,
            website_domain=site_domain,
            website_category_name=cat_name,
            featured_media_id=row.featured_media_id,
            featured_image_url=featured_url,
            content_type=row.content_type,
            classification_method=row.classification_method,
            manual_classification_override=row.manual_classification_override,
            is_excluded=row.is_excluded,
            url=row.url,
            canonical_url=row.canonical_url,
            title=row.title,
            author=row.author,
            meta_description=row.meta_description,
            h1_text=row.h1_text,
            language=row.language,
            categories=list(row.categories or []),
            tags=list(row.tags or []),
            keywords=list(row.keywords or []),
            discovery_sources=list(row.discovery_sources or []),
            word_count=row.word_count,
            http_status=row.http_status,
            extraction_status=row.extraction_status,
            extraction_error=row.extraction_error,
            status=row.status,
            is_historical_baseline=row.is_historical_baseline,
            near_duplicate_of_id=row.near_duplicate_of_id,
            near_duplicate_score=row.near_duplicate_score,
            published_at=ensure_utc(row.published_at),
            source_updated_at=ensure_utc(row.source_updated_at),
            first_discovered_at=ensure_utc(row.first_discovered_at) or now,
            last_discovered_at=ensure_utc(row.last_discovered_at) or now,
            last_checked_at=ensure_utc(row.last_checked_at) or now,
            approval_status=approval.status if approval else None,
            keyword_approval_status=kw.approval_status if kw else None,
            focus_keyphrase=kw.focus_keyphrase if kw else None,
            secondary_keywords=list(kw.secondary_keywords_json or []) if kw else [],
            cannibalization_count=cannibal_count,
            google_index_status=row.google_index_status or "uninspected",
            google_index_verified_at=ensure_utc(row.google_index_verified_at),
            google_index_last_attempt_at=ensure_utc(row.google_index_last_attempt_at),
            google_index_coverage_state=row.google_index_coverage_state,
            google_index_verdict=row.google_index_verdict,
        )

    def _to_detail(self, row: WebsiteContent) -> ContentDetailResponse:
        now = utc_now()
        base = self._to_list_item(row)
        media = self.media_repo.get_by_id(row.featured_media_id) if row.featured_media_id else None
        revisions = self.content_repo.list_revisions(row.id)
        kw_mapping = None
        app_item = None
        if (
            self.approval_service is not None
            and not row.is_excluded
            and row.content_type in APPROVAL_ELIGIBLE_CONTENT_TYPES
        ):
            with contextlib.suppress(Exception):
                detail = self.approval_service.get_approval_detail(row.id)
                kw_mapping = detail.keyword_mapping
                app_item = detail
        return ContentDetailResponse(
            **base.model_dump(),
            url_hash=row.url_hash,
            content_hash=row.content_hash,
            original_content=row.original_content,
            extracted_content=row.extracted_content,
            markdown_content=row.markdown_content,
            optimized_context=row.optimized_context,
            structured_data_json=row.structured_data_json,
            featured_media=MediaService.to_response(media) if media is not None else None,
            revision_count=len(revisions),
            keyword_mapping=kw_mapping,
            content_approval=app_item,
            created_at=ensure_utc(row.created_at) or now,
            updated_at=ensure_utc(row.updated_at) or now,
        )

    def get_stats(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> ContentStatsResponse:
        return self._stats_response(website_id=website_id, category_id=category_id)

    def list_contents(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
        category_id: int | None = None,
        tab: str | None = None,
        content_type: str | None = None,
        extraction_status: str | None = None,
        language: str | None = None,
        tag_or_category: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        change_filter: str | None = None,
        google_index_status: str | None = None,
        include_excluded: bool = False,
        sort_by: str = "last_discovered_at",
        sort_dir: str = "desc",
    ) -> ContentListResponse:
        content_types: list[str] | None = None
        if tab and tab in TAB_TO_FILTERS:
            preset = TAB_TO_FILTERS[tab]
            content_type = str(preset["content_type"]) if "content_type" in preset else content_type
            content_types = (
                list(preset["content_types"])  # type: ignore[arg-type]
                if "content_types" in preset
                else None
            )
            extraction_status = (
                str(preset["extraction_status"])
                if "extraction_status" in preset
                else extraction_status
            )
            status = str(preset["status"]) if "status" in preset else status
            include_excluded = bool(preset.get("include_excluded", include_excluded))

        rows, total = self.content_repo.list_paginated(
            page=page,
            page_size=page_size,
            website_id=website_id,
            category_id=category_id,
            content_type=content_type,
            content_types=content_types,
            extraction_status=extraction_status,
            language=language,
            tag_or_category=tag_or_category,
            status=status,
            date_from=date_from,
            date_to=date_to,
            search=search,
            change_filter=change_filter,
            google_index_status=google_index_status,
            include_excluded=include_excluded,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        sibling_cache: dict[int, list[tuple[ContentKeyword, WebsiteContent]]] = {}
        website_meta = {
            site_id: self._resolve_website_meta(site_id)
            for site_id in dict.fromkeys(row.website_id for row in rows)
        }
        return ContentListResponse(
            items=[
                self._to_list_item(
                    row, sibling_cache=sibling_cache, website_meta=website_meta[row.website_id]
                )
                for row in rows
            ],
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
            ),
            stats=self._stats_response(website_id=website_id, category_id=category_id),
        )

    def get_content(self, content_id: int) -> ContentDetailResponse:
        row = self.content_repo.get_by_id(content_id)
        if row is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        return self._to_detail(row)

    def update_content(
        self,
        content_id: int,
        payload: ContentUpdateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> ContentDetailResponse:
        existing = self.content_repo.get_by_id(content_id)
        if existing is None:
            raise NotFoundError(f"Content #{content_id} not found.")

        raw = payload.model_dump(exclude_unset=True)
        updates: dict[str, object] = {}

        if "content_type" in raw and raw["content_type"] is not None:
            ctype = str(raw["content_type"]).strip()
            if ctype not in CONTENT_TYPES:
                raise ValidationAppError(
                    f"Invalid content_type '{ctype}'. Allowed: {', '.join(CONTENT_TYPES)}."
                )
            updates["content_type"] = ctype
            updates["manual_classification_override"] = bool(
                raw.get("manual_classification_override", True)
            )
            updates["classification_method"] = (
                "manual" if updates["manual_classification_override"] else "heuristic"
            )
        elif (
            "manual_classification_override" in raw
            and raw["manual_classification_override"] is not None
        ):
            updates["manual_classification_override"] = bool(raw["manual_classification_override"])

        if "is_excluded" in raw and raw["is_excluded"] is not None:
            excluded = bool(raw["is_excluded"])
            updates["is_excluded"] = excluded
            if excluded:
                updates["status"] = "excluded"
            elif existing.status == "excluded":
                updates["status"] = (
                    "extracted" if existing.extraction_status == "extracted" else "discovered"
                )

        if "status" in raw and raw["status"] is not None:
            new_status = str(raw["status"]).strip()
            if new_status not in ALLOWED_CONTENT_STATUSES:
                raise ValidationAppError(
                    f"Invalid status '{new_status}'. "
                    f"Allowed: {', '.join(ALLOWED_CONTENT_STATUSES)}."
                )
            updates["status"] = new_status
            if new_status == "excluded":
                updates["is_excluded"] = True

        if "categories" in raw and raw["categories"] is not None:
            updates["categories"] = [
                str(c).strip()[:100] for c in raw["categories"] if str(c).strip()
            ]
        if "tags" in raw and raw["tags"] is not None:
            updates["tags"] = [str(t).strip()[:100] for t in raw["tags"] if str(t).strip()]
        if "language" in raw and raw["language"] is not None:
            updates["language"] = str(raw["language"]).strip()[:32]

        updated = self.content_repo.update(content_id, updates)
        assert updated is not None
        if self.approval_service is not None and not updated.is_excluded:
            site = self.website_repo.get_by_id(updated.website_id)
            if site is not None:
                with contextlib.suppress(Exception):
                    if updated.extraction_status == "extracted":
                        self.approval_service.sync_extracted_content(
                            content=updated, website=site, changed=False
                        )
                    else:
                        self.approval_service.sync_discovered_content(
                            content=updated, website=site
                        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="content",
            action="content.updated",
            level="info",
            message=f"Updated content #{updated.id} ({updated.content_type}): {updated.title[:80]}",
            metadata={"content_id": updated.id, "updated_fields": sorted(updates.keys())},
            ip_address=ip_address,
        )
        return self._to_detail(updated)

    def list_revisions(self, content_id: int) -> list[ContentRevisionResponse]:
        if self.content_repo.get_by_id(content_id) is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        rows = self.content_repo.list_revisions(content_id)
        now = utc_now()
        return [
            ContentRevisionResponse(
                id=row.id,
                content_id=row.content_id,
                revision_number=row.revision_number,
                content_type=row.content_type,
                title=row.title,
                meta_description=row.meta_description,
                markdown_content=row.markdown_content,
                content_hash=row.content_hash,
                created_at=ensure_utc(row.created_at) or now,
            )
            for row in rows
        ]

    def reprocess_content(
        self,
        content_id: int,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> ContentDetailResponse:
        existing = self.content_repo.get_by_id(content_id)
        if existing is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        site = self.website_repo.get_by_id(existing.website_id)
        if site is None:
            raise NotFoundError(f"Website #{existing.website_id} not found.")

        robots = RobotsPolicyChecker(
            fetcher=self.fetcher,
            user_agent=self.settings.scanner_user_agent,
            respect_robots=self.settings.scanner_respect_robots_txt,
        )
        if not robots.is_allowed(existing.url):
            raise ValidationAppError(f"Blocked by robots.txt policy for {existing.url}.")

        now_naive = utc_now().replace(tzinfo=None)
        try:
            response = self.fetcher.fetch(existing.url)
        except ScannerError as exc:
            updated = self.content_repo.update(
                existing.id,
                {
                    "extraction_status": "failed",
                    "extraction_error": str(exc)[:500],
                    "status": "failed",
                    "last_checked_at": now_naive,
                },
            )
            assert updated is not None
            return self._to_detail(updated)

        if response.status_code != 200:
            updated = self.content_repo.update(
                existing.id,
                {
                    "http_status": response.status_code,
                    "extraction_status": "failed",
                    "extraction_error": f"HTTP {response.status_code} during re-extraction.",
                    "status": "failed",
                    "last_checked_at": now_naive,
                },
            )
            assert updated is not None
            return self._to_detail(updated)

        rules = self.source_config_repo.list_rules(site.id, enabled_only=True)
        extracted = self.extractor.extract_from_html(
            response.text,
            page_url=existing.url,
            domain=site.domain,
            url_rules=rules,
            manual_override_type=(
                existing.content_type if existing.manual_classification_override else None
            ),
            default_language=site.primary_language,
        )

        featured_media_id = existing.featured_media_id
        if extracted.featured_image_url:
            try:
                asset = self.media_processor.process_featured_image(
                    source_url=extracted.featured_image_url,
                    website_id=site.id,
                    alt_text=extracted.featured_image_alt or extracted.title,
                )
                if asset is not None:
                    featured_media_id = asset.id
            except (MediaValidationError, ScannerError):
                pass

        changed = bool(existing.content_hash) and has_content_changed(
            existing, extracted.content_hash
        )
        if changed and (existing.markdown_content or existing.original_content):
            create_revision_snapshot(self.content_repo, existing)

        recent = self.content_repo.list_recent_for_website(site.id, limit=50)
        dup_match = find_near_duplicate(
            title=extracted.title,
            markdown_content=extracted.markdown_content,
            existing_contents=recent,
            exclude_content_id=existing.id,
        )

        updated = self.content_repo.update(
            existing.id,
            {
                "featured_media_id": featured_media_id,
                "content_type": extracted.content_type,
                "classification_method": extracted.classification_method,
                "title": extracted.title,
                "canonical_url": extracted.canonical_url,
                "h1_text": extracted.h1_text,
                "author": extracted.author,
                "meta_description": extracted.meta_description,
                "original_content": extracted.original_content,
                "extracted_content": extracted.extracted_content,
                "markdown_content": extracted.markdown_content,
                "optimized_context": extracted.optimized_context,
                "structured_data_json": extracted.structured_data_json,
                "keywords": extracted.keywords,
                "categories": extracted.categories,
                "tags": extracted.tags,
                "language": extracted.language,
                "content_hash": extracted.content_hash,
                "word_count": extracted.word_count,
                "http_status": response.status_code,
                "extraction_status": "extracted",
                "extraction_error": None,
                "status": "updated" if changed else "extracted",
                "near_duplicate_of_id": dup_match[0] if dup_match else None,
                "near_duplicate_score": dup_match[1] if dup_match else None,
                "published_at": (
                    extracted.published_at.replace(tzinfo=None)
                    if extracted.published_at
                    else existing.published_at
                ),
                "source_updated_at": (
                    extracted.source_updated_at.replace(tzinfo=None)
                    if extracted.source_updated_at
                    else existing.source_updated_at
                ),
                "last_checked_at": now_naive,
            },
        )
        assert updated is not None
        if self.approval_service is not None:
            with contextlib.suppress(Exception):
                self.approval_service.sync_extracted_content(
                    content=updated,
                    website=site,
                    extracted_headings=extracted.headings,
                    extracted_images=extracted.images,
                    featured_image_url=extracted.featured_image_url,
                    featured_image_alt=extracted.featured_image_alt,
                    changed=changed,
                )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="content",
            action="content.reprocessed",
            level="info",
            message=f"Reprocessed content #{updated.id} ({updated.title[:80]}).",
            metadata={"content_id": updated.id, "changed": changed, "words": updated.word_count},
            ip_address=ip_address,
        )
        return self._to_detail(updated)
