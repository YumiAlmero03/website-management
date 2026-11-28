from __future__ import annotations

import math
from typing import Any

from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.social_post import SocialPost
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.social_post_repo import SocialPostRepositoryProtocol
from app.repositories.social_profile_repo import SocialProfileRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.social_post import (
    SocialPostListResponse,
    SocialPostRejectRequest,
    SocialPostResponse,
    SocialPostRevisionResponse,
    SocialPostStatsResponse,
    SocialPostUpdateRequest,
)
from app.services.ai.response_validator import (
    measure_platform_character_count,
    sanitize_hashtags,
)

ALLOWED_DRAFT_STATUSES: tuple[str, ...] = (
    "pending_review",
    "approved",
    "rejected",
    "generation_failed",
    "archived",
)


class SocialPostService:
    """Manages Phase 3 generated social drafts, editing, approvals, and version history."""

    def __init__(
        self,
        *,
        settings: Settings,
        social_post_repo: SocialPostRepositoryProtocol,
        social_profile_repo: SocialProfileRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
    ) -> None:
        self.settings = settings
        self.repo = social_post_repo
        self.profile_repo = social_profile_repo
        self.website_repo = website_repo
        self.content_repo = content_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo

    def to_response(self, row: SocialPost) -> SocialPostResponse:
        now = utc_now()
        site = self.website_repo.get_by_id(row.website_id)
        profile = self.profile_repo.get_by_id(row.social_profile_id)
        platform = self.profile_repo.get_platform_by_id(row.platform_id)
        content = (
            self.content_repo.get_by_id(row.website_content_id)
            if row.website_content_id
            else None
        )
        media = self.media_repo.get_by_id(row.featured_media_id) if row.featured_media_id else None
        featured_img_url = None
        if media is not None:
            featured_img_url = (
                f"/api/v1/media/{media.id}/file" if media.file_path else media.source_url
            )

        return SocialPostResponse(
            id=row.id,
            website_id=row.website_id,
            website_name=site.name if site else None,
            website_content_id=row.website_content_id,
            source_title=content.title if content else None,
            source_content_type=content.content_type if content else None,
            social_profile_id=row.social_profile_id,
            social_profile_name=profile.profile_name if profile else None,
            platform_id=row.platform_id,
            platform_key=platform.platform_key if platform else None,
            platform_display_name=platform.display_name if platform else None,
            featured_media_id=row.featured_media_id,
            featured_image_url=featured_img_url,
            ai_generation_job_id=row.ai_generation_job_id,
            ai_provider_id=row.ai_provider_id,
            generation_model=row.generation_model,
            prompt_template_id=row.prompt_template_id,
            title=row.title,
            caption=row.caption,
            assembled_content=row.assembled_content,
            hashtags=list(row.hashtags_json or []),
            cta_text=row.cta_text,
            source_url=row.source_url,
            language=row.language,
            character_count=row.character_count,
            character_limit=row.character_limit,
            validation_warnings=list(row.validation_warnings_json or []),
            status=row.status,
            is_manually_edited=row.is_manually_edited,
            current_version=row.current_version,
            error_message=row.error_message,
            approved_by=row.approved_by,
            approved_at=ensure_utc(row.approved_at),
            rejected_by=row.rejected_by,
            rejected_at=ensure_utc(row.rejected_at),
            rejection_reason=row.rejection_reason,
            generated_at=ensure_utc(row.generated_at),
            created_at=ensure_utc(row.created_at) or now,
            updated_at=ensure_utc(row.updated_at) or now,
        )

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
    ) -> SocialPostListResponse:
        rows, total = self.repo.list_posts(
            website_id=website_id,
            social_profile_id=social_profile_id,
            platform_id=platform_id,
            status=status,
            website_content_id=website_content_id,
            page=page,
            page_size=page_size,
        )
        raw_stats = self.repo.get_stats(
            website_id=website_id,
            social_profile_id=social_profile_id,
            platform_id=platform_id,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return SocialPostListResponse(
            items=[self.to_response(r) for r in rows],
            meta=PaginationMeta(
                page=page, page_size=page_size, total_items=total, total_pages=total_pages
            ),
            stats=SocialPostStatsResponse(**raw_stats),
        )

    def get_post(self, post_id: int) -> SocialPostResponse:
        row = self.repo.get_by_id(post_id)
        if row is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        return self.to_response(row)

    def update_post(
        self,
        post_id: int,
        payload: SocialPostUpdateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialPostResponse:
        existing = self.repo.get_by_id(post_id)
        if existing is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        site = self.website_repo.get_by_id(existing.website_id)
        profile = self.profile_repo.get_by_id(existing.social_profile_id)
        platform = self.profile_repo.get_platform_by_id(existing.platform_id)
        if profile is None or platform is None:
            raise NotFoundError("Associated social profile or platform not found.")

        if payload.status is not None and payload.status not in ALLOWED_DRAFT_STATUSES:
            raise ValidationAppError(f"Invalid draft status '{payload.status}'.")

        caption = payload.caption.strip() if payload.caption is not None else existing.caption
        title = payload.title.strip() if payload.title is not None else existing.title
        cta_text = payload.cta_text.strip() if payload.cta_text is not None else existing.cta_text
        if payload.hashtags is not None:
            hashtags = sanitize_hashtags(
                payload.hashtags,
                restricted_keywords=list(site.restricted_keywords or []) if site else [],
                include_hashtags=True,
                platform=platform,
            )
        else:
            hashtags = list(existing.hashtags_json or [])

        parts = [caption]
        if cta_text and cta_text.lower() not in caption.lower():
            parts.append(cta_text)
        if existing.source_url and existing.source_url not in caption:
            parts.append(existing.source_url)
        if hashtags:
            tag_str = " ".join(hashtags)
            if tag_str.lower() not in caption.lower():
                parts.append(tag_str)
        assembled = "\n\n".join(parts).strip()

        char_count = measure_platform_character_count(assembled, platform)
        limit = existing.character_limit
        warnings = [
            w for w in (existing.validation_warnings_json or []) if "exceeds limit" not in w.lower()
        ]
        if limit is not None and char_count > limit:
            warnings.append(
                f"Edited draft ({char_count} chars) exceeds "
                f"{platform.display_name} limit ({limit})."
            )

        updates: dict[str, Any] = {
            "title": title or None,
            "caption": caption,
            "assembled_content": assembled,
            "hashtags_json": hashtags,
            "cta_text": cta_text or None,
            "character_count": char_count,
            "validation_warnings_json": warnings,
            "is_manually_edited": True,
        }
        if payload.status is not None:
            updates["status"] = payload.status

        updated = self.repo.update_post(
            post_id,
            updates,
            create_revision=True,
            change_type="manual_edit",
            edited_by=user_id,
            notes="Edited by administrator",
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_posts",
            action="social_post.edited",
            level="info",
            message=f"Edited social draft #{updated.id} (v{updated.current_version}).",
            metadata={"social_post_id": updated.id, "website_id": updated.website_id},
            ip_address=ip_address,
        )
        return self.to_response(updated)

    def approve_post(
        self, post_id: int, *, user_id: int | None, ip_address: str | None
    ) -> SocialPostResponse:
        existing = self.repo.get_by_id(post_id)
        if existing is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        if existing.status == "generation_failed":
            raise ValidationAppError("Cannot approve a failed draft; regenerate it first.")

        updated = self.repo.update_post(
            post_id,
            {
                "status": "approved",
                "approved_by": user_id,
                "approved_at": utc_now_naive(),
                "rejected_by": None,
                "rejected_at": None,
                "rejection_reason": None,
            },
            create_revision=False,
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_posts",
            action="social_post.approved",
            level="info",
            message=f"Approved social draft #{updated.id} for review/export readiness.",
            metadata={"social_post_id": updated.id, "website_id": updated.website_id},
            ip_address=ip_address,
        )
        return self.to_response(updated)

    def reject_post(
        self,
        post_id: int,
        payload: SocialPostRejectRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialPostResponse:
        existing = self.repo.get_by_id(post_id)
        if existing is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        updated = self.repo.update_post(
            post_id,
            {
                "status": "rejected",
                "rejected_by": user_id,
                "rejected_at": utc_now_naive(),
                "rejection_reason": payload.reason.strip()[:500] if payload.reason else None,
            },
            create_revision=False,
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_posts",
            action="social_post.rejected",
            level="info",
            message=f"Rejected social draft #{updated.id}.",
            metadata={"social_post_id": updated.id, "website_id": updated.website_id},
            ip_address=ip_address,
        )
        return self.to_response(updated)

    def archive_post(
        self, post_id: int, *, user_id: int | None, ip_address: str | None
    ) -> SocialPostResponse:
        existing = self.repo.get_by_id(post_id)
        if existing is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        updated = self.repo.update_post(
            post_id,
            {"status": "archived", "dedupe_key": None},
            create_revision=False,
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_posts",
            action="social_post.archived",
            level="info",
            message=f"Archived social draft #{updated.id}.",
            metadata={"social_post_id": updated.id, "website_id": updated.website_id},
            ip_address=ip_address,
        )
        return self.to_response(updated)

    def list_revisions(self, post_id: int) -> list[SocialPostRevisionResponse]:
        if self.repo.get_by_id(post_id) is None:
            raise NotFoundError(f"Social draft #{post_id} not found.")
        return [
            SocialPostRevisionResponse(
                id=r.id,
                social_post_id=r.social_post_id,
                version_number=r.version_number,
                title=r.title,
                caption=r.caption,
                assembled_content=r.assembled_content,
                hashtags=list(r.hashtags_json or []),
                cta_text=r.cta_text,
                generation_model=r.generation_model,
                change_type=r.change_type,
                edited_by=r.edited_by,
                notes=r.notes,
                created_at=ensure_utc(r.created_at) or utc_now(),
            )
            for r in self.repo.list_revisions(post_id)
        ]
