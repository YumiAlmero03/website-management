from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.social_post import SocialPost, SocialPostRevision


class SocialPostRepositoryProtocol(Protocol):
    def list_posts(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_id: int | None = None,
        status: str | None = None,
        website_content_id: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[SocialPost], int]: ...

    def get_stats(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_id: int | None = None,
    ) -> dict[str, int]: ...

    def get_by_id(self, post_id: int) -> SocialPost | None: ...

    def get_by_dedupe_key(self, dedupe_key: str) -> SocialPost | None: ...

    def list_for_content(self, website_content_id: int) -> list[SocialPost]: ...

    def get_active_for_content_and_profile(
        self, website_content_id: int, social_profile_id: int
    ) -> SocialPost | None: ...

    def create_post(
        self,
        data: dict[str, Any],
        *,
        change_type: str = "initial_generated",
        edited_by: int | None = None,
        notes: str | None = None,
    ) -> SocialPost: ...

    def update_post(
        self,
        post_id: int,
        data: dict[str, Any],
        *,
        create_revision: bool = False,
        change_type: str = "manual_edit",
        edited_by: int | None = None,
        notes: str | None = None,
    ) -> SocialPost | None: ...

    def list_revisions(self, post_id: int) -> list[SocialPostRevision]: ...


class SQLAlchemySocialPostRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_posts(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_id: int | None = None,
        status: str | None = None,
        website_content_id: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[SocialPost], int]:
        stmt = select(SocialPost)
        count_stmt = select(func.count(SocialPost.id))
        if website_id is not None:
            stmt = stmt.where(SocialPost.website_id == website_id)
            count_stmt = count_stmt.where(SocialPost.website_id == website_id)
        if social_profile_id is not None:
            stmt = stmt.where(SocialPost.social_profile_id == social_profile_id)
            count_stmt = count_stmt.where(SocialPost.social_profile_id == social_profile_id)
        if platform_id is not None:
            stmt = stmt.where(SocialPost.platform_id == platform_id)
            count_stmt = count_stmt.where(SocialPost.platform_id == platform_id)
        if website_content_id is not None:
            stmt = stmt.where(SocialPost.website_content_id == website_content_id)
            count_stmt = count_stmt.where(SocialPost.website_content_id == website_content_id)
        if status and status != "all":
            stmt = stmt.where(SocialPost.status == status)
            count_stmt = count_stmt.where(SocialPost.status == status)

        total = int(self.db.execute(count_stmt).scalar() or 0)
        offset = (page - 1) * page_size
        items = list(
            self.db.execute(stmt.order_by(SocialPost.id.desc()).offset(offset).limit(page_size))
            .scalars()
            .all()
        )
        return items, total

    def get_stats(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_id: int | None = None,
    ) -> dict[str, int]:
        stmt = select(SocialPost.status, func.count(SocialPost.id)).group_by(SocialPost.status)
        if website_id is not None:
            stmt = stmt.where(SocialPost.website_id == website_id)
        if social_profile_id is not None:
            stmt = stmt.where(SocialPost.social_profile_id == social_profile_id)
        if platform_id is not None:
            stmt = stmt.where(SocialPost.platform_id == platform_id)
        counts = {row[0]: int(row[1]) for row in self.db.execute(stmt).fetchall()}
        return {
            "total_drafts": sum(counts.values()),
            "pending_review": counts.get("pending_review", 0),
            "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0),
            "generation_failed": counts.get("generation_failed", 0),
            "archived": counts.get("archived", 0),
        }

    def get_by_id(self, post_id: int) -> SocialPost | None:
        return self.db.get(SocialPost, post_id)

    def get_by_dedupe_key(self, dedupe_key: str) -> SocialPost | None:
        stmt = select(SocialPost).where(SocialPost.dedupe_key == dedupe_key)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_content(self, website_content_id: int) -> list[SocialPost]:
        stmt = (
            select(SocialPost)
            .where(SocialPost.website_content_id == website_content_id)
            .order_by(SocialPost.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_active_for_content_and_profile(
        self, website_content_id: int, social_profile_id: int
    ) -> SocialPost | None:
        stmt = (
            select(SocialPost)
            .where(
                SocialPost.website_content_id == website_content_id,
                SocialPost.social_profile_id == social_profile_id,
                SocialPost.status != "archived",
            )
            .order_by(SocialPost.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def create_post(
        self,
        data: dict[str, Any],
        *,
        change_type: str = "initial_generated",
        edited_by: int | None = None,
        notes: str | None = None,
    ) -> SocialPost:
        now = utc_now_naive()
        row = SocialPost(**data, current_version=1, created_at=now, updated_at=now)
        self.db.add(row)
        self.db.flush()
        self.db.add(
            SocialPostRevision(
                social_post_id=row.id,
                version_number=1,
                title=row.title,
                caption=row.caption,
                assembled_content=row.assembled_content,
                hashtags_json=list(row.hashtags_json or []),
                cta_text=row.cta_text,
                generation_model=row.generation_model,
                change_type=change_type,
                edited_by=edited_by,
                notes=notes,
                created_at=now,
            )
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_post(
        self,
        post_id: int,
        data: dict[str, Any],
        *,
        create_revision: bool = False,
        change_type: str = "manual_edit",
        edited_by: int | None = None,
        notes: str | None = None,
    ) -> SocialPost | None:
        row = self.db.get(SocialPost, post_id)
        if row is None:
            return None
        now = utc_now_naive()
        for key, value in data.items():
            setattr(row, key, value)
        if create_revision:
            row.current_version += 1
            self.db.add(
                SocialPostRevision(
                    social_post_id=row.id,
                    version_number=row.current_version,
                    title=row.title,
                    caption=row.caption,
                    assembled_content=row.assembled_content,
                    hashtags_json=list(row.hashtags_json or []),
                    cta_text=row.cta_text,
                    generation_model=row.generation_model,
                    change_type=change_type,
                    edited_by=edited_by,
                    notes=notes,
                    created_at=now,
                )
            )
        row.updated_at = now
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_revisions(self, post_id: int) -> list[SocialPostRevision]:
        stmt = (
            select(SocialPostRevision)
            .where(SocialPostRevision.social_post_id == post_id)
            .order_by(SocialPostRevision.version_number.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
