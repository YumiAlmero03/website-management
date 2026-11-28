from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import ColumnElement, and_, case, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.content_revision import ContentRevision
from app.models.website import Website
from app.models.website_content import WebsiteContent


class ContentRepositoryProtocol(Protocol):
    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
        category_id: int | None = None,
        content_type: str | None = None,
        content_types: list[str] | None = None,
        extraction_status: str | None = None,
        language: str | None = None,
        tag_or_category: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        change_filter: str | None = None,
        include_excluded: bool = False,
        sort_by: str = "last_discovered_at",
        sort_dir: str = "desc",
    ) -> tuple[list[WebsiteContent], int]: ...

    def get_stats(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
        discovered_since: datetime | None = None,
    ) -> dict[str, int]: ...

    def get_by_id(self, content_id: int) -> WebsiteContent | None: ...

    def get_by_website_and_url_hash(
        self,
        website_id: int,
        url_hash: str,
    ) -> WebsiteContent | None: ...

    def list_recent_for_website(
        self, website_id: int, *, limit: int = 50
    ) -> list[WebsiteContent]: ...

    def list_pending_for_website(
        self, website_id: int, *, limit: int = 100
    ) -> list[WebsiteContent]: ...

    def list_failed_for_website(
        self, website_id: int, *, limit: int = 100
    ) -> list[WebsiteContent]: ...

    def list_for_website(
        self, website_id: int, *, limit: int | None = None
    ) -> list[WebsiteContent]: ...

    def count_by_website(self, website_id: int) -> int: ...

    def count_all(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
        content_type: str | None = None,
        extraction_status: str | None = None,
        status: str | None = None,
        discovered_since: datetime | None = None,
    ) -> int: ...

    def create(self, data: dict[str, Any]) -> WebsiteContent: ...

    def update(self, content_id: int, data: dict[str, Any]) -> WebsiteContent | None: ...

    def list_revisions(self, content_id: int) -> list[ContentRevision]: ...

    def get_next_revision_number(self, content_id: int) -> int: ...

    def create_revision(
        self,
        *,
        content_id: int,
        revision_number: int,
        title: str,
        meta_description: str | None,
        markdown_content: str | None,
        content_hash: str,
        content_type: str | None = None,
    ) -> ContentRevision: ...


class SQLAlchemyContentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
        category_id: int | None = None,
        content_type: str | None = None,
        content_types: list[str] | None = None,
        extraction_status: str | None = None,
        language: str | None = None,
        tag_or_category: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        change_filter: str | None = None,
        include_excluded: bool = False,
        sort_by: str = "last_discovered_at",
        sort_dir: str = "desc",
    ) -> tuple[list[WebsiteContent], int]:
        stmt = select(WebsiteContent)
        count_stmt = select(func.count()).select_from(WebsiteContent)

        if category_id is not None:
            stmt = stmt.join(Website, Website.id == WebsiteContent.website_id).where(
                Website.category_id == category_id
            )
            count_stmt = count_stmt.join(Website, Website.id == WebsiteContent.website_id).where(
                Website.category_id == category_id
            )

        filters = []
        if website_id is not None:
            filters.append(WebsiteContent.website_id == website_id)
        if not include_excluded and status != "excluded":
            filters.append(WebsiteContent.is_excluded.is_(False))
        if content_type:
            filters.append(WebsiteContent.content_type == content_type.strip())
        elif content_types:
            filters.append(WebsiteContent.content_type.in_(content_types))
        if extraction_status:
            filters.append(WebsiteContent.extraction_status == extraction_status.strip())
        if language:
            filters.append(WebsiteContent.language == language.strip())
        if status:
            filters.append(WebsiteContent.status == status.strip())
        if change_filter == "updated":
            filters.append(WebsiteContent.status == "updated")
        elif change_filter == "new":
            filters.append(WebsiteContent.status.in_(["discovered", "extracted", "optimized"]))
        if date_from is not None:
            filters.append(WebsiteContent.first_discovered_at >= date_from.replace(tzinfo=None))
        if date_to is not None:
            filters.append(WebsiteContent.first_discovered_at <= date_to.replace(tzinfo=None))
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    WebsiteContent.title.ilike(term),
                    WebsiteContent.meta_description.ilike(term),
                    WebsiteContent.canonical_url.ilike(term),
                    WebsiteContent.url.ilike(term),
                )
            )

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        sort_map = {
            "last_discovered_at": WebsiteContent.last_discovered_at,
            "first_discovered_at": WebsiteContent.first_discovered_at,
            "last_checked_at": WebsiteContent.last_checked_at,
            "published_at": WebsiteContent.published_at,
            "word_count": WebsiteContent.word_count,
            "title": WebsiteContent.title,
        }
        sort_col = sort_map.get(sort_by, WebsiteContent.last_discovered_at)
        order_expr = sort_col.asc() if (sort_dir or "").lower() == "asc" else sort_col.desc()
        stmt = stmt.order_by(order_expr, WebsiteContent.id.desc())

        if tag_or_category:
            cat_lower = tag_or_category.strip().lower()
            all_rows = list(self.db.execute(stmt).scalars().all())
            filtered = [
                row
                for row in all_rows
                if any(
                    str(c).lower() == cat_lower
                    for c in [*(row.categories or []), *(row.tags or [])]
                )
            ]
            total = len(filtered)
            start = (page - 1) * page_size
            return filtered[start : start + page_size], total

        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(
            self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        )
        return rows, total

    def get_stats(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
        discovered_since: datetime | None = None,
    ) -> dict[str, int]:
        content = WebsiteContent
        active = content.is_excluded.is_(False)

        def count_active(*conditions: ColumnElement[bool]) -> ColumnElement[int]:
            return func.count(case((and_(active, *conditions), 1)))

        other_types = ("category", "tag", "archive", "custom")
        content_types = ("homepage", "page", "game_page", "blog_post", "blog_index", *other_types)
        counts = {
            "total_discovered": count_active(),
            "total_extracted": count_active(content.extraction_status == "extracted"),
            **{
                f"{kind}_count": count_active(content.content_type == kind)
                for kind in content_types
            },
            "other_count": count_active(content.content_type.in_(other_types)),
            "pending_count": count_active(content.extraction_status == "pending"),
            "failed_count": count_active(content.extraction_status == "failed"),
            "updated_count": count_active(content.status == "updated"),
            "excluded_count": func.count(case((content.is_excluded.is_(True), 1))),
            "discovered_today_count": (
                count_active(content.first_discovered_at >= discovered_since.replace(tzinfo=None))
                if discovered_since is not None
                else literal(0)
            ),
        }
        stmt = select(*(value.label(key) for key, value in counts.items())).select_from(content)
        if category_id is not None:
            stmt = stmt.join(Website, Website.id == content.website_id).where(
                Website.category_id == category_id
            )
        if website_id is not None:
            stmt = stmt.where(content.website_id == website_id)
        return dict(self.db.execute(stmt).mappings().one())

    def get_by_id(self, content_id: int) -> WebsiteContent | None:
        return self.db.get(WebsiteContent, content_id)

    def get_by_website_and_url_hash(
        self,
        website_id: int,
        url_hash: str,
    ) -> WebsiteContent | None:
        stmt = select(WebsiteContent).where(
            WebsiteContent.website_id == website_id,
            WebsiteContent.url_hash == url_hash,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_recent_for_website(self, website_id: int, *, limit: int = 50) -> list[WebsiteContent]:
        stmt = (
            select(WebsiteContent)
            .where(
                WebsiteContent.website_id == website_id,
                WebsiteContent.extraction_status == "extracted",
                WebsiteContent.is_excluded.is_(False),
            )
            .order_by(WebsiteContent.first_discovered_at.desc(), WebsiteContent.id.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_pending_for_website(
        self, website_id: int, *, limit: int = 100
    ) -> list[WebsiteContent]:
        stmt = (
            select(WebsiteContent)
            .where(
                WebsiteContent.website_id == website_id,
                WebsiteContent.extraction_status == "pending",
                WebsiteContent.is_excluded.is_(False),
            )
            .order_by(WebsiteContent.id.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_failed_for_website(self, website_id: int, *, limit: int = 100) -> list[WebsiteContent]:
        stmt = (
            select(WebsiteContent)
            .where(
                WebsiteContent.website_id == website_id,
                WebsiteContent.extraction_status == "failed",
                WebsiteContent.is_excluded.is_(False),
            )
            .order_by(WebsiteContent.id.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_website(
        self, website_id: int, *, limit: int | None = None
    ) -> list[WebsiteContent]:
        stmt = (
            select(WebsiteContent)
            .where(WebsiteContent.website_id == website_id)
            .order_by(WebsiteContent.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def count_by_website(self, website_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(WebsiteContent)
            .where(WebsiteContent.website_id == website_id, WebsiteContent.is_excluded.is_(False))
        )
        return int(self.db.execute(stmt).scalar_one())

    def count_all(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
        content_type: str | None = None,
        extraction_status: str | None = None,
        status: str | None = None,
        discovered_since: datetime | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(WebsiteContent)
            .where(WebsiteContent.is_excluded.is_(False))
        )
        if category_id is not None:
            stmt = stmt.join(Website, Website.id == WebsiteContent.website_id).where(
                Website.category_id == category_id
            )
        if website_id is not None:
            stmt = stmt.where(WebsiteContent.website_id == website_id)
        if content_type is not None:
            stmt = stmt.where(WebsiteContent.content_type == content_type)
        if extraction_status is not None:
            stmt = stmt.where(WebsiteContent.extraction_status == extraction_status)
        if status is not None:
            stmt = stmt.where(WebsiteContent.status == status)
        if discovered_since is not None:
            stmt = stmt.where(
                WebsiteContent.first_discovered_at >= discovered_since.replace(tzinfo=None)
            )
        return int(self.db.execute(stmt).scalar_one())

    def create(self, data: dict[str, Any]) -> WebsiteContent:
        now = utc_now_naive()
        defaults = {
            "first_discovered_at": now,
            "last_discovered_at": now,
            "last_checked_at": now,
            "created_at": now,
            "updated_at": now,
        }
        merged = {**defaults, **data}
        if not merged.get("url"):
            merged["url"] = merged.get("canonical_url", "")
        content = WebsiteContent(**merged)
        self.db.add(content)
        self.db.commit()
        self.db.refresh(content)
        return content

    def update(self, content_id: int, data: dict[str, Any]) -> WebsiteContent | None:
        content = self.db.get(WebsiteContent, content_id)
        if content is None:
            return None
        for key, value in data.items():
            setattr(content, key, value)
        content.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(content)
        return content

    def list_revisions(self, content_id: int) -> list[ContentRevision]:
        stmt = (
            select(ContentRevision)
            .where(ContentRevision.content_id == content_id)
            .order_by(ContentRevision.revision_number.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_next_revision_number(self, content_id: int) -> int:
        stmt = select(func.max(ContentRevision.revision_number)).where(
            ContentRevision.content_id == content_id
        )
        current = self.db.execute(stmt).scalar_one_or_none()
        return int(current or 0) + 1

    def create_revision(
        self,
        *,
        content_id: int,
        revision_number: int,
        title: str,
        meta_description: str | None,
        markdown_content: str | None,
        content_hash: str,
        content_type: str | None = None,
    ) -> ContentRevision:
        revision = ContentRevision(
            content_id=content_id,
            revision_number=revision_number,
            content_type=content_type,
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
