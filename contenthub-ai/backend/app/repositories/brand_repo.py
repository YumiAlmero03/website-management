from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.brand import Brand


class BrandRepositoryProtocol(Protocol):
    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        is_active: bool | None = None,
        language: str | None = None,
    ) -> tuple[list[Brand], int]: ...

    def list_all(self) -> list[Brand]: ...

    def get_by_id(self, brand_id: int) -> Brand | None: ...

    def get_by_slug(self, slug: str) -> Brand | None: ...

    def count_all(self, *, is_active: bool | None = None) -> int: ...

    def create(self, data: dict[str, Any]) -> Brand: ...

    def update(self, brand_id: int, data: dict[str, Any]) -> Brand | None: ...

    def delete(self, brand_id: int) -> bool: ...


class SQLAlchemyBrandRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        is_active: bool | None = None,
        language: str | None = None,
    ) -> tuple[list[Brand], int]:
        filters = []
        if is_active is not None:
            filters.append(Brand.is_active == is_active)
        if language:
            filters.append(Brand.primary_language == language.strip())
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    Brand.name.ilike(term),
                    Brand.slug.ilike(term),
                    Brand.description.ilike(term),
                    Brand.target_country.ilike(term),
                )
            )

        count_stmt = select(func.count()).select_from(Brand)
        data_stmt = select(Brand).order_by(Brand.created_at.desc(), Brand.id.desc())
        if filters:
            count_stmt = count_stmt.where(*filters)
            data_stmt = data_stmt.where(*filters)

        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(
            self.db.execute(data_stmt.offset((page - 1) * page_size).limit(page_size))
            .scalars()
            .all()
        )
        return rows, total

    def list_all(self) -> list[Brand]:
        stmt = select(Brand).order_by(Brand.name.asc())
        return list(self.db.execute(stmt).scalars().all())

    def get_by_id(self, brand_id: int) -> Brand | None:
        return self.db.get(Brand, brand_id)

    def get_by_slug(self, slug: str) -> Brand | None:
        stmt = select(Brand).where(Brand.slug == slug.strip().lower())
        return self.db.execute(stmt).scalar_one_or_none()

    def count_all(self, *, is_active: bool | None = None) -> int:
        stmt = select(func.count()).select_from(Brand)
        if is_active is not None:
            stmt = stmt.where(Brand.is_active == is_active)
        return int(self.db.execute(stmt).scalar_one())

    def create(self, data: dict[str, Any]) -> Brand:
        now = utc_now_naive()
        brand = Brand(**data, created_at=now, updated_at=now)
        self.db.add(brand)
        self.db.commit()
        self.db.refresh(brand)
        return brand

    def update(self, brand_id: int, data: dict[str, Any]) -> Brand | None:
        brand = self.db.get(Brand, brand_id)
        if brand is None:
            return None
        for key, value in data.items():
            setattr(brand, key, value)
        brand.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(brand)
        return brand

    def delete(self, brand_id: int) -> bool:
        brand = self.db.get(Brand, brand_id)
        if brand is None:
            return False
        self.db.delete(brand)
        self.db.commit()
        return True
