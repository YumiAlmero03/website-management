from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.models.ai_generation_job import AiGenerationJob
from app.models.ai_generation_log import AiGenerationLog
from app.models.ai_provider import AiProvider
from app.models.ai_response_cache import AiResponseCache
from app.models.base import utc_now_naive
from app.models.platform import Platform
from app.models.prompt_template import PromptTemplate, PromptTemplateRevision
from app.models.social_post import SocialPost, SocialPostRevision
from app.models.social_profile import SocialProfile
from app.models.website_knowledge_profile import (
    WebsiteKnowledgeProfile,
    WebsiteKnowledgeProfileRevision,
)
from app.services.ai.defaults import DEFAULT_PLATFORMS, DEFAULT_PROMPT_TEMPLATES
from app.services.ai.model_registry import normalize_model_name
from app.services.ai.provider import (
    ProviderGenerationResult,
    ProviderModelDescriptor,
    ProviderTestResult,
)


class InMemorySocialProfileRepository:
    def __init__(self) -> None:
        self._platforms: dict[int, Platform] = {}
        self._profiles: dict[int, SocialProfile] = {}
        self._seq = 0
        now = utc_now_naive()
        for idx, p in enumerate(DEFAULT_PLATFORMS, start=1):
            self._platforms[idx] = Platform(
                id=idx,
                platform_key=p["platform_key"],
                display_name=p["display_name"],
                category=p["category"],
                default_max_chars=p["default_max_chars"],
                url_counts_as_chars=p["url_counts_as_chars"],
                supports_hashtags=bool(p["supports_hashtags"]),
                supports_cta=bool(p["supports_cta"]),
                supports_source_url=bool(p["supports_source_url"]),
                supports_title=bool(p["supports_title"]),
                supports_media=bool(p["supports_media"]),
                supports_free_auto_publish=bool(p["supports_free_auto_publish"]),
                credential_fields_json=list(p["credential_fields_json"]),
                capabilities_json=dict(p["capabilities_json"]),
                is_enabled=True,
                sort_order=int(p["sort_order"]),
                created_at=now,
                updated_at=now,
            )

    def list_platforms(self, *, enabled_only: bool = True) -> list[Platform]:
        items = list(self._platforms.values())
        if enabled_only:
            items = [p for p in items if p.is_enabled]
        items.sort(key=lambda p: (p.sort_order, p.id))
        return items

    def get_platform_by_key(self, platform_key: str) -> Platform | None:
        norm = platform_key.strip().lower()
        for p in self._platforms.values():
            if p.platform_key == norm:
                return p
        return None

    def get_platform_by_id(self, platform_id: int) -> Platform | None:
        return self._platforms.get(platform_id)

    def list_for_website(
        self,
        website_id: int,
        *,
        active_only: bool = False,
        generation_only: bool = False,
        automatic_only: bool = False,
    ) -> list[SocialProfile]:
        rows = [r for r in self._profiles.values() if r.website_id == website_id]
        if active_only:
            rows = [r for r in rows if r.is_active]
        if generation_only:
            rows = [r for r in rows if r.generation_enabled]
        if automatic_only:
            rows = [r for r in rows if r.automatic_generation_enabled]
        rows.sort(key=lambda r: r.id)
        return rows

    def list_all(self, *, website_id: int | None = None) -> list[SocialProfile]:
        rows = list(self._profiles.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        rows.sort(key=lambda r: (r.website_id, r.id))
        return rows

    def get_by_id(self, profile_id: int) -> SocialProfile | None:
        return self._profiles.get(profile_id)

    def create(self, data: dict[str, Any]) -> SocialProfile:
        self._seq += 1
        now = utc_now_naive()
        row = SocialProfile(id=self._seq, **data, created_at=now, updated_at=now)
        self._profiles[row.id] = row
        return row

    def update(self, profile_id: int, data: dict[str, Any]) -> SocialProfile | None:
        row = self._profiles.get(profile_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = utc_now_naive()
        return row

    def delete(self, profile_id: int) -> bool:
        return self._profiles.pop(profile_id, None) is not None


class InMemoryAiRepository:
    def __init__(self) -> None:
        self._providers: dict[int, AiProvider] = {}
        self._provider_seq = 0
        self._knowledge: dict[int, WebsiteKnowledgeProfile] = {}
        self._knowledge_seq = 0
        self._knowledge_revs: list[WebsiteKnowledgeProfileRevision] = []
        self._knowledge_rev_seq = 0
        self._prompts: dict[int, PromptTemplate] = {}
        self._prompt_seq = 0
        self._prompt_revs: list[PromptTemplateRevision] = []
        self._prompt_rev_seq = 0
        self._cache: dict[int, AiResponseCache] = {}
        self._cache_seq = 0
        self._jobs: dict[int, AiGenerationJob] = {}
        self._job_seq = 0
        self._logs: list[AiGenerationLog] = []
        self._log_seq = 0

        now = utc_now_naive()
        for tpl in DEFAULT_PROMPT_TEMPLATES:
            self._prompt_seq += 1
            self._prompts[self._prompt_seq] = PromptTemplate(
                id=self._prompt_seq,
                scope_key="global",
                website_id=None,
                social_profile_id=None,
                **tpl,
                created_at=now,
                updated_at=now,
            )

    def list_providers(self) -> list[AiProvider]:
        rows = list(self._providers.values())
        rows.sort(key=lambda r: (not r.is_default, r.id))
        return rows

    def get_provider_by_id(self, provider_id: int) -> AiProvider | None:
        return self._providers.get(provider_id)

    def get_provider_by_name(self, name: str) -> AiProvider | None:
        for r in self._providers.values():
            if r.name == name.strip():
                return r
        return None

    def get_default_provider(self) -> AiProvider | None:
        active = [r for r in self._providers.values() if r.is_active]
        active.sort(key=lambda r: (not r.is_default, r.id))
        return active[0] if active else None

    def create_provider(self, data: dict[str, Any]) -> AiProvider:
        self._provider_seq += 1
        now = utc_now_naive()
        row = AiProvider(id=self._provider_seq, **data, created_at=now, updated_at=now)
        self._providers[row.id] = row
        return row

    def update_provider(self, provider_id: int, data: dict[str, Any]) -> AiProvider | None:
        row = self._providers.get(provider_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = utc_now_naive()
        return row

    def clear_default_providers(self, *, except_id: int | None = None) -> None:
        for r in self._providers.values():
            if except_id is None or r.id != except_id:
                r.is_default = False

    def get_knowledge_profile(self, website_id: int) -> WebsiteKnowledgeProfile | None:
        return self._knowledge.get(website_id)

    def save_knowledge_profile(
        self,
        *,
        website_id: int,
        data: dict[str, Any],
        change_source: str,
        user_id: int | None,
    ) -> WebsiteKnowledgeProfile:
        now = utc_now_naive()
        existing = self._knowledge.get(website_id)
        if existing is None:
            self._knowledge_seq += 1
            row = WebsiteKnowledgeProfile(
                id=self._knowledge_seq,
                website_id=website_id,
                profile_version=1,
                **data,
                created_at=now,
                updated_at=now,
            )
            self._knowledge[website_id] = row
        else:
            for k, v in data.items():
                setattr(existing, k, v)
            existing.profile_version += 1
            existing.updated_at = now
            row = existing

        self._knowledge_rev_seq += 1
        snapshot = {
            "brand_name": row.brand_name,
            "business_overview": row.business_overview,
            "products_and_services": list(row.products_and_services or []),
            "manual_overrides": dict(row.manual_overrides_json or {}),
            "status": row.status,
        }
        self._knowledge_revs.append(
            WebsiteKnowledgeProfileRevision(
                id=self._knowledge_rev_seq,
                knowledge_profile_id=row.id,
                website_id=website_id,
                profile_version=row.profile_version,
                snapshot_json=snapshot,
                content_fingerprint=row.content_fingerprint,
                change_source=change_source,
                created_by=user_id,
                created_at=now,
            )
        )
        return row

    def list_knowledge_revisions(
        self, website_id: int
    ) -> list[WebsiteKnowledgeProfileRevision]:
        revs = [r for r in self._knowledge_revs if r.website_id == website_id]
        revs.sort(key=lambda r: -r.profile_version)
        return revs

    def list_prompts(
        self,
        *,
        task_type: str | None = None,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        active_only: bool = False,
    ) -> list[PromptTemplate]:
        rows = list(self._prompts.values())
        if task_type:
            rows = [r for r in rows if r.task_type == task_type]
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if social_profile_id is not None:
            rows = [r for r in rows if r.social_profile_id == social_profile_id]
        if active_only:
            rows = [r for r in rows if r.is_active]
        rows.sort(key=lambda r: (r.scope_key, r.task_type, r.id))
        return rows

    def get_prompt_by_id(self, prompt_id: int) -> PromptTemplate | None:
        return self._prompts.get(prompt_id)

    def get_prompt_by_key_scope(self, template_key: str, scope_key: str) -> PromptTemplate | None:
        for r in self._prompts.values():
            if r.template_key == template_key and r.scope_key == scope_key:
                return r
        return None

    def resolve_prompt(
        self,
        *,
        task_type: str,
        platform_key: str | None = None,
        website_id: int | None = None,
        social_profile_id: int | None = None,
    ) -> PromptTemplate | None:
        active = [r for r in self._prompts.values() if r.is_active]
        if social_profile_id is not None:
            for r in active:
                if r.social_profile_id == social_profile_id and (
                    r.task_type == task_type or (platform_key and r.platform_key == platform_key)
                ):
                    return r
        if website_id is not None:
            for r in active:
                if (
                    r.website_id == website_id
                    and r.social_profile_id is None
                    and platform_key
                    and r.platform_key == platform_key
                ):
                    return r
            for r in active:
                if (
                    r.website_id == website_id
                    and r.social_profile_id is None
                    and r.task_type == task_type
                ):
                    return r
        if platform_key:
            for r in active:
                if (
                    r.website_id is None
                    and r.social_profile_id is None
                    and r.platform_key == platform_key
                ):
                    return r
        for r in active:
            if r.website_id is None and r.social_profile_id is None and r.task_type == task_type:
                return r
        return None

    def create_prompt(self, data: dict[str, Any], *, user_id: int | None) -> PromptTemplate:
        self._prompt_seq += 1
        now = utc_now_naive()
        row = PromptTemplate(id=self._prompt_seq, **data, created_at=now, updated_at=now)
        self._prompts[row.id] = row
        self._prompt_rev_seq += 1
        self._prompt_revs.append(
            PromptTemplateRevision(
                id=self._prompt_rev_seq,
                prompt_template_id=row.id,
                version=row.version,
                system_instructions=row.system_instructions,
                user_prompt_template=row.user_prompt_template,
                change_note="Initial version",
                created_by=user_id,
                created_at=now,
            )
        )
        return row

    def update_prompt(
        self,
        prompt_id: int,
        data: dict[str, Any],
        *,
        user_id: int | None,
        change_note: str | None = None,
    ) -> PromptTemplate | None:
        row = self._prompts.get(prompt_id)
        if row is None:
            return None
        now = utc_now_naive()
        changed = (
            (
                "system_instructions" in data
                and data["system_instructions"] != row.system_instructions
            )
            or (
                "user_prompt_template" in data
                and data["user_prompt_template"] != row.user_prompt_template
            )
        )
        for k, v in data.items():
            setattr(row, k, v)
        if changed:
            row.version += 1
            self._prompt_rev_seq += 1
            self._prompt_revs.append(
                PromptTemplateRevision(
                    id=self._prompt_rev_seq,
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
        return row

    def list_prompt_revisions(self, prompt_id: int) -> list[PromptTemplateRevision]:
        revs = [r for r in self._prompt_revs if r.prompt_template_id == prompt_id]
        revs.sort(key=lambda r: -r.version)
        return revs

    def get_cache_entry(
        self, cache_key_hash: str, *, now: datetime | None = None
    ) -> AiResponseCache | None:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        for entry in self._cache.values():
            if entry.cache_key_hash == cache_key_hash and entry.expires_at > current:
                return entry
        return None

    def upsert_cache_entry(self, data: dict[str, Any]) -> AiResponseCache:
        for entry in self._cache.values():
            if entry.cache_key_hash == data["cache_key_hash"]:
                for k, v in data.items():
                    setattr(entry, k, v)
                return entry
        self._cache_seq += 1
        row = AiResponseCache(id=self._cache_seq, **data, created_at=utc_now_naive())
        self._cache[row.id] = row
        return row

    def record_cache_hit(self, cache_id: int) -> None:
        entry = self._cache.get(cache_id)
        if entry is not None:
            entry.hit_count += 1
            entry.last_hit_at = utc_now_naive()

    def list_cache_entries(
        self, *, website_id: int | None = None, limit: int = 100
    ) -> list[AiResponseCache]:
        rows = list(self._cache.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        rows.sort(key=lambda r: -r.id)
        return rows[:limit]

    def delete_cache_entries(
        self,
        *,
        cache_ids: list[int] | None = None,
        website_id: int | None = None,
        expired_only: bool = False,
        now: datetime | None = None,
    ) -> int:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        to_del = []
        for cid, entry in self._cache.items():
            if cache_ids and cid not in cache_ids:
                continue
            if website_id is not None and entry.website_id != website_id:
                continue
            if expired_only and entry.expires_at > current:
                continue
            to_del.append(cid)
        for cid in to_del:
            del self._cache[cid]
        return len(to_del)

    def get_cache_stats(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        total = len(self._cache)
        active = sum(1 for e in self._cache.values() if e.expires_at > current)
        hits = sum(e.hit_count for e in self._cache.values())
        return {
            "total_entries": total,
            "active_entries": active,
            "expired_entries": total - active,
            "total_hits": hits,
        }

    def create_job(self, data: dict[str, Any]) -> AiGenerationJob:
        self._job_seq += 1
        now = utc_now_naive()
        row = AiGenerationJob(id=self._job_seq, **data, created_at=now, updated_at=now)
        self._jobs[row.id] = row
        return row

    def get_job_by_id(self, job_id: int) -> AiGenerationJob | None:
        return self._jobs.get(job_id)

    def get_job_by_idempotency_key(self, idempotency_key: str) -> AiGenerationJob | None:
        for r in self._jobs.values():
            if r.idempotency_key == idempotency_key:
                return r
        return None

    def list_jobs(
        self,
        *,
        website_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[AiGenerationJob], int]:
        rows = list(self._jobs.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if status:
            rows = [r for r in rows if r.status == status]
        rows.sort(key=lambda r: -r.id)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def list_due_jobs(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> list[AiGenerationJob]:
        current = (now or utc_now_naive()).replace(tzinfo=None)
        rows = [
            r
            for r in self._jobs.values()
            if r.status in {"queued", "deferred"}
            and (r.next_retry_at is None or r.next_retry_at <= current)
        ]
        rows.sort(key=lambda r: r.id)
        return rows[:limit]

    def claim_job(self, job_id: int, *, worker_id: str) -> AiGenerationJob | None:
        job = self._jobs.get(job_id)
        if job is None or job.status not in {"queued", "deferred"}:
            return None
        now = utc_now_naive()
        job.status = "processing"
        job.worker_id = worker_id
        job.heartbeat_at = now
        job.started_at = job.started_at or now
        job.attempt_count += 1
        job.defer_reason = None
        job.updated_at = now
        return job

    def count_processing_jobs(self) -> int:
        return sum(1 for r in self._jobs.values() if r.status == "processing")

    def recover_stale_jobs(self, *, stale_minutes: int) -> list[AiGenerationJob]:
        now = utc_now_naive()
        cutoff = now - timedelta(minutes=stale_minutes)
        recovered = []
        for job in self._jobs.values():
            hb = job.heartbeat_at or job.started_at
            if job.status == "processing" and hb is not None and hb < cutoff:
                if job.attempt_count < job.max_attempts:
                    job.status = "deferred"
                    job.defer_reason = (
                        f"Recovered stale job after {stale_minutes}m worker heartbeat timeout."
                    )
                    job.next_retry_at = now
                else:
                    job.status = "failed"
                    job.error_code = "STALE_TIMEOUT"
                    job.completed_at = now
                job.worker_id = None
                job.updated_at = now
                recovered.append(job)
        return recovered

    def update_job(self, job_id: int, data: dict[str, Any]) -> AiGenerationJob | None:
        row = self._jobs.get(job_id)
        if row is None:
            return None
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = utc_now_naive()
        return row

    def count_jobs_by_status(self, status: str) -> int:
        return sum(1 for r in self._jobs.values() if r.status == status)

    def create_log(self, data: dict[str, Any]) -> AiGenerationLog:
        self._log_seq += 1
        row = AiGenerationLog(id=self._log_seq, **data, created_at=utc_now_naive())
        self._logs.append(row)
        return row

    def list_logs(
        self,
        *,
        website_id: int | None = None,
        provider_id: int | None = None,
        task_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AiGenerationLog], int]:
        rows = list(reversed(self._logs))
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if provider_id is not None:
            rows = [r for r in rows if r.ai_provider_id == provider_id]
        if task_type:
            rows = [r for r in rows if r.task_type == task_type]
        if status:
            rows = [r for r in rows if r.status == status]
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def list_logs_since(self, since_utc: datetime) -> list[AiGenerationLog]:
        naive_since = since_utc.replace(tzinfo=None)
        return [r for r in reversed(self._logs) if r.created_at >= naive_since]


class InMemorySocialPostRepository:
    def __init__(self) -> None:
        self._posts: dict[int, SocialPost] = {}
        self._seq = 0
        self._revs: list[SocialPostRevision] = []
        self._rev_seq = 0

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
        rows = list(self._posts.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if social_profile_id is not None:
            rows = [r for r in rows if r.social_profile_id == social_profile_id]
        if platform_id is not None:
            rows = [r for r in rows if r.platform_id == platform_id]
        if website_content_id is not None:
            rows = [r for r in rows if r.website_content_id == website_content_id]
        if status and status != "all":
            rows = [r for r in rows if r.status == status]
        rows.sort(key=lambda r: -r.id)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def get_stats(
        self,
        *,
        website_id: int | None = None,
        social_profile_id: int | None = None,
        platform_id: int | None = None,
    ) -> dict[str, int]:
        rows = list(self._posts.values())
        if website_id is not None:
            rows = [r for r in rows if r.website_id == website_id]
        if social_profile_id is not None:
            rows = [r for r in rows if r.social_profile_id == social_profile_id]
        if platform_id is not None:
            rows = [r for r in rows if r.platform_id == platform_id]
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        return {
            "total_drafts": len(rows),
            "pending_review": counts.get("pending_review", 0),
            "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0),
            "generation_failed": counts.get("generation_failed", 0),
            "archived": counts.get("archived", 0),
        }

    def get_by_id(self, post_id: int) -> SocialPost | None:
        return self._posts.get(post_id)

    def get_by_dedupe_key(self, dedupe_key: str) -> SocialPost | None:
        for r in self._posts.values():
            if r.dedupe_key == dedupe_key:
                return r
        return None

    def list_for_content(self, website_content_id: int) -> list[SocialPost]:
        rows = [r for r in self._posts.values() if r.website_content_id == website_content_id]
        rows.sort(key=lambda r: -r.id)
        return rows

    def get_active_for_content_and_profile(
        self, website_content_id: int, social_profile_id: int
    ) -> SocialPost | None:
        matches = [
            r
            for r in self._posts.values()
            if r.website_content_id == website_content_id
            and r.social_profile_id == social_profile_id
            and r.status != "archived"
        ]
        matches.sort(key=lambda r: -r.id)
        return matches[0] if matches else None

    def create_post(
        self,
        data: dict[str, Any],
        *,
        change_type: str = "initial_generated",
        edited_by: int | None = None,
        notes: str | None = None,
    ) -> SocialPost:
        self._seq += 1
        now = utc_now_naive()
        row = SocialPost(
            id=self._seq, **data, current_version=1, created_at=now, updated_at=now
        )
        self._posts[row.id] = row
        self._rev_seq += 1
        self._revs.append(
            SocialPostRevision(
                id=self._rev_seq,
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
        row = self._posts.get(post_id)
        if row is None:
            return None
        now = utc_now_naive()
        for k, v in data.items():
            setattr(row, k, v)
        if create_revision:
            row.current_version += 1
            self._rev_seq += 1
            self._revs.append(
                SocialPostRevision(
                    id=self._rev_seq,
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
        return row

    def list_revisions(self, post_id: int) -> list[SocialPostRevision]:
        revs = [r for r in self._revs if r.social_post_id == post_id]
        revs.sort(key=lambda r: -r.version_number)
        return revs


class FakeGeminiProviderClient:
    """Deterministic local fake implementing AiProviderClientProtocol for offline testing."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.next_error: Exception | None = None
        self.custom_handler: Any = None
        self.models: list[ProviderModelDescriptor] = [
            ProviderModelDescriptor(
                name="gemini-3.5-flash-lite",
                display_name="Gemini 3.5 Flash-Lite",
                input_token_limit=1048576,
                output_token_limit=65536,
                supported_actions=("generateContent", "interactions"),
                is_flash_recommended=True,
            ),
            ProviderModelDescriptor(
                name="gemini-4-hydrogen",
                display_name="Gemini 4 Hydrogen",
                input_token_limit=1048576,
                output_token_limit=65536,
                supported_actions=("generateContent", "interactions"),
                is_flash_recommended=True,
            ),
        ]

    def list_models(
        self, *, api_key: str, timeout_seconds: int = 45
    ) -> list[ProviderModelDescriptor]:
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        return list(self.models)

    def test_connection(
        self,
        *,
        api_key: str,
        selected_model: str,
        timeout_seconds: int = 45,
        verify_generation: bool = False,
    ) -> ProviderTestResult:
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            return ProviderTestResult(
                connected=False,
                selected_model=normalize_model_name(selected_model),
                model_available=False,
                latency_ms=12,
                discovered_models=[],
                error_detail=str(err),
            )
        target = normalize_model_name(selected_model)
        available = any(m.name == target for m in self.models)
        return ProviderTestResult(
            connected=True,
            selected_model=target,
            model_available=available,
            latency_ms=42,
            discovered_models=list(self.models),
            error_detail=None if available else f"Model '{target}' not listed",
            generation_probe_tokens=12 if (verify_generation and available) else None,
        )

    def count_tokens(
        self,
        *,
        api_key: str,
        model_name: str,
        system_instruction: str,
        user_prompt: str,
        timeout_seconds: int = 45,
    ) -> int | None:
        return max(1, (len(system_instruction) + len(user_prompt)) // 4)

    def generate_structured(
        self,
        *,
        api_key: str,
        model_name: str,
        system_instruction: str,
        user_prompt: str,
        response_schema: dict[str, Any],
        temperature: float = 0.4,
        max_output_tokens: int = 1500,
        timeout_seconds: int = 45,
    ) -> ProviderGenerationResult:
        self.calls.append(
            {
                "api_key": api_key,
                "model_name": model_name,
                "system_instruction": system_instruction,
                "user_prompt": user_prompt,
                "response_schema": response_schema,
            }
        )
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        if self.custom_handler is not None:
            return self.custom_handler(model_name, system_instruction, user_prompt, response_schema)

        # Default knowledge response if schema expects WebsiteKnowledgeAnalysisOutput
        if "business_overview" in (response_schema.get("properties") or {}):
            import json

            raw = json.dumps(
                {
                    "business_overview": "AI-synthesized factual overview of the registered brand.",
                    "products_and_services": ["Online Entertainment Platform", "Guides"],
                    "main_features": ["Fast Interface", "Mobile Support"],
                    "target_audience": "Adult digital entertainment readers",
                    "recommended_writing_tone": "Energetic & Informative",
                    "main_keywords": ["brand", "guides", "updates"],
                    "content_pillars": ["How-to Guides", "Platform Updates"],
                    "relevant_publishing_restrictions": "21+ Responsible Participation Notice",
                }
            )
            return ProviderGenerationResult(
                raw_text=raw,
                model_name=model_name,
                latency_ms=110,
                measured_input_tokens=180,
                measured_output_tokens=85,
                total_measured_tokens=265,
                raw_usage_available=True,
            )

        # Default multi-profile social batch response parsed from prompt's social_profile_id lines
        import json
        import re

        drafts = []
        pattern = r"social_profile_id=(\d+)\s*\|\s*platform=([a-z0-9_]+)"
        for match in re.finditer(pattern, user_prompt):
            pid = int(match.group(1))
            plat = match.group(2)
            caption = (
                f"Check out this new update on {plat}!"
                if plat != "linkedin"
                else "New insightful guide published for our readers."
            )
            drafts.append(
                {
                    "social_profile_id": pid,
                    "platform": plat,
                    "title": "Featured Pin Update" if plat == "pinterest" else None,
                    "caption": caption,
                    "hashtags": ["BrandUpdate", "News"],
                    "cta": "Learn more",
                    "needs_review": False,
                }
            )
        return ProviderGenerationResult(
            raw_text=json.dumps({"drafts": drafts}),
            model_name=model_name,
            latency_ms=145,
            measured_input_tokens=240,
            measured_output_tokens=120,
            total_measured_tokens=360,
            raw_usage_available=True,
        )
