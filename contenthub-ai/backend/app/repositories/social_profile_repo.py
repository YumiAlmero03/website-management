from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.platform import Platform
from app.models.social_profile import SocialProfile


class SocialProfileRepositoryProtocol(Protocol):
    def list_platforms(self, *, enabled_only: bool = True) -> list[Platform]: ...

    def get_platform_by_key(self, platform_key: str) -> Platform | None: ...

    def get_platform_by_id(self, platform_id: int) -> Platform | None: ...

    def list_for_website(
        self,
        website_id: int,
        *,
        active_only: bool = False,
        generation_only: bool = False,
        automatic_only: bool = False,
    ) -> list[SocialProfile]: ...

    def list_all(self, *, website_id: int | None = None) -> list[SocialProfile]: ...

    def get_by_id(self, profile_id: int) -> SocialProfile | None: ...

    def create(self, data: dict[str, Any]) -> SocialProfile: ...

    def update(self, profile_id: int, data: dict[str, Any]) -> SocialProfile | None: ...

    def delete(self, profile_id: int) -> bool: ...


class SQLAlchemySocialProfileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_platforms(self, *, enabled_only: bool = True) -> list[Platform]:
        stmt = select(Platform)
        if enabled_only:
            stmt = stmt.where(Platform.is_enabled.is_(True))
        stmt = stmt.order_by(Platform.sort_order.asc(), Platform.id.asc())
        return list(self.db.execute(stmt).scalars().all())

    def get_platform_by_key(self, platform_key: str) -> Platform | None:
        normalized = platform_key.strip().lower()
        stmt = select(Platform).where(Platform.platform_key == normalized)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_platform_by_id(self, platform_id: int) -> Platform | None:
        return self.db.get(Platform, platform_id)

    def list_for_website(
        self,
        website_id: int,
        *,
        active_only: bool = False,
        generation_only: bool = False,
        automatic_only: bool = False,
    ) -> list[SocialProfile]:
        stmt = select(SocialProfile).where(SocialProfile.website_id == website_id)
        if active_only:
            stmt = stmt.where(SocialProfile.is_active.is_(True))
        if generation_only:
            stmt = stmt.where(SocialProfile.generation_enabled.is_(True))
        if automatic_only:
            stmt = stmt.where(SocialProfile.automatic_generation_enabled.is_(True))
        stmt = stmt.order_by(SocialProfile.id.asc())
        return list(self.db.execute(stmt).scalars().all())

    def list_all(self, *, website_id: int | None = None) -> list[SocialProfile]:
        stmt = select(SocialProfile)
        if website_id is not None:
            stmt = stmt.where(SocialProfile.website_id == website_id)
        stmt = stmt.order_by(SocialProfile.website_id.asc(), SocialProfile.id.asc())
        return list(self.db.execute(stmt).scalars().all())

    def get_by_id(self, profile_id: int) -> SocialProfile | None:
        return self.db.get(SocialProfile, profile_id)

    def create(self, data: dict[str, Any]) -> SocialProfile:
        now = utc_now_naive()
        row = SocialProfile(**data, created_at=now, updated_at=now)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(self, profile_id: int, data: dict[str, Any]) -> SocialProfile | None:
        row = self.db.get(SocialProfile, profile_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        row.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, profile_id: int) -> bool:
        row = self.db.get(SocialProfile, profile_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True
