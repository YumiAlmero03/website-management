from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.ai_generation_job import AiGenerationJob
from app.models.ai_generation_log import AiGenerationLog
from app.models.ai_provider import AiProvider
from app.models.ai_response_cache import AiResponseCache
from app.models.base import utc_now_naive
from app.models.prompt_template import PromptTemplate, PromptTemplateRevision
from app.models.website_knowledge_profile import (
    WebsiteKnowledgeProfile,
    WebsiteKnowledgeProfileRevision,
)


class AiRepositoryProtocol(Protocol):
    # Providers
    def list_providers(self) -> list[AiProvider]: ...
    def get_provider_by_id(self, provider_id: int) -> AiProvider | None: ...
    def get_provider_by_name(self, name: str) -> AiProvider | None: ...
    def get_default_provider(self) -> AiProvider | None: ...
    def create_provider(self, data: dict[str, Any]) -> AiProvider: ...
    def update_provider(self, provider_id: int, data: dict[str, Any]) -> AiProvider | None: ...
    def clear_default_providers(self, *, except_id: int | None = None) -> None: ...

    # Knowledge profiles
    def get_knowledge_profile(self, website_id: int) -> WebsiteKnowledgeProfile | None: ...
    def save_knowledge_profile(
        self,
        *,
        website_id: int,
        data: dict[str, Any],
        change_source: str,
        user_id: int | None,
    ) -> WebsiteKnowledgeProfile: ...
    def list_knowledge_revisions(
        self, website_id: int
    ) -> list[WebsiteKnowledgeProfileRevision]: ...

    # Prompt templates
    def list_prompts(
        self,
        *,
        task_type: str | None = None,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        active_only: bool = False,
    ) -> list[PromptTemplate]: ...
    def get_prompt_by_id(self, prompt_id: int) -> PromptTemplate | None: ...
    def get_prompt_by_key_scope(
        self, template_key: str, scope_key: str
    ) -> PromptTemplate | None: ...
    def resolve_prompt(
        self,
        *,
        task_type: str,
        platform_key: str | None = None,
        website_id: int | None = None,
        social_profile_id: int | None = None,
    ) -> PromptTemplate | None: ...
    def create_prompt(self, data: dict[str, Any], *, user_id: int | None) -> PromptTemplate: ...
    def update_prompt(
        self,
        prompt_id: int,
        data: dict[str, Any],
        *,
        user_id: int | None,
        change_note: str | None = None,
    ) -> PromptTemplate | None: ...
    def list_prompt_revisions(self, prompt_id: int) -> list[PromptTemplateRevision]: ...

    # Cache
    def get_cache_entry(
        self, cache_key_hash: str, *, now: datetime | None = None
    ) -> AiResponseCache | None: ...
    def upsert_cache_entry(self, data: dict[str, Any]) -> AiResponseCache: ...
    def record_cache_hit(self, cache_id: int) -> None: ...
    def list_cache_entries(
        self, *, website_id: int | None = None, limit: int = 100
    ) -> list[AiResponseCache]: ...
    def delete_cache_entries(
        self,
        *,
        cache_ids: list[int] | None = None,
        website_id: int | None = None,
        expired_only: bool = False,
        now: datetime | None = None,
    ) -> int: ...
    def get_cache_stats(self, *, now: datetime | None = None) -> dict[str, Any]: ...

    # Jobs
    def create_job(self, data: dict[str, Any]) -> AiGenerationJob: ...
    def get_job_by_id(self, job_id: int) -> AiGenerationJob | None: ...
    def get_job_by_idempotency_key(self, idempotency_key: str) -> AiGenerationJob | None: ...
    def list_jobs(
        self,
        *,
        website_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[AiGenerationJob], int]: ...
    def list_due_jobs(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> list[AiGenerationJob]: ...
    def claim_job(self, job_id: int, *, worker_id: str) -> AiGenerationJob | None: ...
    def count_processing_jobs(self) -> int: ...
    def recover_stale_jobs(self, *, stale_minutes: int) -> list[AiGenerationJob]: ...
    def update_job(self, job_id: int, data: dict[str, Any]) -> AiGenerationJob | None: ...
    def count_jobs_by_status(self, status: str) -> int: ...

    # Logs & Usage
    def create_log(self, data: dict[str, Any]) -> AiGenerationLog: ...
    def get_log_by_id(self, log_id: int) -> AiGenerationLog | None: ...
    def list_logs(
        self,
        *,
        website_id: int | None = None,
        provider_id: int | None = None,
        task_type: str | None = None,
        status: str | None = None,
        model_search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AiGenerationLog], int]: ...
    def list_logs_since(self, since_utc: datetime) -> list[AiGenerationLog]: ...


class SQLAlchemyAiRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --------------------------------------------------------------------------
    # Providers
    # --------------------------------------------------------------------------
    def list_providers(self) -> list[AiProvider]:
        stmt = select(AiProvider).order_by(AiProvider.is_default.desc(), AiProvider.id.asc())
        return list(self.db.execute(stmt).scalars().all())

    def get_provider_by_id(self, provider_id: int) -> AiProvider | None:
        return self.db.get(AiProvider, provider_id)

    def get_provider_by_name(self, name: str) -> AiProvider | None:
        stmt = select(AiProvider).where(AiProvider.name == name.strip())
        return self.db.execute(stmt).scalar_one_or_none()

    def get_default_provider(self) -> AiProvider | None:
        stmt = (
            select(AiProvider)
            .where(AiProvider.is_active.is_(True))
            .order_by(AiProvider.is_default.desc(), AiProvider.id.asc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def create_provider(self, data: dict[str, Any]) -> AiProvider:
        now = utc_now_naive()
        row = AiProvider(**data, created_at=now, updated_at=now)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_provider(self, provider_id: int, data: dict[str, Any]) -> AiProvider | None:
        row = self.db.get(AiProvider, provider_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        row.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(row)
        return row

    def clear_default_providers(self, *, except_id: int | None = None) -> None:
        stmt = update(AiProvider).values(is_default=False)
        if except_id is not None:
            stmt = stmt.where(AiProvider.id != except_id)
        self.db.execute(stmt)
        self.db.commit()

    # --------------------------------------------------------------------------
    # Website Knowledge Profiles
    # --------------------------------------------------------------------------
    def get_knowledge_profile(self, website_id: int) -> WebsiteKnowledgeProfile | None:
        stmt = select(WebsiteKnowledgeProfile).where(
            WebsiteKnowledgeProfile.website_id == website_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def save_knowledge_profile(
        self,
        *,
        website_id: int,
        data: dict[str, Any],
        change_source: str,
        user_id: int | None,
    ) -> WebsiteKnowledgeProfile:
        now = utc_now_naive()
        existing = self.get_knowledge_profile(website_id)
        if existing is None:
            row = WebsiteKnowledgeProfile(
                website_id=website_id,
                profile_version=1,
                **data,
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
            self.db.flush()
        else:
            for key, value in data.items():
                setattr(existing, key, value)
            existing.profile_version += 1
            existing.updated_at = now
            row = existing

        snapshot = {
            "brand_name": row.brand_name,
            "brand_description": row.brand_description,
            "website_category": row.website_category,
            "business_overview": row.business_overview,
            "products_and_services": list(row.products_and_services or []),
            "main_features": list(row.main_features or []),
            "target_audience": row.target_audience,
            "target_country": row.target_country,
            "primary_language": row.primary_language,
            "secondary_languages": list(row.secondary_languages or []),
            "recommended_writing_tone": row.recommended_writing_tone,
            "main_keywords": list(row.main_keywords or []),
            "content_pillars": list(row.content_pillars or []),
            "important_internal_links": list(row.important_internal_links or []),
            "relevant_publishing_restrictions": row.relevant_publishing_restrictions,
            "administrator_notes": row.administrator_notes,
            "manual_overrides": dict(row.manual_overrides_json or {}),
            "status": row.status,
        }
        rev = WebsiteKnowledgeProfileRevision(
            knowledge_profile_id=row.id,
            website_id=website_id,
            profile_version=row.profile_version,
            snapshot_json=snapshot,
            content_fingerprint=row.content_fingerprint,
            change_source=change_source,
            created_by=user_id,
            created_at=now,
        )
        self.db.add(rev)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_knowledge_revisions(
        self, website_id: int
    ) -> list[WebsiteKnowledgeProfileRevision]:
        stmt = (
            select(WebsiteKnowledgeProfileRevision)
            .where(WebsiteKnowledgeProfileRevision.website_id == website_id)
            .order_by(WebsiteKnowledgeProfileRevision.profile_version.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    # --------------------------------------------------------------------------
    # Prompt Templates
    # --------------------------------------------------------------------------
    def list_prompts(
        self,
        *,
        task_type: str | None = None,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        active_only: bool = False,
    ) -> list[PromptTemplate]:
        stmt = select(PromptTemplate)
        if task_type:
            stmt = stmt.where(PromptTemplate.task_type == task_type)
        if website_id is not None:
            stmt = stmt.where(PromptTemplate.website_id == website_id)
        if social_profile_id is not None:
            stmt = stmt.where(PromptTemplate.social_profile_id == social_profile_id)
        if active_only:
            stmt = stmt.where(PromptTemplate.is_active.is_(True))
        stmt = stmt.order_by(
            PromptTemplate.scope_key.asc(),
            PromptTemplate.task_type.asc(),
            PromptTemplate.id.asc(),
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_prompt_by_id(self, prompt_id: int) -> PromptTemplate | None:
        return self.db.get(PromptTemplate, prompt_id)

    def get_prompt_by_key_scope(self, template_key: str, scope_key: str) -> PromptTemplate | None:
        stmt = select(PromptTemplate).where(
            PromptTemplate.template_key == template_key,
            PromptTemplate.scope_key == scope_key,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def resolve_prompt(
        self,
        *,
        task_type: str,
        platform_key: str | None = None,
        website_id: int | None = None,
        social_profile_id: int | None = None,
    ) -> PromptTemplate | None:
        """Resolve effective prompt using exact precedence:
        1. Social profile override -> 2. Website override ->
        3. Global platform template -> 4. Global default template.
        """
        candidates: list[PromptTemplate] = []
        stmt = select(PromptTemplate).where(PromptTemplate.is_active.is_(True))
        all_active = list(self.db.execute(stmt).scalars().all())

        def _matches_platform_or_task(t: PromptTemplate) -> bool:
            if t.task_type == task_type:
                return True
            return bool(platform_key and t.platform_key == platform_key)

        if social_profile_id is not None:
            for t in all_active:
                if t.social_profile_id == social_profile_id and _matches_platform_or_task(t):
                    candidates.append(t)
            if candidates:
                return candidates[0]

        if website_id is not None:
            # Prefer exact website+platform match, then website+task match
            for t in all_active:
                if (
                    t.website_id == website_id
                    and t.social_profile_id is None
                    and platform_key
                    and t.platform_key == platform_key
                ):
                    return t
            for t in all_active:
                if (
                    t.website_id == website_id
                    and t.social_profile_id is None
                    and t.task_type == task_type
                ):
                    return t

        if platform_key:
            for t in all_active:
                if (
                    t.website_id is None
                    and t.social_profile_id is None
                    and t.platform_key == platform_key
                ):
                    return t

        for t in all_active:
            if (
                t.website_id is None
                and t.social_profile_id is None
                and t.task_type == task_type
            ):
                return t
        return None

    def create_prompt(self, data: dict[str, Any], *, user_id: int | None) -> PromptTemplate:
        now = utc_now_naive()
        row = PromptTemplate(**data, created_at=now, updated_at=now)
        self.db.add(row)
        self.db.flush()
        self.db.add(
            PromptTemplateRevision(
                prompt_template_id=row.id,
                version=row.version,
                system_instructions=row.system_instructions,
                user_prompt_template=row.user_prompt_template,
                change_note="Initial version",
                created_by=user_id,
                created_at=now,
            )
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_prompt(
        self,
        prompt_id: int,
        data: dict[str, Any],
        *,
        user_id: int | None,
        change_note: str | None = None,
    ) -> PromptTemplate | None:
        row = self.db.get(PromptTemplate, prompt_id)
        if row is None:
            return None
        now = utc_now_naive()
        content_changed = (
            (
                "system_instructions" in data
                and data["system_instructions"] != row.system_instructions
            )
            or (
                "user_prompt_template" in data
                and data["user_prompt_template"] != row.user_prompt_template
            )
        )
        for key, value in data.items():
            setattr(row, key, value)
        if content_changed:
            row.version += 1
            self.db.add(
                PromptTemplateRevision(
                    prompt_template_id=row.id,
                    version=row.version,
                    system_instructions=row.system_instructions,
                    user_prompt_template=row.user_prompt_template,
                    change_note=change_note,
                    created_by=user_id,
                    created_at=now,
                )
            )
        row.updated_at = now
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_prompt_revisions(self, prompt_id: int) -> list[PromptTemplateRevision]:
        stmt = (
            select(PromptTemplateRevision)
            .where(PromptTemplateRevision.prompt_template_id == prompt_id)
            .order_by(PromptTemplateRevision.version.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    # --------------------------------------------------------------------------
    # Cache
    # --------------------------------------------------------------------------
    def get_cache_entry(
        self, cache_key_hash: str, *, now: datetime | None = None
    ) -> AiResponseCache | None:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        stmt = select(AiResponseCache).where(
            AiResponseCache.cache_key_hash == cache_key_hash,
            AiResponseCache.expires_at > current,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def upsert_cache_entry(self, data: dict[str, Any]) -> AiResponseCache:
        stmt = select(AiResponseCache).where(
            AiResponseCache.cache_key_hash == data["cache_key_hash"]
        )
        existing = self.db.execute(stmt).scalar_one_or_none()
        now = utc_now_naive()
        if existing is not None:
            for key, value in data.items():
                setattr(existing, key, value)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        row = AiResponseCache(**data, created_at=now)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def record_cache_hit(self, cache_id: int) -> None:
        row = self.db.get(AiResponseCache, cache_id)
        if row is not None:
            row.hit_count += 1
            row.last_hit_at = utc_now_naive()
            self.db.commit()

    def list_cache_entries(
        self, *, website_id: int | None = None, limit: int = 100
    ) -> list[AiResponseCache]:
        stmt = select(AiResponseCache)
        if website_id is not None:
            stmt = stmt.where(AiResponseCache.website_id == website_id)
        stmt = stmt.order_by(AiResponseCache.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def delete_cache_entries(
        self,
        *,
        cache_ids: list[int] | None = None,
        website_id: int | None = None,
        expired_only: bool = False,
        now: datetime | None = None,
    ) -> int:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        stmt = select(AiResponseCache)
        if cache_ids:
            stmt = stmt.where(AiResponseCache.id.in_(cache_ids))
        if website_id is not None:
            stmt = stmt.where(AiResponseCache.website_id == website_id)
        if expired_only:
            stmt = stmt.where(AiResponseCache.expires_at <= current)
        rows = list(self.db.execute(stmt).scalars().all())
        for row in rows:
            self.db.delete(row)
        self.db.commit()
        return len(rows)

    def get_cache_stats(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        total_entries = int(self.db.execute(select(func.count(AiResponseCache.id))).scalar() or 0)
        active_entries = int(
            self.db.execute(
                select(func.count(AiResponseCache.id)).where(AiResponseCache.expires_at > current)
            ).scalar()
            or 0
        )
        total_hits = int(
            self.db.execute(select(func.coalesce(func.sum(AiResponseCache.hit_count), 0))).scalar()
            or 0
        )
        return {
            "total_entries": total_entries,
            "active_entries": active_entries,
            "expired_entries": max(0, total_entries - active_entries),
            "total_hits": total_hits,
        }

    # --------------------------------------------------------------------------
    # Background Jobs
    # --------------------------------------------------------------------------
    def create_job(self, data: dict[str, Any]) -> AiGenerationJob:
        now = utc_now_naive()
        row = AiGenerationJob(**data, created_at=now, updated_at=now)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_job_by_id(self, job_id: int) -> AiGenerationJob | None:
        return self.db.get(AiGenerationJob, job_id)

    def get_job_by_idempotency_key(self, idempotency_key: str) -> AiGenerationJob | None:
        stmt = select(AiGenerationJob).where(AiGenerationJob.idempotency_key == idempotency_key)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_jobs(
        self,
        *,
        website_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[AiGenerationJob], int]:
        stmt = select(AiGenerationJob)
        count_stmt = select(func.count(AiGenerationJob.id))
        if website_id is not None:
            stmt = stmt.where(AiGenerationJob.website_id == website_id)
            count_stmt = count_stmt.where(AiGenerationJob.website_id == website_id)
        if status:
            stmt = stmt.where(AiGenerationJob.status == status)
            count_stmt = count_stmt.where(AiGenerationJob.status == status)
        total = int(self.db.execute(count_stmt).scalar() or 0)
        offset = (page - 1) * page_size
        items = list(
            self.db.execute(
                stmt.order_by(AiGenerationJob.id.desc()).offset(offset).limit(page_size)
            )
            .scalars()
            .all()
        )
        return items, total

    def list_due_jobs(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> list[AiGenerationJob]:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        stmt = (
            select(AiGenerationJob)
            .where(
                AiGenerationJob.status.in_(("queued", "deferred")),
                or_(
                    AiGenerationJob.next_retry_at.is_(None),
                    AiGenerationJob.next_retry_at <= current,
                ),
            )
            .order_by(AiGenerationJob.id.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def claim_job(self, job_id: int, *, worker_id: str) -> AiGenerationJob | None:
        stmt = (
            select(AiGenerationJob)
            .where(
                AiGenerationJob.id == job_id,
                AiGenerationJob.status.in_(("queued", "deferred")),
            )
            .with_for_update()
        )
        job = self.db.execute(stmt).scalar_one_or_none()
        if job is None:
            self.db.rollback()
            return None
        now = utc_now_naive()
        job.status = "processing"
        job.worker_id = worker_id[:120]
        job.heartbeat_at = now
        job.started_at = job.started_at or now
        job.attempt_count += 1
        job.defer_reason = None
        job.updated_at = now
        self.db.commit()
        self.db.refresh(job)
        return job

    def count_processing_jobs(self) -> int:
        stmt = select(func.count(AiGenerationJob.id)).where(AiGenerationJob.status == "processing")
        return int(self.db.execute(stmt).scalar() or 0)

    def recover_stale_jobs(self, *, stale_minutes: int) -> list[AiGenerationJob]:
        now = utc_now_naive()
        cutoff = now - timedelta(minutes=stale_minutes)
        stmt = select(AiGenerationJob).where(
            AiGenerationJob.status == "processing",
            or_(
                AiGenerationJob.heartbeat_at < cutoff,
                (AiGenerationJob.heartbeat_at.is_(None) & (AiGenerationJob.started_at < cutoff)),
            ),
        )
        stale = list(self.db.execute(stmt).scalars().all())
        for job in stale:
            if job.attempt_count < job.max_attempts:
                job.status = "deferred"
                job.defer_reason = (
                    f"Recovered stale job after {stale_minutes}m worker heartbeat timeout."
                )
                job.next_retry_at = now
            else:
                job.status = "failed"
                job.error_code = "STALE_TIMEOUT"
                job.error_message = (
                    f"Exceeded {stale_minutes}m worker heartbeat timeout on final attempt."
                )
                job.completed_at = now
            job.worker_id = None
            job.updated_at = now
        if stale:
            self.db.commit()
        return stale

    def update_job(self, job_id: int, data: dict[str, Any]) -> AiGenerationJob | None:
        row = self.db.get(AiGenerationJob, job_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        row.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(row)
        return row

    def count_jobs_by_status(self, status: str) -> int:
        stmt = select(func.count(AiGenerationJob.id)).where(AiGenerationJob.status == status)
        return int(self.db.execute(stmt).scalar() or 0)

    # --------------------------------------------------------------------------
    # Logs & Usage
    # --------------------------------------------------------------------------
    def create_log(self, data: dict[str, Any]) -> AiGenerationLog:
        row = AiGenerationLog(**data, created_at=utc_now_naive())
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_log_by_id(self, log_id: int) -> AiGenerationLog | None:
        return self.db.get(AiGenerationLog, log_id)

    def list_logs(
        self,
        *,
        website_id: int | None = None,
        provider_id: int | None = None,
        task_type: str | None = None,
        status: str | None = None,
        model_search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AiGenerationLog], int]:
        stmt = select(AiGenerationLog)
        count_stmt = select(func.count(AiGenerationLog.id))
        if website_id is not None:
            stmt = stmt.where(AiGenerationLog.website_id == website_id)
            count_stmt = count_stmt.where(AiGenerationLog.website_id == website_id)
        if provider_id is not None:
            stmt = stmt.where(AiGenerationLog.ai_provider_id == provider_id)
            count_stmt = count_stmt.where(AiGenerationLog.ai_provider_id == provider_id)
        if task_type:
            stmt = stmt.where(AiGenerationLog.task_type == task_type)
            count_stmt = count_stmt.where(AiGenerationLog.task_type == task_type)
        if status:
            stmt = stmt.where(AiGenerationLog.status == status)
            count_stmt = count_stmt.where(AiGenerationLog.status == status)
        if model_search:
            matches_model = func.lower(AiGenerationLog.model_name).contains(
                model_search.casefold(), autoescape=True
            )
            stmt = stmt.where(matches_model)
            count_stmt = count_stmt.where(matches_model)
        total = int(self.db.execute(count_stmt).scalar() or 0)
        offset = (page - 1) * page_size
        items = list(
            self.db.execute(
                stmt.order_by(AiGenerationLog.id.desc()).offset(offset).limit(page_size)
            )
            .scalars()
            .all()
        )
        return items, total

    def list_logs_since(self, since_utc: datetime) -> list[AiGenerationLog]:
        naive_since = since_utc.replace(tzinfo=None)
        stmt = (
            select(AiGenerationLog)
            .where(AiGenerationLog.created_at >= naive_since)
            .order_by(AiGenerationLog.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
