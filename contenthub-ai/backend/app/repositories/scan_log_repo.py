from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.website import Website
from app.models.website_scan_item import WebsiteScanItem
from app.models.website_scan_log import WebsiteScanLog

ACTIVE_SCAN_STATUSES: tuple[str, ...] = ("pending", "processing")
RESUMABLE_SCAN_STATUSES: tuple[str, ...] = ("incomplete", "paused", "partially_completed")


class ScanLogRepositoryProtocol(Protocol):
    def get_by_id(self, scan_id: int) -> WebsiteScanLog | None: ...

    def get_active_for_website(self, website_id: int) -> WebsiteScanLog | None: ...

    def get_latest_incomplete_for_website(self, website_id: int) -> WebsiteScanLog | None: ...

    def list_for_website(
        self,
        website_id: int,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[WebsiteScanLog], int]: ...

    def list_recent(
        self,
        *,
        limit: int = 8,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> list[WebsiteScanLog]: ...

    def count_by_status(
        self,
        status: str,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> int: ...

    def create(
        self,
        *,
        website_id: int,
        scan_method: str,
        trigger_type: str,
        scan_mode: str = "full",
        status: str = "pending",
    ) -> WebsiteScanLog: ...

    def claim_pending(self, scan_id: int) -> WebsiteScanLog | None: ...

    def update(self, scan_id: int, data: dict[str, Any]) -> WebsiteScanLog | None: ...

    def recover_stale_scans(
        self,
        *,
        stale_minutes: int,
        website_id: int | None = None,
    ) -> list[WebsiteScanLog]: ...

    # Durable per-URL scan items (website_scan_items)
    def upsert_scan_item(
        self,
        *,
        scan_log_id: int,
        website_id: int,
        url: str,
        normalized_url: str,
        url_hash: str,
        content_type: str,
        discovery_sources: list[str] | None = None,
        discovered_title: str | None = None,
        discovered_published_at: datetime | None = None,
        discovered_modified_at: datetime | None = None,
        status: str = "pending",
        content_id: int | None = None,
        http_status: int | None = None,
        failure_reason: str | None = None,
        error_detail: str | None = None,
    ) -> WebsiteScanItem: ...

    def list_scan_items(
        self,
        scan_log_id: int,
        *,
        status: str | None = None,
        failures_or_excluded_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[WebsiteScanItem], int]: ...

    def list_pending_scan_items(
        self, scan_log_id: int, *, limit: int = 100
    ) -> list[WebsiteScanItem]: ...

    def update_scan_item(self, item_id: int, data: dict[str, Any]) -> WebsiteScanItem | None: ...

    def count_scan_items_by_status(self, scan_log_id: int) -> dict[str, int]: ...


class SQLAlchemyScanLogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, scan_id: int) -> WebsiteScanLog | None:
        return self.db.get(WebsiteScanLog, scan_id)

    def get_active_for_website(self, website_id: int) -> WebsiteScanLog | None:
        stmt = (
            select(WebsiteScanLog)
            .where(
                WebsiteScanLog.website_id == website_id,
                WebsiteScanLog.status.in_(ACTIVE_SCAN_STATUSES),
            )
            .order_by(WebsiteScanLog.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_incomplete_for_website(self, website_id: int) -> WebsiteScanLog | None:
        stmt = (
            select(WebsiteScanLog)
            .where(
                WebsiteScanLog.website_id == website_id,
                WebsiteScanLog.status.in_(RESUMABLE_SCAN_STATUSES),
            )
            .order_by(WebsiteScanLog.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_website(
        self,
        website_id: int,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[WebsiteScanLog], int]:
        count_stmt = (
            select(func.count())
            .select_from(WebsiteScanLog)
            .where(WebsiteScanLog.website_id == website_id)
        )
        data_stmt = (
            select(WebsiteScanLog)
            .where(WebsiteScanLog.website_id == website_id)
            .order_by(WebsiteScanLog.created_at.desc(), WebsiteScanLog.id.desc())
        )
        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(
            self.db.execute(data_stmt.offset((page - 1) * page_size).limit(page_size))
            .scalars()
            .all()
        )
        return rows, total

    def list_recent(
        self,
        *,
        limit: int = 8,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> list[WebsiteScanLog]:
        stmt = select(WebsiteScanLog)
        if category_id is not None:
            stmt = stmt.join(Website, Website.id == WebsiteScanLog.website_id).where(
                Website.category_id == category_id
            )
        if website_id is not None:
            stmt = stmt.where(WebsiteScanLog.website_id == website_id)
        stmt = stmt.order_by(WebsiteScanLog.created_at.desc(), WebsiteScanLog.id.desc()).limit(
            limit
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_by_status(
        self,
        status: str,
        *,
        website_id: int | None = None,
        category_id: int | None = None,
    ) -> int:
        stmt = (
            select(func.count()).select_from(WebsiteScanLog).where(WebsiteScanLog.status == status)
        )
        if category_id is not None:
            stmt = stmt.join(Website, Website.id == WebsiteScanLog.website_id).where(
                Website.category_id == category_id
            )
        if website_id is not None:
            stmt = stmt.where(WebsiteScanLog.website_id == website_id)
        return int(self.db.execute(stmt).scalar_one())

    def create(
        self,
        *,
        website_id: int,
        scan_method: str,
        trigger_type: str,
        scan_mode: str = "full",
        status: str = "pending",
    ) -> WebsiteScanLog:
        now = utc_now_naive()
        scan = WebsiteScanLog(
            website_id=website_id,
            scan_method=scan_method,
            scan_mode=scan_mode,
            trigger_type=trigger_type,
            status=status,
            heartbeat_at=now,
            created_at=now,
        )
        self.db.add(scan)
        self.db.commit()
        self.db.refresh(scan)
        return scan

    def claim_pending(self, scan_id: int) -> WebsiteScanLog | None:
        stmt = (
            select(WebsiteScanLog)
            .where(WebsiteScanLog.id == scan_id, WebsiteScanLog.status == "pending")
            .with_for_update()
        )
        scan = self.db.execute(stmt).scalar_one_or_none()
        if scan is None:
            self.db.rollback()
            return None
        now = utc_now_naive()
        scan.status = "processing"
        scan.started_at = now
        scan.heartbeat_at = now
        self.db.commit()
        self.db.refresh(scan)
        return scan

    def update(self, scan_id: int, data: dict[str, Any]) -> WebsiteScanLog | None:
        scan = self.db.get(WebsiteScanLog, scan_id)
        if scan is None:
            return None
        for key, value in data.items():
            setattr(scan, key, value)
        self.db.commit()
        self.db.refresh(scan)
        return scan

    def recover_stale_scans(
        self,
        *,
        stale_minutes: int,
        website_id: int | None = None,
    ) -> list[WebsiteScanLog]:
        now = utc_now_naive()
        cutoff = now - timedelta(minutes=stale_minutes)
        stmt = select(WebsiteScanLog).where(
            WebsiteScanLog.status.in_(ACTIVE_SCAN_STATUSES),
            or_(
                WebsiteScanLog.heartbeat_at < cutoff,
                (WebsiteScanLog.heartbeat_at.is_(None) & (WebsiteScanLog.created_at < cutoff)),
            ),
        )
        if website_id is not None:
            stmt = stmt.where(WebsiteScanLog.website_id == website_id)

        stale_rows = list(self.db.execute(stmt).scalars().all())
        for row in stale_rows:
            row.status = "paused" if row.urls_pending_extraction > 0 else "failed"
            row.completed_at = now
            row.error_message = (
                f"Recovered interrupted scan after exceeding {stale_minutes} minute "
                "heartbeat timeout; use Resume Incomplete Scan to continue."
            )
        if stale_rows:
            self.db.commit()
        return stale_rows

    def upsert_scan_item(
        self,
        *,
        scan_log_id: int,
        website_id: int,
        url: str,
        normalized_url: str,
        url_hash: str,
        content_type: str,
        discovery_sources: list[str] | None = None,
        discovered_title: str | None = None,
        discovered_published_at: datetime | None = None,
        discovered_modified_at: datetime | None = None,
        status: str = "pending",
        content_id: int | None = None,
        http_status: int | None = None,
        failure_reason: str | None = None,
        error_detail: str | None = None,
    ) -> WebsiteScanItem:
        stmt = select(WebsiteScanItem).where(
            WebsiteScanItem.scan_log_id == scan_log_id,
            WebsiteScanItem.url_hash == url_hash,
        )
        existing = self.db.execute(stmt).scalar_one_or_none()
        now = utc_now_naive()
        if existing is not None:
            merged_sources = list(existing.discovery_sources or [])
            for src in discovery_sources or []:
                if src not in merged_sources:
                    merged_sources.append(src)
            existing.discovery_sources = merged_sources
            existing.content_type = content_type or existing.content_type
            if discovered_title and not existing.discovered_title:
                existing.discovered_title = discovered_title[:500]
            if content_id is not None:
                existing.content_id = content_id
            if status:
                existing.status = status
            if http_status is not None:
                existing.http_status = http_status
            if failure_reason is not None:
                existing.failure_reason = failure_reason[:120]
            if error_detail is not None:
                existing.error_detail = error_detail[:500]
            existing.updated_at = now
            self.db.commit()
            self.db.refresh(existing)
            return existing

        item = WebsiteScanItem(
            scan_log_id=scan_log_id,
            website_id=website_id,
            content_id=content_id,
            url=url[:1000],
            normalized_url=normalized_url[:1000],
            url_hash=url_hash,
            content_type=content_type,
            discovery_sources=list(discovery_sources or []),
            discovered_title=discovered_title[:500] if discovered_title else None,
            discovered_published_at=discovered_published_at,
            discovered_modified_at=discovered_modified_at,
            status=status,
            http_status=http_status,
            failure_reason=failure_reason[:120] if failure_reason else None,
            error_detail=error_detail[:500] if error_detail else None,
            processed_at=now
            if status in {"excluded", "failed", "extracted", "updated", "unchanged"}
            else None,
            created_at=now,
            updated_at=now,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def list_scan_items(
        self,
        scan_log_id: int,
        *,
        status: str | None = None,
        failures_or_excluded_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[WebsiteScanItem], int]:
        stmt = select(WebsiteScanItem).where(WebsiteScanItem.scan_log_id == scan_log_id)
        count_stmt = (
            select(func.count())
            .select_from(WebsiteScanItem)
            .where(WebsiteScanItem.scan_log_id == scan_log_id)
        )
        if status:
            stmt = stmt.where(WebsiteScanItem.status == status)
            count_stmt = count_stmt.where(WebsiteScanItem.status == status)
        elif failures_or_excluded_only:
            stmt = stmt.where(WebsiteScanItem.status.in_(["failed", "excluded"]))
            count_stmt = count_stmt.where(WebsiteScanItem.status.in_(["failed", "excluded"]))

        stmt = stmt.order_by(WebsiteScanItem.id.asc())
        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(
            self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        )
        return rows, total

    def list_pending_scan_items(
        self, scan_log_id: int, *, limit: int = 100
    ) -> list[WebsiteScanItem]:
        stmt = (
            select(WebsiteScanItem)
            .where(
                WebsiteScanItem.scan_log_id == scan_log_id,
                WebsiteScanItem.status == "pending",
            )
            .order_by(WebsiteScanItem.id.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def update_scan_item(self, item_id: int, data: dict[str, Any]) -> WebsiteScanItem | None:
        item = self.db.get(WebsiteScanItem, item_id)
        if item is None:
            return None
        for key, value in data.items():
            setattr(item, key, value)
        item.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(item)
        return item

    def count_scan_items_by_status(self, scan_log_id: int) -> dict[str, int]:
        rows = self.db.execute(
            select(WebsiteScanItem.status, func.count())
            .where(WebsiteScanItem.scan_log_id == scan_log_id)
            .group_by(WebsiteScanItem.status)
        ).fetchall()
        return {str(status_val): int(cnt) for status_val, cnt in rows}
