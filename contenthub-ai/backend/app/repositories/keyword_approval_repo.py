from __future__ import annotations

import re
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.content_approval import ContentApproval, ContentApprovalHistory
from app.models.content_keyword import ContentKeyword, ContentKeywordRevision
from app.models.website_content import WebsiteContent
from app.schemas.keyword_approval import APPROVAL_ELIGIBLE_CONTENT_TYPES


def normalize_keyphrase(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()[:255]


class KeywordApprovalRepositoryProtocol(Protocol):
    def get_keyword_by_content_id(self, content_id: int) -> ContentKeyword | None: ...
    def list_keywords_for_website(
        self, website_id: int, *, approval_status: str | None = None
    ) -> list[ContentKeyword]: ...
    def upsert_keyword(
        self,
        *,
        website_id: int,
        website_content_id: int,
        data: dict[str, Any],
        create_revision: bool = True,
        change_note: str | None = None,
        changed_by: int | None = None,
    ) -> ContentKeyword: ...
    def list_keyword_revisions(self, content_keyword_id: int) -> list[ContentKeywordRevision]: ...

    def get_approval_by_content_id(self, content_id: int) -> ContentApproval | None: ...
    def upsert_approval(
        self,
        *,
        website_id: int,
        website_content_id: int,
        data: dict[str, Any],
    ) -> tuple[ContentApproval, str | None]: ...
    def record_approval_history(
        self,
        *,
        content_approval_id: int,
        from_status: str | None,
        to_status: str,
        content_type: str | None,
        focus_keyphrase: str | None,
        action: str,
        note: str | None,
        acted_by: int | None,
    ) -> ContentApprovalHistory: ...
    def list_approval_history(self, content_approval_id: int) -> list[ContentApprovalHistory]: ...
    def get_status_counts(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> dict[str, int]: ...
    def list_approvals_paginated(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
        status: str | None = None,
        content_type: str | None = None,
        search: str | None = None,
        eligible_types: tuple[str, ...] = APPROVAL_ELIGIBLE_CONTENT_TYPES,
    ) -> tuple[list[tuple[WebsiteContent, ContentApproval | None, ContentKeyword | None]], int]: ...
    def list_approved_keyword_entries(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
        content_type: str | None = None,
        search: str | None = None,
        approved_only: bool = True,
    ) -> tuple[list[tuple[WebsiteContent, ContentKeyword, ContentApproval | None]], int]: ...


class SQLAlchemyKeywordApprovalRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_keyword_by_content_id(self, content_id: int) -> ContentKeyword | None:
        stmt = select(ContentKeyword).where(ContentKeyword.website_content_id == content_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_keywords_for_website(
        self, website_id: int, *, approval_status: str | None = None
    ) -> list[ContentKeyword]:
        stmt = select(ContentKeyword).where(ContentKeyword.website_id == website_id)
        if approval_status:
            stmt = stmt.where(ContentKeyword.approval_status == approval_status)
        stmt = stmt.order_by(ContentKeyword.updated_at.desc(), ContentKeyword.id.desc())
        return list(self.db.execute(stmt).scalars().all())

    def upsert_keyword(
        self,
        *,
        website_id: int,
        website_content_id: int,
        data: dict[str, Any],
        create_revision: bool = True,
        change_note: str | None = None,
        changed_by: int | None = None,
    ) -> ContentKeyword:
        now = utc_now_naive()
        existing = self.get_keyword_by_content_id(website_content_id)
        payload = dict(data)
        if "focus_keyphrase" in payload:
            payload["focus_keyphrase"] = str(payload["focus_keyphrase"] or "").strip()[:255]
            payload["focus_keyphrase_norm"] = normalize_keyphrase(payload["focus_keyphrase"])

        if existing is None:
            record = ContentKeyword(
                website_id=website_id,
                website_content_id=website_content_id,
                focus_keyphrase=payload.get("focus_keyphrase", ""),
                focus_keyphrase_norm=payload.get("focus_keyphrase_norm", ""),
                secondary_keywords_json=list(payload.get("secondary_keywords_json", [])),
                anchor_text_variations_json=list(
                    payload.get("anchor_text_variations_json", [])
                ),
                image_alt_suggestions_json=list(payload.get("image_alt_suggestions_json", [])),
                keyword_generation_method=payload.get("keyword_generation_method", "python"),
                keyword_generation_status=payload.get("keyword_generation_status", "pending"),
                keyword_evidence_json=list(payload.get("keyword_evidence_json", [])),
                keyword_scores_json=dict(payload.get("keyword_scores_json", {}) or {}),
                keyword_model=payload.get("keyword_model"),
                keyword_input_hash=payload.get("keyword_input_hash"),
                keyword_generated_at=payload.get("keyword_generated_at"),
                game_name=payload.get("game_name"),
                provider_name=payload.get("provider_name"),
                approval_status=payload.get("approval_status", "pending_review"),
                suggestion_source=payload.get("suggestion_source", "python_auto"),
                is_admin_locked=bool(payload.get("is_admin_locked", False)),
                version=int(payload.get("version", 1)),
                last_reviewed_at=payload.get("last_reviewed_at"),
                approved_by=payload.get("approved_by"),
                approved_at=payload.get("approved_at"),
                created_by=payload.get("created_by", changed_by),
                created_at=now,
                updated_at=now,
            )
            self.db.add(record)
            self.db.flush()
            if create_revision:
                self._insert_revision(
                    record=record,
                    revision_number=record.version,
                    change_note=change_note or "Initial keyword mapping",
                    changed_by=changed_by,
                )
            self.db.commit()
            self.db.refresh(record)
            return record

        bump_ver = bool(payload.pop("bump_version", False))
        for key, value in payload.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
        if bump_ver:
            existing.version += 1
        existing.updated_at = now

        if create_revision:
            max_rev = (
                self.db.execute(
                    select(func.max(ContentKeywordRevision.revision_number)).where(
                        ContentKeywordRevision.content_keyword_id == existing.id
                    )
                ).scalar_one_or_none()
                or 0
            )
            next_rev = max(int(max_rev) + 1, existing.version)
            self._insert_revision(
                record=existing,
                revision_number=next_rev,
                change_note=change_note,
                changed_by=changed_by,
            )

        self.db.commit()
        self.db.refresh(existing)
        return existing

    def _insert_revision(
        self,
        *,
        record: ContentKeyword,
        revision_number: int,
        change_note: str | None,
        changed_by: int | None,
    ) -> None:
        self.db.add(
            ContentKeywordRevision(
                content_keyword_id=record.id,
                revision_number=revision_number,
                focus_keyphrase=record.focus_keyphrase,
                secondary_keywords_json=list(record.secondary_keywords_json or []),
                anchor_text_variations_json=list(record.anchor_text_variations_json or []),
                image_alt_suggestions_json=list(record.image_alt_suggestions_json or []),
                approval_status=record.approval_status,
                suggestion_source=record.suggestion_source,
                change_note=change_note[:500] if change_note else None,
                changed_by=changed_by,
                created_at=utc_now_naive(),
            )
        )

    def list_keyword_revisions(self, content_keyword_id: int) -> list[ContentKeywordRevision]:
        stmt = (
            select(ContentKeywordRevision)
            .where(ContentKeywordRevision.content_keyword_id == content_keyword_id)
            .order_by(ContentKeywordRevision.revision_number.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_approval_by_content_id(self, content_id: int) -> ContentApproval | None:
        stmt = select(ContentApproval).where(ContentApproval.website_content_id == content_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def upsert_approval(
        self,
        *,
        website_id: int,
        website_content_id: int,
        data: dict[str, Any],
    ) -> tuple[ContentApproval, str | None]:
        now = utc_now_naive()
        existing = self.get_approval_by_content_id(website_content_id)
        if existing is None:
            record = ContentApproval(
                website_id=website_id,
                website_content_id=website_content_id,
                status=data.get("status", "pending_review"),
                classified_content_type=data.get("classified_content_type", "page"),
                submitted_content_hash=data.get("submitted_content_hash"),
                review_note=data.get("review_note"),
                rejection_reason=data.get("rejection_reason"),
                auto_generation_triggered_at=data.get("auto_generation_triggered_at"),
                reviewed_by=data.get("reviewed_by"),
                reviewed_at=data.get("reviewed_at"),
                approved_at=data.get("approved_at"),
                rejected_at=data.get("rejected_at"),
                created_at=now,
                updated_at=now,
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            return record, None

        prev_status = existing.status
        for key, value in data.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
        existing.updated_at = now
        self.db.commit()
        self.db.refresh(existing)
        return existing, prev_status

    def record_approval_history(
        self,
        *,
        content_approval_id: int,
        from_status: str | None,
        to_status: str,
        content_type: str | None,
        focus_keyphrase: str | None,
        action: str,
        note: str | None,
        acted_by: int | None,
    ) -> ContentApprovalHistory:
        row = ContentApprovalHistory(
            content_approval_id=content_approval_id,
            from_status=from_status,
            to_status=to_status,
            content_type=content_type,
            focus_keyphrase=focus_keyphrase[:255] if focus_keyphrase else None,
            action=action,
            note=note[:500] if note else None,
            acted_by=acted_by,
            created_at=utc_now_naive(),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_approval_history(self, content_approval_id: int) -> list[ContentApprovalHistory]:
        stmt = (
            select(ContentApprovalHistory)
            .where(ContentApprovalHistory.content_approval_id == content_approval_id)
            .order_by(ContentApprovalHistory.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_status_counts(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> dict[str, int]:
        from app.models.website import Website

        stmt = (
            select(ContentApproval.status, func.count())
            .select_from(ContentApproval)
            .join(WebsiteContent, ContentApproval.website_content_id == WebsiteContent.id)
            .where(
                WebsiteContent.is_excluded.is_(False),
                WebsiteContent.content_type.in_(APPROVAL_ELIGIBLE_CONTENT_TYPES),
            )
        )
        if website_id is not None:
            stmt = stmt.where(ContentApproval.website_id == website_id)
        if category_id is not None:
            stmt = stmt.join(Website, ContentApproval.website_id == Website.id).where(
                Website.category_id == category_id
            )
        stmt = stmt.group_by(ContentApproval.status)
        rows = self.db.execute(stmt).all()
        counts = {
            "total_eligible": 0,
            "awaiting_extraction": 0,
            "pending_review": 0,
            "needs_rereview": 0,
            "approved": 0,
            "rejected": 0,
        }
        for st, cnt in rows:
            val = int(cnt or 0)
            counts["total_eligible"] += val
            if st in counts:
                counts[st] = val
        return counts

    def list_approvals_paginated(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
        status: str | None = None,
        content_type: str | None = None,
        search: str | None = None,
        eligible_types: tuple[str, ...] = APPROVAL_ELIGIBLE_CONTENT_TYPES,
    ) -> tuple[list[tuple[WebsiteContent, ContentApproval | None, ContentKeyword | None]], int]:
        base = (
            select(WebsiteContent, ContentApproval, ContentKeyword)
            .outerjoin(ContentApproval, ContentApproval.website_content_id == WebsiteContent.id)
            .outerjoin(ContentKeyword, ContentKeyword.website_content_id == WebsiteContent.id)
            .where(
                WebsiteContent.is_excluded.is_(False),
                WebsiteContent.content_type.in_(eligible_types),
            )
        )
        if website_id is not None:
            base = base.where(WebsiteContent.website_id == website_id)
        if content_type:
            base = base.where(WebsiteContent.content_type == content_type)
        if status:
            if status == "pending_review":
                base = base.where(
                    or_(
                        ContentApproval.status == "pending_review",
                        (
                            ContentApproval.id.is_(None)
                            & (WebsiteContent.extraction_status == "extracted")
                        ),
                    )
                )
            elif status == "awaiting_extraction":
                base = base.where(
                    or_(
                        ContentApproval.status == "awaiting_extraction",
                        (
                            ContentApproval.id.is_(None)
                            & (WebsiteContent.extraction_status != "extracted")
                        ),
                    )
                )
            else:
                base = base.where(ContentApproval.status == status)
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            base = base.where(
                or_(
                    WebsiteContent.title.ilike(pattern),
                    WebsiteContent.canonical_url.ilike(pattern),
                    ContentKeyword.focus_keyphrase.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = int(self.db.execute(count_stmt).scalar_one() or 0)
        offset = (page - 1) * page_size
        stmt = (
            base.order_by(WebsiteContent.last_discovered_at.desc(), WebsiteContent.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = [(r[0], r[1], r[2]) for r in self.db.execute(stmt).all()]
        return rows, total

    def list_approved_keyword_entries(
        self,
        *,
        page: int,
        page_size: int,
        website_id: int | None = None,
        content_type: str | None = None,
        search: str | None = None,
        approved_only: bool = True,
    ) -> tuple[list[tuple[WebsiteContent, ContentKeyword, ContentApproval | None]], int]:
        base = (
            select(WebsiteContent, ContentKeyword, ContentApproval)
            .join(ContentKeyword, ContentKeyword.website_content_id == WebsiteContent.id)
            .outerjoin(ContentApproval, ContentApproval.website_content_id == WebsiteContent.id)
            .where(WebsiteContent.is_excluded.is_(False))
        )
        if approved_only:
            base = base.where(
                ContentKeyword.approval_status == "approved",
                ContentApproval.status == "approved",
            )
        if website_id is not None:
            base = base.where(WebsiteContent.website_id == website_id)
        if content_type:
            base = base.where(WebsiteContent.content_type == content_type)
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            base = base.where(
                or_(
                    WebsiteContent.title.ilike(pattern),
                    WebsiteContent.canonical_url.ilike(pattern),
                    ContentKeyword.focus_keyphrase.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = int(self.db.execute(count_stmt).scalar_one() or 0)
        offset = (page - 1) * page_size
        stmt = (
            base.order_by(ContentKeyword.updated_at.desc(), ContentKeyword.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = [(r[0], r[1], r[2]) for r in self.db.execute(stmt).all()]
        return rows, total
