from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.publishing import (
    OAuthStateSession,
    PublicationRecord,
    PublishingJob,
    PublishingLog,
    PublishingSchedule,
    SocialPostMedia,
    SocialProfileConnection,
)


class PublishingRepositoryProtocol(Protocol):
    # Connections
    def get_connection_by_profile_id(
        self, social_profile_id: int
    ) -> SocialProfileConnection | None: ...
    def upsert_connection(
        self,
        *,
        social_profile_id: int,
        website_id: int,
        platform_id: int,
        data: dict[str, Any],
    ) -> SocialProfileConnection: ...
    def list_connections(
        self, *, website_id: int | None = None
    ) -> list[SocialProfileConnection]: ...

    # OAuth state
    def create_oauth_state(self, data: dict[str, Any]) -> OAuthStateSession: ...
    def get_oauth_state_by_hash(self, state_hash: str) -> OAuthStateSession | None: ...
    def get_latest_oauth_state_for_profile(
        self, social_profile_id: int, *, status: str | None = None
    ) -> OAuthStateSession | None: ...
    def update_oauth_state(
        self, state_id: int, data: dict[str, Any]
    ) -> OAuthStateSession | None: ...

    # Post media
    def list_post_media(self, social_post_id: int) -> list[SocialPostMedia]: ...
    def get_post_media_by_id(self, media_row_id: int) -> SocialPostMedia | None: ...
    def get_post_media_by_token(self, token: str) -> SocialPostMedia | None: ...
    def add_post_media(self, data: dict[str, Any]) -> SocialPostMedia: ...
    def replace_post_media(
        self, social_post_id: int, items: list[dict[str, Any]]
    ) -> list[SocialPostMedia]: ...
    def update_post_media(
        self, media_row_id: int, data: dict[str, Any]
    ) -> SocialPostMedia | None: ...
    def delete_post_media(self, media_row_id: int) -> bool: ...

    # Schedules
    def create_schedule(self, data: dict[str, Any]) -> PublishingSchedule: ...
    def get_schedule_by_id(self, schedule_id: int) -> PublishingSchedule | None: ...
    def list_schedules(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_key: str | None = None,
        status: str | None = None,
        start_utc: datetime | None = None,
        end_utc: datetime | None = None,
    ) -> list[PublishingSchedule]: ...
    def list_active_schedules_for_post(
        self, social_post_id: int
    ) -> list[PublishingSchedule]: ...
    def update_schedule(
        self, schedule_id: int, data: dict[str, Any]
    ) -> PublishingSchedule | None: ...

    # Jobs
    def create_job(self, data: dict[str, Any]) -> PublishingJob: ...
    def get_job_by_id(self, job_id: int) -> PublishingJob | None: ...
    def get_job_by_idempotency_key(self, idempotency_key: str) -> PublishingJob | None: ...
    def get_active_job_for_post(self, social_post_id: int) -> PublishingJob | None: ...
    def list_jobs(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_key: str | None = None,
        status: str | None = None,
        social_post_id: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[PublishingJob], int]: ...
    def list_due_jobs(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> list[PublishingJob]: ...
    def claim_job(self, job_id: int, *, worker_id: str) -> PublishingJob | None: ...
    def count_processing_jobs(self) -> int: ...
    def recover_stale_jobs(self, *, stale_minutes: int) -> list[PublishingJob]: ...
    def update_job(self, job_id: int, data: dict[str, Any]) -> PublishingJob | None: ...

    # Logs & history
    def create_log(self, data: dict[str, Any]) -> PublishingLog: ...
    def list_logs_for_post(self, social_post_id: int) -> list[PublishingLog]: ...
    def list_logs_for_job(self, publishing_job_id: int) -> list[PublishingLog]: ...
    def create_record(self, data: dict[str, Any]) -> PublicationRecord: ...
    def get_record_by_idempotency_key(
        self, idempotency_key: str
    ) -> PublicationRecord | None: ...
    def get_latest_published_for_post(
        self, social_post_id: int
    ) -> PublicationRecord | None: ...
    def get_latest_for_profile(
        self, social_profile_id: int
    ) -> PublicationRecord | None: ...
    def list_history(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_key: str | None = None,
        outcome: str | None = None,
        publishing_method: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[PublicationRecord], int]: ...
    def count_published_in_window(
        self,
        *,
        start_utc: datetime,
        end_utc: datetime | None = None,
        website_id: int | None = None,
        platform_id: int | None = None,
    ) -> int: ...
    def count_published_for_profile_since(
        self, social_profile_id: int, since_utc: datetime
    ) -> int: ...


class SQLAlchemyPublishingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # Connections
    def get_connection_by_profile_id(
        self, social_profile_id: int
    ) -> SocialProfileConnection | None:
        stmt = select(SocialProfileConnection).where(
            SocialProfileConnection.social_profile_id == social_profile_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def upsert_connection(
        self,
        *,
        social_profile_id: int,
        website_id: int,
        platform_id: int,
        data: dict[str, Any],
    ) -> SocialProfileConnection:
        now = utc_now_naive()
        existing = self.get_connection_by_profile_id(social_profile_id)
        if existing is None:
            row = SocialProfileConnection(
                social_profile_id=social_profile_id,
                website_id=website_id,
                platform_id=platform_id,
                **data,
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
        else:
            for k, v in data.items():
                setattr(existing, k, v)
            existing.updated_at = now
            row = existing
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_connections(
        self, *, website_id: int | None = None
    ) -> list[SocialProfileConnection]:
        stmt = select(SocialProfileConnection)
        if website_id is not None:
            stmt = stmt.where(SocialProfileConnection.website_id == website_id)
        stmt = stmt.order_by(SocialProfileConnection.id.asc())
        return list(self.db.execute(stmt).scalars().all())

    # OAuth state
    def create_oauth_state(self, data: dict[str, Any]) -> OAuthStateSession:
        row = OAuthStateSession(**data, created_at=utc_now_naive())
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_oauth_state_by_hash(self, state_hash: str) -> OAuthStateSession | None:
        stmt = select(OAuthStateSession).where(OAuthStateSession.state_hash == state_hash)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_oauth_state_for_profile(
        self, social_profile_id: int, *, status: str | None = None
    ) -> OAuthStateSession | None:
        stmt = select(OAuthStateSession).where(
            OAuthStateSession.social_profile_id == social_profile_id
        )
        if status:
            stmt = stmt.where(OAuthStateSession.status == status)
        stmt = stmt.order_by(OAuthStateSession.id.desc()).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def update_oauth_state(
        self, state_id: int, data: dict[str, Any]
    ) -> OAuthStateSession | None:
        row = self.db.get(OAuthStateSession, state_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        self.db.commit()
        self.db.refresh(row)
        return row

    # Post media
    def list_post_media(self, social_post_id: int) -> list[SocialPostMedia]:
        stmt = (
            select(SocialPostMedia)
            .where(SocialPostMedia.social_post_id == social_post_id)
            .order_by(SocialPostMedia.sort_order.asc(), SocialPostMedia.id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_post_media_by_id(self, media_row_id: int) -> SocialPostMedia | None:
        return self.db.get(SocialPostMedia, media_row_id)

    def get_post_media_by_token(self, token: str) -> SocialPostMedia | None:
        stmt = select(SocialPostMedia).where(SocialPostMedia.public_media_token == token)
        return self.db.execute(stmt).scalar_one_or_none()

    def add_post_media(self, data: dict[str, Any]) -> SocialPostMedia:
        now = utc_now_naive()
        row = SocialPostMedia(**data, created_at=now, updated_at=now)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def replace_post_media(
        self, social_post_id: int, items: list[dict[str, Any]]
    ) -> list[SocialPostMedia]:
        existing = self.list_post_media(social_post_id)
        for row in existing:
            self.db.delete(row)
        self.db.flush()
        now = utc_now_naive()
        created: list[SocialPostMedia] = []
        for idx, item in enumerate(items):
            payload = dict(item)
            payload.setdefault("sort_order", idx)
            payload["social_post_id"] = social_post_id
            row = SocialPostMedia(**payload, created_at=now, updated_at=now)
            self.db.add(row)
            created.append(row)
        self.db.commit()
        for row in created:
            self.db.refresh(row)
        return created

    def update_post_media(
        self, media_row_id: int, data: dict[str, Any]
    ) -> SocialPostMedia | None:
        row = self.db.get(SocialPostMedia, media_row_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_post_media(self, media_row_id: int) -> bool:
        row = self.db.get(SocialPostMedia, media_row_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    # Schedules
    def create_schedule(self, data: dict[str, Any]) -> PublishingSchedule:
        now = utc_now_naive()
        row = PublishingSchedule(**data, created_at=now, updated_at=now)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_schedule_by_id(self, schedule_id: int) -> PublishingSchedule | None:
        return self.db.get(PublishingSchedule, schedule_id)

    def list_schedules(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_key: str | None = None,
        status: str | None = None,
        start_utc: datetime | None = None,
        end_utc: datetime | None = None,
    ) -> list[PublishingSchedule]:
        stmt = select(PublishingSchedule)
        if website_id is not None:
            stmt = stmt.where(PublishingSchedule.website_id == website_id)
        if social_profile_id is not None:
            stmt = stmt.where(PublishingSchedule.social_profile_id == social_profile_id)
        if platform_key:
            stmt = stmt.where(PublishingSchedule.platform_key == platform_key)
        if status and status != "all":
            stmt = stmt.where(PublishingSchedule.status == status)
        if start_utc is not None:
            stmt = stmt.where(PublishingSchedule.scheduled_at >= start_utc.replace(tzinfo=None))
        if end_utc is not None:
            stmt = stmt.where(PublishingSchedule.scheduled_at <= end_utc.replace(tzinfo=None))
        stmt = stmt.order_by(PublishingSchedule.scheduled_at.asc(), PublishingSchedule.id.asc())
        return list(self.db.execute(stmt).scalars().all())

    def list_active_schedules_for_post(
        self, social_post_id: int
    ) -> list[PublishingSchedule]:
        stmt = (
            select(PublishingSchedule)
            .where(
                PublishingSchedule.social_post_id == social_post_id,
                PublishingSchedule.status.in_(("scheduled", "queued", "deferred")),
            )
            .order_by(PublishingSchedule.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def update_schedule(
        self, schedule_id: int, data: dict[str, Any]
    ) -> PublishingSchedule | None:
        row = self.db.get(PublishingSchedule, schedule_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(row)
        return row

    # Jobs
    def create_job(self, data: dict[str, Any]) -> PublishingJob:
        now = utc_now_naive()
        row = PublishingJob(**data, created_at=now, updated_at=now)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_job_by_id(self, job_id: int) -> PublishingJob | None:
        return self.db.get(PublishingJob, job_id)

    def get_job_by_idempotency_key(self, idempotency_key: str) -> PublishingJob | None:
        stmt = select(PublishingJob).where(PublishingJob.idempotency_key == idempotency_key)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_active_job_for_post(self, social_post_id: int) -> PublishingJob | None:
        stmt = (
            select(PublishingJob)
            .where(
                PublishingJob.social_post_id == social_post_id,
                PublishingJob.status.in_(
                    ("queued", "processing", "deferred", "verification_required")
                ),
            )
            .order_by(PublishingJob.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_jobs(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_key: str | None = None,
        status: str | None = None,
        social_post_id: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[PublishingJob], int]:
        stmt = select(PublishingJob)
        count_stmt = select(func.count(PublishingJob.id))
        if website_id is not None:
            stmt = stmt.where(PublishingJob.website_id == website_id)
            count_stmt = count_stmt.where(PublishingJob.website_id == website_id)
        if social_profile_id is not None:
            stmt = stmt.where(PublishingJob.social_profile_id == social_profile_id)
            count_stmt = count_stmt.where(PublishingJob.social_profile_id == social_profile_id)
        if platform_key:
            stmt = stmt.where(PublishingJob.platform_key == platform_key)
            count_stmt = count_stmt.where(PublishingJob.platform_key == platform_key)
        if social_post_id is not None:
            stmt = stmt.where(PublishingJob.social_post_id == social_post_id)
            count_stmt = count_stmt.where(PublishingJob.social_post_id == social_post_id)
        if status and status != "all":
            stmt = stmt.where(PublishingJob.status == status)
            count_stmt = count_stmt.where(PublishingJob.status == status)

        total = int(self.db.execute(count_stmt).scalar() or 0)
        offset = (page - 1) * page_size
        items = list(
            self.db.execute(stmt.order_by(PublishingJob.id.desc()).offset(offset).limit(page_size))
            .scalars()
            .all()
        )
        return items, total

    def list_due_jobs(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> list[PublishingJob]:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        stmt = (
            select(PublishingJob)
            .where(
                PublishingJob.status.in_(("queued", "deferred")),
                func.coalesce(PublishingJob.next_retry_at, PublishingJob.available_at) <= current,
            )
            .order_by(PublishingJob.priority.asc(), PublishingJob.id.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def claim_job(self, job_id: int, *, worker_id: str) -> PublishingJob | None:
        now = utc_now_naive()
        stmt = (
            select(PublishingJob)
            .where(
                PublishingJob.id == job_id,
                PublishingJob.status.in_(("queued", "deferred")),
            )
            .with_for_update()
        )
        job = self.db.execute(stmt).scalar_one_or_none()
        if job is None:
            self.db.rollback()
            return None
        job.status = "processing"
        job.worker_id = worker_id[:120]
        job.locked_at = now
        job.heartbeat_at = now
        job.started_at = job.started_at or now
        job.attempt_count += 1
        job.paused_reason = None
        job.updated_at = now
        self.db.commit()
        self.db.refresh(job)
        return job

    def count_processing_jobs(self) -> int:
        stmt = select(func.count(PublishingJob.id)).where(PublishingJob.status == "processing")
        return int(self.db.execute(stmt).scalar() or 0)

    def recover_stale_jobs(self, *, stale_minutes: int) -> list[PublishingJob]:
        now = utc_now_naive()
        cutoff = now - timedelta(minutes=stale_minutes)
        stmt = (
            select(PublishingJob)
            .where(
                PublishingJob.status == "processing",
                or_(
                    PublishingJob.heartbeat_at < cutoff,
                    (
                        PublishingJob.heartbeat_at.is_(None)
                        & (PublishingJob.started_at < cutoff)
                    ),
                ),
            )
            .with_for_update()
        )
        stale = list(self.db.execute(stmt).scalars().all())
        for job in stale:
            if job.requires_verification or job.publishing_method == "api":
                job.status = "verification_required"
                job.requires_verification = True
                job.error_category = "unknown_result"
                job.error_message = (
                    f"Worker exceeded {stale_minutes}m heartbeat while publishing; "
                    "reconcile external outcome before retrying."
                )
            elif job.attempt_count < job.max_attempts:
                job.status = "deferred"
                job.paused_reason = f"Recovered stale job after {stale_minutes}m timeout."
                job.next_retry_at = now
            else:
                job.status = "failed"
                job.error_category = "unknown_result"
                job.error_message = f"Exceeded {stale_minutes}m worker heartbeat timeout."
                job.completed_at = now
            job.worker_id = None
            job.locked_at = None
            job.updated_at = now
        if stale:
            self.db.commit()
        return stale

    def update_job(self, job_id: int, data: dict[str, Any]) -> PublishingJob | None:
        row = self.db.get(PublishingJob, job_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(row)
        return row

    # Logs & history
    def create_log(self, data: dict[str, Any]) -> PublishingLog:
        row = PublishingLog(**data, created_at=utc_now_naive())
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_logs_for_post(self, social_post_id: int) -> list[PublishingLog]:
        stmt = (
            select(PublishingLog)
            .where(PublishingLog.social_post_id == social_post_id)
            .order_by(PublishingLog.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_logs_for_job(self, publishing_job_id: int) -> list[PublishingLog]:
        stmt = (
            select(PublishingLog)
            .where(PublishingLog.publishing_job_id == publishing_job_id)
            .order_by(PublishingLog.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def create_record(self, data: dict[str, Any]) -> PublicationRecord:
        now = utc_now_naive()
        row = PublicationRecord(**data, created_at=now, updated_at=now)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_record_by_idempotency_key(
        self, idempotency_key: str
    ) -> PublicationRecord | None:
        stmt = select(PublicationRecord).where(
            PublicationRecord.idempotency_key == idempotency_key
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_published_for_post(
        self, social_post_id: int
    ) -> PublicationRecord | None:
        stmt = (
            select(PublicationRecord)
            .where(
                PublicationRecord.social_post_id == social_post_id,
                PublicationRecord.outcome.in_(("published", "manually_published")),
            )
            .order_by(PublicationRecord.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_for_profile(
        self, social_profile_id: int
    ) -> PublicationRecord | None:
        stmt = (
            select(PublicationRecord)
            .where(
                PublicationRecord.social_profile_id == social_profile_id,
                PublicationRecord.outcome.in_(("published", "manually_published")),
            )
            .order_by(PublicationRecord.published_at.desc(), PublicationRecord.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_history(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_key: str | None = None,
        outcome: str | None = None,
        publishing_method: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[PublicationRecord], int]:
        stmt = select(PublicationRecord)
        count_stmt = select(func.count(PublicationRecord.id))
        filters: list[Any] = []
        if website_id is not None:
            filters.append(PublicationRecord.website_id == website_id)
        if social_profile_id is not None:
            filters.append(PublicationRecord.social_profile_id == social_profile_id)
        if platform_key and platform_key != "all":
            filters.append(PublicationRecord.platform_key == platform_key)
        if outcome and outcome != "all":
            filters.append(PublicationRecord.outcome == outcome)
        if publishing_method and publishing_method != "all":
            filters.append(PublicationRecord.publishing_method == publishing_method)
        if date_from is not None:
            filters.append(
                func.coalesce(PublicationRecord.published_at, PublicationRecord.created_at)
                >= date_from.replace(tzinfo=None)
            )
        if date_to is not None:
            filters.append(
                func.coalesce(PublicationRecord.published_at, PublicationRecord.created_at)
                <= date_to.replace(tzinfo=None)
            )
        for f in filters:
            stmt = stmt.where(f)
            count_stmt = count_stmt.where(f)

        total = int(self.db.execute(count_stmt).scalar() or 0)
        offset = (page - 1) * page_size
        items = list(
            self.db.execute(
                stmt.order_by(PublicationRecord.id.desc()).offset(offset).limit(page_size)
            )
            .scalars()
            .all()
        )
        return items, total

    def count_published_in_window(
        self,
        *,
        start_utc: datetime,
        end_utc: datetime | None = None,
        website_id: int | None = None,
        platform_id: int | None = None,
    ) -> int:
        stmt = select(func.count(PublicationRecord.id)).where(
            PublicationRecord.outcome.in_(("published", "manually_published")),
            PublicationRecord.published_at.is_not(None),
            PublicationRecord.published_at >= start_utc.replace(tzinfo=None),
        )
        if end_utc is not None:
            stmt = stmt.where(PublicationRecord.published_at <= end_utc.replace(tzinfo=None))
        if website_id is not None:
            stmt = stmt.where(PublicationRecord.website_id == website_id)
        if platform_id is not None:
            stmt = stmt.where(PublicationRecord.platform_id == platform_id)
        return int(self.db.execute(stmt).scalar() or 0)

    def count_published_for_profile_since(
        self, social_profile_id: int, since_utc: datetime
    ) -> int:
        stmt = select(func.count(PublicationRecord.id)).where(
            PublicationRecord.social_profile_id == social_profile_id,
            PublicationRecord.outcome.in_(("published", "manually_published")),
            PublicationRecord.published_at.is_not(None),
            PublicationRecord.published_at >= since_utc.replace(tzinfo=None),
        )
        return int(self.db.execute(stmt).scalar() or 0)
