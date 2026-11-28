from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import func, or_, select
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
        publishing_status: str | None = None,
        view: str | None = None,
        website_content_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
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

    def get_revision_by_id(self, revision_id: int) -> SocialPostRevision | None: ...


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
        publishing_status: str | None = None,
        view: str | None = None,
        website_content_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[SocialPost], int]:
        stmt = select(SocialPost)
        count_stmt = select(func.count(SocialPost.id))
        filters: list[Any] = []
        if website_id is not None:
            filters.append(SocialPost.website_id == website_id)
        if social_profile_id is not None:
            filters.append(SocialPost.social_profile_id == social_profile_id)
        if platform_id is not None:
            filters.append(SocialPost.platform_id == platform_id)
        if website_content_id is not None:
            filters.append(SocialPost.website_content_id == website_content_id)
        if status and status != "all":
            filters.append(SocialPost.status == status)
        if publishing_status and publishing_status != "all":
            filters.append(SocialPost.publishing_status == publishing_status)
        if view and view != "all":
            if view == "drafts":
                filters.append(SocialPost.status != "archived")
            elif view == "pending_review":
                filters.append(SocialPost.status == "pending_review")
            elif view == "approved":
                filters.append(
                    (SocialPost.status == "approved")
                    & SocialPost.publishing_status.in_(("unscheduled", "approved", "cancelled"))
                )
            elif view == "scheduled":
                filters.append(
                    SocialPost.publishing_status.in_(("scheduled", "queued", "deferred"))
                )
            elif view == "publishing":
                filters.append(
                    SocialPost.publishing_status.in_(("publishing", "verification_required"))
                )
            elif view == "published":
                filters.append(
                    SocialPost.publishing_status.in_(("published", "manually_published"))
                )
            elif view == "failed":
                filters.append(
                    or_(
                        SocialPost.publishing_status == "failed",
                        SocialPost.status == "generation_failed",
                    )
                )
            elif view == "manual_publishing":
                filters.append(
                    (SocialPost.status == "approved")
                    & SocialPost.publishing_status.in_(
                        ("unscheduled", "approved", "manually_published", "cancelled")
                    )
                )
            elif view == "archived":
                filters.append(SocialPost.status == "archived")
        if date_from is not None:
            dt_from = date_from.replace(tzinfo=None)
            filters.append(
                func.coalesce(
                    SocialPost.published_at, SocialPost.scheduled_for, SocialPost.created_at
                )
                >= dt_from
            )
        if date_to is not None:
            dt_to = date_to.replace(tzinfo=None)
            filters.append(
                func.coalesce(
                    SocialPost.published_at, SocialPost.scheduled_for, SocialPost.created_at
                )
                <= dt_to
            )
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    SocialPost.caption.ilike(term),
                    SocialPost.title.ilike(term),
                    SocialPost.source_url.ilike(term),
                )
            )
        for f in filters:
            stmt = stmt.where(f)
            count_stmt = count_stmt.where(f)

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
        pub_stmt = select(SocialPost.publishing_status, func.count(SocialPost.id)).group_by(
            SocialPost.publishing_status
        )
        if website_id is not None:
            stmt = stmt.where(SocialPost.website_id == website_id)
            pub_stmt = pub_stmt.where(SocialPost.website_id == website_id)
        if social_profile_id is not None:
            stmt = stmt.where(SocialPost.social_profile_id == social_profile_id)
            pub_stmt = pub_stmt.where(SocialPost.social_profile_id == social_profile_id)
        if platform_id is not None:
            stmt = stmt.where(SocialPost.platform_id == platform_id)
            pub_stmt = pub_stmt.where(SocialPost.platform_id == platform_id)

        counts = {row[0]: int(row[1]) for row in self.db.execute(stmt).fetchall()}
        pub_counts = {row[0]: int(row[1]) for row in self.db.execute(pub_stmt).fetchall()}
        total = sum(counts.values())
        archived = counts.get("archived", 0)
        return {
            "total_drafts": total,
            "drafts": total - archived,
            "pending_review": counts.get("pending_review", 0),
            "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0),
            "generation_failed": counts.get("generation_failed", 0),
            "archived": archived,
            "scheduled": (
                pub_counts.get("scheduled", 0)
                + pub_counts.get("queued", 0)
                + pub_counts.get("deferred", 0)
            ),
            "publishing": (
                pub_counts.get("publishing", 0) + pub_counts.get("verification_required", 0)
            ),
            "published": (
                pub_counts.get("published", 0) + pub_counts.get("manually_published", 0)
            ),
            "manually_published": pub_counts.get("manually_published", 0),
            "failed_publishing": pub_counts.get("failed", 0),
            "verification_required": pub_counts.get("verification_required", 0),
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

    def get_revision_by_id(self, revision_id: int) -> SocialPostRevision | None:
        return self.db.get(SocialPostRevision, revision_id)
