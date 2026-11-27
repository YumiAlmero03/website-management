from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.website import Website


class WebsiteRepositoryProtocol(Protocol):
    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        brand_id: int | None = None,
        status: str | None = None,
        website_type: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Website], int]: ...

    def list_by_brand(self, brand_id: int) -> list[Website]: ...

    def list_due_for_scan(self, *, now: datetime) -> list[Website]: ...

    def get_by_id(self, website_id: int) -> Website | None: ...

    def get_by_brand_and_domain(self, brand_id: int, domain: str) -> Website | None: ...

    def count_by_brand(self, brand_id: int) -> int: ...

    def count_all(
        self,
        *,
        brand_id: int | None = None,
        website_id: int | None = None,
        status: str | None = None,
    ) -> int: ...

    def count_due(
        self,
        *,
        now: datetime,
        brand_id: int | None = None,
        website_id: int | None = None,
    ) -> int: ...

    def create(self, data: dict[str, Any]) -> Website: ...

    def update(self, website_id: int, data: dict[str, Any]) -> Website | None: ...

    def delete(self, website_id: int) -> bool: ...


class SQLAlchemyWebsiteRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        brand_id: int | None = None,
        status: str | None = None,
        website_type: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Website], int]:
        filters = []
        if brand_id is not None:
            filters.append(Website.brand_id == brand_id)
        if status:
            filters.append(Website.status == status.strip())
        if website_type:
            filters.append(Website.website_type == website_type.strip())
        if search:
            term = f"%{search.strip()}%"
            filters.append(or_(Website.name.ilike(term), Website.domain.ilike(term)))

        count_stmt = select(func.count()).select_from(Website)
        data_stmt = select(Website).order_by(Website.created_at.desc(), Website.id.desc())
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

    def list_by_brand(self, brand_id: int) -> list[Website]:
        stmt = select(Website).where(Website.brand_id == brand_id).order_by(Website.name.asc())
        return list(self.db.execute(stmt).scalars().all())

    def list_due_for_scan(self, *, now: datetime) -> list[Website]:
        naive_now = now.replace(tzinfo=None)
        stmt = (
            select(Website)
            .where(
                Website.status == "active",
                Website.auto_scan.is_(True),
                or_(Website.next_scan_at.is_(None), Website.next_scan_at <= naive_now),
            )
            .order_by(Website.next_scan_at.asc(), Website.id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_id(self, website_id: int) -> Website | None:
        return self.db.get(Website, website_id)

    def get_by_brand_and_domain(self, brand_id: int, domain: str) -> Website | None:
        stmt = select(Website).where(
            Website.brand_id == brand_id,
            Website.domain == domain.strip().lower(),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def count_by_brand(self, brand_id: int) -> int:
        stmt = select(func.count()).select_from(Website).where(Website.brand_id == brand_id)
        return int(self.db.execute(stmt).scalar_one())

    def count_all(
        self,
        *,
        brand_id: int | None = None,
        website_id: int | None = None,
        status: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Website)
        if brand_id is not None:
            stmt = stmt.where(Website.brand_id == brand_id)
        if website_id is not None:
            stmt = stmt.where(Website.id == website_id)
        if status is not None:
            stmt = stmt.where(Website.status == status)
        return int(self.db.execute(stmt).scalar_one())

    def count_due(
        self,
        *,
        now: datetime,
        brand_id: int | None = None,
        website_id: int | None = None,
    ) -> int:
        naive_now = now.replace(tzinfo=None)
        stmt = (
            select(func.count())
            .select_from(Website)
            .where(
                Website.status == "active",
                Website.auto_scan.is_(True),
                or_(Website.next_scan_at.is_(None), Website.next_scan_at <= naive_now),
            )
        )
        if brand_id is not None:
            stmt = stmt.where(Website.brand_id == brand_id)
        if website_id is not None:
            stmt = stmt.where(Website.id == website_id)
        return int(self.db.execute(stmt).scalar_one())

    def create(self, data: dict[str, Any]) -> Website:
        now = utc_now_naive()
        website = Website(**data, created_at=now, updated_at=now)
        self.db.add(website)
        self.db.commit()
        self.db.refresh(website)
        return website

    def update(self, website_id: int, data: dict[str, Any]) -> Website | None:
        website = self.db.get(Website, website_id)
        if website is None:
            return None
        for key, value in data.items():
            setattr(website, key, value)
        website.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(website)
        return website

    def delete(self, website_id: int) -> bool:
        website = self.db.get(Website, website_id)
        if website is None:
            return False
        self.db.delete(website)
        self.db.commit()
        return True
