from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.website_category import WebsiteCategory


class WebsiteCategoryRepositoryProtocol(Protocol):
    def list_all(self, *, include_archived: bool = False) -> list[WebsiteCategory]: ...

    def get_by_id(self, category_id: int) -> WebsiteCategory | None: ...

    def get_by_slug(self, slug: str) -> WebsiteCategory | None: ...

    def get_by_name(self, name: str) -> WebsiteCategory | None: ...

    def count_all(self, *, include_archived: bool = False) -> int: ...

    def create(self, data: dict[str, Any]) -> WebsiteCategory: ...

    def update(self, category_id: int, data: dict[str, Any]) -> WebsiteCategory | None: ...

    def delete(self, category_id: int) -> bool: ...


class SQLAlchemyWebsiteCategoryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self, *, include_archived: bool = False) -> list[WebsiteCategory]:
        stmt = select(WebsiteCategory).order_by(
            WebsiteCategory.is_archived.asc(),
            WebsiteCategory.sort_order.asc(),
            WebsiteCategory.name.asc(),
        )
        if not include_archived:
            stmt = stmt.where(WebsiteCategory.is_archived.is_(False))
        return list(self.db.execute(stmt).scalars().all())

    def get_by_id(self, category_id: int) -> WebsiteCategory | None:
        return self.db.get(WebsiteCategory, category_id)

    def get_by_slug(self, slug: str) -> WebsiteCategory | None:
        stmt = select(WebsiteCategory).where(WebsiteCategory.slug == slug.strip().lower())
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_name(self, name: str) -> WebsiteCategory | None:
        stmt = select(WebsiteCategory).where(
            func.lower(WebsiteCategory.name) == name.strip().lower()
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def count_all(self, *, include_archived: bool = False) -> int:
        stmt = select(func.count()).select_from(WebsiteCategory)
        if not include_archived:
            stmt = stmt.where(WebsiteCategory.is_archived.is_(False))
        return int(self.db.execute(stmt).scalar_one())

    def create(self, data: dict[str, Any]) -> WebsiteCategory:
        now = utc_now_naive()
        category = WebsiteCategory(**data, created_at=now, updated_at=now)
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def update(self, category_id: int, data: dict[str, Any]) -> WebsiteCategory | None:
        category = self.db.get(WebsiteCategory, category_id)
        if category is None:
            return None
        for key, value in data.items():
            setattr(category, key, value)
        category.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(category)
        return category

    def delete(self, category_id: int) -> bool:
        category = self.db.get(WebsiteCategory, category_id)
        if category is None:
            return False
        self.db.delete(category)
        self.db.commit()
        return True
