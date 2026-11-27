from __future__ import annotations

import math
from datetime import datetime

from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.source_article import SourceArticle
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.article_repo import ArticleRepositoryProtocol
from app.repositories.brand_repo import BrandRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.article import (
    ArticleDetailResponse,
    ArticleListItemResponse,
    ArticleListResponse,
    ArticleRevisionResponse,
    ArticleUpdateRequest,
)
from app.schemas.common import PaginationMeta
from app.schemas.media import MediaAssetResponse
from app.services.content.extractor import ContentExtractionEngine
from app.services.content.media import MediaAssetProcessor, MediaValidationError
from app.services.content.revisions import create_revision_snapshot, has_content_changed
from app.services.scanner.exceptions import ScannerError
from app.services.scanner.security import SafeHttpFetcher

ALLOWED_ARTICLE_STATUSES: tuple[str, ...] = (
    "discovered",
    "extracted",
    "optimized",
    "unchanged",
    "updated",
    "archived",
    "error",
)


class ArticleService:
    def __init__(
        self,
        *,
        settings: Settings,
        article_repo: ArticleRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        brand_repo: BrandRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        fetcher: SafeHttpFetcher,
    ) -> None:
        self.settings = settings
        self.article_repo = article_repo
        self.website_repo = website_repo
        self.brand_repo = brand_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo
        self.fetcher = fetcher
        self.extractor = ContentExtractionEngine(settings=settings)
        self.media_processor = MediaAssetProcessor(
            settings=settings,
            fetcher=fetcher,
            media_repo=media_repo,
        )

    def _resolve_media_url(
        self, media_id: int | None
    ) -> tuple[str | None, MediaAssetResponse | None]:
        if media_id is None:
            return None, None
        asset = self.media_repo.get_by_id(media_id)
        if asset is None:
            return None, None
        now = utc_now()
        resp = MediaAssetResponse(
            id=asset.id,
            brand_id=asset.brand_id,
            file_name=asset.file_name,
            file_path=asset.file_path,
            source_url=asset.source_url,
            mime_type=asset.mime_type,
            file_size=asset.file_size,
            width=asset.width,
            height=asset.height,
            alt_text=asset.alt_text,
            checksum=asset.checksum,
            created_at=ensure_utc(asset.created_at) or now,
        )
        display_url = f"/api/v1/media/{asset.id}/file" if asset.file_path else asset.source_url
        return display_url, resp

    def _to_list_item(self, article: SourceArticle) -> ArticleListItemResponse:
        now = utc_now()
        site = self.website_repo.get_by_id(article.website_id)
        brand = self.brand_repo.get_by_id(site.brand_id) if site else None
        featured_url, _ = self._resolve_media_url(article.featured_media_id)
        return ArticleListItemResponse(
            id=article.id,
            website_id=article.website_id,
            website_name=site.name if site else None,
            brand_id=brand.id if brand else None,
            brand_name=brand.name if brand else None,
            featured_media_id=article.featured_media_id,
            featured_image_url=featured_url,
            title=article.title,
            canonical_url=article.canonical_url,
            author=article.author,
            meta_description=article.meta_description,
            language=article.language,
            categories=list(article.categories or []),
            tags=list(article.tags or []),
            keywords=list(article.keywords or []),
            word_count=article.word_count,
            status=article.status,
            is_historical_baseline=article.is_historical_baseline,
            near_duplicate_of_id=article.near_duplicate_of_id,
            near_duplicate_score=article.near_duplicate_score,
            published_at=ensure_utc(article.published_at),
            source_updated_at=ensure_utc(article.source_updated_at),
            discovered_at=ensure_utc(article.discovered_at) or now,
            last_checked_at=ensure_utc(article.last_checked_at) or now,
        )

    def _to_detail(self, article: SourceArticle) -> ArticleDetailResponse:
        now = utc_now()
        base = self._to_list_item(article)
        _, media_resp = self._resolve_media_url(article.featured_media_id)
        revisions = self.article_repo.list_revisions(article.id)
        return ArticleDetailResponse(
            **base.model_dump(),
            url_hash=article.url_hash,
            content_hash=article.content_hash,
            original_content=article.original_content,
            markdown_content=article.markdown_content,
            optimized_context=article.optimized_context,
            featured_media=media_resp,
            revision_count=len(revisions),
            created_at=ensure_utc(article.created_at) or now,
            updated_at=ensure_utc(article.updated_at) or now,
        )

    def list_articles(
        self,
        *,
        page: int,
        page_size: int,
        brand_id: int | None = None,
        website_id: int | None = None,
        language: str | None = None,
        category: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        change_filter: str | None = None,
    ) -> ArticleListResponse:
        rows, total = self.article_repo.list_paginated(
            page=page,
            page_size=page_size,
            brand_id=brand_id,
            website_id=website_id,
            language=language,
            category=category,
            status=status,
            date_from=date_from,
            date_to=date_to,
            search=search,
            change_filter=change_filter,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return ArticleListResponse(
            items=[self._to_list_item(row) for row in rows],
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
            ),
        )

    def get_article(self, article_id: int) -> ArticleDetailResponse:
        article = self.article_repo.get_by_id(article_id)
        if article is None:
            raise NotFoundError(f"Article #{article_id} not found.")
        return self._to_detail(article)

    def list_revisions(self, article_id: int) -> list[ArticleRevisionResponse]:
        if self.article_repo.get_by_id(article_id) is None:
            raise NotFoundError(f"Article #{article_id} not found.")
        now = utc_now()
        rows = self.article_repo.list_revisions(article_id)
        return [
            ArticleRevisionResponse(
                id=row.id,
                article_id=row.article_id,
                revision_number=row.revision_number,
                title=row.title,
                meta_description=row.meta_description,
                markdown_content=row.markdown_content,
                content_hash=row.content_hash,
                created_at=ensure_utc(row.created_at) or now,
            )
            for row in rows
        ]

    def update_article(
        self,
        article_id: int,
        payload: ArticleUpdateRequest,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> ArticleDetailResponse:
        article = self.article_repo.get_by_id(article_id)
        if article is None:
            raise NotFoundError(f"Article #{article_id} not found.")

        raw = payload.model_dump(exclude_unset=True)
        updates: dict[str, object] = {}

        if "status" in raw and raw["status"] is not None:
            if raw["status"] not in ALLOWED_ARTICLE_STATUSES:
                raise ValidationAppError(
                    f"Invalid article status '{raw['status']}'. "
                    f"Allowed: {', '.join(ALLOWED_ARTICLE_STATUSES)}."
                )
            updates["status"] = raw["status"]
        if "categories" in raw and raw["categories"] is not None:
            updates["categories"] = [c.strip() for c in raw["categories"] if c.strip()]
        if "tags" in raw and raw["tags"] is not None:
            updates["tags"] = [t.strip() for t in raw["tags"] if t.strip()]
        if "language" in raw and raw["language"] is not None:
            updates["language"] = raw["language"].strip()[:32]

        updated = self.article_repo.update(article_id, updates)
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="articles",
            action="article.updated",
            level="info",
            message=f"Updated article #{article_id} ('{updated.title[:80]}').",
            metadata={"article_id": article_id, "updated_fields": sorted(updates.keys())},
            ip_address=ip_address,
        )
        return self._to_detail(updated)

    def reprocess_article(
        self,
        article_id: int,
        *,
        user_id: int,
        ip_address: str | None,
    ) -> ArticleDetailResponse:
        article = self.article_repo.get_by_id(article_id)
        if article is None:
            raise NotFoundError(f"Article #{article_id} not found.")
        site = self.website_repo.get_by_id(article.website_id)
        if site is None:
            raise NotFoundError(f"Source website #{article.website_id} not found.")

        try:
            response = self.fetcher.fetch(
                article.canonical_url,
                accept="text/html,application/xhtml+xml,text/markdown;q=0.9,*/*;q=0.5",
            )
        except ScannerError as exc:
            raise ValidationAppError(f"Failed to re-fetch article URL: {exc}") from exc

        if response.status_code != 200:
            raise ValidationAppError(
                f"Source URL returned HTTP {response.status_code} during re-extraction."
            )

        extracted = self.extractor.extract_from_html(
            response.text,
            page_url=response.final_url,
            domain=site.domain,
            default_language=article.language or "en",
        )

        now_naive = utc_now_naive()
        changed = has_content_changed(article, extracted.content_hash)
        if changed:
            create_revision_snapshot(self.article_repo, article)

        featured_media_id = article.featured_media_id
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

        updated = self.article_repo.update(
            article.id,
            {
                "featured_media_id": featured_media_id,
                "title": extracted.title,
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
                "status": "updated" if changed else "optimized",
                "published_at": extracted.published_at.replace(tzinfo=None)
                if extracted.published_at
                else article.published_at,
                "source_updated_at": extracted.source_updated_at.replace(tzinfo=None)
                if extracted.source_updated_at
                else article.source_updated_at,
                "last_checked_at": now_naive,
            },
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="articles",
            action="article.reprocessed",
            level="info",
            message=f"Re-extracted article #{article.id} (content_changed={changed}).",
            metadata={"article_id": article.id, "content_changed": changed},
            ip_address=ip_address,
        )
        return self._to_detail(updated)
