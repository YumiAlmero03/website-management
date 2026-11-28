from __future__ import annotations

from typing import Any

from app.models.base import utc_now_naive
from app.models.content_approval import ContentApproval, ContentApprovalHistory
from app.models.content_keyword import ContentKeyword, ContentKeywordRevision
from app.models.website_content import WebsiteContent
from app.repositories.keyword_approval_repo import normalize_keyphrase
from app.schemas.keyword_approval import APPROVAL_ELIGIBLE_CONTENT_TYPES


class InMemoryKeywordApprovalRepository:
    def __init__(self, content_repo: Any) -> None:
        self.content_repo = content_repo
        self._keywords: dict[int, ContentKeyword] = {}
        self._kw_revisions: dict[int, list[ContentKeywordRevision]] = {}
        self._approvals: dict[int, ContentApproval] = {}
        self._approval_history: dict[int, list[ContentApprovalHistory]] = {}
        self._seq_kw = 0
        self._seq_kw_rev = 0
        self._seq_app = 0
        self._seq_app_hist = 0

    def get_keyword_by_content_id(self, content_id: int) -> ContentKeyword | None:
        return self._keywords.get(content_id)

    def list_keywords_for_website(
        self, website_id: int, *, approval_status: str | None = None
    ) -> list[ContentKeyword]:
        rows = [k for k in self._keywords.values() if k.website_id == website_id]
        if approval_status:
            rows = [k for k in rows if k.approval_status == approval_status]
        rows.sort(key=lambda r: (r.updated_at, r.id), reverse=True)
        return rows

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
        payload = dict(data)
        if "focus_keyphrase" in payload:
            payload["focus_keyphrase"] = str(payload["focus_keyphrase"] or "").strip()[:255]
            payload["focus_keyphrase_norm"] = normalize_keyphrase(payload["focus_keyphrase"])

        existing = self._keywords.get(website_content_id)
        if existing is None:
            self._seq_kw += 1
            record = ContentKeyword(
                id=self._seq_kw,
                website_id=website_id,
                website_content_id=website_content_id,
                focus_keyphrase=payload.get("focus_keyphrase", ""),
                focus_keyphrase_norm=payload.get("focus_keyphrase_norm", ""),
                secondary_keywords_json=list(payload.get("secondary_keywords_json", [])),
                anchor_text_variations_json=list(
                    payload.get("anchor_text_variations_json", [])
                ),
                image_alt_suggestions_json=list(payload.get("image_alt_suggestions_json", [])),
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
            self._keywords[website_content_id] = record
            if create_revision:
                self._add_kw_revision(record, record.version, change_note, changed_by)
            return record

        bump_ver = bool(payload.pop("bump_version", False))
        for k, v in payload.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
        if bump_ver:
            existing.version += 1
        existing.updated_at = now
        if create_revision:
            revs = self._kw_revisions.get(existing.id, [])
            next_rev = max([r.revision_number for r in revs], default=0) + 1
            next_rev = max(next_rev, existing.version)
            self._add_kw_revision(existing, next_rev, change_note, changed_by)
        return existing

    def _add_kw_revision(
        self,
        record: ContentKeyword,
        revision_number: int,
        change_note: str | None,
        changed_by: int | None,
    ) -> None:
        self._seq_kw_rev += 1
        rev = ContentKeywordRevision(
            id=self._seq_kw_rev,
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
        self._kw_revisions.setdefault(record.id, []).append(rev)

    def list_keyword_revisions(self, content_keyword_id: int) -> list[ContentKeywordRevision]:
        revs = list(self._kw_revisions.get(content_keyword_id, []))
        revs.sort(key=lambda r: r.revision_number, reverse=True)
        return revs

    def get_approval_by_content_id(self, content_id: int) -> ContentApproval | None:
        return self._approvals.get(content_id)

    def upsert_approval(
        self,
        *,
        website_id: int,
        website_content_id: int,
        data: dict[str, Any],
    ) -> tuple[ContentApproval, str | None]:
        now = utc_now_naive()
        existing = self._approvals.get(website_content_id)
        if existing is None:
            self._seq_app += 1
            rec = ContentApproval(
                id=self._seq_app,
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
            self._approvals[website_content_id] = rec
            return rec, None

        prev = existing.status
        for k, v in data.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
        existing.updated_at = now
        return existing, prev

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
        self._seq_app_hist += 1
        row = ContentApprovalHistory(
            id=self._seq_app_hist,
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
        self._approval_history.setdefault(content_approval_id, []).append(row)
        return row

    def list_approval_history(self, content_approval_id: int) -> list[ContentApprovalHistory]:
        rows = list(self._approval_history.get(content_approval_id, []))
        rows.sort(key=lambda r: r.id, reverse=True)
        return rows

    def get_status_counts(
        self,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> dict[str, int]:
        counts = {
            "total_eligible": 0,
            "awaiting_extraction": 0,
            "pending_review": 0,
            "needs_rereview": 0,
            "approved": 0,
            "rejected": 0,
        }
        eligible_contents = [
            c
            for c in self.content_repo._items.values()
            if not c.is_excluded and c.content_type in APPROVAL_ELIGIBLE_CONTENT_TYPES
        ]
        if website_id is not None:
            eligible_contents = [c for c in eligible_contents if c.website_id == website_id]
        if category_id is not None and getattr(self.content_repo, "website_repo", None):
            wmap = self.content_repo.website_repo._items
            eligible_contents = [
                c
                for c in eligible_contents
                if wmap.get(c.website_id) and wmap[c.website_id].category_id == category_id
            ]
        for c in eligible_contents:
            app = self._approvals.get(c.id)
            fallback_st = (
                "pending_review" if c.extraction_status == "extracted" else "awaiting_extraction"
            )
            st = app.status if app is not None else fallback_st
            counts["total_eligible"] += 1
            if st in counts:
                counts[st] += 1
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
        rows: list[tuple[WebsiteContent, ContentApproval | None, ContentKeyword | None]] = []
        for c in self.content_repo._items.values():
            if c.is_excluded or c.content_type not in eligible_types:
                continue
            if website_id is not None and c.website_id != website_id:
                continue
            if content_type and c.content_type != content_type:
                continue
            app = self._approvals.get(c.id)
            kw = self._keywords.get(c.id)
            fallback_st = (
                "pending_review" if c.extraction_status == "extracted" else "awaiting_extraction"
            )
            eff_st = app.status if app is not None else fallback_st
            if status and eff_st != status:
                continue
            if search and search.strip():
                q = search.strip().lower()
                hay = f"{c.title} {c.canonical_url} {kw.focus_keyphrase if kw else ''}".lower()
                if q not in hay:
                    continue
            rows.append((c, app, kw))
        rows.sort(key=lambda r: (r[0].last_discovered_at, r[0].id), reverse=True)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

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
        rows: list[tuple[WebsiteContent, ContentKeyword, ContentApproval | None]] = []
        for c in self.content_repo._items.values():
            if c.is_excluded:
                continue
            kw = self._keywords.get(c.id)
            app = self._approvals.get(c.id)
            if kw is None:
                continue
            if approved_only and (
                kw.approval_status != "approved" or app is None or app.status != "approved"
            ):
                continue
            if website_id is not None and c.website_id != website_id:
                continue
            if content_type and c.content_type != content_type:
                continue
            if search and search.strip():
                q = search.strip().lower()
                hay = f"{c.title} {c.canonical_url} {kw.focus_keyphrase}".lower()
                if q not in hay:
                    continue
            rows.append((c, kw, app))
        rows.sort(key=lambda r: (r[1].updated_at, r[1].id), reverse=True)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total
