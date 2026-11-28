from __future__ import annotations

import contextlib
import math
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from app.config import BACKEND_ROOT, Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.models.ai_generation_job import AiGenerationJob
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.platform import Platform
from app.models.prompt_template import PromptTemplate
from app.models.social_post import SocialPost
from app.models.social_profile import SocialProfile
from app.models.website import Website
from app.models.website_content import WebsiteContent
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.ai_repo import AiRepositoryProtocol
from app.repositories.category_repo import WebsiteCategoryRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.keyword_approval_repo import KeywordApprovalRepositoryProtocol
from app.repositories.social_post_repo import SocialPostRepositoryProtocol
from app.repositories.social_profile_repo import SocialProfileRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.ai import (
    AiGenerationJobListResponse,
    AiGenerationJobResponse,
    GenerateSocialDestinationsPreview,
    GenerateSocialRequest,
)
from app.schemas.common import PaginationMeta
from app.schemas.social_post import SocialPostRegenerateRequest
from app.services.ai.cache import (
    AiResponseCacheService,
    compute_cache_key,
    compute_sha256_json,
)
from app.services.ai.context_builder import (
    ALLOWED_CONTEXT_MODES,
    format_knowledge_summary,
    prepare_article_context,
    sanitize_untrusted_text,
)
from app.services.ai.exceptions import (
    AiError,
    AiPermanentError,
    AiProviderNotConfiguredError,
    AiQuotaExhaustedError,
    AiTransientError,
)
from app.services.ai.prompt_builder import render_sandboxed_prompt
from app.services.ai.provider import AiProviderClientProtocol
from app.services.ai.quota_manager import QuotaManager
from app.services.ai.response_validator import (
    MultiProfileSocialBatchOutput,
    ValidatedAssembledDraft,
    parse_structured_response,
    validate_multi_profile_batch,
)
from app.services.ai.token_tracker import estimate_tokens_from_text, resolve_usage_fields
from app.services.monitoring.health_service import HealthService
from app.services.settings_service import SettingsService

logger = get_logger("ai.generation")

AiJobDispatcher = Callable[[int], None]

DEFAULT_MANUAL_ELIGIBLE_CONTENT_TYPES: frozenset[str] = frozenset(
    {"blog_post", "page", "game_page", "homepage"}
)
AUTO_ELIGIBLE_CONTENT_TYPES: frozenset[str] = frozenset({"blog_post"})
MAX_PROFILES_PER_GEMINI_BATCH = 6


def default_ai_job_dispatcher(job_id: int) -> None:
    """Spawn a detached AI worker via `python -m app.cli run-ai-job --job-id <id>`."""
    cfg = Settings()
    log_file = None
    with contextlib.suppress(OSError):
        log_dir = cfg.resolved_storage_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = (log_dir / "ai-worker.log").open("ab")

    try:
        subprocess.Popen(
            [sys.executable, "-m", "app.cli", "run-ai-job", "--job-id", str(job_id)],
            cwd=str(BACKEND_ROOT),
            stdout=log_file if log_file is not None else subprocess.DEVNULL,
            stderr=log_file if log_file is not None else subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        if log_file is not None:
            with contextlib.suppress(OSError):
                log_file.close()


class AiGenerationService:
    """Handles automatic social profile selection, cached/batched Gemini generation, and jobs."""

    def __init__(
        self,
        *,
        settings: Settings,
        ai_repo: AiRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        category_repo: WebsiteCategoryRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        social_profile_repo: SocialProfileRepositoryProtocol,
        social_post_repo: SocialPostRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        health_service: HealthService,
        settings_service: SettingsService,
        provider_client: AiProviderClientProtocol,
        dispatcher: AiJobDispatcher | None = None,
        keyword_approval_repo: KeywordApprovalRepositoryProtocol | None = None,
    ) -> None:
        self.settings = settings
        self.ai_repo = ai_repo
        self.website_repo = website_repo
        self.category_repo = category_repo
        self.content_repo = content_repo
        self.profile_repo = social_profile_repo
        self.post_repo = social_post_repo
        self.activity_repo = activity_repo
        self.health_service = health_service
        self.settings_service = settings_service
        self.provider_client = provider_client
        self.dispatcher = dispatcher or default_ai_job_dispatcher
        self.keyword_approval_repo = keyword_approval_repo
        self.quota_manager = QuotaManager(ai_repo=ai_repo, timezone_name=settings.app_timezone)
        self.cache_service = AiResponseCacheService(
            ai_repo=ai_repo, default_ttl_days=settings.ai_cache_ttl_days
        )

    def _to_job_response(self, job: AiGenerationJob) -> AiGenerationJobResponse:
        now = utc_now()
        site = self.website_repo.get_by_id(job.website_id)
        content = (
            self.content_repo.get_by_id(job.website_content_id)
            if job.website_content_id
            else None
        )
        return AiGenerationJobResponse(
            id=job.id,
            job_uuid=job.job_uuid,
            job_type=job.job_type,
            trigger_type=job.trigger_type,
            website_id=job.website_id,
            website_name=site.name if site else None,
            website_content_id=job.website_content_id,
            content_title=content.title if content else None,
            target_profile_ids=list(job.target_profile_ids_json or []),
            ai_provider_id=job.ai_provider_id,
            context_mode=job.context_mode,
            force_regenerate=job.force_regenerate,
            regenerate_social_post_id=job.regenerate_social_post_id,
            idempotency_key=job.idempotency_key,
            status=job.status,
            defer_reason=job.defer_reason,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            next_retry_at=ensure_utc(job.next_retry_at),
            worker_id=job.worker_id,
            heartbeat_at=ensure_utc(job.heartbeat_at),
            error_code=job.error_code,
            error_message=job.error_message,
            result_summary=dict(job.result_summary_json) if job.result_summary_json else None,
            started_at=ensure_utc(job.started_at),
            completed_at=ensure_utc(job.completed_at),
            created_at=ensure_utc(job.created_at) or now,
            updated_at=ensure_utc(job.updated_at) or now,
        )

    def preview_destinations(self, content_id: int) -> GenerateSocialDestinationsPreview:
        content = self.content_repo.get_by_id(content_id)
        if content is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        site = self.website_repo.get_by_id(content.website_id)
        if site is None:
            raise NotFoundError(f"Website #{content.website_id} not found.")
        profiles = self.profile_repo.list_for_website(
            site.id, active_only=True, generation_only=True
        )
        items: list[dict[str, Any]] = []
        for p in profiles:
            plat = self.profile_repo.get_platform_by_id(p.platform_id)
            items.append(
                {
                    "id": p.id,
                    "profile_name": p.profile_name,
                    "platform_key": plat.platform_key if plat else "custom_social",
                    "platform_display_name": plat.display_name if plat else "Custom",
                    "publishing_method": p.publishing_method,
                    "effective_language": p.custom_language or site.primary_language,
                }
            )
        empty_msg = (
            "No social profiles configured for content generation. "
            "Configure your website's social profiles first."
            if not items
            else None
        )
        return GenerateSocialDestinationsPreview(
            website_id=site.id,
            website_name=site.name,
            eligible_profiles=items,
            empty_message=empty_msg,
            configure_url=f"/websites/{site.id}?tab=social-profiles",
        )

    def _validate_content_eligible(
        self, content: WebsiteContent, *, automatic: bool
    ) -> Website:
        site = self.website_repo.get_by_id(content.website_id)
        if site is None:
            raise NotFoundError(f"Website #{content.website_id} not found.")
        if content.is_excluded:
            raise ValidationAppError("Excluded content cannot generate social posts.")
        if content.extraction_status != "extracted":
            raise ValidationAppError(
                "Content must finish extraction successfully before generating social posts."
            )
        allowed = (
            AUTO_ELIGIBLE_CONTENT_TYPES
            if automatic
            else DEFAULT_MANUAL_ELIGIBLE_CONTENT_TYPES
        )
        if content.content_type not in allowed:
            raise ValidationAppError(
                f"Content type '{content.content_type}' is disabled by default "
                "for social generation."
            )
        has_context = bool(
            (content.optimized_context and content.optimized_context.strip())
            or (content.markdown_content and content.markdown_content.strip())
            or (content.meta_description and content.meta_description.strip())
        )
        if not has_context:
            raise ValidationAppError(
                "Source content does not have sufficient extracted context for generation."
            )
        if self.keyword_approval_repo is not None:
            approval = self.keyword_approval_repo.get_approval_by_content_id(content.id)
            kw = self.keyword_approval_repo.get_keyword_by_content_id(content.id)
            if (approval is not None and approval.status == "rejected") or (
                kw is not None and kw.approval_status == "rejected"
            ):
                raise ValidationAppError(
                    "Rejected content is excluded from AI generation. "
                    "Return it to review and approve it first."
                )
            if automatic and (
                approval is None
                or approval.status != "approved"
                or kw is None
                or kw.approval_status != "approved"
            ):
                    raise ValidationAppError(
                        "Automatic social draft generation requires both approved content "
                        "and approved keyword mapping."
                    )
        return site

    def _resolve_provider_and_key(self, provider_id: int | None) -> tuple[Any, str]:
        provider = (
            self.ai_repo.get_provider_by_id(provider_id)
            if provider_id is not None
            else self.ai_repo.get_default_provider()
        )
        if provider is None:
            raise AiProviderNotConfiguredError(
                "No active Gemini configuration found. Configure Gemini under AI Management first."
            )
        if not provider.is_active or not provider.generation_enabled:
            raise AiProviderNotConfiguredError(
                f"Gemini configuration '{provider.name}' is inactive or generation is disabled."
            )
        if provider.encrypted_api_key:
            api_key = decrypt_secret(provider.encrypted_api_key, self.settings.app_encryption_key)
        elif self.settings.gemini_api_key and self.settings.gemini_api_key.strip():
            api_key = self.settings.gemini_api_key.strip()
        else:
            raise AiProviderNotConfiguredError(
                f"Gemini configuration '{provider.name}' has no API key configured."
            )
        return provider, api_key

    def _profile_config_hash(
        self,
        *,
        profiles: list[tuple[SocialProfile, Platform]],
        website: Website,
        prompts_map: dict[int, PromptTemplate | None],
    ) -> str:
        serialized = [
            {
                "id": p.id,
                "platform": plat.platform_key,
                "name": p.profile_name,
                "lang": p.custom_language or website.primary_language,
                "tone": p.writing_tone or website.tone or "",
                "instr": p.platform_ai_instructions or "",
                "hashtags": p.default_hashtags or [],
                "cta": p.default_cta or "",
                "len": p.preferred_length or "medium",
                "limit": p.character_limit or plat.default_max_chars,
                "src_url": p.include_source_url,
                "inc_tags": p.include_hashtags,
                "inc_emoji": p.include_emojis,
                "restrict": p.content_restrictions or "",
                "prompt_id": prompts_map[p.id].id if prompts_map.get(p.id) else None,
                "prompt_ver": prompts_map[p.id].version if prompts_map.get(p.id) else 0,
                "website_ai_instr": website.ai_instructions or "",
                "website_guidelines": website.writing_guidelines or "",
            }
            for p, plat in profiles
        ]
        return compute_sha256_json(serialized)

    def enqueue_social_generation(
        self,
        content_id: int,
        payload: GenerateSocialRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
        dispatch: bool = True,
    ) -> AiGenerationJobResponse:
        content = self.content_repo.get_by_id(content_id)
        if content is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        automatic = payload.trigger_type == "auto_scan"
        site = self._validate_content_eligible(content, automatic=automatic)

        mode = (
            payload.context_mode
            if payload.context_mode in ALLOWED_CONTEXT_MODES
            else "optimized"
        )
        profiles = self.profile_repo.list_for_website(
            site.id,
            active_only=True,
            generation_only=True,
            automatic_only=automatic,
        )
        if not profiles:
            raise ValidationAppError(
                "No social profiles configured for content generation. "
                "Configure your website's social profiles first.",
                code="NO_ELIGIBLE_SOCIAL_PROFILES",
            )

        provider = (
            self.ai_repo.get_provider_by_id(payload.provider_id)
            if payload.provider_id is not None
            else self.ai_repo.get_default_provider()
        )
        if provider is None:
            raise AiProviderNotConfiguredError()

        target_ids = [p.id for p in profiles]
        idem = (
            f"manual:{content.id}:{compute_sha256_json(target_ids)[:12]}:"
            f"{uuid.uuid4().hex[:8]}"
            if payload.force_regenerate or payload.trigger_type == "manual"
            else f"auto_scan:{site.id}:{content.id}:{compute_sha256_json(target_ids)[:16]}"
        )

        # Prevent duplicate auto-scan enqueue across daily runs
        existing_job = self.ai_repo.get_job_by_idempotency_key(idem)
        if existing_job is not None:
            return self._to_job_response(existing_job)

        # Deduplicate already running identical manual request on the same content
        existing_jobs, _ = self.ai_repo.list_jobs(website_id=site.id, page=1, page_size=25)
        for ej in existing_jobs:
            if (
                ej.website_content_id == content.id
                and ej.regenerate_social_post_id is None
                and ej.status in {"queued", "processing"}
            ):
                raise ConflictError(
                    f"AI generation job #{ej.id} is already {ej.status} for this content."
                )

        job = self.ai_repo.create_job(
            {
                "job_uuid": str(uuid.uuid4()),
                "job_type": "social_generation",
                "trigger_type": payload.trigger_type,
                "website_id": site.id,
                "website_content_id": content.id,
                "target_profile_ids_json": target_ids,
                "ai_provider_id": provider.id,
                "prompt_template_id": None,
                "context_mode": mode,
                "force_regenerate": payload.force_regenerate,
                "regenerate_social_post_id": None,
                "idempotency_key": idem,
                "status": "queued",
                "attempt_count": 0,
                "max_attempts": self.settings.ai_job_max_attempts,
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="scheduler" if automatic else "admin",
            category="ai",
            action="ai_job.queued",
            level="info",
            message=(
                f"Queued social draft generation job #{job.id} ({payload.trigger_type}) "
                f"for '{content.title[:80]}' across {len(target_ids)} profile(s)."
            ),
            metadata={"job_id": job.id, "website_id": site.id, "content_id": content.id},
            ip_address=ip_address,
        )

        if dispatch:
            try:
                self.dispatcher(job.id)
            except Exception as exc:
                self.ai_repo.update_job(
                    job.id,
                    {
                        "status": "failed",
                        "completed_at": utc_now_naive(),
                        "error_code": "DISPATCH_FAILED",
                        "error_message": f"Failed to dispatch AI job worker: {exc}"[:500],
                    },
                )
                raise

        return self._to_job_response(job)

    def enqueue_auto_scan_generation(
        self,
        *,
        website: Website,
        content: WebsiteContent,
    ) -> AiGenerationJobResponse | None:
        """Called by website scanner when an eligible newly published blog post is detected."""
        if not website.auto_generate or not website.initial_scan_completed:
            return None
        if content.content_type != "blog_post" or content.extraction_status != "extracted":
            return None
        if content.is_historical_baseline:
            return None
        if website.auto_generate_require_published_at and content.published_at is None:
            return None
        if self.keyword_approval_repo is not None:
            approval = self.keyword_approval_repo.get_approval_by_content_id(content.id)
            kw = self.keyword_approval_repo.get_keyword_by_content_id(content.id)
            if (
                approval is None
                or approval.status != "approved"
                or kw is None
                or kw.approval_status != "approved"
            ):
                return None

        profiles = self.profile_repo.list_for_website(
            website.id, active_only=True, generation_only=True, automatic_only=True
        )
        if not profiles:
            return None

        # Skip profiles that already have active non-archived drafts for this article
        eligible_profiles = [
            p
            for p in profiles
            if self.post_repo.get_active_for_content_and_profile(content.id, p.id) is None
        ]
        if not eligible_profiles:
            return None

        try:
            provider = (
                self.ai_repo.get_default_provider()
            )
            if provider is None or not provider.is_active or not provider.generation_enabled:
                return None
            return self.enqueue_social_generation(
                content.id,
                GenerateSocialRequest(
                    provider_id=provider.id,
                    context_mode=website.auto_generate_context_mode or "optimized",
                    force_regenerate=False,
                    trigger_type="auto_scan",
                ),
                user_id=None,
                ip_address=None,
                dispatch=True,
            )
        except (ValidationAppError, ConflictError, AiProviderNotConfiguredError) as exc:
            logger.info("Skipped auto-generation for content #%s: %s", content.id, exc)
            return None

    def enqueue_regeneration_for_post(
        self,
        post_id: int,
        payload: SocialPostRegenerateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
        dispatch: bool = True,
    ) -> AiGenerationJobResponse:
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        if post.website_content_id is None:
            raise ValidationAppError(
                "Draft has no linked source content record to regenerate from."
            )
        content = self.content_repo.get_by_id(post.website_content_id)
        if content is None:
            raise NotFoundError("Source content for this draft no longer exists.")
        self._validate_content_eligible(content, automatic=False)

        provider = (
            self.ai_repo.get_provider_by_id(payload.provider_id)
            if payload.provider_id is not None
            else self.ai_repo.get_default_provider()
        )
        if provider is None:
            raise AiProviderNotConfiguredError()

        mode = (
            payload.context_mode
            if payload.context_mode in ALLOWED_CONTEXT_MODES
            else "optimized"
        )
        job = self.ai_repo.create_job(
            {
                "job_uuid": str(uuid.uuid4()),
                "job_type": "social_generation",
                "trigger_type": "regenerate",
                "website_id": post.website_id,
                "website_content_id": post.website_content_id,
                "target_profile_ids_json": [post.social_profile_id],
                "ai_provider_id": provider.id,
                "prompt_template_id": None,
                "context_mode": mode,
                "force_regenerate": payload.force,
                "regenerate_social_post_id": post.id,
                "idempotency_key": f"regen:{post.id}:{uuid.uuid4().hex[:12]}",
                "status": "queued",
                "attempt_count": 0,
                "max_attempts": self.settings.ai_job_max_attempts,
                "created_by": user_id,
            }
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="social_post.regenerate_queued",
            level="info",
            message=f"Queued regeneration job #{job.id} for draft #{post.id}.",
            metadata={"job_id": job.id, "social_post_id": post.id},
            ip_address=ip_address,
        )
        if dispatch:
            try:
                self.dispatcher(job.id)
            except Exception as exc:
                self.ai_repo.update_job(
                    job.id,
                    {
                        "status": "failed",
                        "completed_at": utc_now_naive(),
                        "error_code": "DISPATCH_FAILED",
                        "error_message": f"Failed to dispatch AI job worker: {exc}"[:500],
                    },
                )
                raise
        return self._to_job_response(job)

    def _guardian_allows(self) -> tuple[bool, str]:
        effective = self.settings_service.get_effective_map()
        res = self.health_service.get_system_resources(effective_settings=effective)
        if res.guardian_status == "critical":
            return False, f"Resource Guardian critical ({', '.join(res.guardian_reasons)})"
        return True, res.guardian_status

    def execute_job(self, job_id: int, *, worker_id: str | None = None) -> AiGenerationJobResponse:
        wid = worker_id or f"ai-worker:{os.getpid()}"
        self.ai_repo.recover_stale_jobs(stale_minutes=self.settings.ai_job_stale_timeout_minutes)

        ok_rg, rg_msg = self._guardian_allows()
        if not ok_rg:
            updated = self.ai_repo.update_job(
                job_id,
                {
                    "status": "deferred",
                    "defer_reason": rg_msg[:255],
                    "next_retry_at": utc_now_naive() + timedelta(minutes=2),
                },
            )
            if updated is None:
                raise NotFoundError(f"AI job #{job_id} not found.")
            return self._to_job_response(updated)

        if self.ai_repo.count_processing_jobs() >= self.settings.resource_max_concurrent_generation:
            existing = self.ai_repo.get_job_by_id(job_id)
            if existing is None:
                raise NotFoundError(f"AI job #{job_id} not found.")
            if existing.status in {"queued", "deferred"}:
                deferred = self.ai_repo.update_job(
                    job_id,
                    {
                        "status": "deferred",
                        "defer_reason": (
                            "Concurrent AI generation limit reached; queued for next slot."
                        ),
                        "next_retry_at": utc_now_naive() + timedelta(seconds=30),
                    },
                )
                assert deferred is not None
                return self._to_job_response(deferred)

        claimed = self.ai_repo.claim_job(job_id, worker_id=wid)
        if claimed is None:
            existing = self.ai_repo.get_job_by_id(job_id)
            if existing is None:
                raise NotFoundError(f"AI job #{job_id} not found.")
            return self._to_job_response(existing)

        content = (
            self.content_repo.get_by_id(claimed.website_content_id)
            if claimed.website_content_id
            else None
        )
        site = self.website_repo.get_by_id(claimed.website_id)
        if site is None or content is None:
            failed = self.ai_repo.update_job(
                claimed.id,
                {
                    "status": "failed",
                    "error_code": "MISSING_SOURCE",
                    "error_message": "Target website or source content no longer exists.",
                    "completed_at": utc_now_naive(),
                },
            )
            assert failed is not None
            return self._to_job_response(failed)

        try:
            provider, api_key = self._resolve_provider_and_key(claimed.ai_provider_id)
        except AiProviderNotConfiguredError as exc:
            failed = self.ai_repo.update_job(
                claimed.id,
                {
                    "status": "failed",
                    "error_code": exc.code,
                    "error_message": str(exc)[:500],
                    "completed_at": utc_now_naive(),
                },
            )
            assert failed is not None
            return self._to_job_response(failed)

        # Revalidate target social profiles and exclude any disabled since enqueueing
        profile_pairs: list[tuple[SocialProfile, Platform]] = []
        for pid in list(claimed.target_profile_ids_json or []):
            prof = self.profile_repo.get_by_id(int(pid))
            if (
                prof is None
                or prof.website_id != site.id
                or not prof.is_active
                or not prof.generation_enabled
            ):
                continue
            plat = self.profile_repo.get_platform_by_id(prof.platform_id)
            if plat is not None:
                profile_pairs.append((prof, plat))

        if not profile_pairs:
            failed = self.ai_repo.update_job(
                claimed.id,
                {
                    "status": "failed",
                    "error_code": "NO_ELIGIBLE_SOCIAL_PROFILES",
                    "error_message": (
                        "No social profiles configured for content generation. "
                        "Configure your website's social profiles first."
                    ),
                    "completed_at": utc_now_naive(),
                },
            )
            assert failed is not None
            return self._to_job_response(failed)

        created_draft_ids: list[int] = []
        updated_draft_ids: list[int] = []
        profile_errors: dict[int, str] = {}
        cache_hits = 0
        api_calls = 0

        # Split profiles into clean batches (<=6 per Gemini request)
        batches = [
            profile_pairs[i : i + MAX_PROFILES_PER_GEMINI_BATCH]
            for i in range(0, len(profile_pairs), MAX_PROFILES_PER_GEMINI_BATCH)
        ]

        knowledge = self.ai_repo.get_knowledge_profile(site.id)
        knowledge_version = knowledge.profile_version if knowledge else 0
        knowledge_summary = format_knowledge_summary(site, knowledge)
        cat = self.category_repo.get_by_id(site.category_id) if site.category_id else None

        pkg = prepare_article_context(
            content,
            context_mode=claimed.context_mode if provider.token_optimization_enabled else "full",
            max_optimized_chars=self.settings.content_max_context_chars,
        )
        kw_record = (
            self.keyword_approval_repo.get_keyword_by_content_id(content.id)
            if self.keyword_approval_repo is not None
            else None
        )
        focus_kp = sanitize_untrusted_text(kw_record.focus_keyphrase) if kw_record else ""
        sec_kws = (
            [
                sanitize_untrusted_text(k)
                for k in (kw_record.secondary_keywords_json or [])
                if str(k).strip()
            ]
            if kw_record
            else []
        )
        anchor_texts = (
            [
                sanitize_untrusted_text(a)
                for a in (kw_record.anchor_text_variations_json or [])
                if str(a).strip()
            ]
            if kw_record
            else []
        )
        relevant_links_str = ""
        if self.keyword_approval_repo is not None and focus_kp:
            from app.services.content_approval_service import KeywordReuseService

            reuse_svc = KeywordReuseService(
                keyword_approval_repo=self.keyword_approval_repo,
                content_repo=self.content_repo,
                website_repo=self.website_repo,
            )
            rel_links = reuse_svc.find_relevant_internal_links(
                website_id=site.id,
                exclude_content_id=content.id,
                query_phrases=[focus_kp, *sec_kws],
                limit=4,
            )
            if rel_links:
                relevant_links_str = "; ".join(
                    f"{sanitize_untrusted_text(item['recommended_anchor'])} -> {item['url']}"
                    for item in rel_links
                )
        kw_fingerprint = (
            f"v{kw_record.version}:{kw_record.approval_status}:"
            f"{kw_record.focus_keyphrase_norm}:{'|'.join(sec_kws[:10])}"
            if kw_record
            else ""
        )
        combined_keywords: list[str] = []
        seen_kw_norm: set[str] = set()
        for raw_kw in [focus_kp, *sec_kws, *(content.keywords or [])]:
            clean_kw = sanitize_untrusted_text(raw_kw)
            if clean_kw and clean_kw.lower() not in seen_kw_norm:
                seen_kw_norm.add(clean_kw.lower())
                combined_keywords.append(clean_kw)

        seo_lines: list[str] = []
        if focus_kp:
            seo_lines.append(f"Approved Focus Keyphrase: {focus_kp}")
        if sec_kws:
            seo_lines.append(f"Approved Secondary Keywords: {', '.join(sec_kws)}")
        if anchor_texts:
            seo_lines.append(f"Approved Anchor Texts: {', '.join(anchor_texts[:5])}")
        if relevant_links_str:
            seo_lines.append(f"Relevant Internal Links: {relevant_links_str}")
        effective_context_text = (
            ("\n".join(seo_lines) + "\n\n" + pkg.text) if seo_lines else pkg.text
        )

        try:
            for batch in batches:
                self.ai_repo.update_job(claimed.id, {"heartbeat_at": utc_now_naive()})

                # Skip profiles that already have non-archived drafts unless regenerating
                pending_batch: list[tuple[SocialProfile, Platform]] = []
                for prof, plat in batch:
                    if claimed.regenerate_social_post_id is None and not claimed.force_regenerate:
                        existing_draft = self.post_repo.get_active_for_content_and_profile(
                            content.id, prof.id
                        )
                        if existing_draft is not None:
                            updated_draft_ids.append(existing_draft.id)
                            continue
                    pending_batch.append((prof, plat))

                if not pending_batch:
                    continue

                prompts_map: dict[int, PromptTemplate | None] = {}
                for prof, plat in pending_batch:
                    prompts_map[prof.id] = self.ai_repo.resolve_prompt(
                        task_type="multi_platform_social",
                        platform_key=plat.platform_key,
                        website_id=site.id,
                        social_profile_id=prof.id,
                    )

                batch_prompt = (
                    prompts_map[pending_batch[0][0].id]
                    if len(pending_batch) == 1
                    else self.ai_repo.resolve_prompt(
                        task_type="multi_platform_social", website_id=site.id
                    )
                )
                sys_tpl = (
                    batch_prompt.system_instructions
                    if batch_prompt
                    else "Generate JSON social drafts cleanly."
                )
                usr_tpl = (
                    batch_prompt.user_prompt_template
                    if batch_prompt
                    else (
                        "{{ target_profiles_summary }}\n"
                        "<source_content>\n{{ optimized_context }}\n</source_content>"
                    )
                )

                profile_lines: list[str] = []
                for prof, plat in pending_batch:
                    eff_lang = prof.custom_language or site.primary_language
                    eff_tone = prof.writing_tone or site.tone or "Clear"
                    eff_limit = prof.character_limit or plat.default_max_chars
                    eff_tags = list(prof.default_hashtags or site.default_hashtags or [])
                    eff_cta = prof.default_cta or site.default_cta or ""
                    p_tpl = prompts_map.get(prof.id)
                    extra_prompt_hint = (
                        f" override_prompt={p_tpl.template_key}v{p_tpl.version}" if p_tpl else ""
                    )
                    profile_lines.append(
                        f"- social_profile_id={prof.id} | platform={plat.platform_key} | "
                        f"profile_name='{prof.profile_name}' | language={eff_lang} | "
                        f"tone='{eff_tone}' | "
                        f"preferred_length={prof.preferred_length or 'medium'} | "
                        f"character_limit={eff_limit} | "
                        f"include_source_url={prof.include_source_url} | "
                        f"include_hashtags={prof.include_hashtags} | "
                        f"include_emojis={prof.include_emojis} | "
                        f"hashtags={eff_tags} | cta='{eff_cta}' | "
                        f"instructions='{prof.platform_ai_instructions or ''}' | "
                        f"restrictions='{prof.content_restrictions or ''}'{extra_prompt_hint}"
                    )

                primary_prof, primary_plat = pending_batch[0]
                system_prompt, user_prompt = render_sandboxed_prompt(
                    system_instructions=sys_tpl,
                    user_prompt_template=usr_tpl,
                    variables={
                        "website_name": site.name,
                        "brand_name": site.brand_name or site.name,
                        "website_category": cat.name if cat else "General",
                        "website_url": f"https://{site.domain}/",
                        "website_knowledge": knowledge_summary,
                        "content_title": sanitize_untrusted_text(content.title),
                        "content_url": content.canonical_url,
                        "target_url": content.canonical_url,
                        "content_type": content.content_type,
                        "meta_description": sanitize_untrusted_text(content.meta_description or ""),
                        "optimized_context": effective_context_text,
                        "keywords": ", ".join(combined_keywords),
                        "focus_keyphrase": focus_kp,
                        "secondary_keywords": ", ".join(sec_kws),
                        "approved_anchor_texts": ", ".join(anchor_texts),
                        "relevant_internal_links": relevant_links_str,
                        "language": primary_prof.custom_language or site.primary_language,
                        "tone": primary_prof.writing_tone or site.tone or "Informative",
                        "profile_name": primary_prof.profile_name,
                        "platform": primary_plat.platform_key,
                        "character_limit": (
                            primary_prof.character_limit or primary_plat.default_max_chars or 2000
                        ),
                        "hashtags": ", ".join(
                            primary_prof.default_hashtags or site.default_hashtags or []
                        ),
                        "cta": primary_prof.default_cta or site.default_cta or "",
                        "custom_instructions": site.ai_instructions or "",
                        "target_profiles_summary": "\n".join(profile_lines),
                        "content_restrictions": (
                            f"{site.writing_guidelines or ''} "
                            f"{', '.join(site.restricted_keywords or [])}"
                        ).strip(),
                    },
                )
                if "social_profile_id=" not in user_prompt:
                    header_lines = "\n".join(profile_lines)
                    user_prompt = (
                        "Destination Profile Specifications "
                        "(echo exact social_profile_id and platform):\n"
                        f"{header_lines}\n\n{user_prompt}"
                    )

                profile_config_hash = self._profile_config_hash(
                    profiles=pending_batch, website=site, prompts_map=prompts_map
                )
                gen_settings = {
                    "temperature": provider.default_temperature,
                    "max_output_tokens": provider.max_output_tokens,
                    "auto_source_url": True,
                }
                cache_key = compute_cache_key(
                    website_id=site.id,
                    ai_provider_id=provider.id,
                    model_name=provider.selected_model,
                    task_type="multi_platform_social",
                    prompt_template_id=batch_prompt.id if batch_prompt else None,
                    prompt_version=batch_prompt.version if batch_prompt else 1,
                    source_content_hash=content.content_hash,
                    knowledge_version=knowledge_version,
                    profile_config_hash=profile_config_hash,
                    language=site.primary_language,
                    context_mode=pkg.context_mode,
                    generation_settings=gen_settings,
                    keyword_mapping_fingerprint=kw_fingerprint,
                    schema_version="v1",
                )

                est_tokens = estimate_tokens_from_text(system_prompt + user_prompt)
                cached_entry = (
                    self.cache_service.get_valid(cache_key_hash=cache_key, website_id=site.id)
                    if (provider.response_caching_enabled and not claimed.force_regenerate)
                    else None
                )

                expected_map = {p.id: (p, plat) for p, plat in pending_batch}
                if cached_entry is not None:
                    cache_hits += 1
                    self.ai_repo.record_cache_hit(cached_entry.id)
                    parsed_batch = MultiProfileSocialBatchOutput.model_validate(
                        cached_entry.response_json
                    )
                    usage_fields = resolve_usage_fields(
                        estimated_input_tokens=est_tokens, cache_hit=True
                    )
                    self.ai_repo.create_log(
                        {
                            "job_id": claimed.id,
                            "ai_provider_id": provider.id,
                            "prompt_template_id": batch_prompt.id if batch_prompt else None,
                            "website_id": site.id,
                            "website_content_id": content.id,
                            "task_type": "social_generation",
                            "model_name": cached_entry.model_name,
                            "context_mode": pkg.context_mode,
                            "cache_hit": True,
                            "cache_key_hash": cache_key,
                            "status": "succeeded",
                            **usage_fields,
                            "latency_ms": 0,
                            "truncated_input": pkg.truncated,
                            "truncation_note": pkg.truncation_note,
                        }
                    )
                else:
                    # Quota check MUST happen before invoking Gemini; never falls back to paid model
                    try:
                        self.quota_manager.ensure_available(
                            provider, planned_input_tokens=est_tokens
                        )
                    except AiQuotaExhaustedError as qexc:
                        self.ai_repo.create_log(
                            {
                                "job_id": claimed.id,
                                "ai_provider_id": provider.id,
                                "prompt_template_id": batch_prompt.id if batch_prompt else None,
                                "website_id": site.id,
                                "website_content_id": content.id,
                                "task_type": "social_generation",
                                "model_name": provider.selected_model,
                                "context_mode": pkg.context_mode,
                                "cache_hit": False,
                                "cache_key_hash": cache_key,
                                "status": "quota_blocked",
                                "estimated_input_tokens": est_tokens,
                                "token_usage_status": "unknown",
                                "truncated_input": pkg.truncated,
                                "truncation_note": pkg.truncation_note,
                                "error_code": qexc.code,
                                "error_message": str(qexc)[:500],
                            }
                        )
                        raise

                    gen_res = self.provider_client.generate_structured(
                        api_key=api_key,
                        model_name=provider.selected_model,
                        system_instruction=system_prompt,
                        user_prompt=user_prompt,
                        response_schema=MultiProfileSocialBatchOutput.model_json_schema(),
                        temperature=provider.default_temperature,
                        max_output_tokens=provider.max_output_tokens,
                        timeout_seconds=provider.request_timeout_seconds,
                    )
                    api_calls += 1
                    parsed_raw = parse_structured_response(
                        gen_res.raw_text, MultiProfileSocialBatchOutput
                    )
                    assert isinstance(parsed_raw, MultiProfileSocialBatchOutput)
                    parsed_batch = parsed_raw

                    usage_fields = resolve_usage_fields(
                        estimated_input_tokens=est_tokens, provider_result=gen_res
                    )
                    self.ai_repo.create_log(
                        {
                            "job_id": claimed.id,
                            "ai_provider_id": provider.id,
                            "prompt_template_id": batch_prompt.id if batch_prompt else None,
                            "website_id": site.id,
                            "website_content_id": content.id,
                            "task_type": "social_generation",
                            "model_name": gen_res.model_name,
                            "context_mode": pkg.context_mode,
                            "cache_hit": False,
                            "cache_key_hash": cache_key,
                            "status": "succeeded",
                            **usage_fields,
                            "latency_ms": gen_res.latency_ms,
                            "truncated_input": pkg.truncated,
                            "truncation_note": pkg.truncation_note,
                        }
                    )

                    gen_res_raw = gen_res

                accepted_drafts, batch_errors = validate_multi_profile_batch(
                    output=parsed_batch,
                    expected_profiles=expected_map,
                    source_url=content.canonical_url,
                    website_default_hashtags=list(site.default_hashtags or []),
                    website_restricted_keywords=list(site.restricted_keywords or []),
                )

                # Cache only schema-validated, complete batch responses (never cache invalid output)
                if (
                    cached_entry is None
                    and provider.response_caching_enabled
                    and not batch_errors
                    and accepted_drafts
                ):
                    self.cache_service.store(
                        cache_key_hash=cache_key,
                        ai_provider_id=provider.id,
                        website_id=site.id,
                        website_content_id=content.id,
                        prompt_template_id=batch_prompt.id if batch_prompt else None,
                        task_type="multi_platform_social",
                        model_name=gen_res_raw.model_name,
                        prompt_version=batch_prompt.version if batch_prompt else 1,
                        context_mode=pkg.context_mode,
                        language=site.primary_language,
                        source_content_hash=content.content_hash,
                        profile_config_hash=profile_config_hash,
                        generation_settings=gen_settings,
                        response_json=parsed_batch.model_dump(),
                        input_tokens=gen_res_raw.measured_input_tokens,
                        output_tokens=gen_res_raw.measured_output_tokens,
                    )

                for pid, valid_draft in accepted_drafts.items():
                    prof, plat = expected_map[pid]
                    post_id = self._persist_validated_draft(
                        claimed=claimed,
                        site=site,
                        content=content,
                        profile=prof,
                        platform=plat,
                        provider_id=provider.id,
                        model_name=provider.selected_model,
                        prompt_id=prompts_map[pid].id if prompts_map.get(pid) else None,
                        draft=valid_draft,
                    )
                    if claimed.regenerate_social_post_id == post_id:
                        updated_draft_ids.append(post_id)
                    else:
                        created_draft_ids.append(post_id)

                for pid, err_msg in batch_errors.items():
                    prof, plat = expected_map[pid]
                    profile_errors[pid] = err_msg
                    self._persist_failed_draft(
                        claimed=claimed,
                        site=site,
                        content=content,
                        profile=prof,
                        platform=plat,
                        provider_id=provider.id,
                        model_name=provider.selected_model,
                        error_msg=err_msg,
                    )

        except AiQuotaExhaustedError as exc:
            deferred = self.ai_repo.update_job(
                claimed.id,
                {
                    "status": "deferred",
                    "defer_reason": str(exc)[:255],
                    "next_retry_at": utc_now_naive() + timedelta(minutes=15),
                    "error_code": exc.code,
                    "error_message": str(exc)[:500],
                    "result_summary_json": {
                        "created_draft_ids": created_draft_ids,
                        "updated_draft_ids": updated_draft_ids,
                        "profile_errors": profile_errors,
                        "cache_hits": cache_hits,
                        "api_calls": api_calls,
                    },
                },
            )
            assert deferred is not None
            return self._to_job_response(deferred)

        except AiTransientError as exc:
            self.ai_repo.create_log(
                {
                    "job_id": claimed.id,
                    "ai_provider_id": provider.id,
                    "prompt_template_id": None,
                    "website_id": site.id,
                    "website_content_id": content.id,
                    "task_type": "social_generation",
                    "model_name": provider.selected_model,
                    "context_mode": pkg.context_mode,
                    "cache_hit": False,
                    "status": "rate_limited"
                    if exc.code == "GEMINI_RATE_LIMITED"
                    else ("timeout" if exc.code == "GEMINI_TIMEOUT" else "failed"),
                    "token_usage_status": "unknown",
                    "error_code": exc.code,
                    "error_message": str(exc)[:500],
                }
            )
            if claimed.attempt_count < claimed.max_attempts:
                backoff_secs = min(600, 30 * (2 ** max(0, claimed.attempt_count - 1)))
                deferred = self.ai_repo.update_job(
                    claimed.id,
                    {
                        "status": "deferred",
                        "defer_reason": str(exc)[:255],
                        "next_retry_at": utc_now_naive() + timedelta(seconds=backoff_secs),
                        "error_code": exc.code,
                        "error_message": str(exc)[:500],
                    },
                )
                assert deferred is not None
                return self._to_job_response(deferred)
            failed = self.ai_repo.update_job(
                claimed.id,
                {
                    "status": "failed",
                    "error_code": exc.code,
                    "error_message": str(exc)[:500],
                    "completed_at": utc_now_naive(),
                },
            )
            assert failed is not None
            return self._to_job_response(failed)

        except (AiPermanentError, AiError) as exc:
            self.ai_repo.create_log(
                {
                    "job_id": claimed.id,
                    "ai_provider_id": provider.id,
                    "prompt_template_id": None,
                    "website_id": site.id,
                    "website_content_id": content.id,
                    "task_type": "social_generation",
                    "model_name": provider.selected_model,
                    "context_mode": pkg.context_mode,
                    "cache_hit": False,
                    "status": (
                        "invalid_response"
                        if exc.code == "AI_RESPONSE_VALIDATION_ERROR"
                        else "failed"
                    ),
                    "token_usage_status": "unknown",
                    "error_code": exc.code,
                    "error_message": str(exc)[:500],
                }
            )
            failed = self.ai_repo.update_job(
                claimed.id,
                {
                    "status": "failed",
                    "error_code": exc.code,
                    "error_message": str(exc)[:500],
                    "completed_at": utc_now_naive(),
                    "result_summary_json": {
                        "created_draft_ids": created_draft_ids,
                        "updated_draft_ids": updated_draft_ids,
                        "profile_errors": profile_errors,
                        "cache_hits": cache_hits,
                        "api_calls": api_calls,
                    },
                },
            )
            assert failed is not None
            return self._to_job_response(failed)

        if profile_errors and (created_draft_ids or updated_draft_ids):
            final_status = "partially_completed"
        elif profile_errors and not (created_draft_ids or updated_draft_ids):
            final_status = "failed"
        else:
            final_status = "completed"

        finished = self.ai_repo.update_job(
            claimed.id,
            {
                "status": final_status,
                "completed_at": utc_now_naive(),
                "error_code": "PARTIAL_VALIDATION_ERROR" if profile_errors else None,
                "error_message": (
                    f"{len(profile_errors)} profile draft(s) failed validation."
                    if profile_errors
                    else None
                ),
                "result_summary_json": {
                    "created_draft_ids": created_draft_ids,
                    "updated_draft_ids": updated_draft_ids,
                    "profile_errors": profile_errors,
                    "cache_hits": cache_hits,
                    "api_calls": api_calls,
                },
            },
        )
        assert finished is not None
        return self._to_job_response(finished)

    def _persist_validated_draft(
        self,
        *,
        claimed: AiGenerationJob,
        site: Website,
        content: WebsiteContent,
        profile: SocialProfile,
        platform: Platform,
        provider_id: int,
        model_name: str,
        prompt_id: int | None,
        draft: ValidatedAssembledDraft,
    ) -> int:
        now = utc_now_naive()
        eff_lang = profile.custom_language or site.primary_language
        existing: SocialPost | None = None
        if claimed.regenerate_social_post_id is not None:
            existing = self.post_repo.get_by_id(claimed.regenerate_social_post_id)
        if existing is None:
            existing = self.post_repo.get_active_for_content_and_profile(content.id, profile.id)

        if existing is not None:
            # Never overwrite manual/approved drafts unless admin explicitly regenerated
            if claimed.regenerate_social_post_id is None and not claimed.force_regenerate:
                return existing.id
            if (
                existing.is_manually_edited or existing.status == "approved"
            ) and claimed.regenerate_social_post_id is None:
                return existing.id

            updated = self.post_repo.update_post(
                existing.id,
                {
                    "ai_generation_job_id": claimed.id,
                    "ai_provider_id": provider_id,
                    "generation_model": model_name,
                    "prompt_template_id": prompt_id,
                    "title": draft.title,
                    "caption": draft.caption,
                    "assembled_content": draft.assembled_content,
                    "hashtags_json": draft.hashtags,
                    "cta_text": draft.cta_text,
                    "source_url": draft.source_url,
                    "language": eff_lang,
                    "character_count": draft.character_count,
                    "character_limit": draft.character_limit,
                    "validation_warnings_json": draft.validation_warnings,
                    "status": "pending_review",
                    "is_manually_edited": False,
                    "error_message": None,
                    "generated_at": now,
                },
                create_revision=True,
                change_type="regenerated",
                edited_by=claimed.created_by,
                notes=f"Regenerated v{existing.current_version + 1} via job #{claimed.id}",
            )
            assert updated is not None
            return updated.id

        dedupe = compute_sha256_json(
            {"content_id": content.id, "social_profile_id": profile.id, "active": True}
        )
        created = self.post_repo.create_post(
            {
                "website_id": site.id,
                "website_content_id": content.id,
                "social_profile_id": profile.id,
                "platform_id": platform.id,
                "featured_media_id": content.featured_media_id,
                "ai_generation_job_id": claimed.id,
                "ai_provider_id": provider_id,
                "generation_model": model_name,
                "prompt_template_id": prompt_id,
                "title": draft.title,
                "caption": draft.caption,
                "assembled_content": draft.assembled_content,
                "hashtags_json": draft.hashtags,
                "cta_text": draft.cta_text,
                "source_url": draft.source_url,
                "language": eff_lang,
                "character_count": draft.character_count,
                "character_limit": draft.character_limit,
                "validation_warnings_json": draft.validation_warnings,
                "status": "pending_review",
                "is_manually_edited": False,
                "dedupe_key": dedupe,
                "generated_at": now,
            },
            change_type="initial_generated",
            edited_by=claimed.created_by,
            notes=f"Generated via job #{claimed.id}",
        )
        return created.id

    def _persist_failed_draft(
        self,
        *,
        claimed: AiGenerationJob,
        site: Website,
        content: WebsiteContent,
        profile: SocialProfile,
        platform: Platform,
        provider_id: int,
        model_name: str,
        error_msg: str,
    ) -> None:
        existing = self.post_repo.get_active_for_content_and_profile(content.id, profile.id)
        if existing is not None and (existing.status == "approved" or existing.is_manually_edited):
            return
        if existing is not None:
            self.post_repo.update_post(
                existing.id,
                {
                    "status": "generation_failed",
                    "error_message": error_msg[:500],
                    "ai_generation_job_id": claimed.id,
                },
                create_revision=False,
            )
            return
        dedupe = compute_sha256_json(
            {"content_id": content.id, "social_profile_id": profile.id, "active": True}
        )
        self.post_repo.create_post(
            {
                "website_id": site.id,
                "website_content_id": content.id,
                "social_profile_id": profile.id,
                "platform_id": platform.id,
                "featured_media_id": content.featured_media_id,
                "ai_generation_job_id": claimed.id,
                "ai_provider_id": provider_id,
                "generation_model": model_name,
                "title": content.title[:250],
                "caption": "",
                "assembled_content": "",
                "hashtags_json": [],
                "source_url": content.canonical_url,
                "language": profile.custom_language or site.primary_language,
                "character_count": 0,
                "character_limit": profile.character_limit or platform.default_max_chars,
                "validation_warnings_json": [error_msg[:220]],
                "status": "generation_failed",
                "is_manually_edited": False,
                "dedupe_key": dedupe,
                "error_message": error_msg[:500],
            },
            change_type="initial_generated",
            notes=f"Generation failed in job #{claimed.id}",
        )

    def run_pending_jobs(self, *, limit: int = 10) -> list[AiGenerationJobResponse]:
        self.ai_repo.recover_stale_jobs(stale_minutes=self.settings.ai_job_stale_timeout_minutes)
        due = self.ai_repo.list_due_jobs(limit=limit)
        results: list[AiGenerationJobResponse] = []
        for job in due:
            ok_rg, _ = self._guardian_allows()
            if not ok_rg:
                break
            results.append(self.execute_job(job.id))
        return results

    def list_jobs(
        self,
        *,
        website_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> AiGenerationJobListResponse:
        rows, total = self.ai_repo.list_jobs(
            website_id=website_id, status=status, page=page, page_size=page_size
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return AiGenerationJobListResponse(
            items=[self._to_job_response(r) for r in rows],
            meta=PaginationMeta(
                page=page, page_size=page_size, total_items=total, total_pages=total_pages
            ),
        )

    def get_job(self, job_id: int) -> AiGenerationJobResponse:
        row = self.ai_repo.get_job_by_id(job_id)
        if row is None:
            raise NotFoundError(f"AI job #{job_id} not found.")
        return self._to_job_response(row)

    def retry_job(
        self,
        job_id: int,
        *,
        user_id: int | None,
        ip_address: str | None,
        dispatch: bool = True,
    ) -> AiGenerationJobResponse:
        existing = self.ai_repo.get_job_by_id(job_id)
        if existing is None:
            raise NotFoundError(f"AI job #{job_id} not found.")
        if existing.status in {"processing", "completed"}:
            raise ConflictError(f"AI job #{job_id} is already '{existing.status}'.")

        updated = self.ai_repo.update_job(
            job_id,
            {
                "status": "queued",
                "defer_reason": None,
                "next_retry_at": None,
                "error_code": None,
                "error_message": None,
                "completed_at": None,
            },
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="ai_job.retried",
            level="info",
            message=f"Retried AI generation job #{job_id}.",
            metadata={"job_id": job_id, "website_id": updated.website_id},
            ip_address=ip_address,
        )
        if dispatch:
            self.dispatcher(job_id)
        return self._to_job_response(updated)

    def cancel_job(
        self,
        job_id: int,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> AiGenerationJobResponse:
        existing = self.ai_repo.get_job_by_id(job_id)
        if existing is None:
            raise NotFoundError(f"AI job #{job_id} not found.")
        if existing.status in {"completed", "cancelled"}:
            raise ConflictError(f"AI job #{job_id} cannot be cancelled from '{existing.status}'.")
        updated = self.ai_repo.update_job(
            job_id,
            {
                "status": "cancelled",
                "completed_at": utc_now_naive(),
            },
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="ai_job.cancelled",
            level="warning",
            message=f"Cancelled AI generation job #{job_id}.",
            metadata={"job_id": job_id, "website_id": updated.website_id},
            ip_address=ip_address,
        )
        return self._to_job_response(updated)
