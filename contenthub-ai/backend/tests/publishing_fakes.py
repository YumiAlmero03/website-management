from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

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


class InMemoryPublishingRepository:
    def __init__(self) -> None:
        self._connections: dict[int, SocialProfileConnection] = {}
        self._conn_seq = 0
        self._oauth_states: dict[int, OAuthStateSession] = {}
        self._state_seq = 0
        self._media: dict[int, SocialPostMedia] = {}
        self._media_seq = 0
        self._schedules: dict[int, PublishingSchedule] = {}
        self._sched_seq = 0
        self._jobs: dict[int, PublishingJob] = {}
        self._job_seq = 0
        self._logs: list[PublishingLog] = []
        self._log_seq = 0
        self._records: dict[int, PublicationRecord] = {}
        self._rec_seq = 0

    def get_connection_by_profile_id(
        self, social_profile_id: int
    ) -> SocialProfileConnection | None:
        return self._connections.get(social_profile_id)

    def upsert_connection(
        self,
        *,
        social_profile_id: int,
        website_id: int,
        platform_id: int,
        data: dict[str, Any],
    ) -> SocialProfileConnection:
        now = utc_now_naive()
        existing = self._connections.get(social_profile_id)
        if existing is None:
            self._conn_seq += 1
            defaults: dict[str, Any] = {
                "auth_type": "manual",
                "connection_status": "not_connected",
                "available_targets_json": [],
                "granted_scopes_json": [],
                "required_scopes_json": [],
                "missing_scopes_json": [],
                "eligibility_status": "unknown",
                "allow_paid_publishing": False,
                "metadata_json": {},
            }
            defaults.update(data)
            row = SocialProfileConnection(
                id=self._conn_seq,
                social_profile_id=social_profile_id,
                website_id=website_id,
                platform_id=platform_id,
                **defaults,
                created_at=now,
                updated_at=now,
            )
            self._connections[social_profile_id] = row
            return row
        for k, v in data.items():
            setattr(existing, k, v)
        existing.updated_at = now
        return existing

    def list_connections(
        self, *, website_id: int | None = None
    ) -> list[SocialProfileConnection]:
        rows = list(self._connections.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        rows.sort(key=lambda r: r.id)
        return rows

    def create_oauth_state(self, data: dict[str, Any]) -> OAuthStateSession:
        self._state_seq += 1
        row = OAuthStateSession(
            id=self._state_seq,
            **data,
            created_at=utc_now_naive(),
        )
        self._oauth_states[row.id] = row
        return row

    def get_oauth_state_by_hash(self, state_hash: str) -> OAuthStateSession | None:
        for row in self._oauth_states.values():
            if row.state_hash == state_hash:
                return row
        return None

    def get_latest_oauth_state_for_profile(
        self, social_profile_id: int, *, status: str | None = None
    ) -> OAuthStateSession | None:
        rows = [
            r
            for r in self._oauth_states.values()
            if r.social_profile_id == social_profile_id
            and (status is None or r.status == status)
        ]
        rows.sort(key=lambda r: r.id, reverse=True)
        return rows[0] if rows else None

    def update_oauth_state(
        self, state_id: int, data: dict[str, Any]
    ) -> OAuthStateSession | None:
        row = self._oauth_states.get(state_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        return row

    def list_post_media(self, social_post_id: int) -> list[SocialPostMedia]:
        rows = [r for r in self._media.values() if r.social_post_id == social_post_id]
        rows.sort(key=lambda r: (r.sort_order, r.id))
        return rows

    def get_post_media_by_id(self, media_row_id: int) -> SocialPostMedia | None:
        return self._media.get(media_row_id)

    def get_post_media_by_token(self, token: str) -> SocialPostMedia | None:
        for row in self._media.values():
            if row.public_media_token == token:
                return row
        return None

    def add_post_media(self, data: dict[str, Any]) -> SocialPostMedia:
        self._media_seq += 1
        now = utc_now_naive()
        defaults: dict[str, Any] = {"sort_order": 0, "role": "primary", "is_prepared": False}
        defaults.update(data)
        row = SocialPostMedia(
            id=self._media_seq, **defaults, created_at=now, updated_at=now
        )
        self._media[row.id] = row
        return row

    def replace_post_media(
        self, social_post_id: int, items: list[dict[str, Any]]
    ) -> list[SocialPostMedia]:
        to_del = [k for k, v in self._media.items() if v.social_post_id == social_post_id]
        for k in to_del:
            del self._media[k]
        out: list[SocialPostMedia] = []
        for idx, item in enumerate(items):
            payload = dict(item)
            payload.setdefault("sort_order", idx)
            payload["social_post_id"] = social_post_id
            out.append(self.add_post_media(payload))
        return out

    def update_post_media(
        self, media_row_id: int, data: dict[str, Any]
    ) -> SocialPostMedia | None:
        row = self._media.get(media_row_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = utc_now_naive()
        return row

    def delete_post_media(self, media_row_id: int) -> bool:
        return self._media.pop(media_row_id, None) is not None

    def create_schedule(self, data: dict[str, Any]) -> PublishingSchedule:
        self._sched_seq += 1
        now = utc_now_naive()
        defaults: dict[str, Any] = {
            "display_timezone": "Asia/Manila",
            "status": "scheduled",
            "rescheduled_count": 0,
        }
        defaults.update(data)
        row = PublishingSchedule(
            id=self._sched_seq, **defaults, created_at=now, updated_at=now
        )
        self._schedules[row.id] = row
        return row

    def get_schedule_by_id(self, schedule_id: int) -> PublishingSchedule | None:
        return self._schedules.get(schedule_id)

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
        rows = list(self._schedules.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if social_profile_id is not None:
            rows = [r for r in rows if r.social_profile_id == social_profile_id]
        if platform_key:
            rows = [r for r in rows if r.platform_key == platform_key]
        if status and status != "all":
            rows = [r for r in rows if r.status == status]
        if start_utc is not None:
            s_naive = start_utc.replace(tzinfo=None)
            rows = [r for r in rows if r.scheduled_at >= s_naive]
        if end_utc is not None:
            e_naive = end_utc.replace(tzinfo=None)
            rows = [r for r in rows if r.scheduled_at <= e_naive]
        rows.sort(key=lambda r: (r.scheduled_at, r.id))
        return rows

    def list_active_schedules_for_post(
        self, social_post_id: int
    ) -> list[PublishingSchedule]:
        rows = [
            r
            for r in self._schedules.values()
            if r.social_post_id == social_post_id
            and r.status in {"scheduled", "queued", "deferred"}
        ]
        rows.sort(key=lambda r: r.id, reverse=True)
        return rows

    def update_schedule(
        self, schedule_id: int, data: dict[str, Any]
    ) -> PublishingSchedule | None:
        row = self._schedules.get(schedule_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = utc_now_naive()
        return row

    def create_job(self, data: dict[str, Any]) -> PublishingJob:
        self._job_seq += 1
        now = utc_now_naive()
        defaults: dict[str, Any] = {
            "publishing_method": "api",
            "status": "queued",
            "priority": 5,
            "available_at": now,
            "attempt_count": 0,
            "max_attempts": 3,
            "timeout_seconds": 60,
            "requires_verification": False,
        }
        defaults.update(data)
        row = PublishingJob(id=self._job_seq, **defaults, created_at=now, updated_at=now)
        self._jobs[row.id] = row
        return row

    def get_job_by_id(self, job_id: int) -> PublishingJob | None:
        return self._jobs.get(job_id)

    def get_job_by_idempotency_key(self, idempotency_key: str) -> PublishingJob | None:
        for row in self._jobs.values():
            if row.idempotency_key == idempotency_key:
                return row
        return None

    def get_active_job_for_post(self, social_post_id: int) -> PublishingJob | None:
        rows = [
            r
            for r in self._jobs.values()
            if r.social_post_id == social_post_id
            and r.status in {"queued", "processing", "deferred", "verification_required"}
        ]
        rows.sort(key=lambda r: r.id, reverse=True)
        return rows[0] if rows else None

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
        rows = list(self._jobs.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if social_profile_id is not None:
            rows = [r for r in rows if r.social_profile_id == social_profile_id]
        if platform_key:
            rows = [r for r in rows if r.platform_key == platform_key]
        if social_post_id is not None:
            rows = [r for r in rows if r.social_post_id == social_post_id]
        if status and status != "all":
            rows = [r for r in rows if r.status == status]
        rows.sort(key=lambda r: r.id, reverse=True)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def list_due_jobs(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> list[PublishingJob]:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        due = [
            r
            for r in self._jobs.values()
            if r.status in {"queued", "deferred"}
            and (r.next_retry_at or r.available_at) <= current
        ]
        due.sort(key=lambda r: (r.priority, r.id))
        return due[:limit]

    def claim_job(self, job_id: int, *, worker_id: str) -> PublishingJob | None:
        row = self._jobs.get(job_id)
        if row is None or row.status not in {"queued", "deferred"}:
            return None
        now = utc_now_naive()
        row.status = "processing"
        row.worker_id = worker_id[:120]
        row.locked_at = now
        row.heartbeat_at = now
        row.started_at = row.started_at or now
        row.attempt_count += 1
        row.paused_reason = None
        row.updated_at = now
        return row

    def count_processing_jobs(self) -> int:
        return sum(1 for r in self._jobs.values() if r.status == "processing")

    def recover_stale_jobs(self, *, stale_minutes: int) -> list[PublishingJob]:
        now = utc_now_naive()
        cutoff = now - timedelta(minutes=stale_minutes)
        recovered: list[PublishingJob] = []
        for job in self._jobs.values():
            hb = job.heartbeat_at or job.started_at
            if job.status == "processing" and hb is not None and hb < cutoff:
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
                    job.next_retry_at = now
                else:
                    job.status = "failed"
                    job.completed_at = now
                job.worker_id = None
                job.locked_at = None
                job.updated_at = now
                recovered.append(job)
        return recovered

    def update_job(self, job_id: int, data: dict[str, Any]) -> PublishingJob | None:
        row = self._jobs.get(job_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = utc_now_naive()
        return row

    def create_log(self, data: dict[str, Any]) -> PublishingLog:
        self._log_seq += 1
        defaults: dict[str, Any] = {"attempt_number": 1}
        defaults.update(data)
        row = PublishingLog(id=self._log_seq, **defaults, created_at=utc_now_naive())
        self._logs.append(row)
        return row

    def list_logs_for_post(self, social_post_id: int) -> list[PublishingLog]:
        rows = [r for r in self._logs if r.social_post_id == social_post_id]
        rows.sort(key=lambda r: r.id, reverse=True)
        return rows

    def list_logs_for_job(self, publishing_job_id: int) -> list[PublishingLog]:
        rows = [r for r in self._logs if r.publishing_job_id == publishing_job_id]
        rows.sort(key=lambda r: r.id, reverse=True)
        return rows

    def create_record(self, data: dict[str, Any]) -> PublicationRecord:
        self._rec_seq += 1
        now = utc_now_naive()
        defaults: dict[str, Any] = {
            "hashtags_snapshot_json": [],
            "attempt_count": 1,
            "publishing_method": "api",
            "verification_status": "unverified",
            "outcome": "published",
        }
        defaults.update(data)
        row = PublicationRecord(
            id=self._rec_seq, **defaults, created_at=now, updated_at=now
        )
        self._records[row.id] = row
        return row

    def get_record_by_idempotency_key(
        self, idempotency_key: str
    ) -> PublicationRecord | None:
        for row in self._records.values():
            if row.idempotency_key == idempotency_key:
                return row
        return None

    def get_latest_published_for_post(
        self, social_post_id: int
    ) -> PublicationRecord | None:
        rows = [
            r
            for r in self._records.values()
            if r.social_post_id == social_post_id
            and r.outcome in {"published", "manually_published"}
        ]
        rows.sort(key=lambda r: r.id, reverse=True)
        return rows[0] if rows else None

    def get_latest_for_profile(
        self, social_profile_id: int
    ) -> PublicationRecord | None:
        rows = [
            r
            for r in self._records.values()
            if r.social_profile_id == social_profile_id
            and r.outcome in {"published", "manually_published"}
        ]
        rows.sort(key=lambda r: (r.published_at or r.created_at, r.id), reverse=True)
        return rows[0] if rows else None

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
        rows = list(self._records.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if social_profile_id is not None:
            rows = [r for r in rows if r.social_profile_id == social_profile_id]
        if platform_key and platform_key != "all":
            rows = [r for r in rows if r.platform_key == platform_key]
        if outcome and outcome != "all":
            rows = [r for r in rows if r.outcome == outcome]
        if publishing_method and publishing_method != "all":
            rows = [r for r in rows if r.publishing_method == publishing_method]
        if date_from is not None:
            df = date_from.replace(tzinfo=None)
            rows = [r for r in rows if (r.published_at or r.created_at) >= df]
        if date_to is not None:
            dt = date_to.replace(tzinfo=None)
            rows = [r for r in rows if (r.published_at or r.created_at) <= dt]
        rows.sort(key=lambda r: r.id, reverse=True)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def count_published_in_window(
        self,
        *,
        start_utc: datetime,
        end_utc: datetime | None = None,
        website_id: int | None = None,
        platform_id: int | None = None,
    ) -> int:
        s_naive = start_utc.replace(tzinfo=None)
        e_naive = end_utc.replace(tzinfo=None) if end_utc else None
        count = 0
        for r in self._records.values():
            if r.outcome not in {"published", "manually_published"} or r.published_at is None:
                continue
            if r.published_at < s_naive:
                continue
            if e_naive is not None and r.published_at > e_naive:
                continue
            if website_id is not None and r.website_id != website_id:
                continue
            if platform_id is not None and r.platform_id != platform_id:
                continue
            count += 1
        return count

    def count_published_for_profile_since(
        self, social_profile_id: int, since_utc: datetime
    ) -> int:
        s_naive = since_utc.replace(tzinfo=None)
        return sum(
            1
            for r in self._records.values()
            if r.social_profile_id == social_profile_id
            and r.outcome in {"published", "manually_published"}
            and r.published_at is not None
            and r.published_at >= s_naive
        )
