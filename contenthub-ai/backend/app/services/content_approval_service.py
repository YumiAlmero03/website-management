from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any

from rapidfuzz import fuzz

from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.base import ensure_utc, utc_now, utc_now_naive
from app.models.content_approval import ContentApproval
from app.models.content_keyword import ContentKeyword
from app.models.website import Website
from app.models.website_content import WebsiteContent
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.ai_repo import AiRepositoryProtocol
from app.repositories.content_repo import ContentRepositoryProtocol
from app.repositories.keyword_approval_repo import (
    KeywordApprovalRepositoryProtocol,
    normalize_keyphrase,
)
from app.repositories.media_repo import MediaRepositoryProtocol
from app.repositories.website_repo import WebsiteRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.keyword_approval import (
    APPROVAL_ELIGIBLE_CONTENT_TYPES,
    AiKeywordRefineRequest,
    AiKeywordSuggestionPreviewResponse,
    ApproveContentRequest,
    ApproveContentResultResponse,
    ApprovedKeywordMapEntryResponse,
    BulkApproveRequest,
    BulkApproveResultResponse,
    CannibalizationMatchResponse,
    ContentApprovalDetailResponse,
    ContentApprovalHistoryResponse,
    ContentApprovalItemResponse,
    ContentApprovalListResponse,
    ContentApprovalStatsResponse,
    ContentKeywordResponse,
    ContentKeywordRevisionResponse,
    ImageAltSuggestionItem,
    KeywordMapListResponse,
    KeywordMappingUpdateRequest,
    RejectContentRequest,
    ReopenReviewRequest,
)
from app.services.ai.exceptions import AiError, AiProviderNotConfiguredError
from app.services.ai.localai import LocalAiKeywordResponseError, LocalAiProvider
from app.services.ai.prompt_log import encrypt_prompt_exchange, redact_ai_log_text
from app.services.ai.provider import AiProviderClientProtocol
from app.services.ai.token_tracker import estimate_tokens_from_text, resolve_usage_fields
from app.services.content.keyword_suggester import (
    build_synced_anchor_texts,
    detect_cannibalization_warnings,
    suggest_keywords_for_content,
)
from app.services.scanner.classifier import CONTENT_TYPES

if TYPE_CHECKING:
    from app.services.ai.generation_service import AiGenerationService


ALLOWED_APPROVAL_STATUSES: tuple[str, ...] = (
    "awaiting_extraction",
    "pending_review",
    "approved",
    "rejected",
    "needs_rereview",
)


def _clean_string_list(
    values: list[str] | None, *, exclude_norm: str = "", limit: int = 20
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if exclude_norm:
        seen.add(exclude_norm)
    for raw in values or []:
        clean = " ".join(str(raw or "").split()).strip()
        if not clean:
            continue
        norm = normalize_keyphrase(clean)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(clean[:255])
        if len(out) >= limit:
            break
    return out


def _normalize_alt_items(
    items: list[ImageAltSuggestionItem] | list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in items or []:
        if isinstance(raw, ImageAltSuggestionItem):
            out.append(raw.model_dump())
        elif isinstance(raw, dict):
            suggested = str(raw.get("suggested_alt") or "").strip()
            if not suggested:
                continue
            out.append(
                ImageAltSuggestionItem(
                    image_url=raw.get("image_url"),
                    current_alt=raw.get("current_alt"),
                    suggested_alt=suggested[:300],
                    context=raw.get("context"),
                ).model_dump()
            )
    return out[:20]


class KeywordReuseService:
    """Exposes approved website-scoped keyword mappings and internal link anchor suggestions."""

    def __init__(
        self,
        *,
        keyword_approval_repo: KeywordApprovalRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
    ) -> None:
        self.repo = keyword_approval_repo
        self.content_repo = content_repo
        self.website_repo = website_repo

    def get_approved_keyword_map(
        self,
        website_id: int,
        *,
        content_type: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> list[ApprovedKeywordMapEntryResponse]:
        site = self.website_repo.get_by_id(website_id)
        if site is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        rows, _ = self.repo.list_approved_keyword_entries(
            page=page,
            page_size=page_size,
            website_id=website_id,
            content_type=content_type,
            approved_only=True,
        )
        sibling_pairs = self._load_website_keyword_pairs(website_id)
        entries: list[ApprovedKeywordMapEntryResponse] = []
        for content, kw, _approval in rows:
            warnings = detect_cannibalization_warnings(
                content_id=content.id,
                focus_keyphrase=kw.focus_keyphrase,
                sibling_records=sibling_pairs,
            )
            entries.append(
                ApprovedKeywordMapEntryResponse(
                    website_id=content.website_id,
                    website_name=site.name,
                    content_id=content.id,
                    canonical_url=content.canonical_url,
                    title=content.title,
                    content_type=content.content_type,
                    focus_keyphrase=kw.focus_keyphrase,
                    secondary_keywords=list(kw.secondary_keywords_json or []),
                    anchor_text_variations=list(kw.anchor_text_variations_json or []),
                    image_alt_suggestions=[
                        ImageAltSuggestionItem.model_validate(item)
                        for item in (kw.image_alt_suggestions_json or [])
                        if isinstance(item, dict) and item.get("suggested_alt")
                    ],
                    approval_status=kw.approval_status,
                    keyword_version=kw.version,
                    last_reviewed_at=ensure_utc(kw.last_reviewed_at),
                    cannibalization_warnings=warnings,
                )
            )
        return entries

    def find_relevant_internal_links(
        self,
        *,
        website_id: int,
        exclude_content_id: int,
        query_phrases: list[str],
        limit: int = 5,
    ) -> list[dict[str, str]]:
        rows, _ = self.repo.list_approved_keyword_entries(
            page=1,
            page_size=100,
            website_id=website_id,
            approved_only=True,
        )
        query_blob = " ".join(p.lower() for p in query_phrases if p)
        scored: list[tuple[float, dict[str, str]]] = []
        for content, kw, _approval in rows:
            if content.id == exclude_content_id:
                continue
            anchors = list(kw.anchor_text_variations_json or [])
            anchor = anchors[0] if anchors else (kw.focus_keyphrase or content.title)
            cand_blob = f"{kw.focus_keyphrase} {' '.join(kw.secondary_keywords_json or [])}".lower()
            score = (
                float(fuzz.token_set_ratio(query_blob, cand_blob))
                if query_blob
                else 50.0
            )
            if content.content_type == "homepage":
                score += 5.0
            scored.append(
                (
                    score,
                    {
                        "title": content.title,
                        "url": content.canonical_url,
                        "focus_keyphrase": kw.focus_keyphrase,
                        "recommended_anchor": anchor,
                    },
                )
            )
        scored.sort(key=lambda pair: -pair[0])
        return [item for _score, item in scored[:limit]]

    def _load_website_keyword_pairs(
        self, website_id: int
    ) -> list[tuple[ContentKeyword, WebsiteContent]]:
        return self.repo.list_website_keyword_pairs(website_id)


class ContentApprovalService:
    """Manages content review queue, inline keyword editing during approval, and AI gating."""

    def __init__(
        self,
        *,
        settings: Settings,
        keyword_approval_repo: KeywordApprovalRepositoryProtocol,
        content_repo: ContentRepositoryProtocol,
        website_repo: WebsiteRepositoryProtocol,
        media_repo: MediaRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        ai_repo: AiRepositoryProtocol | None = None,
        provider_client: AiProviderClientProtocol | None = None,
        ai_generation_service: AiGenerationService | None = None,
    ) -> None:
        self.settings = settings
        self.repo = keyword_approval_repo
        self.content_repo = content_repo
        self.website_repo = website_repo
        self.media_repo = media_repo
        self.activity_repo = activity_repo
        self.ai_repo = ai_repo
        self.provider_client = provider_client
        self.ai_generation_service = ai_generation_service
        self.reuse_service = KeywordReuseService(
            keyword_approval_repo=keyword_approval_repo,
            content_repo=content_repo,
            website_repo=website_repo,
        )

    # ------------------------------------------------------------------
    # Scanner & Extraction Lifecycle Synchronization
    # ------------------------------------------------------------------
    def sync_discovered_content(
        self,
        *,
        content: WebsiteContent,
        website: Website,
    ) -> None:
        """Register newly discovered eligible URLs in `awaiting_extraction` state."""
        if content.is_excluded or content.content_type not in APPROVAL_ELIGIBLE_CONTENT_TYPES:
            return
        existing_app = self.repo.get_approval_by_content_id(content.id)
        if existing_app is not None:
            return

        initial_status = (
            "pending_review"
            if content.extraction_status == "extracted"
            else "awaiting_extraction"
        )
        approval, _ = self.repo.upsert_approval(
            website_id=website.id,
            website_content_id=content.id,
            data={
                "status": initial_status,
                "classified_content_type": content.content_type,
                "submitted_content_hash": content.content_hash,
            },
        )
        existing_kw = self.repo.get_keyword_by_content_id(content.id)
        if existing_kw is None:
            knowledge = (
                self.ai_repo.get_knowledge_profile(website.id) if self.ai_repo else None
            )
            suggested = suggest_keywords_for_content(
                content=content,
                website=website,
                knowledge=knowledge,
            )
            self.repo.upsert_keyword(
                website_id=website.id,
                website_content_id=content.id,
                data={
                    "focus_keyphrase": suggested.focus_keyphrase,
                    "secondary_keywords_json": suggested.secondary_keywords,
                    "anchor_text_variations_json": suggested.anchor_text_variations,
                    "image_alt_suggestions_json": suggested.image_alt_suggestions,
                    "approval_status": initial_status,
                    "suggestion_source": suggested.suggestion_source,
                    "keyword_generation_method": suggested.keyword_generation_method,
                    "keyword_generation_status": suggested.keyword_generation_status,
                    "keyword_evidence_json": suggested.keyword_evidence or [],
                    "keyword_scores_json": suggested.keyword_scores or {},
                    "keyword_model": suggested.keyword_model,
                    "keyword_generated_at": utc_now_naive(),
                    "game_name": suggested.game_name,
                    "provider_name": suggested.provider_name,
                    "is_admin_locked": False,
                },
                create_revision=True,
                change_note="Auto-created placeholder upon URL discovery",
                changed_by=None,
            )
        self.repo.record_approval_history(
            content_approval_id=approval.id,
            from_status=None,
            to_status=initial_status,
            content_type=content.content_type,
            focus_keyphrase=None,
            action="created",
            note=f"Discovered {content.content_type} URL during scan",
            acted_by=None,
        )

    def sync_extracted_content(
        self,
        *,
        content: WebsiteContent,
        website: Website,
        extracted_headings: list[str] | list[dict[str, str]] | None = None,
        extracted_images: list[dict[str, Any]] | None = None,
        featured_image_url: str | None = None,
        featured_image_alt: str | None = None,
        changed: bool = False,
    ) -> None:
        """Generate suggestions on extraction while preserving approved/rejected decisions."""
        if content.is_excluded or content.content_type not in APPROVAL_ELIGIBLE_CONTENT_TYPES:
            return

        knowledge = self.ai_repo.get_knowledge_profile(website.id) if self.ai_repo else None
        existing_app = self.repo.get_approval_by_content_id(content.id)
        existing_kw = self.repo.get_keyword_by_content_id(content.id)

        eff_feat_url = featured_image_url
        eff_feat_alt = featured_image_alt
        if not eff_feat_url and content.featured_media_id is not None:
            media = self.media_repo.get_by_id(content.featured_media_id)
            if media is not None:
                eff_feat_url = media.source_url
                if not eff_feat_alt:
                    eff_feat_alt = media.alt_text

        suggested = suggest_keywords_for_content(
            content=content,
            website=website,
            knowledge=knowledge,
            extracted_headings=extracted_headings,
            extracted_images=extracted_images,
            featured_image_url=eff_feat_url,
            featured_image_alt=eff_feat_alt,
        )

        # Unchanged approved/rejected URL: never re-request approval or overwrite keywords.
        hash_changed = bool(
            existing_app is not None
            and existing_app.submitted_content_hash
            and content.content_hash
            and existing_app.submitted_content_hash != content.content_hash
        )
        effective_changed = changed or hash_changed

        if existing_app is not None:
            if existing_app.status == "rejected" and not effective_changed:
                return
            if existing_app.status == "approved" and not effective_changed:
                return

        # Determine next queue status
        if existing_app is None:
            next_status = "pending_review"
            action_name = "created"
            hist_note = f"Extracted {content.content_type} queued for approval"
        elif existing_app.status in {"approved", "rejected"} and effective_changed:
            next_status = "needs_rereview"
            action_name = "content_changed_rereview"
            hist_note = (
                "Meaningful content update detected; returned for administrator re-review"
            )
        elif existing_app.status == "awaiting_extraction":
            next_status = "pending_review"
            action_name = "extracted_ready"
            hist_note = "Content extraction completed; ready for review"
        else:
            next_status = existing_app.status
            action_name = "extracted_ready"
            hist_note = "Content re-extracted"

        # Preserve approved or admin-locked keywords during subsequent scans!
        preserve_keywords = bool(
            existing_kw is not None
            and (existing_kw.is_admin_locked or existing_kw.approval_status == "approved")
        )
        if not preserve_keywords:
            kw_status = (
                existing_kw.approval_status
                if (existing_kw and existing_kw.approval_status == "approved")
                else next_status
            )
            saved_kw = self.repo.upsert_keyword(
                website_id=website.id,
                website_content_id=content.id,
                data={
                    "focus_keyphrase": suggested.focus_keyphrase,
                    "secondary_keywords_json": suggested.secondary_keywords,
                    "anchor_text_variations_json": suggested.anchor_text_variations,
                    "image_alt_suggestions_json": suggested.image_alt_suggestions,
                    "approval_status": kw_status,
                    "suggestion_source": suggested.suggestion_source,
                    "keyword_generation_method": suggested.keyword_generation_method,
                    "keyword_generation_status": suggested.keyword_generation_status,
                    "keyword_evidence_json": suggested.keyword_evidence or [],
                    "keyword_scores_json": suggested.keyword_scores or {},
                    "keyword_model": suggested.keyword_model,
                    "keyword_generated_at": utc_now_naive(),
                    "game_name": suggested.game_name,
                    "provider_name": suggested.provider_name,
                    "is_admin_locked": False,
                },
                create_revision=existing_kw is None,
                change_note="Python keyword suggestion from extracted content",
                changed_by=None,
            )
        else:
            saved_kw = existing_kw

        prev_status = existing_app.status if existing_app else None
        # Only create/mutate approval if status changed or newly created or content hash changed
        should_update_approval = (
            existing_app is None
            or prev_status != next_status
            or effective_changed
            or existing_app.classified_content_type != content.content_type
        )
        if should_update_approval:
            approval, old_st = self.repo.upsert_approval(
                website_id=website.id,
                website_content_id=content.id,
                data={
                    "status": next_status,
                    "classified_content_type": content.content_type,
                    "submitted_content_hash": content.content_hash,
                },
            )
            if existing_app is None or old_st != next_status or effective_changed:
                self.repo.record_approval_history(
                    content_approval_id=approval.id,
                    from_status=old_st,
                    to_status=next_status,
                    content_type=content.content_type,
                    focus_keyphrase=saved_kw.focus_keyphrase if saved_kw else None,
                    action=action_name,
                    note=hist_note,
                    acted_by=None,
                )

    # ------------------------------------------------------------------
    # Querying Queue & Details
    # ------------------------------------------------------------------
    def _ensure_records_for_content(
        self, content: WebsiteContent
    ) -> tuple[ContentApproval | None, ContentKeyword | None]:
        approval = self.repo.get_approval_by_content_id(content.id)
        kw = self.repo.get_keyword_by_content_id(content.id)
        if (
            approval is None
            and not content.is_excluded
            and content.content_type in APPROVAL_ELIGIBLE_CONTENT_TYPES
        ):
            site = self.website_repo.get_by_id(content.website_id)
            if site is not None:
                if content.extraction_status == "extracted":
                    self.sync_extracted_content(content=content, website=site)
                else:
                    self.sync_discovered_content(content=content, website=site)
                approval = self.repo.get_approval_by_content_id(content.id)
                kw = self.repo.get_keyword_by_content_id(content.id)
        return approval, kw

    def _to_keyword_response(
        self,
        kw: ContentKeyword,
        *,
        sibling_pairs: list[tuple[ContentKeyword, WebsiteContent]] | None = None,
    ) -> ContentKeywordResponse:
        warnings: list[CannibalizationMatchResponse] = []
        if sibling_pairs is not None and kw.focus_keyphrase:
            warnings = detect_cannibalization_warnings(
                content_id=kw.website_content_id,
                focus_keyphrase=kw.focus_keyphrase,
                sibling_records=sibling_pairs,
            )
        return ContentKeywordResponse(
            id=kw.id,
            website_id=kw.website_id,
            website_content_id=kw.website_content_id,
            focus_keyphrase=kw.focus_keyphrase,
            secondary_keywords=list(kw.secondary_keywords_json or []),
            anchor_text_variations=list(kw.anchor_text_variations_json or []),
            image_alt_suggestions=[
                ImageAltSuggestionItem.model_validate(item)
                for item in (kw.image_alt_suggestions_json or [])
                if isinstance(item, dict) and item.get("suggested_alt")
            ],
            approval_status=kw.approval_status,
            suggestion_source=kw.suggestion_source,
            is_admin_locked=kw.is_admin_locked,
            version=kw.version,
            cannibalization_warnings=warnings,
            last_reviewed_at=ensure_utc(kw.last_reviewed_at),
            approved_by=kw.approved_by,
            approved_at=ensure_utc(kw.approved_at),
            keyword_generation_method=getattr(kw, "keyword_generation_method", None) or "python",
            keyword_generation_status=getattr(kw, "keyword_generation_status", None) or "pending",
            keyword_evidence=list(getattr(kw, "keyword_evidence_json", None) or []),
            keyword_scores=dict(getattr(kw, "keyword_scores_json", None) or {}),
            keyword_model=getattr(kw, "keyword_model", None),
            keyword_input_hash=getattr(kw, "keyword_input_hash", None),
            keyword_generated_at=ensure_utc(getattr(kw, "keyword_generated_at", None)),
            game_name=getattr(kw, "game_name", None),
            provider_name=getattr(kw, "provider_name", None),
            created_at=ensure_utc(kw.created_at) or utc_now(),
            updated_at=ensure_utc(kw.updated_at) or utc_now(),
        )

    def _to_approval_item(
        self,
        *,
        content: WebsiteContent,
        approval: ContentApproval | None,
        kw: ContentKeyword | None,
        site: Website | None,
        sibling_pairs: list[tuple[ContentKeyword, WebsiteContent]],
    ) -> ContentApprovalItemResponse:
        featured_img_url = None
        if content.featured_media_id is not None:
            media = self.media_repo.get_by_id(content.featured_media_id)
            if media is not None:
                featured_img_url = (
                    f"/api/v1/media/{media.id}/file" if media.file_path else media.source_url
                )

        kw_resp = (
            self._to_keyword_response(kw, sibling_pairs=sibling_pairs)
            if kw is not None
            else None
        )
        warnings = kw_resp.cannibalization_warnings if kw_resp else []
        fallback_status = (
            "pending_review"
            if content.extraction_status == "extracted"
            else "awaiting_extraction"
        )
        eff_status = approval.status if approval is not None else fallback_status
        now = utc_now()
        return ContentApprovalItemResponse(
            approval_id=approval.id if approval else None,
            website_id=content.website_id,
            website_name=site.name if site else None,
            website_domain=site.domain if site else None,
            content_id=content.id,
            title=content.title,
            url=content.url,
            canonical_url=content.canonical_url,
            content_type=content.content_type,
            extraction_status=content.extraction_status,
            extraction_error=content.extraction_error,
            is_historical_baseline=content.is_historical_baseline,
            is_excluded=content.is_excluded,
            word_count=content.word_count,
            meta_title=content.title,
            meta_description=content.meta_description,
            h1_text=content.h1_text,
            language=content.language,
            optimized_context_preview=(content.optimized_context or "")[:700] or None,
            featured_image_url=featured_img_url,
            published_at=ensure_utc(content.published_at),
            first_discovered_at=ensure_utc(content.first_discovered_at),
            last_discovered_at=ensure_utc(content.last_discovered_at),
            status=eff_status,
            classified_content_type=(
                approval.classified_content_type if approval else content.content_type
            ),
            review_note=approval.review_note if approval else None,
            rejection_reason=approval.rejection_reason if approval else None,
            auto_generation_triggered_at=(
                ensure_utc(approval.auto_generation_triggered_at) if approval else None
            ),
            reviewed_by=approval.reviewed_by if approval else None,
            reviewed_at=ensure_utc(approval.reviewed_at) if approval else None,
            approved_at=ensure_utc(approval.approved_at) if approval else None,
            rejected_at=ensure_utc(approval.rejected_at) if approval else None,
            keyword_mapping=kw_resp,
            cannibalization_warnings=warnings,
            updated_at=ensure_utc(approval.updated_at if approval else content.updated_at) or now,
            created_at=ensure_utc(approval.created_at if approval else content.created_at) or now,
        )

    def get_stats(
        self, *, website_id: int | None = None, category_id: int | None = None
    ) -> ContentApprovalStatsResponse:
        counts = self.repo.get_status_counts(website_id=website_id, category_id=category_id)
        flagged = 0
        if website_id is not None:
            pairs = self.reuse_service._load_website_keyword_pairs(website_id)
            for kw, c in pairs:
                if c.is_excluded or kw.approval_status == "rejected":
                    continue
                if detect_cannibalization_warnings(
                    content_id=c.id,
                    focus_keyphrase=kw.focus_keyphrase,
                    sibling_records=pairs,
                ):
                    flagged += 1
        return ContentApprovalStatsResponse(**counts, cannibalization_flagged=flagged)

    def list_approvals(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        website_id: int | None = None,
        status: str | None = None,
        content_type: str | None = None,
        search: str | None = None,
    ) -> ContentApprovalListResponse:
        if status and status not in ALLOWED_APPROVAL_STATUSES:
            raise ValidationAppError(f"Unsupported approval status '{status}'.")
        rows, total = self.repo.list_approvals_paginated(
            page=page,
            page_size=page_size,
            website_id=website_id,
            status=status,
            content_type=content_type,
            search=search,
        )
        site_cache: dict[int, Website | None] = {}
        sibling_cache: dict[int, list[tuple[ContentKeyword, WebsiteContent]]] = {}
        items: list[ContentApprovalItemResponse] = []
        for content, approval, kw in rows:
            if approval is None and kw is None:
                approval, kw = self._ensure_records_for_content(content)
            if content.website_id not in site_cache:
                site_cache[content.website_id] = self.website_repo.get_by_id(content.website_id)
            if content.website_id not in sibling_cache:
                sibling_cache[content.website_id] = self.reuse_service._load_website_keyword_pairs(
                    content.website_id
                )
            items.append(
                self._to_approval_item(
                    content=content,
                    approval=approval,
                    kw=kw,
                    site=site_cache[content.website_id],
                    sibling_pairs=sibling_cache[content.website_id],
                )
            )
        stats = self.get_stats(website_id=website_id)
        return ContentApprovalListResponse(
            items=items,
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=max(1, math.ceil(total / page_size)),
            ),
            stats=stats,
        )

    def get_approval_detail(self, content_id: int) -> ContentApprovalDetailResponse:
        content = self.content_repo.get_by_id(content_id)
        if content is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        site = self.website_repo.get_by_id(content.website_id)
        approval, kw = self._ensure_records_for_content(content)
        siblings = self.reuse_service._load_website_keyword_pairs(content.website_id)
        base_item = self._to_approval_item(
            content=content,
            approval=approval,
            kw=kw,
            site=site,
            sibling_pairs=siblings,
        )
        kw_revs = (
            [
                ContentKeywordRevisionResponse(
                    id=r.id,
                    content_keyword_id=r.content_keyword_id,
                    revision_number=r.revision_number,
                    focus_keyphrase=r.focus_keyphrase,
                    secondary_keywords=list(r.secondary_keywords_json or []),
                    anchor_text_variations=list(r.anchor_text_variations_json or []),
                    image_alt_suggestions=[
                        ImageAltSuggestionItem.model_validate(item)
                        for item in (r.image_alt_suggestions_json or [])
                        if isinstance(item, dict) and item.get("suggested_alt")
                    ],
                    approval_status=r.approval_status,
                    suggestion_source=r.suggestion_source,
                    change_note=r.change_note,
                    changed_by=r.changed_by,
                    created_at=ensure_utc(r.created_at) or utc_now(),
                )
                for r in self.repo.list_keyword_revisions(kw.id)
            ]
            if kw is not None
            else []
        )
        app_hist = (
            [
                ContentApprovalHistoryResponse(
                    id=h.id,
                    content_approval_id=h.content_approval_id,
                    from_status=h.from_status,
                    to_status=h.to_status,
                    content_type=h.content_type,
                    focus_keyphrase=h.focus_keyphrase,
                    action=h.action,
                    note=h.note,
                    acted_by=h.acted_by,
                    created_at=ensure_utc(h.created_at) or utc_now(),
                )
                for h in self.repo.list_approval_history(approval.id)
            ]
            if approval is not None
            else []
        )
        return ContentApprovalDetailResponse(
            **base_item.model_dump(),
            markdown_content=content.markdown_content,
            extracted_content=content.extracted_content,
            yake_keywords=list(content.keywords or []),
            keyword_revisions=kw_revs,
            approval_history=app_hist,
        )

    # ------------------------------------------------------------------
    # Keyword Editing & Approval Actions (with inline editing support)
    # ------------------------------------------------------------------
    def _apply_classification_override_if_needed(
        self,
        *,
        content: WebsiteContent,
        new_content_type: str | None,
        user_id: int | None,
    ) -> WebsiteContent:
        if not new_content_type or new_content_type == content.content_type:
            return content
        if new_content_type not in CONTENT_TYPES:
            raise ValidationAppError(f"Unsupported content type '{new_content_type}'.")
        updated = self.content_repo.update(
            content.id,
            {
                "content_type": new_content_type,
                "manual_classification_override": True,
                "classification_method": "manual",
            },
        )
        assert updated is not None
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="content",
            action="content_approval.reclassified",
            level="info",
            message=(
                f"Reclassified content #{updated.id} from "
                f"'{content.content_type}' to '{new_content_type}'."
            ),
            metadata={
                "content_id": updated.id,
                "from": content.content_type,
                "to": new_content_type,
            },
        )
        return updated

    def update_keywords_inline(
        self,
        content_id: int,
        payload: KeywordMappingUpdateRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> ContentApprovalDetailResponse:
        content = self.content_repo.get_by_id(content_id)
        if content is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        content = self._apply_classification_override_if_needed(
            content=content, new_content_type=payload.content_type, user_id=user_id
        )
        approval, kw = self._ensure_records_for_content(content)

        focus = " ".join(payload.focus_keyphrase.split()).strip()[:255]
        if len(focus) < 2:
            raise ValidationAppError("Focus keyphrase must contain at least 2 characters.")
        focus_norm = normalize_keyphrase(focus)
        sec = _clean_string_list(payload.secondary_keywords, exclude_norm=focus_norm, limit=25)
        anchors = build_synced_anchor_texts(focus, sec)
        alts = _normalize_alt_items(payload.image_alt_suggestions)
        now = utc_now_naive()

        fallback_kw_status = (
            "pending_review"
            if content.extraction_status == "extracted"
            else "awaiting_extraction"
        )
        prev_status = kw.approval_status if kw else fallback_kw_status
        saved_kw = self.repo.upsert_keyword(
            website_id=content.website_id,
            website_content_id=content.id,
            data={
                "focus_keyphrase": focus,
                "secondary_keywords_json": sec,
                "anchor_text_variations_json": anchors,
                "image_alt_suggestions_json": alts,
                "approval_status": prev_status,
                "suggestion_source": "manual",
                "is_admin_locked": True,
                "last_reviewed_at": now,
                "bump_version": kw is not None,
            },
            create_revision=True,
            change_note=payload.change_note or "Edited keyword mapping manually",
            changed_by=user_id,
        )
        if approval is not None:
            updated_app, _ = self.repo.upsert_approval(
                website_id=content.website_id,
                website_content_id=content.id,
                data={
                    "classified_content_type": content.content_type,
                    "reviewed_by": user_id,
                    "reviewed_at": now,
                },
            )
            self.repo.record_approval_history(
                content_approval_id=updated_app.id,
                from_status=updated_app.status,
                to_status=updated_app.status,
                content_type=content.content_type,
                focus_keyphrase=saved_kw.focus_keyphrase,
                action="keywords_edited",
                note=payload.change_note or f"Updated focus keyphrase to '{focus}'",
                acted_by=user_id,
            )

        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="content",
            action="content_keywords.updated",
            level="info",
            message=f"Updated keyword mapping for content #{content.id}: '{focus}'.",
            metadata={"content_id": content.id, "focus_keyphrase": focus},
            ip_address=ip_address,
        )
        return self.get_approval_detail(content.id)

    def approve_content(
        self,
        content_id: int,
        payload: ApproveContentRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> ApproveContentResultResponse:
        content = self.content_repo.get_by_id(content_id)
        if content is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        if content.is_excluded:
            raise ValidationAppError("Excluded content cannot be approved.")
        if content.extraction_status != "extracted":
            raise ValidationAppError(
                "Content must finish extraction successfully before it can be approved."
            )
        site = self.website_repo.get_by_id(content.website_id)
        if site is None:
            raise NotFoundError(f"Website #{content.website_id} not found.")

        content = self._apply_classification_override_if_needed(
            content=content, new_content_type=payload.content_type, user_id=user_id
        )
        if content.content_type not in APPROVAL_ELIGIBLE_CONTENT_TYPES:
            raise ValidationAppError(
                f"Content type '{content.content_type}' is not eligible for approval. "
                f"Reclassify to {', '.join(APPROVAL_ELIGIBLE_CONTENT_TYPES)} first."
            )

        approval, kw = self._ensure_records_for_content(content)
        edited_inline = any(
            v is not None
            for v in (
                payload.focus_keyphrase,
                payload.secondary_keywords,
                payload.anchor_text_variations,
                payload.image_alt_suggestions,
                payload.content_type,
            )
        )

        # Resolve effective focus keyphrase & related keyword lists (inline edits take precedence)
        existing_focus = kw.focus_keyphrase if kw else ""
        raw_focus = (
            payload.focus_keyphrase
            if payload.focus_keyphrase is not None
            else existing_focus
        )
        eff_focus = " ".join(raw_focus.split()).strip()[:255]
        if len(eff_focus) < 2:
            knowledge = self.ai_repo.get_knowledge_profile(site.id) if self.ai_repo else None
            fallback = suggest_keywords_for_content(
                content=content, website=site, knowledge=knowledge
            )
            eff_focus = fallback.focus_keyphrase
        if len(eff_focus) < 2:
            raise ValidationAppError(
                "A non-empty focus keyphrase (at least 2 characters) is required before approving."
            )

        eff_focus_norm = normalize_keyphrase(eff_focus)
        eff_secondary = (
            _clean_string_list(payload.secondary_keywords, exclude_norm=eff_focus_norm, limit=25)
            if payload.secondary_keywords is not None
            else list(kw.secondary_keywords_json or [] if kw else [])
        )
        eff_anchors = build_synced_anchor_texts(eff_focus, eff_secondary)
        eff_alts = (
            _normalize_alt_items(payload.image_alt_suggestions)
            if payload.image_alt_suggestions is not None
            else list(kw.image_alt_suggestions_json or [] if kw else [])
        )

        # Check if keyword values changed so version bumps & stale AI cache invalidates cleanly.
        kw_values_changed = kw is None or (
            kw.focus_keyphrase != eff_focus
            or list(kw.secondary_keywords_json or []) != eff_secondary
            or list(kw.anchor_text_variations_json or []) != eff_anchors
            or list(kw.image_alt_suggestions_json or []) != eff_alts
        )
        now = utc_now_naive()
        next_source = (
            "manual"
            if (payload.focus_keyphrase is not None or payload.secondary_keywords is not None)
            else (kw.suggestion_source if kw else "python_auto")
        )
        saved_kw = self.repo.upsert_keyword(
            website_id=site.id,
            website_content_id=content.id,
            data={
                "focus_keyphrase": eff_focus,
                "secondary_keywords_json": eff_secondary,
                "anchor_text_variations_json": eff_anchors,
                "image_alt_suggestions_json": eff_alts,
                "approval_status": "approved",
                "suggestion_source": next_source,
                "is_admin_locked": True,
                "last_reviewed_at": now,
                "approved_by": user_id,
                "approved_at": now,
                "bump_version": kw is not None and kw_values_changed,
            },
            create_revision=kw is None or kw_values_changed or (kw.approval_status != "approved"),
            change_note=(
                payload.review_note
                or (
                    "Approved with inline keyword edits"
                    if edited_inline
                    else "Approved content and keywords"
                )
            ),
            changed_by=user_id,
        )

        saved_app, prev_status = self.repo.upsert_approval(
            website_id=site.id,
            website_content_id=content.id,
            data={
                "status": "approved",
                "classified_content_type": content.content_type,
                "submitted_content_hash": content.content_hash,
                "review_note": payload.review_note,
                "rejection_reason": None,
                "reviewed_by": user_id,
                "reviewed_at": now,
                "approved_at": now,
            },
        )
        self.repo.record_approval_history(
            content_approval_id=saved_app.id,
            from_status=prev_status,
            to_status="approved",
            content_type=content.content_type,
            focus_keyphrase=saved_kw.focus_keyphrase,
            action="approved_with_edits" if edited_inline else "approved",
            note=payload.review_note,
            acted_by=user_id,
        )

        auto_job_id: int | None = None
        auto_note: str | None = None
        if (
            payload.trigger_auto_generation
            and self.ai_generation_service is not None
            and saved_app.auto_generation_triggered_at is None
        ):
            if (
                site.status == "active"
                and site.auto_generate
                and site.initial_scan_completed
                and not content.is_historical_baseline
                and content.content_type == "blog_post"
                and saved_app.status == "approved"
                and saved_kw.approval_status == "approved"
            ):
                try:
                    job = self.ai_generation_service.enqueue_auto_scan_generation(
                        website=site, content=content
                    )
                    if job is not None:
                        auto_job_id = job.id
                        self.repo.upsert_approval(
                            website_id=site.id,
                            website_content_id=content.id,
                            data={"auto_generation_triggered_at": utc_now_naive()},
                        )
                        auto_note = f"Queued automatic social draft generation job #{job.id}."
                    else:
                        auto_note = "Content approved; no automatic social draft job needed."
                except Exception as exc:  # pragma: no cover - defensive guard
                    auto_note = f"Content approved; auto-generation skipped ({exc})."
            elif content.is_historical_baseline:
                auto_note = (
                    "Historical baseline content approved without automatic social generation."
                )
        elif saved_app.auto_generation_triggered_at is not None:
            auto_note = (
                "Content approved (automatic social generation already triggered previously)."
            )

        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="content",
            action="content_approval.approved",
            level="info",
            message=(
                f"Approved content #{content.id} ('{content.title[:70]}') "
                f"with focus keyphrase '{eff_focus}'."
            ),
            metadata={
                "content_id": content.id,
                "focus_keyphrase": eff_focus,
                "inline_edits": edited_inline,
                "auto_generation_job_id": auto_job_id,
            },
            ip_address=ip_address,
        )

        detail = self.get_approval_detail(content.id)
        return ApproveContentResultResponse(
            item=detail,
            auto_generation_job_id=auto_job_id,
            auto_generation_note=auto_note,
            cannibalization_warnings=detail.cannibalization_warnings,
        )

    def bulk_approve(
        self,
        payload: BulkApproveRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> BulkApproveResultResponse:
        overrides_map = {item.content_id: item for item in payload.overrides}
        approved_ids: list[int] = []
        skipped: list[dict[str, str | int]] = []
        job_ids: list[int] = []

        for cid in dict.fromkeys(payload.content_ids):
            ov = overrides_map.get(cid)
            req = ApproveContentRequest(
                focus_keyphrase=ov.focus_keyphrase if ov else None,
                secondary_keywords=ov.secondary_keywords if ov else None,
                anchor_text_variations=ov.anchor_text_variations if ov else None,
                image_alt_suggestions=ov.image_alt_suggestions if ov else None,
                content_type=ov.content_type if ov else None,
                review_note=payload.review_note,
                trigger_auto_generation=payload.trigger_auto_generation,
            )
            try:
                res = self.approve_content(
                    cid, req, user_id=user_id, ip_address=ip_address
                )
                approved_ids.append(cid)
                if res.auto_generation_job_id is not None:
                    job_ids.append(res.auto_generation_job_id)
            except (NotFoundError, ValidationAppError) as exc:
                skipped.append({"content_id": cid, "reason": str(exc)})

        return BulkApproveResultResponse(
            approved_content_ids=approved_ids,
            skipped_items=skipped,
            auto_generation_job_ids=job_ids,
            total_approved=len(approved_ids),
            total_skipped=len(skipped),
        )

    def reject_content(
        self,
        content_id: int,
        payload: RejectContentRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> ContentApprovalDetailResponse:
        content = self.content_repo.get_by_id(content_id)
        if content is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        approval, kw = self._ensure_records_for_content(content)
        now = utc_now_naive()
        reason = payload.reason.strip()[:500] if payload.reason else None

        if kw is not None:
            self.repo.upsert_keyword(
                website_id=content.website_id,
                website_content_id=content.id,
                data={
                    "approval_status": "rejected",
                    "last_reviewed_at": now,
                },
                create_revision=True,
                change_note=reason or "Keyword mapping rejected alongside content",
                changed_by=user_id,
            )

        saved_app, prev_status = self.repo.upsert_approval(
            website_id=content.website_id,
            website_content_id=content.id,
            data={
                "status": "rejected",
                "classified_content_type": content.content_type,
                "submitted_content_hash": content.content_hash,
                "rejection_reason": reason,
                "reviewed_by": user_id,
                "reviewed_at": now,
                "rejected_at": now,
            },
        )
        self.repo.record_approval_history(
            content_approval_id=saved_app.id,
            from_status=prev_status,
            to_status="rejected",
            content_type=content.content_type,
            focus_keyphrase=kw.focus_keyphrase if kw else None,
            action="rejected",
            note=reason or "Rejected by administrator",
            acted_by=user_id,
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="content",
            action="content_approval.rejected",
            level="info",
            message=f"Rejected content #{content.id} ('{content.title[:70]}').",
            metadata={"content_id": content.id, "reason": reason},
            ip_address=ip_address,
        )
        return self.get_approval_detail(content.id)

    def reopen_for_review(
        self,
        content_id: int,
        payload: ReopenReviewRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> ContentApprovalDetailResponse:
        content = self.content_repo.get_by_id(content_id)
        if content is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        approval, kw = self._ensure_records_for_content(content)
        now = utc_now_naive()
        next_status = (
            "needs_rereview" if content.extraction_status == "extracted" else "awaiting_extraction"
        )
        note = payload.note.strip()[:500] if payload.note else "Returned for administrator review"

        if kw is not None:
            self.repo.upsert_keyword(
                website_id=content.website_id,
                website_content_id=content.id,
                data={
                    "approval_status": next_status,
                    "last_reviewed_at": now,
                },
                create_revision=True,
                change_note=note,
                changed_by=user_id,
            )
        saved_app, prev_status = self.repo.upsert_approval(
            website_id=content.website_id,
            website_content_id=content.id,
            data={
                "status": next_status,
                "review_note": note,
                "reviewed_by": user_id,
                "reviewed_at": now,
            },
        )
        self.repo.record_approval_history(
            content_approval_id=saved_app.id,
            from_status=prev_status,
            to_status=next_status,
            content_type=content.content_type,
            focus_keyphrase=kw.focus_keyphrase if kw else None,
            action="returned_for_review",
            note=note,
            acted_by=user_id,
        )
        self.activity_repo.create(
            user_id=user_id,
            actor_type="admin",
            category="content",
            action="content_approval.reopened",
            level="info",
            message=f"Returned content #{content.id} to review ({next_status}).",
            metadata={"content_id": content.id, "note": note},
            ip_address=ip_address,
        )
        return self.get_approval_detail(content.id)

    def list_keyword_map(
        self,
        *,
        website_id: int | None = None,
        content_type: str | None = None,
        search: str | None = None,
        approved_only: bool = True,
        page: int = 1,
        page_size: int = 25,
    ) -> KeywordMapListResponse:
        rows, total = self.repo.list_approved_keyword_entries(
            page=page,
            page_size=page_size,
            website_id=website_id,
            content_type=content_type,
            search=search,
            approved_only=approved_only,
        )
        site_cache: dict[int, Website | None] = {}
        sibling_cache: dict[int, list[tuple[ContentKeyword, WebsiteContent]]] = {}
        items: list[ApprovedKeywordMapEntryResponse] = []
        conflicts = 0
        for content, kw, _app in rows:
            if content.website_id not in site_cache:
                site_cache[content.website_id] = self.website_repo.get_by_id(content.website_id)
            if content.website_id not in sibling_cache:
                sibling_cache[content.website_id] = self.reuse_service._load_website_keyword_pairs(
                    content.website_id
                )
            warnings = detect_cannibalization_warnings(
                content_id=content.id,
                focus_keyphrase=kw.focus_keyphrase,
                sibling_records=sibling_cache[content.website_id],
            )
            if warnings:
                conflicts += 1
            site = site_cache[content.website_id]
            items.append(
                ApprovedKeywordMapEntryResponse(
                    website_id=content.website_id,
                    website_name=site.name if site else None,
                    content_id=content.id,
                    canonical_url=content.canonical_url,
                    title=content.title,
                    content_type=content.content_type,
                    focus_keyphrase=kw.focus_keyphrase,
                    secondary_keywords=list(kw.secondary_keywords_json or []),
                    anchor_text_variations=list(kw.anchor_text_variations_json or []),
                    image_alt_suggestions=[
                        ImageAltSuggestionItem.model_validate(item)
                        for item in (kw.image_alt_suggestions_json or [])
                        if isinstance(item, dict) and item.get("suggested_alt")
                    ],
                    approval_status=kw.approval_status,
                    keyword_version=kw.version,
                    last_reviewed_at=ensure_utc(kw.last_reviewed_at),
                    cannibalization_warnings=warnings,
                )
            )
        return KeywordMapListResponse(
            items=items,
            meta=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=max(1, math.ceil(total / page_size)),
            ),
            total_cannibalization_conflicts=conflicts,
        )

    def suggest_keywords_with_ai(
        self,
        content_id: int,
        payload: AiKeywordRefineRequest,
        *,
        user_id: int | None,
        ip_address: str | None,
    ) -> AiKeywordSuggestionPreviewResponse:
        """Admin-triggered LocalAI refinement; Gemini is never used for keyword extraction."""
        content = self.content_repo.get_by_id(content_id)
        if content is None:
            raise NotFoundError(f"Content #{content_id} not found.")
        if content.extraction_status != "extracted":
            raise ValidationAppError("Extract content before requesting AI keyword suggestions.")
        if self.ai_repo is None:
            raise AiProviderNotConfiguredError("AI provider service is unavailable.")

        provider = (
            self.ai_repo.get_provider_by_id(payload.provider_id)
            if payload.provider_id is not None
            else next(
                (
                    item for item in self.ai_repo.list_providers()
                    if item.provider_type == "localai" and item.is_active
                ),
                None,
            )
        )
        if provider is None or provider.provider_type != "localai":
            raise AiProviderNotConfiguredError(
                "No active LocalAI configuration found. Configure LocalAI under AI Management."
            )
        if not provider.is_active or not provider.generation_enabled:
            raise AiProviderNotConfiguredError("The LocalAI configuration is disabled.")
        from app.core.security import decrypt_secret

        api_key = ""
        if provider.encrypted_api_key:
            api_key = decrypt_secret(provider.encrypted_api_key, self.settings.app_encryption_key)

        site = self.website_repo.get_by_id(content.website_id)
        if site is None:
            raise NotFoundError(f"Website #{content.website_id} not found.")
        knowledge = self.ai_repo.get_knowledge_profile(site.id)
        python_result = suggest_keywords_for_content(
            content=content, website=site, knowledge=knowledge
        )
        if content.content_type == "game_page":
            focus = python_result.focus_keyphrase
            secondary = python_result.secondary_keywords
            suggestion_source = "template_generated"
        else:
            page_link = (content.canonical_url or content.url or "").strip()
            focus = python_result.focus_keyphrase
            user_prompt = (
                f"Get secondary keywords in this link: {page_link}. "
                f"Do not include the main keyword: {focus}."
            )
            sys_inst = (
                "Suggest secondary keywords using only the page link in the user message. "
                "Do not use page content, excerpts, titles, or other source text. "
                "Exclude the supplied main keyword from the secondary keyword list. "
                "Preserve the page language and avoid duplicates. "
                'Return JSON only matching {"secondary_keywords": ["..."]}.'
            )
            secondary = python_result.secondary_keywords
            suggestion_source = "python_only"
            exchange = None
            error_code = None
            error_message = None
            log_status = "succeeded"
            started = time.monotonic()
            try:
                parsed, exchange = LocalAiProvider().select_keywords(
                    base_url=provider.base_url or "http://127.0.0.1:8081/v1",
                    api_key=api_key,
                    model_name=provider.selected_model,
                    system_instruction=sys_inst,
                    user_prompt=user_prompt,
                    temperature=provider.default_temperature,
                    max_output_tokens=provider.max_output_tokens,
                    timeout_seconds=provider.request_timeout_seconds,
                    max_retries=provider.max_retry_attempts,
                )
                secondary = _clean_string_list(
                    parsed.secondary_keywords,
                    exclude_norm=normalize_keyphrase(focus),
                    limit=12,
                )
                suggestion_source = "localai_assisted"
            except Exception as exc:
                if isinstance(exc, LocalAiKeywordResponseError):
                    exchange = exc.result
                error_code = exc.code if isinstance(exc, AiError) else "LOCALAI_KEYWORD_FAILED"
                error_message = (
                    str(exc) if isinstance(exc, AiError) else "Keyword refinement failed."
                )
                log_status = (
                    "invalid_response" if error_code == "LOCALAI_INVALID_RESPONSE" else "failed"
                )

            self.ai_repo.create_log({
                "ai_provider_id": provider.id,
                "website_id": site.id,
                "website_content_id": content.id,
                "task_type": "keyword_refinement",
                "model_name": exchange.model_name if exchange else provider.selected_model,
                "context_mode": "optimized",
                "cache_hit": False,
                "status": log_status,
                "latency_ms": (
                    exchange.latency_ms if exchange else int((time.monotonic() - started) * 1000)
                ),
                "error_code": error_code,
                "error_message": (
                    redact_ai_log_text(error_message, api_key)[:500] if error_message else None
                ),
                **resolve_usage_fields(
                    estimated_input_tokens=estimate_tokens_from_text(sys_inst + user_prompt),
                    provider_result=exchange,
                ),
                "encrypted_prompt_exchange": encrypt_prompt_exchange(
                    self.settings.app_encryption_key,
                    system_instruction=sys_inst,
                    user_prompt=user_prompt,
                    response=(exchange.raw_text or None) if exchange else None,
                    api_key=api_key,
                ),
            })

        existing_kw = self.repo.get_keyword_by_content_id(content.id)
        existing_alts = list(existing_kw.image_alt_suggestions_json or []) if existing_kw else []
        updated_alts = [
            ImageAltSuggestionItem.model_validate(item)
            for item in existing_alts
            if isinstance(item, dict)
        ]
        anchors = build_synced_anchor_texts(focus, secondary)

        if payload.apply_immediately:
            self.update_keywords_inline(
                content.id,
                KeywordMappingUpdateRequest(
                    focus_keyphrase=focus,
                    secondary_keywords=secondary,
                    anchor_text_variations=anchors,
                    image_alt_suggestions=updated_alts,
                    change_note=f"Applied {suggestion_source} keyword refinement",
                ),
                user_id=user_id,
                ip_address=ip_address,
            )

        return AiKeywordSuggestionPreviewResponse(
            content_id=content.id,
            focus_keyphrase=focus,
            secondary_keywords=secondary,
            anchor_text_variations=anchors,
            image_alt_suggestions=updated_alts,
            suggestion_source=suggestion_source,
            provider_name=provider.name,
            applied=payload.apply_immediately,
        )
