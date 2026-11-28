from __future__ import annotations

from typing import Any

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now
from app.models.prompt_template import PromptTemplate
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.ai_repo import AiRepositoryProtocol
from app.repositories.category_repo import WebsiteCategoryRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.keyword_approval_repo import KeywordApprovalRepositoryProtocol
from app.repositories.social_profile_repo import SocialProfileRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.ai import (
    PromptPreviewRequest,
    PromptPreviewResponse,
    PromptTemplateCreateRequest,
    PromptTemplateResponse,
    PromptTemplateRevisionResponse,
    PromptTemplateUpdateRequest,
)
from app.services.ai.context_builder import format_knowledge_summary, prepare_article_context
from app.services.ai.defaults import ALLOWED_PROMPT_VARIABLES, PROMPT_TASK_TYPES
from app.services.ai.prompt_builder import render_sandboxed_prompt, validate_template_source
from app.services.ai.token_tracker import estimate_tokens_from_text


class PromptManagerService:
    """Manages editable sandboxed prompt templates, overrides, versioning, and offline previews."""

    def __init__(
        self,
        *,
        ai_repo: AiRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        category_repo: WebsiteCategoryRepositoryProtocol,
        social_profile_repo: SocialProfileRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        keyword_approval_repo: KeywordApprovalRepositoryProtocol | None = None,
    ) -> None:
        self.ai_repo = ai_repo
        self.website_repo = website_repo
        self.category_repo = category_repo
        self.social_profile_repo = social_profile_repo
        self.content_repo = content_repo
        self.activity_repo = activity_repo
        self.keyword_approval_repo = keyword_approval_repo

    def _to_response(self, row: PromptTemplate) -> PromptTemplateResponse:
        now = utc_now()
        site = self.website_repo.get_by_id(row.website_id) if row.website_id else None
        profile = (
            self.social_profile_repo.get_by_id(row.social_profile_id)
            if row.social_profile_id
            else None
        )
        return PromptTemplateResponse(
            id=row.id,
            template_key=row.template_key,
            scope_key=row.scope_key,
            name=row.name,
            task_type=row.task_type,
            platform_key=row.platform_key,
            website_id=row.website_id,
            website_name=site.name if site else None,
            social_profile_id=row.social_profile_id,
            social_profile_name=profile.profile_name if profile else None,
            system_instructions=row.system_instructions,
            user_prompt_template=row.user_prompt_template,
            available_variables=list(row.available_variables_json or ALLOWED_PROMPT_VARIABLES),
            response_schema_name=row.response_schema_name,
            version=row.version,
            is_active=row.is_active,
            is_system_default=row.is_system_default,
            created_at=ensure_utc(row.created_at) or now,
            updated_at=ensure_utc(row.updated_at) or now,
        )

    def list_prompts(
        self,
        *,
        task_type: str | None = None,
        website_id: int | None = None,
        social_profile_id: int | None = None,
    ) -> list[PromptTemplateResponse]:
        rows = self.ai_repo.list_prompts(
            task_type=task_type, website_id=website_id, social_profile_id=social_profile_id
        )
        return [self._to_response(r) for r in rows]

    def create_prompt(
        self,
        payload: PromptTemplateCreateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> PromptTemplateResponse:
        if payload.task_type not in PROMPT_TASK_TYPES:
            raise ValidationAppError(f"Unsupported task_type '{payload.task_type}'.")

        validate_template_source(payload.system_instructions, label="system_instructions")
        validate_template_source(payload.user_prompt_template, label="user_prompt_template")

        scope_key = "global"
        website_id = payload.website_id
        if payload.social_profile_id is not None:
            prof = self.social_profile_repo.get_by_id(payload.social_profile_id)
            if prof is None:
                raise NotFoundError(f"Social profile #{payload.social_profile_id} not found.")
            website_id = prof.website_id
            scope_key = f"profile:{prof.id}"
        elif website_id is not None:
            site = self.website_repo.get_by_id(website_id)
            if site is None:
                raise NotFoundError(f"Website #{website_id} not found.")
            scope_key = f"website:{site.id}"

        clean_key = payload.template_key.strip().lower()
        if self.ai_repo.get_prompt_by_key_scope(clean_key, scope_key) is not None:
            raise ConflictError(
                f"Prompt template '{clean_key}' already exists for scope '{scope_key}'."
            )

        created = self.ai_repo.create_prompt(
            {
                "template_key": clean_key,
                "scope_key": scope_key,
                "name": payload.name.strip(),
                "task_type": payload.task_type,
                "platform_key": (
                    payload.platform_key.strip().lower() if payload.platform_key else None
                ),
                "website_id": website_id,
                "social_profile_id": payload.social_profile_id,
                "system_instructions": payload.system_instructions.strip(),
                "user_prompt_template": payload.user_prompt_template.strip(),
                "available_variables_json": list(ALLOWED_PROMPT_VARIABLES),
                "response_schema_name": payload.response_schema_name,
                "version": 1,
                "is_active": payload.is_active,
                "is_system_default": False,
            },
            user_id=user_id,
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="prompt_template.created",
            level="info",
            message=f"Created prompt template '{created.name}' ({created.scope_key}).",
            metadata={"prompt_id": created.id, "scope": created.scope_key},
            ip_address=ip_address,
        )
        return self._to_response(created)

    def update_prompt(
        self,
        prompt_id: int,
        payload: PromptTemplateUpdateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> PromptTemplateResponse:
        existing = self.ai_repo.get_prompt_by_id(prompt_id)
        if existing is None:
            raise NotFoundError(f"Prompt template #{prompt_id} not found.")

        updates: dict[str, Any] = {}
        if payload.name is not None:
            updates["name"] = payload.name.strip()
        if payload.system_instructions is not None:
            validate_template_source(payload.system_instructions, label="system_instructions")
            updates["system_instructions"] = payload.system_instructions.strip()
        if payload.user_prompt_template is not None:
            validate_template_source(payload.user_prompt_template, label="user_prompt_template")
            updates["user_prompt_template"] = payload.user_prompt_template.strip()
        if payload.is_active is not None:
            updates["is_active"] = payload.is_active

        updated = self.ai_repo.update_prompt(
            prompt_id, updates, user_id=user_id, change_note=payload.change_note
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="ai",
            action="prompt_template.updated",
            level="info",
            message=f"Updated prompt '{updated.name}' to v{updated.version}.",
            metadata={"prompt_id": updated.id, "version": updated.version},
            ip_address=ip_address,
        )
        return self._to_response(updated)

    def list_revisions(self, prompt_id: int) -> list[PromptTemplateRevisionResponse]:
        if self.ai_repo.get_prompt_by_id(prompt_id) is None:
            raise NotFoundError(f"Prompt template #{prompt_id} not found.")
        return [
            PromptTemplateRevisionResponse(
                id=r.id,
                prompt_template_id=r.prompt_template_id,
                version=r.version,
                system_instructions=r.system_instructions,
                user_prompt_template=r.user_prompt_template,
                change_note=r.change_note,
                created_by=r.created_by,
                created_at=ensure_utc(r.created_at) or utc_now(),
            )
            for r in self.ai_repo.list_prompt_revisions(prompt_id)
        ]

    def preview_prompt(
        self, prompt_id: int, payload: PromptPreviewRequest
    ) -> PromptPreviewResponse:
        template = self.ai_repo.get_prompt_by_id(prompt_id)
        if template is None:
            raise NotFoundError(f"Prompt template #{prompt_id} not found.")

        site = self.website_repo.get_by_id(payload.website_id) if payload.website_id else None
        content = (
            self.content_repo.get_by_id(payload.website_content_id)
            if payload.website_content_id
            else None
        )
        profile = (
            self.social_profile_repo.get_by_id(payload.social_profile_id)
            if payload.social_profile_id
            else None
        )
        if content and site is None:
            site = self.website_repo.get_by_id(content.website_id)
        if profile and site is None:
            site = self.website_repo.get_by_id(profile.website_id)

        knowledge = self.ai_repo.get_knowledge_profile(site.id) if site else None
        cat = (
            self.category_repo.get_by_id(site.category_id)
            if (site and site.category_id)
            else None
        )

        pkg = (
            prepare_article_context(content, context_mode=payload.context_mode)
            if content
            else None
        )
        kw_record = (
            self.keyword_approval_repo.get_keyword_by_content_id(content.id)
            if (content is not None and self.keyword_approval_repo is not None)
            else None
        )
        fallback_focus = (
            content.keywords[0] if content and content.keywords else "Sample Focus Keyphrase"
        )
        focus_kp = (
            kw_record.focus_keyphrase
            if kw_record and kw_record.focus_keyphrase
            else fallback_focus
        )
        fallback_sec = (
            list(content.keywords[1:5])
            if content and content.keywords
            else ["secondary seo term"]
        )
        sec_kws = (
            list(kw_record.secondary_keywords_json or [])
            if kw_record
            else fallback_sec
        )
        anchors = (
            list(kw_record.anchor_text_variations_json or [])
            if kw_record
            else [focus_kp, f"{focus_kp} guide"]
        )
        variables: dict[str, Any] = {
            "website_name": site.name if site else "Sample Website",
            "brand_name": (site.brand_name or site.name) if site else "Sample Brand",
            "website_category": cat.name if cat else "General",
            "website_url": f"https://{site.domain}/" if site else "https://example.com/",
            "website_knowledge": (
                format_knowledge_summary(site, knowledge)
                if site
                else "Sample reusable brand & website knowledge context."
            ),
            "content_title": content.title if content else "Sample Blog Post Title",
            "content_url": content.canonical_url if content else "https://example.com/blog/sample",
            "target_url": content.canonical_url if content else "https://example.com/blog/sample",
            "content_type": content.content_type if content else "blog_post",
            "meta_description": (content.meta_description if content else "") or "",
            "optimized_context": (
                pkg.text if pkg else "Compact Python-prepared context summary for preview."
            ),
            "keywords": ", ".join((content.keywords or []) if content else ["sample", "seo"]),
            "focus_keyphrase": focus_kp,
            "secondary_keywords": ", ".join(sec_kws),
            "approved_anchor_texts": ", ".join(anchors),
            "relevant_internal_links": "",
            "language": (
                (profile.custom_language if profile and profile.custom_language else None)
                or (site.primary_language if site else "en")
            ),
            "tone": (
                (profile.writing_tone if profile and profile.writing_tone else None)
                or (site.tone if site else "Informative")
            ),
            "profile_name": profile.profile_name if profile else "Sample Social Profile",
            "platform": template.platform_key or "multi_platform",
            "character_limit": (
                profile.character_limit if profile and profile.character_limit else 1500
            ),
            "hashtags": ", ".join(
                (profile.default_hashtags if profile and profile.default_hashtags else None)
                or (site.default_hashtags if site and site.default_hashtags else ["#ContentHub"])
            ),
            "cta": (
                (profile.default_cta if profile and profile.default_cta else None)
                or (site.default_cta if site else "Read more")
                or ""
            ),
            "custom_instructions": (
                (profile.platform_ai_instructions if profile else None)
                or (site.ai_instructions if site else "")
                or ""
            ),
            "target_profiles_summary": "- profile_id=1 | platform=facebook | name='Sample Page'",
            "content_restrictions": (
                (profile.content_restrictions if profile else None)
                or (site.writing_guidelines if site else "")
                or ""
            ),
        }

        sys_src = payload.system_instructions_override or template.system_instructions
        usr_src = payload.user_prompt_template_override or template.user_prompt_template
        sys_rendered, usr_rendered = render_sandboxed_prompt(
            system_instructions=sys_src,
            user_prompt_template=usr_src,
            variables=variables,
        )
        return PromptPreviewResponse(
            template_id=template.id,
            scope_used=template.scope_key,
            system_prompt=sys_rendered,
            user_prompt=usr_rendered,
            context_mode=payload.context_mode,
            estimated_input_tokens=estimate_tokens_from_text(sys_rendered + usr_rendered),
            variables_used=variables,
        )
