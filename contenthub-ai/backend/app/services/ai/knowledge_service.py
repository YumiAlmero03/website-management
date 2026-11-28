from __future__ import annotations

from typing import Any

from app.config import Settings
from app.core.exceptions import NotFoundError
from app.core.security import decrypt_secret
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.website_knowledge_profile import (
    WebsiteKnowledgeProfile,
    WebsiteKnowledgeProfileRevision,
)
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.ai_repo import AiRepositoryProtocol
from app.repositories.category_repo import WebsiteCategoryRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.ai import (
    KnowledgeInternalLink,
    KnowledgeProfileGenerateRequest,
    KnowledgeProfileResponse,
    KnowledgeProfileRevisionResponse,
    KnowledgeProfileUpdateRequest,
    KnowledgeSourceRef,
)
from app.services.ai.context_builder import select_knowledge_sources
from app.services.ai.exceptions import (
    AiError,
    AiProviderNotConfiguredError,
    AiQuotaExhaustedError,
    AiTransientError,
)
from app.services.ai.prompt_builder import render_sandboxed_prompt
from app.services.ai.prompt_log import encrypt_prompt_exchange, redact_ai_log_text
from app.services.ai.provider import AiProviderClientProtocol
from app.services.ai.quota_manager import QuotaManager
from app.services.ai.response_validator import (
    WebsiteKnowledgeAnalysisOutput,
    parse_structured_response,
)
from app.services.ai.token_tracker import estimate_tokens_from_text, resolve_usage_fields

_OVERRIDEABLE_FIELDS: tuple[str, ...] = (
    "brand_name",
    "brand_description",
    "website_category",
    "business_overview",
    "products_and_services",
    "main_features",
    "target_audience",
    "target_country",
    "primary_language",
    "secondary_languages",
    "recommended_writing_tone",
    "main_keywords",
    "content_pillars",
    "important_internal_links",
    "relevant_publishing_restrictions",
    "administrator_notes",
)


class KnowledgeProfileService:
    """Manages reusable website knowledge profiles with manual override preservation."""

    def __init__(
        self,
        *,
        settings: Settings,
        ai_repo: AiRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        category_repo: WebsiteCategoryRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        provider_client: AiProviderClientProtocol,
    ) -> None:
        self.settings = settings
        self.ai_repo = ai_repo
        self.website_repo = website_repo
        self.category_repo = category_repo
        self.content_repo = content_repo
        self.activity_repo = activity_repo
        self.provider_client = provider_client
        self.quota_manager = QuotaManager(ai_repo=ai_repo, timezone_name=settings.app_timezone)

    def _compute_live_fingerprint(self, website_id: int) -> str:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            return ""
        contents = self.content_repo.list_for_website(website_id, limit=150)
        _, _, _, fingerprint = select_knowledge_sources(site, contents)
        return fingerprint

    def _to_response(
        self,
        website_id: int,
        profile: WebsiteKnowledgeProfile | None,
    ) -> KnowledgeProfileResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        cat = self.category_repo.get_by_id(site.category_id) if site.category_id else None
        live_fp = self._compute_live_fingerprint(website_id)

        if profile is None:
            return KnowledgeProfileResponse(
                id=None,
                website_id=site.id,
                website_name=site.name,
                brand_name=site.brand_name or site.name,
                brand_description=site.brand_description,
                website_category=cat.name if cat else None,
                business_overview=site.brand_description,
                target_audience=site.target_audience,
                target_country=site.target_country,
                primary_language=site.primary_language,
                secondary_languages=list(site.secondary_languages or []),
                recommended_writing_tone=site.tone,
                main_keywords=list(site.target_keywords or []),
                relevant_publishing_restrictions=site.writing_guidelines,
                content_fingerprint=live_fp,
                is_outdated=False,
                profile_version=0,
                status="not_generated",
            )

        outdated = bool(
            live_fp and profile.content_fingerprint and live_fp != profile.content_fingerprint
        )
        status = "outdated" if outdated and profile.status != "approved" else profile.status
        return KnowledgeProfileResponse(
            id=profile.id,
            website_id=profile.website_id,
            website_name=site.name,
            brand_name=profile.brand_name,
            brand_description=profile.brand_description,
            website_category=profile.website_category,
            business_overview=profile.business_overview,
            products_and_services=list(profile.products_and_services or []),
            main_features=list(profile.main_features or []),
            target_audience=profile.target_audience,
            target_country=profile.target_country,
            primary_language=profile.primary_language,
            secondary_languages=list(profile.secondary_languages or []),
            recommended_writing_tone=profile.recommended_writing_tone,
            main_keywords=list(profile.main_keywords or []),
            content_pillars=list(profile.content_pillars or []),
            important_internal_links=[
                KnowledgeInternalLink(**link) for link in (profile.important_internal_links or [])
            ],
            relevant_publishing_restrictions=profile.relevant_publishing_restrictions,
            source_content_references=[
                KnowledgeSourceRef(**ref) for ref in (profile.source_content_references or [])
            ],
            administrator_notes=profile.administrator_notes,
            manual_overrides=dict(profile.manual_overrides_json or {}),
            field_provenance=dict(profile.field_provenance_json or {}),
            content_fingerprint=profile.content_fingerprint,
            is_outdated=outdated,
            profile_version=profile.profile_version,
            last_generated_at=ensure_utc(profile.last_generated_at),
            last_reviewed_at=ensure_utc(profile.last_reviewed_at),
            approved_by=profile.approved_by,
            status=status,
            created_at=ensure_utc(profile.created_at) or utc_now(),
            updated_at=ensure_utc(profile.updated_at) or utc_now(),
        )

    def get_profile(self, website_id: int) -> KnowledgeProfileResponse:
        existing = self.ai_repo.get_knowledge_profile(website_id)
        return self._to_response(website_id, existing)

    def update_profile(
        self,
        website_id: int,
        payload: KnowledgeProfileUpdateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> KnowledgeProfileResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        cat = self.category_repo.get_by_id(site.category_id) if site.category_id else None
        existing = self.ai_repo.get_knowledge_profile(website_id)

        overrides = dict(existing.manual_overrides_json or {}) if existing else {}
        provenance = dict(existing.field_provenance_json or {}) if existing else {}

        data: dict[str, Any] = {
            "brand_name": existing.brand_name if existing else (site.brand_name or site.name),
            "brand_description": existing.brand_description if existing else site.brand_description,
            "website_category": (
                existing.website_category if existing else (cat.name if cat else None)
            ),
            "business_overview": existing.business_overview if existing else site.brand_description,
            "products_and_services": list(existing.products_and_services or []) if existing else [],
            "main_features": list(existing.main_features or []) if existing else [],
            "target_audience": existing.target_audience if existing else site.target_audience,
            "target_country": existing.target_country if existing else site.target_country,
            "primary_language": existing.primary_language if existing else site.primary_language,
            "secondary_languages": (
                list(existing.secondary_languages or [])
                if existing
                else list(site.secondary_languages or [])
            ),
            "recommended_writing_tone": (
                existing.recommended_writing_tone if existing else site.tone
            ),
            "main_keywords": (
                list(existing.main_keywords or [])
                if existing
                else list(site.target_keywords or [])
            ),
            "content_pillars": list(existing.content_pillars or []) if existing else [],
            "important_internal_links": (
                list(existing.important_internal_links or []) if existing else []
            ),
            "relevant_publishing_restrictions": (
                existing.relevant_publishing_restrictions
                if existing
                else site.writing_guidelines
            ),
            "source_content_references": (
                list(existing.source_content_references or []) if existing else []
            ),
            "administrator_notes": (
                existing.administrator_notes if existing else site.ai_instructions
            ),
            "content_fingerprint": (
                existing.content_fingerprint
                if existing and existing.content_fingerprint
                else self._compute_live_fingerprint(website_id)
            ),
            "last_generated_at": existing.last_generated_at if existing else None,
            "last_reviewed_at": utc_now_naive(),
            "approved_by": existing.approved_by if existing else None,
            "status": existing.status if existing else "draft",
        }

        raw = payload.model_dump(exclude_unset=True)
        for field in _OVERRIDEABLE_FIELDS:
            if field in raw:
                val = raw[field]
                if field == "important_internal_links" and val is not None:
                    val = [
                        v if isinstance(v, dict) else v.model_dump() for v in val
                    ]
                data[field] = val
                overrides[field] = val
                provenance[field] = "admin"

        if payload.approve:
            data["status"] = "approved"
            data["approved_by"] = user_id
            change_source = "approved"
        else:
            if data["status"] == "outdated":
                data["status"] = "generated"
            change_source = "manual_edit"

        data["manual_overrides_json"] = overrides
        data["field_provenance_json"] = provenance

        saved = self.ai_repo.save_knowledge_profile(
            website_id=website_id,
            data=data,
            change_source=change_source,
            user_id=user_id,
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="knowledge_profile.updated",
            level="info",
            message=(
                f"{'Approved' if payload.approve else 'Updated'} knowledge profile "
                f"v{saved.profile_version} for '{site.name}'."
            ),
            metadata={"website_id": website_id, "profile_version": saved.profile_version},
            ip_address=ip_address,
        )
        return self._to_response(website_id, saved)

    def generate_profile(
        self,
        website_id: int,
        payload: KnowledgeProfileGenerateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> KnowledgeProfileResponse:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        cat = self.category_repo.get_by_id(site.category_id) if site.category_id else None
        existing = self.ai_repo.get_knowledge_profile(website_id)

        contents = self.content_repo.list_for_website(website_id, limit=150)
        compact_context, source_refs, internal_links, fingerprint = select_knowledge_sources(
            site, contents
        )

        # Skip Gemini API call when up to date unless force_refresh was requested
        if (
            existing is not None
            and not payload.force_refresh
            and existing.content_fingerprint == fingerprint
            and existing.last_generated_at is not None
        ):
            return self._to_response(website_id, existing)

        provider = (
            self.ai_repo.get_provider_by_id(payload.provider_id)
            if payload.provider_id is not None
            else self.ai_repo.get_default_provider()
        )
        if provider is None:
            raise AiProviderNotConfiguredError(
                "No active Gemini configuration found for knowledge generation."
            )

        if provider.encrypted_api_key:
            api_key = decrypt_secret(provider.encrypted_api_key, self.settings.app_encryption_key)
        elif self.settings.gemini_api_key and self.settings.gemini_api_key.strip():
            api_key = self.settings.gemini_api_key.strip()
        else:
            raise AiProviderNotConfiguredError("Gemini API key is missing.")

        template = self.ai_repo.resolve_prompt(
            task_type="knowledge_analysis", website_id=website_id
        )
        sys_tpl = (
            template.system_instructions
            if template
            else "Synthesize website knowledge from data only without fabricating claims."
        )
        usr_tpl = (
            template.user_prompt_template
            if template
            else (
                "Analyze {{ brand_name }} ({{ website_url }}):\n"
                "<source_content>\n{{ optimized_context }}\n</source_content>"
            )
        )
        system_prompt, user_prompt = render_sandboxed_prompt(
            system_instructions=sys_tpl,
            user_prompt_template=usr_tpl,
            variables={
                "website_name": site.name,
                "brand_name": site.brand_name or site.name,
                "website_category": cat.name if cat else "General",
                "website_url": f"https://{site.domain}/",
                "language": site.primary_language,
                "tone": site.tone or "Clear and authentic",
                "custom_instructions": (
                    f"{site.writing_guidelines or ''} {site.ai_instructions or ''}".strip()
                ),
                "optimized_context": compact_context,
            },
        )

        est_tokens = estimate_tokens_from_text(system_prompt + user_prompt)
        try:
            self.quota_manager.ensure_available(provider, planned_input_tokens=est_tokens)
        except AiQuotaExhaustedError as exc:
            self.ai_repo.create_log(
                {
                    "job_id": None,
                    "ai_provider_id": provider.id,
                    "prompt_template_id": template.id if template else None,
                    "website_id": website_id,
                    "website_content_id": None,
                    "task_type": "knowledge_analysis",
                    "model_name": provider.selected_model,
                    "context_mode": "optimized",
                    "cache_hit": False,
                    "cache_key_hash": None,
                    "status": "quota_blocked",
                    "estimated_input_tokens": est_tokens,
                    "token_usage_status": "unknown",
                    "error_code": exc.code,
                    "error_message": str(exc)[:500],
                    "encrypted_prompt_exchange": encrypt_prompt_exchange(
                        self.settings.app_encryption_key,
                        system_instruction=system_prompt,
                        user_prompt=user_prompt,
                        api_key=api_key,
                    ),
                }
            )
            raise

        gen_res = None
        try:
            gen_res = self.provider_client.generate_structured(
                api_key=api_key,
                model_name=provider.selected_model,
                system_instruction=system_prompt,
                user_prompt=user_prompt,
                response_schema=WebsiteKnowledgeAnalysisOutput.model_json_schema(),
                temperature=min(0.4, provider.default_temperature),
                max_output_tokens=provider.max_output_tokens,
                timeout_seconds=provider.request_timeout_seconds,
            )
            parsed = parse_structured_response(gen_res.raw_text, WebsiteKnowledgeAnalysisOutput)
            assert isinstance(parsed, WebsiteKnowledgeAnalysisOutput)
        except AiError as exc:
            usage_fields = resolve_usage_fields(
                estimated_input_tokens=est_tokens, provider_result=gen_res
            )
            self.ai_repo.create_log(
                {
                    "job_id": None,
                    "ai_provider_id": provider.id,
                    "prompt_template_id": template.id if template else None,
                    "website_id": website_id,
                    "website_content_id": None,
                    "task_type": "knowledge_analysis",
                    "model_name": gen_res.model_name if gen_res else provider.selected_model,
                    "context_mode": "optimized",
                    "cache_hit": False,
                    "status": (
                        "rate_limited"
                        if exc.code == "GEMINI_RATE_LIMITED"
                        else (
                            "timeout"
                            if exc.code == "GEMINI_TIMEOUT"
                            else (
                                "invalid_response"
                                if not isinstance(exc, AiTransientError)
                                else "failed"
                            )
                        )
                    ),
                    **usage_fields,
                    "latency_ms": gen_res.latency_ms if gen_res else None,
                    "error_code": exc.code,
                    "error_message": redact_ai_log_text(str(exc), api_key)[:500],
                    "encrypted_prompt_exchange": encrypt_prompt_exchange(
                        self.settings.app_encryption_key,
                        system_instruction=system_prompt,
                        user_prompt=user_prompt,
                        response=gen_res.raw_text if gen_res else None,
                        api_key=api_key,
                    ),
                }
            )
            raise

        usage_fields = resolve_usage_fields(
            estimated_input_tokens=est_tokens, provider_result=gen_res
        )
        self.ai_repo.create_log(
            {
                "job_id": None,
                "ai_provider_id": provider.id,
                "prompt_template_id": template.id if template else None,
                "website_id": website_id,
                "website_content_id": None,
                "task_type": "knowledge_analysis",
                "model_name": gen_res.model_name,
                "context_mode": "optimized",
                "cache_hit": False,
                "status": "succeeded",
                **usage_fields,
                "latency_ms": gen_res.latency_ms,
                "encrypted_prompt_exchange": encrypt_prompt_exchange(
                    self.settings.app_encryption_key,
                    system_instruction=system_prompt,
                    user_prompt=user_prompt,
                    response=gen_res.raw_text,
                    api_key=api_key,
                ),
            }
        )

        # Merge AI output while strictly preserving manual administrator overrides
        overrides = (
            dict(existing.manual_overrides_json or {})
            if (existing is not None and payload.preserve_manual_overrides)
            else {}
        )
        provenance: dict[str, str] = {}
        ai_fields: dict[str, Any] = {
            "brand_name": site.brand_name or site.name,
            "brand_description": site.brand_description,
            "website_category": cat.name if cat else None,
            "business_overview": parsed.business_overview,
            "products_and_services": parsed.products_and_services[:20],
            "main_features": parsed.main_features[:20],
            "target_audience": parsed.target_audience or site.target_audience,
            "target_country": site.target_country,
            "primary_language": site.primary_language,
            "secondary_languages": list(site.secondary_languages or []),
            "recommended_writing_tone": parsed.recommended_writing_tone or site.tone,
            "main_keywords": parsed.main_keywords[:20] or list(site.target_keywords or []),
            "content_pillars": parsed.content_pillars[:12],
            "important_internal_links": internal_links,
            "relevant_publishing_restrictions": (
                parsed.relevant_publishing_restrictions or site.writing_guidelines
            ),
            "administrator_notes": (
                existing.administrator_notes if existing else site.ai_instructions
            ),
        }

        for k, _v in ai_fields.items():
            if k in overrides:
                ai_fields[k] = overrides[k]
                provenance[k] = "admin"
            elif k in {
                "brand_name",
                "website_category",
                "target_country",
                "primary_language",
                "secondary_languages",
                "important_internal_links",
            }:
                provenance[k] = "extracted"
            else:
                provenance[k] = "ai_generated"

        ai_fields.update(
            {
                "source_content_references": source_refs,
                "manual_overrides_json": overrides,
                "field_provenance_json": provenance,
                "content_fingerprint": fingerprint,
                "last_generated_at": utc_now_naive(),
                "last_reviewed_at": existing.last_reviewed_at if existing else None,
                "approved_by": existing.approved_by if existing else None,
                "status": "generated",
            }
        )

        saved = self.ai_repo.save_knowledge_profile(
            website_id=website_id,
            data=ai_fields,
            change_source="refreshed" if existing else "generated",
            user_id=user_id,
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="knowledge_profile.generated",
            level="info",
            message=(
                f"Generated knowledge profile v{saved.profile_version} for '{site.name}' "
                f"from {len(source_refs)} source item(s)."
            ),
            metadata={"website_id": website_id, "profile_version": saved.profile_version},
            ip_address=ip_address,
        )
        return self._to_response(website_id, saved)

    def list_revisions(self, website_id: int) -> list[KnowledgeProfileRevisionResponse]:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        rows: list[WebsiteKnowledgeProfileRevision] = (
            self.ai_repo.list_knowledge_revisions(website_id)
        )
        return [
            KnowledgeProfileRevisionResponse(
                id=r.id,
                knowledge_profile_id=r.knowledge_profile_id,
                website_id=r.website_id,
                profile_version=r.profile_version,
                snapshot_json=dict(r.snapshot_json or {}),
                content_fingerprint=r.content_fingerprint,
                change_source=r.change_source,
                created_by=r.created_by,
                created_at=ensure_utc(r.created_at) or utc_now(),
            )
            for r in rows
        ]
