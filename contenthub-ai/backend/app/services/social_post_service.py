from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.social_post import SocialPost
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.keyword_approval_repo import KeywordApprovalRepositoryProtocol
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.publishing_repo import PublishingRepositoryProtocol
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
    SocialPostTestDraftRequest,
    SocialPostUpdateRequest,
)
from app.services.ai.response_validator import (
    measure_platform_character_count,
    sanitize_hashtags,
)
from app.services.publishers.validator import build_utm_url

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
        publishing_repo: PublishingRepositoryProtocol | None = None,
        keyword_approval_repo: KeywordApprovalRepositoryProtocol | None = None,
    ) -> None:
        self.settings = settings
        self.repo = social_post_repo
        self.profile_repo = social_profile_repo
        self.website_repo = website_repo
        self.content_repo = content_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo
        self.pub_repo = publishing_repo
        self.keyword_repo = keyword_approval_repo

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
        kw = (
            self.keyword_repo.get_keyword_by_content_id(row.website_content_id)
            if row.website_content_id and self.keyword_repo is not None
            else None
        )
        media = self.media_repo.get_by_id(row.featured_media_id) if row.featured_media_id else None
        featured_img_url = None
        if media is not None:
            featured_img_url = (
                f"/api/v1/media/{media.id}/file" if media.file_path else media.source_url
            )
        extra_media = self.pub_repo.list_post_media(row.id) if self.pub_repo is not None else []
        media_count = len(extra_media) if extra_media else (1 if media is not None else 0)

        return SocialPostResponse(
            id=row.id,
            website_id=row.website_id,
            website_name=site.name if site else None,
            website_content_id=row.website_content_id,
            source_title=content.title if content else None,
            source_content_type=content.content_type if content else None,
            focus_keyphrase=kw.focus_keyphrase if kw else None,
            social_profile_id=row.social_profile_id,
            social_profile_name=profile.profile_name if profile else None,
            publishing_method=profile.publishing_method if profile else None,
            platform_id=row.platform_id,
            platform_key=platform.platform_key if platform else None,
            platform_display_name=platform.display_name if platform else None,
            featured_media_id=row.featured_media_id,
            featured_image_url=featured_img_url,
            media_count=media_count,
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
            publishing_status=row.publishing_status,
            approved_revision_id=row.approved_revision_id,
            alternative_captions=list(row.alternative_captions_json or []),
            utm_params=dict(row.utm_params_json or {}),
            target_url_with_utm=row.target_url_with_utm,
            scheduled_for=ensure_utc(row.scheduled_for),
            display_timezone=row.display_timezone,
            published_at=ensure_utc(row.published_at),
            external_post_id=row.external_post_id,
            published_url=row.published_url,
            verification_status=row.verification_status,
            last_publish_error=row.last_publish_error,
            last_publish_attempt_at=ensure_utc(row.last_publish_attempt_at),
            is_manually_edited=bool(row.is_manually_edited),
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
        publishing_status: str | None = None,
        view: str | None = None,
        website_content_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> SocialPostListResponse:
        rows, total = self.repo.list_posts(
            website_id=website_id,
            social_profile_id=social_profile_id,
            platform_id=platform_id,
            status=status,
            publishing_status=publishing_status,
            view=view,
            website_content_id=website_content_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
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

    def create_test_draft(
        self,
        profile_id: int,
        payload: SocialPostTestDraftRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> SocialPostResponse:
        profile = self.profile_repo.get_by_id(profile_id)
        if profile is None:
            raise NotFoundError(f"Social profile #{profile_id} not found.")
        site = self.website_repo.get_by_id(profile.website_id)
        platform = self.profile_repo.get_platform_by_id(profile.platform_id)
        if site is None or platform is None:
            raise NotFoundError("Associated website or platform not found.")

        caption = payload.caption
        recent_contents = self.content_repo.list_recent_for_website(site.id, limit=1)
        reference_content = recent_contents[0] if recent_contents else None
        source_url = (
            str(reference_content.canonical_url or reference_content.url).strip()
            if reference_content and (reference_content.canonical_url or reference_content.url)
            else None
        )

        media_asset_id = (
            reference_content.featured_media_id if reference_content is not None else None
        )
        if media_asset_id is None:
            media_rows, _ = self.media_repo.list_paginated(
                page=1,
                page_size=1,
                website_id=site.id,
            )
            if media_rows:
                media_asset_id = media_rows[0].id

        assembled_content = caption
        if source_url and source_url not in caption:
            assembled_content = f"{caption}\n\n{source_url}".strip()

        char_count = measure_platform_character_count(caption, platform)
        limit = profile.character_limit or platform.default_max_chars
        warnings = []
        if limit is not None and char_count > limit:
            warnings.append(
                f"Test draft ({char_count} chars) exceeds {platform.display_name} limit ({limit})."
            )

        row = self.repo.create_post(
            {
                "website_id": site.id,
                "website_content_id": reference_content.id if reference_content else None,
                "social_profile_id": profile.id,
                "platform_id": platform.id,
                "title": "Test post",
                "caption": caption,
                "assembled_content": assembled_content,
                "source_url": source_url,
                "featured_media_id": media_asset_id,
                "hashtags_json": [],
                "language": profile.custom_language or site.primary_language,
                "character_count": char_count,
                "character_limit": limit,
                "validation_warnings_json": warnings,
                "status": "pending_review",
                "publishing_status": "unscheduled",
                "is_manually_edited": True,
            },
            change_type="manual_create",
            edited_by=user_id,
            notes="Created from the social profile Test Post action.",
        )
        if media_asset_id is not None and self.pub_repo is not None:
            asset = self.media_repo.get_by_id(media_asset_id)
            if asset is not None:
                self.pub_repo.add_post_media(
                    {
                        "social_post_id": row.id,
                        "media_asset_id": asset.id,
                        "sort_order": 0,
                        "role": "primary",
                        "alt_text": asset.alt_text,
                    }
                )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="social_posts",
            action="social_post.test_draft_created",
            level="info",
            message=f"Created test draft #{row.id} for social profile #{profile.id}.",
            metadata={"social_post_id": row.id, "social_profile_id": profile.id},
            ip_address=ip_address,
        )
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
        source_url = (
            payload.source_url.strip() or None
            if payload.source_url is not None
            else existing.source_url
        )
        utm_params = (
            {
                str(k).strip(): str(v).strip()
                for k, v in payload.utm_params.items()
                if str(v).strip()
            }
            if payload.utm_params is not None
            else dict(existing.utm_params_json or {})
        )
        target_with_utm = build_utm_url(source_url, utm_params) if source_url else None
        alt_captions = (
            [str(c).strip() for c in payload.alternative_captions if str(c).strip()]
            if payload.alternative_captions is not None
            else list(existing.alternative_captions_json or [])
        )
        featured_media_id = existing.featured_media_id
        if payload.clear_featured_media:
            featured_media_id = None
        elif payload.featured_media_id is not None:
            featured_media_id = payload.featured_media_id

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
        effective_link = target_with_utm or source_url
        if effective_link and effective_link not in caption:
            parts.append(effective_link)
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

        material_changed = (
            caption != existing.caption
            or (title or None) != existing.title
            or (cta_text or None) != existing.cta_text
            or hashtags != list(existing.hashtags_json or [])
            or source_url != existing.source_url
            or target_with_utm != existing.target_url_with_utm
            or featured_media_id != existing.featured_media_id
        )
        invalidated_approval = existing.status == "approved" and material_changed

        updates: dict[str, Any] = {
            "title": title or None,
            "caption": caption,
            "assembled_content": assembled,
            "hashtags_json": hashtags,
            "cta_text": cta_text or None,
            "source_url": source_url,
            "utm_params_json": utm_params,
            "target_url_with_utm": target_with_utm,
            "alternative_captions_json": alt_captions,
            "featured_media_id": featured_media_id,
            "character_count": char_count,
            "validation_warnings_json": warnings,
            "is_manually_edited": True,
        }
        if invalidated_approval:
            updates["status"] = "pending_review"
            updates["approved_by"] = None
            updates["approved_at"] = None
            updates["approved_revision_id"] = None
            updates["publishing_status"] = "pending_approval"
            updates["scheduled_for"] = None
            if self.pub_repo is not None:
                for sched in self.pub_repo.list_active_schedules_for_post(post_id):
                    self.pub_repo.update_schedule(
                        sched.id,
                        {
                            "status": "cancelled",
                            "cancel_reason": "Cancelled automatically due to material draft edit.",
                        },
                    )
                active_job = self.pub_repo.get_active_job_for_post(post_id)
                if active_job and active_job.status in {"queued", "deferred"}:
                    self.pub_repo.update_job(
                        active_job.id,
                        {
                            "status": "cancelled",
                            "error_message": "Cancelled due to material draft edit.",
                            "completed_at": utc_now_naive(),
                        },
                    )
        elif payload.status is not None:
            updates["status"] = payload.status
            if payload.status == "archived":
                updates["publishing_status"] = "archived"
                updates["dedupe_key"] = None

        edit_note = (
            "Material edit by administrator — prior approval invalidated"
            if invalidated_approval
            else "Edited by administrator"
        )
        updated = self.repo.update_post(
            post_id,
            updates,
            create_revision=True,
            change_type="manual_edit",
            edited_by=user_id,
            notes=edit_note,
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

        revs = self.repo.list_revisions(post_id)
        latest_rev_id = revs[0].id if revs else None
        next_pub_status = (
            existing.publishing_status
            if existing.publishing_status in {"published", "manually_published", "scheduled"}
            else "approved"
        )
        updated = self.repo.update_post(
            post_id,
            {
                "status": "approved",
                "publishing_status": next_pub_status,
                "approved_revision_id": latest_rev_id,
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
                "publishing_status": "unscheduled",
                "approved_revision_id": None,
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
            {"status": "archived", "publishing_status": "archived", "dedupe_key": None},
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
