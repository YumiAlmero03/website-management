from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.source_article import SourceArticle
from app.models.source_article_revision import SourceArticleRevision
from app.models.website import Website


class ArticleRepositoryProtocol(Protocol):
    def list_paginated(
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
    ) -> tuple[list[SourceArticle], int]: ...

    def get_by_id(self, article_id: int) -> SourceArticle | None: ...

    def get_by_website_and_url_hash(
        self,
        website_id: int,
        url_hash: str,
    ) -> SourceArticle | None: ...

    def list_recent_for_website(
        self, website_id: int, *, limit: int = 50
    ) -> list[SourceArticle]: ...

    def count_by_website(self, website_id: int) -> int: ...

    def count_all(
        self,
        *,
        brand_id: int | None = None,
        website_id: int | None = None,
        status: str | None = None,
        discovered_since: datetime | None = None,
    ) -> int: ...

    def create(self, data: dict[str, Any]) -> SourceArticle: ...

    def update(self, article_id: int, data: dict[str, Any]) -> SourceArticle | None: ...

    def list_revisions(self, article_id: int) -> list[SourceArticleRevision]: ...

    def get_next_revision_number(self, article_id: int) -> int: ...

    def create_revision(
        self,
        *,
        article_id: int,
        revision_number: int,
        title: str,
        meta_description: str | None,
        markdown_content: str | None,
        content_hash: str,
    ) -> SourceArticleRevision: ...


class SQLAlchemyArticleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_paginated(
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
    ) -> tuple[list[SourceArticle], int]:
        stmt = select(SourceArticle)
        count_stmt = select(func.count()).select_from(SourceArticle)

        if brand_id is not None:
            stmt = stmt.join(Website, Website.id == SourceArticle.website_id).where(
                Website.brand_id == brand_id
            )
            count_stmt = count_stmt.join(Website, Website.id == SourceArticle.website_id).where(
                Website.brand_id == brand_id
            )

        filters = []
        if website_id is not None:
            filters.append(SourceArticle.website_id == website_id)
        if language:
            filters.append(SourceArticle.language == language.strip())
        if status:
            filters.append(SourceArticle.status == status.strip())
        if change_filter == "updated":
            filters.append(SourceArticle.status == "updated")
        elif change_filter == "new":
            filters.append(SourceArticle.status.in_(["discovered", "extracted", "optimized"]))
        if date_from is not None:
            filters.append(SourceArticle.discovered_at >= date_from.replace(tzinfo=None))
        if date_to is not None:
            filters.append(SourceArticle.discovered_at <= date_to.replace(tzinfo=None))
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    SourceArticle.title.ilike(term),
                    SourceArticle.meta_description.ilike(term),
                    SourceArticle.canonical_url.ilike(term),
                )
            )

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        stmt = stmt.order_by(SourceArticle.discovered_at.desc(), SourceArticle.id.desc())

        if category:
            # JSON array membership filtering portably in Python when category filter is used.
            cat_lower = category.strip().lower()
            all_rows = list(self.db.execute(stmt).scalars().all())
            filtered = [
                row
                for row in all_rows
                if any(str(c).lower() == cat_lower for c in (row.categories or []))
            ]
            total = len(filtered)
            start = (page - 1) * page_size
            return filtered[start : start + page_size], total

        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(
            self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        )
        return rows, total

    def get_by_id(self, article_id: int) -> SourceArticle | None:
        return self.db.get(SourceArticle, article_id)

    def get_by_website_and_url_hash(
        self,
        website_id: int,
        url_hash: str,
    ) -> SourceArticle | None:
        stmt = select(SourceArticle).where(
            SourceArticle.website_id == website_id,
            SourceArticle.url_hash == url_hash,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_recent_for_website(self, website_id: int, *, limit: int = 50) -> list[SourceArticle]:
        stmt = (
            select(SourceArticle)
            .where(SourceArticle.website_id == website_id)
            .order_by(SourceArticle.discovered_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_by_website(self, website_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(SourceArticle)
            .where(SourceArticle.website_id == website_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    def count_all(
        self,
        *,
        brand_id: int | None = None,
        website_id: int | None = None,
        status: str | None = None,
        discovered_since: datetime | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(SourceArticle)
        if brand_id is not None:
            stmt = stmt.join(Website, Website.id == SourceArticle.website_id).where(
                Website.brand_id == brand_id
            )
        if website_id is not None:
            stmt = stmt.where(SourceArticle.website_id == website_id)
        if status is not None:
            stmt = stmt.where(SourceArticle.status == status)
        if discovered_since is not None:
            stmt = stmt.where(SourceArticle.discovered_at >= discovered_since.replace(tzinfo=None))
        return int(self.db.execute(stmt).scalar_one())

    def create(self, data: dict[str, Any]) -> SourceArticle:
        now = utc_now_naive()
        defaults = {
            "discovered_at": now,
            "last_checked_at": now,
            "created_at": now,
            "updated_at": now,
        }
        merged = {**defaults, **data}
        article = SourceArticle(**merged)
        self.db.add(article)
        self.db.commit()
        self.db.refresh(article)
        return article

    def update(self, article_id: int, data: dict[str, Any]) -> SourceArticle | None:
        article = self.db.get(SourceArticle, article_id)
        if article is None:
            return None
        for key, value in data.items():
            setattr(article, key, value)
        article.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(article)
        return article

    def list_revisions(self, article_id: int) -> list[SourceArticleRevision]:
        stmt = (
            select(SourceArticleRevision)
            .where(SourceArticleRevision.article_id == article_id)
            .order_by(SourceArticleRevision.revision_number.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_next_revision_number(self, article_id: int) -> int:
        stmt = select(func.max(SourceArticleRevision.revision_number)).where(
            SourceArticleRevision.article_id == article_id
        )
        current = self.db.execute(stmt).scalar_one_or_none()
        return int(current or 0) + 1

    def create_revision(
        self,
        *,
        article_id: int,
        revision_number: int,
        title: str,
        meta_description: str | None,
        markdown_content: str | None,
        content_hash: str,
    ) -> SourceArticleRevision:
        revision = SourceArticleRevision(
            article_id=article_id,
            revision_number=revision_number,
            title=title,
            meta_description=meta_description,
            markdown_content=markdown_content,
            content_hash=content_hash,
            created_at=utc_now_naive(),
        )
        self.db.add(revision)
        self.db.commit()
        self.db.refresh(revision)
        return revision
