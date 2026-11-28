from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import math
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import BACKEND_ROOT, Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import redact_text
from app.core.security import decrypt_secret
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.platform import Platform
from app.models.publishing import (
    PublicationRecord,
    PublishingJob,
    SocialPostMedia,
    SocialProfileConnection,
)
from app.models.social_post import SocialPost
from app.models.social_profile import SocialProfile
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.ai_repo import AiRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.keyword_approval_repo import KeywordApprovalRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.publishing_repo import PublishingRepositoryProtocol
from app.repositories.social_post_repo import SocialPostRepositoryProtocol
from app.repositories.social_profile_repo import SocialProfileRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.publishing import (
    CalendarEventResponse,
    CalendarResponse,
    CancelScheduleRequest,
    MarkPublishedRequest,
    PreflightCheckItemResponse,
    PublicationRecordResponse,
    PublishingHistoryListResponse,
    PublishingJobListResponse,
    PublishingJobResponse,
    PublishingLogResponse,
    PublishingPreflightResponse,
    PublishingStatisticsResponse,
    PublishNowRequest,
    ReconcileJobRequest,
    SchedulePostRequest,
    SocialPostMediaAttachmentResponse,
    SocialPostMediaUpdateRequest,
)
from app.schemas.social_post import SocialPostResponse
from app.services.ai.response_validator import measure_platform_character_count
from app.services.monitoring.health_service import HealthService
from app.services.publishers.base import PublishMediaInput, PublishRequest
from app.services.publishers.exceptions import PublisherError, VerificationRequiredError
from app.services.publishers.media import (
    prepare_media_for_platform,
    resolve_public_media_base_url,
)
from app.services.publishers.registry import PublisherAdapterRegistry
from app.services.publishers.validator import (
    assemble_publish_caption,
    validate_publish_preflight,
)
from app.services.scanner.security import SafeHttpFetcher
from app.services.settings_service import SettingsService
from app.services.social_post_service import SocialPostService
from app.services.social_profile_service import CREDENTIAL_COLUMN_MAP

PublishJobDispatcher = Callable[[int], None]

STATUS_COLORS: dict[str, str] = {
    "scheduled": "#0d9488",  # teal-600
    "queued": "#0284c7",  # sky-600
    "deferred": "#d97706",  # amber-600
    "publishing": "#4f46e5",  # indigo-600
    "published": "#16a34a",  # green-600
    "manually_published": "#059669",  # emerald-600
    "failed": "#dc2626",  # red-600
    "verification_required": "#ea580c",  # orange-600
    "manual_reminder": "#7c3aed",  # violet-600
    "cancelled": "#64748b",  # slate-500
}


def default_publish_job_dispatcher(job_id: int) -> None:
    """Spawn detached publish CLI worker (`python -m app.cli run-publish-job --job-id <id>`)."""
    cfg = Settings()
    log_file = None
    with contextlib.suppress(OSError):
        log_dir = cfg.resolved_storage_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = (log_dir / "publishing-worker.log").open("ab")

    try:
        subprocess.Popen(
            [sys.executable, "-m", "app.cli", "run-publish-job", "--job-id", str(job_id)],
            cwd=str(BACKEND_ROOT),
            stdout=log_file if log_file is not None else subprocess.DEVNULL,
            stderr=log_file if log_file is not None else subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        if log_file is not None:
            with contextlib.suppress(OSError):
                log_file.close()


class PublishingService:
    """Orchestrates preflight validation, durable MySQL publishing jobs, scheduling & history."""

    def __init__(
        self,
        *,
        settings: Settings,
        publishing_repo: PublishingRepositoryProtocol,
        social_post_repo: SocialPostRepositoryProtocol,
        social_profile_repo: SocialProfileRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        health_service: HealthService,
        settings_service: SettingsService,
        adapter_registry: PublisherAdapterRegistry,
        social_post_service: SocialPostService,
        keyword_approval_repo: KeywordApprovalRepositoryProtocol | None = None,
        ai_repo: AiRepositoryProtocol | None = None,
        fetcher: SafeHttpFetcher | None = None,
        dispatcher: PublishJobDispatcher | None = None,
    ) -> None:
        self.settings = settings
        self.pub_repo = publishing_repo
        self.post_repo = social_post_repo
        self.profile_repo = social_profile_repo
        self.website_repo = website_repo
        self.content_repo = content_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo
        self.health_service = health_service
        self.settings_service = settings_service
        self.registry = adapter_registry
        self.post_service = social_post_service
        self.keyword_repo = keyword_approval_repo
        self.ai_repo = ai_repo
        self.fetcher = fetcher
        self.dispatcher = dispatcher or default_publish_job_dispatcher

    def _decrypt_credentials(self, profile: SocialProfile) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for fname, col in CREDENTIAL_COLUMN_MAP.items():
            raw = getattr(profile, col, None)
            out[fname] = decrypt_secret(raw, self.settings.app_encryption_key) if raw else None
        return out

    def _effective_timezone(self, profile: SocialProfile | None = None) -> str:
        if profile and profile.display_timezone:
            return profile.display_timezone
        eff = self.settings_service.get_effective_map()
        return str(eff.get("app.timezone", self.settings.app_timezone))

    def _format_local_iso(self, dt_utc: datetime | None, tz_name: str) -> str:
        base = ensure_utc(dt_utc) or utc_now()
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("Asia/Manila")
        return base.astimezone(tz).isoformat()

    def _compute_dedupe_key(self, post: SocialPost, revision_id: int | None) -> str:
        raw = f"{post.id}:{post.social_profile_id}:{revision_id or post.current_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _build_media_attachment_response(
        self,
        row: SocialPostMedia,
    ) -> SocialPostMediaAttachmentResponse:
        asset = self.media_repo.get_by_id(row.media_asset_id)
        preview_url = None
        if asset is not None:
            preview_url = (
                f"/api/v1/media/{asset.id}/file" if asset.file_path else asset.source_url
            )
        pub_base = resolve_public_media_base_url(self.settings)
        pub_url = (
            f"{pub_base}/api/v1/public-media/{row.public_media_token}"
            if (pub_base and row.public_media_token)
            else (
                asset.source_url
                if asset and (asset.source_url or "").startswith("https://")
                else None
            )
        )
        return SocialPostMediaAttachmentResponse(
            id=row.id,
            social_post_id=row.social_post_id,
            media_asset_id=row.media_asset_id,
            sort_order=row.sort_order,
            role=row.role,
            alt_text=row.alt_text or (asset.alt_text if asset else None),
            file_name=asset.file_name if asset else None,
            preview_url=preview_url,
            public_url=pub_url,
            mime_type=asset.mime_type if asset else None,
            width=asset.width if asset else None,
            height=asset.height if asset else None,
            file_size=asset.file_size if asset else None,
            is_prepared=row.is_prepared,
            prepared_mime_type=row.prepared_mime_type,
            prepared_width=row.prepared_width,
            prepared_height=row.prepared_height,
            prepared_file_size=row.prepared_file_size,
        )

    def list_post_media(self, post_id: int) -> list[SocialPostMediaAttachmentResponse]:
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        rows = self.pub_repo.list_post_media(post_id)
        if not rows and post.featured_media_id is not None:
            asset = self.media_repo.get_by_id(post.featured_media_id)
            if asset is not None:
                return [
                    SocialPostMediaAttachmentResponse(
                        id=0,
                        social_post_id=post.id,
                        media_asset_id=asset.id,
                        sort_order=0,
                        role="primary",
                        alt_text=asset.alt_text,
                        file_name=asset.file_name,
                        preview_url=(
                            f"/api/v1/media/{asset.id}/file"
                            if asset.file_path
                            else asset.source_url
                        ),
                        public_url=asset.source_url,
                        mime_type=asset.mime_type,
                        width=asset.width,
                        height=asset.height,
                        file_size=asset.file_size,
                        is_prepared=False,
                    )
                ]
        return [self._build_media_attachment_response(r) for r in rows]

    def update_post_media(
        self,
        post_id: int,
        payload: SocialPostMediaUpdateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> list[SocialPostMediaAttachmentResponse]:
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        items_payload: list[dict[str, Any]] = []
        for idx, item in enumerate(payload.attachments):
            asset = self.media_repo.get_by_id(item.media_asset_id)
            if asset is None:
                raise NotFoundError(f"Media asset #{item.media_asset_id} not found.")
            if asset.website_id is not None and asset.website_id != post.website_id:
                raise ValidationAppError(
                    "Cannot attach media asset belonging to a different website."
                )
            items_payload.append(
                {
                    "media_asset_id": asset.id,
                    "sort_order": item.sort_order if item.sort_order is not None else idx,
                    "role": item.role.strip() or ("primary" if idx == 0 else "carousel"),
                    "alt_text": item.alt_text.strip()[:255] if item.alt_text else None,
                    "is_prepared": False,
                }
            )
        rows = self.pub_repo.replace_post_media(post.id, items_payload)
        first_asset_id = rows[0].media_asset_id if rows else None
        if post.featured_media_id != first_asset_id:
            patch: dict[str, Any] = {"featured_media_id": first_asset_id}
            if post.status == "approved":
                patch["status"] = "pending_review"
                patch["approved_by"] = None
                patch["approved_at"] = None
                patch["approved_revision_id"] = None
                patch["publishing_status"] = "pending_approval"
            self.post_repo.update_post(
                post.id,
                patch,
                create_revision=True,
                change_type="media_updated",
                edited_by=user_id,
                notes="Updated social media attachments",
            )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_posts",
            action="social_post.media_updated",
            level="info",
            message=f"Updated {len(rows)} attachment(s) for social draft #{post.id}.",
            metadata={"social_post_id": post.id},
            ip_address=ip_address,
        )
        return [self._build_media_attachment_response(r) for r in rows]

    def _gather_preflight_context(self, post: SocialPost) -> dict[str, Any]:
        website = self.website_repo.get_by_id(post.website_id)
        profile = self.profile_repo.get_by_id(post.social_profile_id)
        platform = self.profile_repo.get_platform_by_id(post.platform_id)
        connection = (
            self.pub_repo.get_connection_by_profile_id(profile.id) if profile else None
        )
        content_approval = (
            self.keyword_repo.get_approval_by_content_id(post.website_content_id)
            if (post.website_content_id and self.keyword_repo is not None)
            else None
        )
        content_keyword = (
            self.keyword_repo.get_keyword_by_content_id(post.website_content_id)
            if (post.website_content_id and self.keyword_repo is not None)
            else None
        )
        media_rows = self.pub_repo.list_post_media(post.id)
        existing_pub = self.pub_repo.get_latest_published_for_post(post.id)
        active_job = self.pub_repo.get_active_job_for_post(post.id)
        now = utc_now_naive()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = (
            self.pub_repo.count_published_for_profile_since(profile.id, day_start)
            if profile
            else 0
        )
        latest_profile_pub = (
            self.pub_repo.get_latest_for_profile(profile.id) if profile else None
        )
        return {
            "website": website,
            "profile": profile,
            "platform": platform,
            "connection": connection,
            "content_approval": content_approval,
            "content_keyword": content_keyword,
            "media_rows": media_rows,
            "existing_pub": existing_pub,
            "active_job": active_job,
            "daily_count": daily_count,
            "latest_profile_pub": latest_profile_pub,
        }

    def preflight_post(
        self, post_id: int, *, confirm_paid_api: bool = False
    ) -> PublishingPreflightResponse:
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        ctx = self._gather_preflight_context(post)
        res = validate_publish_preflight(
            website=ctx["website"],
            post=post,
            profile=ctx["profile"],
            platform=ctx["platform"],
            connection=ctx["connection"],
            content_approval=ctx["content_approval"],
            content_keyword=ctx["content_keyword"],
            media_rows=ctx["media_rows"],
            existing_published_record=ctx["existing_pub"],
            active_job=ctx["active_job"],
            daily_published_count=ctx["daily_count"],
            latest_profile_publication=ctx["latest_profile_pub"],
            confirm_paid_api=confirm_paid_api,
        )
        profile: SocialProfile | None = ctx["profile"]
        platform: Platform | None = ctx["platform"]
        conn: SocialProfileConnection | None = ctx["connection"]
        assembled = assemble_publish_caption(post)
        char_count = (
            measure_platform_character_count(assembled, platform)
            if platform is not None
            else len(assembled)
        )
        char_limit = (
            profile.character_limit
            if profile and profile.character_limit is not None
            else (platform.default_max_chars if platform else None)
        )
        return PublishingPreflightResponse(
            social_post_id=post.id,
            ready=res.ok,
            platform_key=platform.platform_key if platform else "custom_social",
            publishing_method=profile.publishing_method if profile else "manual",
            destination_name=profile.profile_name if profile else "Unknown profile",
            destination_target=conn.target_resource_name if conn else None,
            assembled_content=assembled,
            character_count=char_count,
            character_limit=char_limit,
            checks=[PreflightCheckItemResponse(**c) for c in res.checks],
            errors=res.errors,
            warnings=res.warnings,
            media=self.list_post_media(post.id),
        )

    def _to_job_response(self, job: PublishingJob) -> PublishingJobResponse:
        now = utc_now()
        site = self.website_repo.get_by_id(job.website_id)
        prof = (
            self.profile_repo.get_by_id(job.social_profile_id)
            if job.social_profile_id
            else None
        )
        return PublishingJobResponse(
            id=job.id,
            job_uuid=job.job_uuid,
            idempotency_key=job.idempotency_key,
            website_id=job.website_id,
            website_name=site.name if site else None,
            social_profile_id=job.social_profile_id,
            profile_name=prof.profile_name if prof else None,
            social_post_id=job.social_post_id,
            publishing_schedule_id=job.publishing_schedule_id,
            approved_revision_id=job.approved_revision_id,
            platform_key=job.platform_key,
            publishing_method=job.publishing_method,
            status=job.status,
            priority=job.priority,
            scheduled_at=ensure_utc(job.scheduled_at),
            available_at=ensure_utc(job.available_at) or now,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            next_retry_at=ensure_utc(job.next_retry_at),
            worker_id=job.worker_id,
            heartbeat_at=ensure_utc(job.heartbeat_at),
            requires_verification=job.requires_verification,
            external_post_id=job.external_post_id,
            published_url=job.published_url,
            error_category=job.error_category,
            error_message=job.error_message,
            paused_reason=job.paused_reason,
            started_at=ensure_utc(job.started_at),
            completed_at=ensure_utc(job.completed_at),
            created_at=ensure_utc(job.created_at) or now,
            updated_at=ensure_utc(job.updated_at) or now,
        )

    def publish_now(
        self,
        post_id: int,
        payload: PublishNowRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> PublishingJobResponse:
        if not payload.confirm:
            raise ValidationAppError(
                "Explicit confirmation (confirm=true) is required before immediate "
                "external publishing."
            )
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        ctx = self._gather_preflight_context(post)
        profile: SocialProfile | None = ctx["profile"]
        platform: Platform | None = ctx["platform"]
        res = validate_publish_preflight(
            website=ctx["website"],
            post=post,
            profile=profile,
            platform=platform,
            connection=ctx["connection"],
            content_approval=ctx["content_approval"],
            content_keyword=ctx["content_keyword"],
            media_rows=ctx["media_rows"],
            existing_published_record=ctx["existing_pub"],
            active_job=ctx["active_job"],
            daily_published_count=ctx["daily_count"],
            latest_profile_publication=ctx["latest_profile_pub"],
            target_method="api",
            confirm_paid_api=payload.confirm_paid_api,
        )
        if not res.ok:
            if ctx["existing_pub"] is not None or ctx["active_job"] is not None:
                raise ConflictError(res.errors[0])
            raise ValidationAppError("; ".join(res.errors))
        assert profile is not None and platform is not None

        if profile.publishing_method == "manual":
            raise ValidationAppError(
                "This profile is configured for Manual Publishing. Use Copy + Mark as Published."
            )

        revs = self.post_repo.list_revisions(post.id)
        approved_rev_id = post.approved_revision_id or (revs[0].id if revs else None)
        dedupe_key = self._compute_dedupe_key(post, approved_rev_id)
        idem_key = f"pub:{post.id}:{approved_rev_id or 0}:{uuid.uuid4().hex[:12]}"
        now = utc_now_naive()

        job = self.pub_repo.create_job(
            {
                "job_uuid": str(uuid.uuid4()),
                "idempotency_key": idem_key,
                "publish_dedupe_key": dedupe_key,
                "website_id": post.website_id,
                "social_profile_id": profile.id,
                "social_post_id": post.id,
                "approved_revision_id": approved_rev_id,
                "platform_key": platform.platform_key,
                "publishing_method": "api",
                "status": "queued",
                "priority": 1,
                "available_at": now,
                "max_attempts": self.settings.publishing_max_attempts,
                "timeout_seconds": self.settings.publishing_request_timeout_seconds,
                "payload_json": {"confirm_paid_api": payload.confirm_paid_api},
                "created_by": user_id,
            }
        )
        self.post_repo.update_post(
            post.id,
            {
                "publishing_status": "queued",
                "approved_revision_id": approved_rev_id,
                "last_publish_error": None,
            },
            create_revision=False,
        )
        self.pub_repo.create_log(
            {
                "publishing_job_id": job.id,
                "website_id": post.website_id,
                "social_profile_id": profile.id,
                "social_post_id": post.id,
                "platform_key": platform.platform_key,
                "attempt_number": 0,
                "action": "preflight",
                "outcome": "succeeded",
                "actor_user_id": user_id,
                "response_summary_json": {"mode": "publish_now", "idempotency_key": idem_key},
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="publishing",
            action="publishing.enqueued",
            level="info",
            message=(
                f"Queued immediate {platform.display_name} publish job #{job.id} "
                f"for post #{post.id}."
            ),
            metadata={"publishing_job_id": job.id, "social_post_id": post.id},
            ip_address=ip_address,
        )
        self.dispatcher(job.id)
        return self._to_job_response(job)

    def schedule_post(
        self,
        post_id: int,
        payload: SchedulePostRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialPostResponse:
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        ctx = self._gather_preflight_context(post)
        profile: SocialProfile | None = ctx["profile"]
        platform: Platform | None = ctx["platform"]
        # Allow rescheduling existing scheduled post cleanly by excluding own queued job check
        active_job = ctx["active_job"]
        check_active_job = (
            active_job
            if active_job and active_job.status in {"processing", "verification_required"}
            else None
        )
        res = validate_publish_preflight(
            website=ctx["website"],
            post=post,
            profile=profile,
            platform=platform,
            connection=ctx["connection"],
            content_approval=ctx["content_approval"],
            content_keyword=ctx["content_keyword"],
            media_rows=ctx["media_rows"],
            existing_published_record=ctx["existing_pub"],
            active_job=check_active_job,
            target_method=profile.publishing_method if profile else "manual",
            confirm_paid_api=payload.confirm_paid_api,
        )
        if not res.ok:
            raise ValidationAppError("; ".join(res.errors))
        assert profile is not None and platform is not None

        tz_name = (payload.display_timezone or self._effective_timezone(profile)).strip()
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError as exc:
            raise ValidationAppError(f"Invalid IANA timezone '{tz_name}'.") from exc

        sched_dt = payload.scheduled_at
        if sched_dt.tzinfo is None:
            sched_utc = sched_dt.replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
        else:
            sched_utc = sched_dt.astimezone(UTC).replace(tzinfo=None)

        if sched_utc < utc_now_naive() - timedelta(minutes=2):
            raise ValidationAppError("Scheduled time must be in the present or future.")

        revs = self.post_repo.list_revisions(post.id)
        approved_rev_id = post.approved_revision_id or (revs[0].id if revs else None)

        existing_scheds = self.pub_repo.list_active_schedules_for_post(post.id)
        if existing_scheds:
            sched = existing_scheds[0]
            sched = self.pub_repo.update_schedule(
                sched.id,
                {
                    "scheduled_at": sched_utc,
                    "display_timezone": tz_name,
                    "approved_revision_id": approved_rev_id,
                    "rescheduled_count": sched.rescheduled_count + 1,
                    "status": "scheduled",
                },
            ) or sched
        else:
            sched = self.pub_repo.create_schedule(
                {
                    "website_id": post.website_id,
                    "social_profile_id": profile.id,
                    "social_post_id": post.id,
                    "platform_key": platform.platform_key,
                    "approved_revision_id": approved_rev_id,
                    "scheduled_at": sched_utc,
                    "display_timezone": tz_name,
                    "status": "scheduled",
                    "created_by": user_id,
                }
            )

        if profile.publishing_method == "api":
            if active_job and active_job.status in {"queued", "deferred"}:
                self.pub_repo.update_job(
                    active_job.id,
                    {
                        "publishing_schedule_id": sched.id,
                        "scheduled_at": sched_utc,
                        "available_at": sched_utc,
                        "next_retry_at": None,
                        "approved_revision_id": approved_rev_id,
                    },
                )
            else:
                self.pub_repo.create_job(
                    {
                        "job_uuid": str(uuid.uuid4()),
                        "idempotency_key": f"sched:{post.id}:{sched.id}:{uuid.uuid4().hex[:8]}",
                        "publish_dedupe_key": self._compute_dedupe_key(post, approved_rev_id),
                        "website_id": post.website_id,
                        "social_profile_id": profile.id,
                        "social_post_id": post.id,
                        "publishing_schedule_id": sched.id,
                        "approved_revision_id": approved_rev_id,
                        "platform_key": platform.platform_key,
                        "publishing_method": "api",
                        "status": "queued",
                        "priority": 5,
                        "scheduled_at": sched_utc,
                        "available_at": sched_utc,
                        "max_attempts": self.settings.publishing_max_attempts,
                        "timeout_seconds": self.settings.publishing_request_timeout_seconds,
                        "payload_json": {"confirm_paid_api": payload.confirm_paid_api},
                        "created_by": user_id,
                    }
                )

        updated = self.post_repo.update_post(
            post.id,
            {
                "publishing_status": "scheduled",
                "approved_revision_id": approved_rev_id,
                "scheduled_for": sched_utc,
                "display_timezone": tz_name,
                "last_publish_error": None,
            },
            create_revision=False,
        )
        assert updated is not None
        self.pub_repo.create_log(
            {
                "website_id": post.website_id,
                "social_profile_id": profile.id,
                "social_post_id": post.id,
                "platform_key": platform.platform_key,
                "attempt_number": 0,
                "action": "schedule",
                "outcome": "succeeded",
                "actor_user_id": user_id,
                "response_summary_json": {
                    "schedule_id": sched.id,
                    "scheduled_utc": sched_utc.isoformat() + "Z",
                    "display_timezone": tz_name,
                },
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="publishing",
            action="publishing.scheduled",
            level="info",
            message=(
                f"Scheduled {platform.display_name} post #{post.id} "
                f"for {sched_utc.isoformat()}Z."
            ),
            metadata={"social_post_id": post.id, "schedule_id": sched.id},
            ip_address=ip_address,
        )
        return self.post_service.to_response(updated)

    def cancel_schedule(
        self,
        post_id: int,
        payload: CancelScheduleRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialPostResponse:
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        active_job = self.pub_repo.get_active_job_for_post(post.id)
        if active_job and active_job.status == "processing":
            raise ConflictError("Cannot cancel schedule while a worker is actively publishing.")

        for sched in self.pub_repo.list_active_schedules_for_post(post.id):
            self.pub_repo.update_schedule(
                sched.id,
                {
                    "status": "cancelled",
                    "cancel_reason": (payload.reason or "Cancelled by administrator")[:500],
                },
            )
        if active_job and active_job.status in {"queued", "deferred"}:
            self.pub_repo.update_job(
                active_job.id,
                {
                    "status": "cancelled",
                    "error_message": (payload.reason or "Schedule cancelled")[:500],
                    "completed_at": utc_now_naive(),
                },
            )
        updated = self.post_repo.update_post(
            post.id,
            {
                "publishing_status": "approved" if post.status == "approved" else "cancelled",
                "scheduled_for": None,
            },
            create_revision=False,
        )
        assert updated is not None
        plat = self.profile_repo.get_platform_by_id(post.platform_id)
        self.pub_repo.create_log(
            {
                "website_id": post.website_id,
                "social_profile_id": post.social_profile_id,
                "social_post_id": post.id,
                "platform_key": plat.platform_key if plat else "custom_social",
                "attempt_number": 0,
                "action": "cancel",
                "outcome": "cancelled",
                "actor_user_id": user_id,
                "response_summary_json": {"reason": payload.reason},
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="publishing",
            action="publishing.schedule_cancelled",
            level="info",
            message=f"Cancelled schedule for social post #{post.id}.",
            metadata={"social_post_id": post.id},
            ip_address=ip_address,
        )
        return self.post_service.to_response(updated)

    def mark_manually_published(
        self,
        post_id: int,
        payload: MarkPublishedRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialPostResponse:
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        if post.status != "approved":
            raise ValidationAppError("Approve the social draft before marking it as published.")
        if post.publishing_status in {"published", "manually_published"}:
            raise ConflictError("Social draft is already recorded as published.")

        raw_url = payload.published_url.strip()
        if not raw_url.startswith(("http://", "https://")):
            raise ValidationAppError("Published URL must be a valid http:// or https:// link.")

        pub_dt = (
            payload.published_at.astimezone(UTC).replace(tzinfo=None)
            if payload.published_at and payload.published_at.tzinfo
            else (payload.published_at or utc_now_naive())
        )
        site = self.website_repo.get_by_id(post.website_id)
        profile = self.profile_repo.get_by_id(post.social_profile_id)
        platform = self.profile_repo.get_platform_by_id(post.platform_id)
        content = (
            self.content_repo.get_by_id(post.website_content_id)
            if post.website_content_id
            else None
        )

        # Cancel any pending schedule/job cleanly
        for sched in self.pub_repo.list_active_schedules_for_post(post.id):
            self.pub_repo.update_schedule(sched.id, {"status": "manually_published"})
        active_job = self.pub_repo.get_active_job_for_post(post.id)
        if active_job and active_job.status in {"queued", "deferred"}:
            self.pub_repo.update_job(
                active_job.id,
                {"status": "cancelled", "completed_at": pub_dt},
            )

        revs = self.post_repo.list_revisions(post.id)
        approved_rev_id = post.approved_revision_id or (revs[0].id if revs else None)
        ext_id = payload.external_post_id.strip()[:255] if payload.external_post_id else None

        updated = self.post_repo.update_post(
            post.id,
            {
                "publishing_status": "manually_published",
                "verification_status": "self_reported",
                "published_at": pub_dt,
                "published_url": raw_url[:1000],
                "external_post_id": ext_id,
                "last_publish_error": None,
            },
            create_revision=False,
        )
        assert updated is not None
        if profile is not None:
            self.profile_repo.update(profile.id, {"last_published_at": pub_dt})

        self.pub_repo.create_record(
            {
                "website_id": post.website_id,
                "website_name_snapshot": site.name if site else f"Website #{post.website_id}",
                "social_profile_id": profile.id if profile else None,
                "profile_name_snapshot": (
                    profile.profile_name if profile else f"Profile #{post.social_profile_id}"
                ),
                "platform_id": post.platform_id,
                "platform_key": platform.platform_key if platform else "custom_social",
                "platform_display_name": platform.display_name if platform else "Custom",
                "social_post_id": post.id,
                "website_content_id": post.website_content_id,
                "source_title_snapshot": content.title if content else post.title,
                "approved_revision_id": approved_rev_id,
                "approved_version_number": post.current_version,
                "publishing_method": "manual",
                "verification_status": "self_reported",
                "outcome": "manually_published",
                "idempotency_key": f"manual:{post.id}:{uuid.uuid4().hex[:12]}",
                "scheduled_at": post.scheduled_for,
                "published_at": pub_dt,
                "external_post_id": ext_id,
                "published_url": raw_url[:1000],
                "caption_snapshot": post.assembled_content,
                "hashtags_snapshot_json": list(post.hashtags_json or []),
                "source_url": post.target_url_with_utm or post.source_url,
                "attempt_count": 1,
                "recorded_by": user_id,
            }
        )
        self.pub_repo.create_log(
            {
                "website_id": post.website_id,
                "social_profile_id": post.social_profile_id,
                "social_post_id": post.id,
                "platform_key": platform.platform_key if platform else "custom_social",
                "attempt_number": 1,
                "action": "manual_record",
                "outcome": "manual_recorded",
                "external_post_id": ext_id,
                "published_url": raw_url[:1000],
                "actor_user_id": user_id,
                "response_summary_json": {"notes": payload.notes},
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="publishing",
            action="publishing.manually_published",
            level="info",
            message=f"Recorded manual publication for social post #{post.id}.",
            metadata={"social_post_id": post.id, "published_url": raw_url[:1000]},
            ip_address=ip_address,
        )
        return self.post_service.to_response(updated)

    def _prepare_media_inputs(
        self,
        *,
        post: SocialPost,
        platform_key: str,
        requires_external_url: bool,
    ) -> list[PublishMediaInput]:
        attachments = self.pub_repo.list_post_media(post.id)
        if not attachments and post.featured_media_id is not None:
            attachments = [
                self.pub_repo.add_post_media(
                    {
                        "social_post_id": post.id,
                        "media_asset_id": post.featured_media_id,
                        "sort_order": 0,
                        "role": "primary",
                    }
                )
            ]
        prepared_inputs: list[PublishMediaInput] = []
        for att in attachments:
            asset = self.media_repo.get_by_id(att.media_asset_id)
            if asset is None:
                continue
            updates, media_in = prepare_media_for_platform(
                settings=self.settings,
                platform_key=platform_key,
                post_id=post.id,
                attachment=att,
                asset=asset,
                fetcher=self.fetcher,
                requires_external_url=requires_external_url,
            )
            self.pub_repo.update_post_media(att.id, updates)
            prepared_inputs.append(media_in)
        return prepared_inputs

    def execute_job(
        self, job_id: int, *, worker_id: str | None = None
    ) -> PublishingJobResponse:
        self.pub_repo.recover_stale_jobs(
            stale_minutes=self.settings.publishing_stale_timeout_minutes
        )
        existing_job = self.pub_repo.get_job_by_id(job_id)
        if existing_job is None:
            raise NotFoundError(f"Publishing job #{job_id} not found.")

        eff_map = self.settings_service.get_effective_map()
        resources = self.health_service.get_system_resources(effective_settings=eff_map)
        if resources.guardian_status == "critical":
            deferred = self.pub_repo.update_job(
                existing_job.id,
                {
                    "status": "deferred",
                    "paused_reason": "Resource Guardian critical pressure; deferred publishing.",
                    "next_retry_at": utc_now_naive()
                    + timedelta(minutes=self.settings.resource_recheck_interval_minutes),
                },
            )
            assert deferred is not None
            self.post_repo.update_post(
                deferred.social_post_id, {"publishing_status": "deferred"}
            )
            return self._to_job_response(deferred)

        if self.pub_repo.count_processing_jobs() >= self.settings.publishing_max_concurrent_jobs:
            return self._to_job_response(existing_job)

        claimed = self.pub_repo.claim_job(
            job_id, worker_id=worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        )
        if claimed is None:
            latest = self.pub_repo.get_job_by_id(job_id)
            assert latest is not None
            return self._to_job_response(latest)

        post = self.post_repo.get_by_id(claimed.social_post_id)
        if post is None:
            failed = self.pub_repo.update_job(
                claimed.id,
                {
                    "status": "failed",
                    "error_category": "rejected_content",
                    "error_message": "Associated social post no longer exists.",
                    "completed_at": utc_now_naive(),
                },
            )
            assert failed is not None
            return self._to_job_response(failed)

        # Duplicate check & re-validation immediately before execution (Section 14 & 20)
        prior_pub = self.pub_repo.get_latest_published_for_post(post.id)
        if prior_pub is not None:
            aborted = self.pub_repo.update_job(
                claimed.id,
                {
                    "status": "cancelled",
                    "error_message": "Aborted duplicate publish: already recorded in history.",
                    "external_post_id": prior_pub.external_post_id,
                    "published_url": prior_pub.published_url,
                    "completed_at": utc_now_naive(),
                },
            )
            assert aborted is not None
            return self._to_job_response(aborted)

        ctx = self._gather_preflight_context(post)
        profile: SocialProfile | None = ctx["profile"]
        platform: Platform | None = ctx["platform"]
        conn: SocialProfileConnection | None = ctx["connection"]
        confirm_paid = bool((claimed.payload_json or {}).get("confirm_paid_api"))
        res = validate_publish_preflight(
            website=ctx["website"],
            post=post,
            profile=profile,
            platform=platform,
            connection=conn,
            content_approval=ctx["content_approval"],
            content_keyword=ctx["content_keyword"],
            media_rows=ctx["media_rows"],
            existing_published_record=None,
            active_job=None,
            daily_published_count=ctx["daily_count"],
            latest_profile_publication=ctx["latest_profile_pub"],
            target_method=claimed.publishing_method,
            confirm_paid_api=confirm_paid,
        )
        if not res.ok or profile is None or platform is None:
            err_msg = "; ".join(res.errors) or "Pre-publish revalidation failed."
            return self._mark_job_failed(
                claimed=claimed,
                post=post,
                profile=profile,
                platform=platform,
                category="policy_restriction",
                message=err_msg,
                http_status=None,
            )

        self.post_repo.update_post(
            post.id,
            {"publishing_status": "publishing", "last_publish_attempt_at": utc_now_naive()},
        )
        if claimed.publishing_schedule_id:
            self.pub_repo.update_schedule(claimed.publishing_schedule_id, {"status": "publishing"})

        adapter = self.registry.get(
            platform.platform_key, publishing_method=claimed.publishing_method
        )
        creds = self._decrypt_credentials(profile)
        try:
            media_inputs = self._prepare_media_inputs(
                post=post,
                platform_key=platform.platform_key,
                requires_external_url=adapter.capabilities.requires_external_media_url,
            )
            pub_req = PublishRequest(
                social_post_id=post.id,
                social_profile_id=profile.id,
                website_id=post.website_id,
                platform_key=platform.platform_key,
                idempotency_key=claimed.idempotency_key,
                title=post.title,
                caption=post.caption,
                assembled_content=assemble_publish_caption(post),
                source_url=post.target_url_with_utm or post.source_url,
                cta_text=post.cta_text,
                target_resource_id=conn.target_resource_id if conn else profile.external_account_id,
                external_account_id=profile.external_account_id,
                scheduled_for_utc=claimed.scheduled_at,
                credentials=creds,
                media=media_inputs,
                metadata={
                    "allow_paid_publishing": bool(conn.allow_paid_publishing) if conn else False
                },
            )
            pub_res = adapter.publish_post(pub_req)
        except VerificationRequiredError as exc:
            return self._mark_verification_required(
                claimed=claimed,
                post=post,
                profile=profile,
                platform=platform,
                exc=exc,
            )
        except PublisherError as exc:
            if exc.retryable and claimed.attempt_count < claimed.max_attempts:
                delay = exc.retry_after_seconds or min(
                    900, 30 * (2 ** max(0, claimed.attempt_count - 1))
                )
                deferred = self.pub_repo.update_job(
                    claimed.id,
                    {
                        "status": "deferred",
                        "paused_reason": redact_text(exc.message)[:255],
                        "error_category": exc.error_category,
                        "error_message": exc.message[:500],
                        "next_retry_at": utc_now_naive() + timedelta(seconds=delay),
                        "worker_id": None,
                        "locked_at": None,
                    },
                )
                self.post_repo.update_post(
                    post.id,
                    {"publishing_status": "deferred", "last_publish_error": exc.message[:500]},
                )
                if claimed.publishing_schedule_id:
                    self.pub_repo.update_schedule(
                        claimed.publishing_schedule_id, {"status": "deferred"}
                    )
                self.pub_repo.create_log(
                    {
                        "publishing_job_id": claimed.id,
                        "website_id": post.website_id,
                        "social_profile_id": profile.id,
                        "social_post_id": post.id,
                        "platform_key": platform.platform_key,
                        "attempt_number": claimed.attempt_count,
                        "action": "publish",
                        "outcome": "deferred",
                        "http_status": exc.http_status,
                        "error_category": exc.error_category,
                        "error_message": exc.message[:500],
                    }
                )
                assert deferred is not None
                return self._to_job_response(deferred)
            return self._mark_job_failed(
                claimed=claimed,
                post=post,
                profile=profile,
                platform=platform,
                category=exc.error_category,
                message=exc.message,
                http_status=exc.http_status,
            )

        return self._record_publish_success(
            claimed=claimed,
            post=post,
            profile=profile,
            platform=platform,
            ext_id=pub_res.external_post_id,
            pub_url=pub_res.published_url,
            http_status=pub_res.http_status,
            verification_status=pub_res.verification_status,
            summary=pub_res.response_summary,
        )

    def _record_publish_success(
        self,
        *,
        claimed: PublishingJob,
        post: SocialPost,
        profile: SocialProfile,
        platform: Platform,
        ext_id: str | None,
        pub_url: str | None,
        http_status: int | None,
        verification_status: str,
        summary: dict[str, Any],
    ) -> PublishingJobResponse:
        now = utc_now_naive()
        site = self.website_repo.get_by_id(post.website_id)
        content = (
            self.content_repo.get_by_id(post.website_content_id)
            if post.website_content_id
            else None
        )
        done = self.pub_repo.update_job(
            claimed.id,
            {
                "status": "published",
                "requires_verification": False,
                "external_post_id": ext_id,
                "published_url": pub_url,
                "error_category": None,
                "error_message": None,
                "result_json": summary,
                "completed_at": now,
                "worker_id": None,
                "locked_at": None,
            },
        )
        if claimed.publishing_schedule_id:
            self.pub_repo.update_schedule(claimed.publishing_schedule_id, {"status": "published"})
        self.post_repo.update_post(
            post.id,
            {
                "publishing_status": "published",
                "verification_status": verification_status,
                "published_at": now,
                "external_post_id": ext_id,
                "published_url": pub_url,
                "last_publish_error": None,
            },
        )
        self.profile_repo.update(profile.id, {"last_published_at": now})
        if self.pub_repo.get_record_by_idempotency_key(claimed.idempotency_key) is None:
            self.pub_repo.create_record(
                {
                    "website_id": post.website_id,
                    "website_name_snapshot": site.name if site else f"Website #{post.website_id}",
                    "social_profile_id": profile.id,
                    "profile_name_snapshot": profile.profile_name,
                    "platform_id": platform.id,
                    "platform_key": platform.platform_key,
                    "platform_display_name": platform.display_name,
                    "social_post_id": post.id,
                    "website_content_id": post.website_content_id,
                    "source_title_snapshot": content.title if content else post.title,
                    "approved_revision_id": claimed.approved_revision_id,
                    "approved_version_number": post.current_version,
                    "publishing_job_id": claimed.id,
                    "publishing_method": claimed.publishing_method,
                    "verification_status": verification_status,
                    "outcome": "published",
                    "idempotency_key": claimed.idempotency_key,
                    "scheduled_at": claimed.scheduled_at,
                    "published_at": now,
                    "external_post_id": ext_id,
                    "published_url": pub_url,
                    "caption_snapshot": post.assembled_content,
                    "hashtags_snapshot_json": list(post.hashtags_json or []),
                    "source_url": post.target_url_with_utm or post.source_url,
                    "attempt_count": claimed.attempt_count,
                    "last_http_status": http_status,
                    "recorded_by": claimed.created_by,
                }
            )
        self.pub_repo.create_log(
            {
                "publishing_job_id": claimed.id,
                "website_id": post.website_id,
                "social_profile_id": profile.id,
                "social_post_id": post.id,
                "platform_key": platform.platform_key,
                "attempt_number": claimed.attempt_count,
                "action": "publish",
                "outcome": "succeeded",
                "http_status": http_status,
                "external_post_id": ext_id,
                "published_url": pub_url,
                "response_summary_json": summary,
            }
        )
        assert done is not None
        return self._to_job_response(done)

    def _mark_verification_required(
        self,
        *,
        claimed: PublishingJob,
        post: SocialPost,
        profile: SocialProfile,
        platform: Platform,
        exc: VerificationRequiredError,
    ) -> PublishingJobResponse:
        job = self.pub_repo.update_job(
            claimed.id,
            {
                "status": "verification_required",
                "requires_verification": True,
                "error_category": "unknown_result",
                "error_message": exc.message[:500],
                "worker_id": None,
                "locked_at": None,
            },
        )
        self.post_repo.update_post(
            post.id,
            {
                "publishing_status": "verification_required",
                "verification_status": "verification_required",
                "last_publish_error": exc.message[:500],
            },
        )
        if claimed.publishing_schedule_id:
            self.pub_repo.update_schedule(
                claimed.publishing_schedule_id, {"status": "verification_required"}
            )
        self.pub_repo.create_log(
            {
                "publishing_job_id": claimed.id,
                "website_id": post.website_id,
                "social_profile_id": profile.id,
                "social_post_id": post.id,
                "platform_key": platform.platform_key,
                "attempt_number": claimed.attempt_count,
                "action": "publish",
                "outcome": "ambiguous",
                "http_status": exc.http_status,
                "error_category": "unknown_result",
                "error_message": exc.message[:500],
            }
        )
        assert job is not None
        return self._to_job_response(job)

    def _mark_job_failed(
        self,
        *,
        claimed: PublishingJob,
        post: SocialPost,
        profile: SocialProfile | None,
        platform: Platform | None,
        category: str,
        message: str,
        http_status: int | None,
    ) -> PublishingJobResponse:
        now = utc_now_naive()
        safe_msg = redact_text(message)[:500]
        job = self.pub_repo.update_job(
            claimed.id,
            {
                "status": "failed",
                "error_category": category,
                "error_message": safe_msg,
                "completed_at": now,
                "worker_id": None,
                "locked_at": None,
            },
        )
        self.post_repo.update_post(
            post.id,
            {"publishing_status": "failed", "last_publish_error": safe_msg},
        )
        if claimed.publishing_schedule_id:
            self.pub_repo.update_schedule(claimed.publishing_schedule_id, {"status": "failed"})

        site = self.website_repo.get_by_id(post.website_id)
        if self.pub_repo.get_record_by_idempotency_key(claimed.idempotency_key) is None:
            self.pub_repo.create_record(
                {
                    "website_id": post.website_id,
                    "website_name_snapshot": site.name if site else f"Website #{post.website_id}",
                    "social_profile_id": profile.id if profile else None,
                    "profile_name_snapshot": (
                        profile.profile_name if profile else f"Profile #{post.social_profile_id}"
                    ),
                    "platform_id": post.platform_id,
                    "platform_key": platform.platform_key if platform else "custom_social",
                    "platform_display_name": platform.display_name if platform else "Custom",
                    "social_post_id": post.id,
                    "website_content_id": post.website_content_id,
                    "approved_revision_id": claimed.approved_revision_id,
                    "approved_version_number": post.current_version,
                    "publishing_job_id": claimed.id,
                    "publishing_method": claimed.publishing_method,
                    "verification_status": "unverified",
                    "outcome": "failed",
                    "idempotency_key": claimed.idempotency_key,
                    "scheduled_at": claimed.scheduled_at,
                    "published_at": None,
                    "caption_snapshot": post.assembled_content,
                    "hashtags_snapshot_json": list(post.hashtags_json or []),
                    "source_url": post.target_url_with_utm or post.source_url,
                    "attempt_count": claimed.attempt_count,
                    "last_http_status": http_status,
                    "error_summary": safe_msg,
                    "recorded_by": claimed.created_by,
                }
            )
        self.pub_repo.create_log(
            {
                "publishing_job_id": claimed.id,
                "website_id": post.website_id,
                "social_profile_id": profile.id if profile else None,
                "social_post_id": post.id,
                "platform_key": platform.platform_key if platform else "custom_social",
                "attempt_number": claimed.attempt_count,
                "action": "publish",
                "outcome": "failed",
                "http_status": http_status,
                "error_category": category,
                "error_message": safe_msg,
            }
        )
        assert job is not None
        return self._to_job_response(job)

    def run_due_jobs(self, *, limit: int = 10) -> list[PublishingJobResponse]:
        self.pub_repo.recover_stale_jobs(
            stale_minutes=self.settings.publishing_stale_timeout_minutes
        )
        due = self.pub_repo.list_due_jobs(now=utc_now_naive(), limit=limit)
        results: list[PublishingJobResponse] = []
        for job in due:
            results.append(self.execute_job(job.id, worker_id="cron-due-publishes"))
        return results

    def reconcile_job(
        self,
        job_id: int,
        payload: ReconcileJobRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> PublishingJobResponse:
        job = self.pub_repo.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Publishing job #{job_id} not found.")
        post = self.post_repo.get_by_id(job.social_post_id)
        if post is None:
            raise NotFoundError(f"Social post #{job.social_post_id} not found.")
        profile = (
            self.profile_repo.get_by_id(job.social_profile_id)
            if job.social_profile_id
            else self.profile_repo.get_by_id(post.social_profile_id)
        )
        platform = self.profile_repo.get_platform_by_id(post.platform_id)
        if profile is None or platform is None:
            raise NotFoundError("Associated social profile or platform not found.")
        conn = self.pub_repo.get_connection_by_profile_id(profile.id)

        resolution = payload.resolution.strip().lower()
        if resolution == "confirm_published":
            return self._record_publish_success(
                claimed=job,
                post=post,
                profile=profile,
                platform=platform,
                ext_id=payload.external_post_id or job.external_post_id,
                pub_url=payload.published_url or job.published_url,
                http_status=200,
                verification_status="verified_after_timeout",
                summary={"reconciled_by": "admin", "notes": payload.notes},
            )
        if resolution == "confirm_missing":
            reset = self.pub_repo.update_job(
                job.id,
                {
                    "status": "queued",
                    "requires_verification": False,
                    "error_category": None,
                    "error_message": None,
                    "available_at": utc_now_naive(),
                    "next_retry_at": None,
                },
            )
            self.post_repo.update_post(post.id, {"publishing_status": "queued"})
            self.pub_repo.create_log(
                {
                    "publishing_job_id": job.id,
                    "website_id": post.website_id,
                    "social_profile_id": profile.id,
                    "social_post_id": post.id,
                    "platform_key": platform.platform_key,
                    "attempt_number": job.attempt_count,
                    "action": "reconcile",
                    "outcome": "verified_missing",
                    "actor_user_id": user_id,
                    "response_summary_json": {"notes": payload.notes},
                }
            )
            self.dispatcher(job.id)
            assert reset is not None
            return self._to_job_response(reset)

        adapter = self.registry.get(platform.platform_key, publishing_method="api")
        rec = adapter.reconcile_publication(
            request=PublishRequest(
                social_post_id=post.id,
                social_profile_id=profile.id,
                website_id=post.website_id,
                platform_key=platform.platform_key,
                idempotency_key=job.idempotency_key,
                title=post.title,
                caption=post.caption,
                assembled_content=assemble_publish_caption(post),
                source_url=post.source_url,
                cta_text=post.cta_text,
                target_resource_id=conn.target_resource_id if conn else profile.external_account_id,
                external_account_id=profile.external_account_id,
                scheduled_for_utc=job.scheduled_at,
                credentials=self._decrypt_credentials(profile),
            ),
            external_post_id=job.external_post_id,
        )
        if rec.exists:
            self.pub_repo.create_log(
                {
                    "publishing_job_id": job.id,
                    "website_id": post.website_id,
                    "social_profile_id": profile.id,
                    "social_post_id": post.id,
                    "platform_key": platform.platform_key,
                    "attempt_number": job.attempt_count,
                    "action": "reconcile",
                    "outcome": "verified_exists",
                    "external_post_id": rec.external_post_id,
                    "published_url": rec.published_url,
                    "actor_user_id": user_id,
                }
            )
            return self._record_publish_success(
                claimed=job,
                post=post,
                profile=profile,
                platform=platform,
                ext_id=rec.external_post_id,
                pub_url=rec.published_url,
                http_status=200,
                verification_status="verified_after_timeout",
                summary={"reconciled": True, "note": rec.note},
            )
        if not rec.indeterminate:
            reset = self.pub_repo.update_job(
                job.id,
                {
                    "status": "queued",
                    "requires_verification": False,
                    "error_category": None,
                    "error_message": None,
                    "available_at": utc_now_naive(),
                },
            )
            self.post_repo.update_post(post.id, {"publishing_status": "queued"})
            self.pub_repo.create_log(
                {
                    "publishing_job_id": job.id,
                    "website_id": post.website_id,
                    "social_profile_id": profile.id,
                    "social_post_id": post.id,
                    "platform_key": platform.platform_key,
                    "attempt_number": job.attempt_count,
                    "action": "reconcile",
                    "outcome": "verified_missing",
                    "actor_user_id": user_id,
                    "response_summary_json": {"note": rec.note},
                }
            )
            self.dispatcher(job.id)
            assert reset is not None
            return self._to_job_response(reset)

        updated = self.pub_repo.update_job(
            job.id,
            {"error_message": (rec.note or "Requires manual platform check.")[:500]},
        )
        assert updated is not None
        return self._to_job_response(updated)

    def retry_job(
        self, job_id: int, *, user_id: int | None, ip_address: str | None
    ) -> PublishingJobResponse:
        job = self.pub_repo.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Publishing job #{job_id} not found.")
        if job.status == "verification_required" or job.requires_verification:
            raise ConflictError(
                "Job outcome is uncertain (verification_required). Reconcile before retrying."
            )
        if job.status in {"published", "processing"}:
            raise ConflictError(f"Job #{job.id} is already {job.status}.")
        if self.pub_repo.get_latest_published_for_post(job.social_post_id) is not None:
            raise ConflictError("Post has already been published; duplicate retry blocked.")

        now = utc_now_naive()
        reset = self.pub_repo.update_job(
            job.id,
            {
                "status": "queued",
                "attempt_count": 0,
                "error_category": None,
                "error_message": None,
                "paused_reason": None,
                "available_at": now,
                "next_retry_at": None,
                "completed_at": None,
            },
        )
        self.post_repo.update_post(job.social_post_id, {"publishing_status": "queued"})
        if job.publishing_schedule_id:
            self.pub_repo.update_schedule(job.publishing_schedule_id, {"status": "queued"})
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="publishing",
            action="publishing.retried",
            level="info",
            message=f"Re-queued publishing job #{job.id}.",
            metadata={"publishing_job_id": job.id},
            ip_address=ip_address,
        )
        self.dispatcher(job.id)
        assert reset is not None
        return self._to_job_response(reset)

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
    ) -> PublishingJobListResponse:
        rows, total = self.pub_repo.list_jobs(
            website_id=website_id,
            social_profile_id=social_profile_id,
            platform_key=platform_key,
            status=status,
            social_post_id=social_post_id,
            page=page,
            page_size=page_size,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return PublishingJobListResponse(
            items=[self._to_job_response(r) for r in rows],
            meta=PaginationMeta(
                page=page, page_size=page_size, total_items=total, total_pages=total_pages
            ),
        )

    def get_job(self, job_id: int) -> PublishingJobResponse:
        job = self.pub_repo.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Publishing job #{job_id} not found.")
        return self._to_job_response(job)

    def list_post_logs(self, post_id: int) -> list[PublishingLogResponse]:
        if self.post_repo.get_by_id(post_id) is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        return [
            PublishingLogResponse(
                id=r.id,
                publishing_job_id=r.publishing_job_id,
                website_id=r.website_id,
                social_profile_id=r.social_profile_id,
                social_post_id=r.social_post_id,
                platform_key=r.platform_key,
                attempt_number=r.attempt_number,
                action=r.action,
                outcome=r.outcome,
                http_status=r.http_status,
                external_post_id=r.external_post_id,
                published_url=r.published_url,
                error_category=r.error_category,
                error_message=r.error_message,
                response_summary=dict(r.response_summary_json or {}),
                created_at=ensure_utc(r.created_at) or utc_now(),
            )
            for r in self.pub_repo.list_logs_for_post(post_id)
        ]

    def get_calendar(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_key: str | None = None,
        status: str | None = None,
        start_utc: datetime | None = None,
        end_utc: datetime | None = None,
    ) -> CalendarResponse:
        default_tz = self._effective_timezone(None)
        schedules = self.pub_repo.list_schedules(
            website_id=website_id,
            social_profile_id=social_profile_id,
            platform_key=platform_key,
            status=status,
            start_utc=start_utc,
            end_utc=end_utc,
        )
        events: list[CalendarEventResponse] = []
        seen_post_ids: set[int] = set()
        for s in schedules:
            if s.status == "cancelled" and status != "cancelled":
                continue
            post = self.post_repo.get_by_id(s.social_post_id)
            if post is None:
                continue
            seen_post_ids.add(post.id)
            site = self.website_repo.get_by_id(s.website_id)
            prof = self.profile_repo.get_by_id(s.social_profile_id) if s.social_profile_id else None
            plat = self.profile_repo.get_platform_by_key(s.platform_key)
            tz_name = (
                prof.display_timezone
                if prof and prof.display_timezone
                else (s.display_timezone or default_tz)
            )
            effective_status = (
                "manual_reminder"
                if (prof and prof.publishing_method == "manual" and s.status == "scheduled")
                else post.publishing_status
            )
            plat_label = plat.display_name if plat else s.platform_key
            events.append(
                CalendarEventResponse(
                    id=f"sched-{s.id}",
                    schedule_id=s.id,
                    social_post_id=post.id,
                    website_id=post.website_id,
                    website_name=site.name if site else None,
                    social_profile_id=post.social_profile_id,
                    profile_name=prof.profile_name if prof else None,
                    platform_key=s.platform_key,
                    platform_display_name=plat_label,
                    title=f"{plat_label}: {(post.title or post.caption)[:45]}",
                    caption_preview=post.caption[:140],
                    publishing_method=prof.publishing_method if prof else "manual",
                    publishing_status=effective_status,
                    start_utc=ensure_utc(s.scheduled_at) or utc_now(),
                    display_timezone=tz_name,
                    local_iso=self._format_local_iso(s.scheduled_at, tz_name),
                    published_url=post.published_url,
                    last_error=post.last_publish_error,
                    color=STATUS_COLORS.get(effective_status, "#0d9488"),
                )
            )

        # Also include published / failed posts in range that lack active schedule rows
        plat_id_filter = None
        if platform_key and platform_key != "all":
            p_row = self.profile_repo.get_platform_by_key(platform_key)
            plat_id_filter = p_row.id if p_row else -1
        posts, _ = self.post_repo.list_posts(
            website_id=website_id,
            social_profile_id=social_profile_id,
            platform_id=plat_id_filter,
            date_from=start_utc,
            date_to=end_utc,
            page=1,
            page_size=200,
        )
        for post in posts:
            if post.id in seen_post_ids:
                continue
            event_dt = post.published_at or post.scheduled_for or post.last_publish_attempt_at
            if event_dt is None:
                continue
            if post.publishing_status not in {
                "published",
                "manually_published",
                "failed",
                "verification_required",
            }:
                continue
            if status and status != "all" and post.publishing_status != status:
                continue
            site = self.website_repo.get_by_id(post.website_id)
            prof = self.profile_repo.get_by_id(post.social_profile_id)
            plat = self.profile_repo.get_platform_by_id(post.platform_id)
            pkey = plat.platform_key if plat else "custom_social"
            plat_label = plat.display_name if plat else pkey
            tz_name = prof.display_timezone if prof and prof.display_timezone else default_tz
            events.append(
                CalendarEventResponse(
                    id=f"post-{post.id}",
                    schedule_id=None,
                    social_post_id=post.id,
                    website_id=post.website_id,
                    website_name=site.name if site else None,
                    social_profile_id=post.social_profile_id,
                    profile_name=prof.profile_name if prof else None,
                    platform_key=pkey,
                    platform_display_name=plat_label,
                    title=f"{plat_label}: {(post.title or post.caption)[:45]}",
                    caption_preview=post.caption[:140],
                    publishing_method=prof.publishing_method if prof else "manual",
                    publishing_status=post.publishing_status,
                    start_utc=ensure_utc(event_dt) or utc_now(),
                    display_timezone=tz_name,
                    local_iso=self._format_local_iso(event_dt, tz_name),
                    published_url=post.published_url,
                    last_error=post.last_publish_error,
                    color=STATUS_COLORS.get(post.publishing_status, "#64748b"),
                )
            )

        events.sort(key=lambda e: e.start_utc)
        return CalendarResponse(timezone=default_tz, events=events)

    def _to_record_response(self, row: PublicationRecord) -> PublicationRecordResponse:
        now = utc_now()
        return PublicationRecordResponse(
            id=row.id,
            website_id=row.website_id,
            website_name=row.website_name_snapshot,
            social_profile_id=row.social_profile_id,
            profile_name=row.profile_name_snapshot,
            platform_id=row.platform_id,
            platform_key=row.platform_key,
            platform_display_name=row.platform_display_name,
            social_post_id=row.social_post_id,
            website_content_id=row.website_content_id,
            source_title=row.source_title_snapshot,
            approved_revision_id=row.approved_revision_id,
            approved_version_number=row.approved_version_number,
            publishing_job_id=row.publishing_job_id,
            publishing_method=row.publishing_method,
            verification_status=row.verification_status,
            outcome=row.outcome,
            scheduled_at=ensure_utc(row.scheduled_at),
            published_at=ensure_utc(row.published_at),
            external_post_id=row.external_post_id,
            published_url=row.published_url,
            caption_snapshot=row.caption_snapshot,
            hashtags=list(row.hashtags_snapshot_json or []),
            source_url=row.source_url,
            attempt_count=row.attempt_count,
            last_http_status=row.last_http_status,
            error_summary=row.error_summary,
            created_at=ensure_utc(row.created_at) or now,
        )

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
    ) -> PublishingHistoryListResponse:
        rows, total = self.pub_repo.list_history(
            website_id=website_id,
            social_profile_id=social_profile_id,
            platform_key=platform_key,
            outcome=outcome,
            publishing_method=publishing_method,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return PublishingHistoryListResponse(
            items=[self._to_record_response(r) for r in rows],
            meta=PaginationMeta(
                page=page, page_size=page_size, total_items=total, total_pages=total_pages
            ),
        )

    def export_history_csv(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_key: str | None = None,
        outcome: str | None = None,
        publishing_method: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> str:
        rows, _ = self.pub_repo.list_history(
            website_id=website_id,
            social_profile_id=social_profile_id,
            platform_key=platform_key,
            outcome=outcome,
            publishing_method=publishing_method,
            date_from=date_from,
            date_to=date_to,
            page=1,
            page_size=2000,
        )
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "Record ID",
                "Website",
                "Social Profile",
                "Platform",
                "Source Content",
                "Draft Version",
                "Method",
                "Verification Status",
                "Outcome",
                "Scheduled At (UTC)",
                "Published At (UTC)",
                "External Post ID",
                "Published URL",
                "Attempts",
                "HTTP Status",
                "Error Summary",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.id,
                    r.website_name_snapshot,
                    r.profile_name_snapshot,
                    r.platform_display_name,
                    r.source_title_snapshot or "",
                    r.approved_version_number or "",
                    r.publishing_method,
                    r.verification_status,
                    r.outcome,
                    r.scheduled_at.isoformat() if r.scheduled_at else "",
                    r.published_at.isoformat() if r.published_at else "",
                    r.external_post_id or "",
                    r.published_url or "",
                    r.attempt_count,
                    r.last_http_status or "",
                    r.error_summary or "",
                ]
            )
        return buf.getvalue()

    def get_statistics(
        self,
        *,
        website_id: int | None = None,
        platform_id: int | None = None,
    ) -> PublishingStatisticsResponse:
        tz_name = self._effective_timezone(None)
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = UTC
        local_now = datetime.now(tz)
        today_start_utc = (
            local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        month_start_utc = (
            local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

        post_stats = self.post_repo.get_stats(website_id=website_id, platform_id=platform_id)
        published_today = self.pub_repo.count_published_in_window(
            start_utc=today_start_utc, website_id=website_id, platform_id=platform_id
        )
        published_month = self.pub_repo.count_published_in_window(
            start_utc=month_start_utc, website_id=website_id, platform_id=platform_id
        )

        conns = self.pub_repo.list_connections(website_id=website_id)
        now = utc_now_naive()
        attention = 0
        expiring = 0
        for c in conns:
            if platform_id is not None and c.platform_id != platform_id:
                continue
            if c.connection_status in {"expired", "error", "missing_permissions", "restricted"}:
                attention += 1
            if c.token_expires_at is not None:
                if c.token_expires_at <= now:
                    if c.connection_status not in {
                        "expired",
                        "error",
                        "missing_permissions",
                        "restricted",
                    }:
                        attention += 1
                elif c.token_expires_at <= now + timedelta(days=7):
                    expiring += 1

        plat_key = None
        if platform_id is not None:
            plat = self.profile_repo.get_platform_by_id(platform_id)
            plat_key = plat.platform_key if plat else None

        upcoming_cal = self.get_calendar(
            website_id=website_id,
            platform_key=plat_key,
            status="scheduled",
            start_utc=now - timedelta(hours=1),
            end_utc=now + timedelta(days=30),
        )
        return PublishingStatisticsResponse(
            timezone=tz_name,
            drafts_awaiting_review=post_stats.get("pending_review", 0),
            approved_posts=post_stats.get("approved", 0),
            scheduled_posts=post_stats.get("scheduled", 0),
            published_today=published_today,
            published_this_month=published_month,
            failed_publications=post_stats.get("failed_publishing", 0),
            verification_required=post_stats.get("verification_required", 0),
            accounts_requiring_attention=attention,
            expiring_credentials=expiring,
            upcoming_scheduled=upcoming_cal.events[:8],
        )

    def resolve_public_media(self, token: str) -> tuple[Path, str]:
        row = self.pub_repo.get_post_media_by_token(token)
        if row is None or not row.prepared_file_path:
            raise NotFoundError("Public media token not found.")
        if row.public_media_expires_at and row.public_media_expires_at <= utc_now_naive():
            raise NotFoundError("Public media token has expired.")
        root = self.settings.resolved_storage_root.resolve()
        candidate = (root / row.prepared_file_path).resolve()
        if not str(candidate).startswith(str(root / "prepared_media")) or not candidate.is_file():
            raise NotFoundError("Prepared media file is missing.")
        return candidate, row.prepared_mime_type or "image/jpeg"
