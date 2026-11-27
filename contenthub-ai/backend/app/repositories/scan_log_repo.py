from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.website import Website
from app.models.website_scan_log import WebsiteScanLog

ACTIVE_SCAN_STATUSES: tuple[str, ...] = ("pending", "processing")


class ScanLogRepositoryProtocol(Protocol):
    def get_by_id(self, scan_id: int) -> WebsiteScanLog | None: ...

    def get_active_for_website(self, website_id: int) -> WebsiteScanLog | None: ...

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
        brand_id: int | None = None,
        website_id: int | None = None,
    ) -> list[WebsiteScanLog]: ...

    def count_by_status(
        self,
        status: str,
        *,
        brand_id: int | None = None,
        website_id: int | None = None,
    ) -> int: ...

    def create(
        self,
        *,
        website_id: int,
        scan_method: str,
        trigger_type: str,
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
        brand_id: int | None = None,
        website_id: int | None = None,
    ) -> list[WebsiteScanLog]:
        stmt = select(WebsiteScanLog)
        if brand_id is not None:
            stmt = stmt.join(Website, Website.id == WebsiteScanLog.website_id).where(
                Website.brand_id == brand_id
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
        brand_id: int | None = None,
        website_id: int | None = None,
    ) -> int:
        stmt = (
            select(func.count()).select_from(WebsiteScanLog).where(WebsiteScanLog.status == status)
        )
        if brand_id is not None:
            stmt = stmt.join(Website, Website.id == WebsiteScanLog.website_id).where(
                Website.brand_id == brand_id
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
        status: str = "pending",
    ) -> WebsiteScanLog:
        now = utc_now_naive()
        scan = WebsiteScanLog(
            website_id=website_id,
            scan_method=scan_method,
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
        """Transactionally claim a pending scan row using row-level locking."""
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
            row.status = "failed"
            row.completed_at = now
            row.error_message = (
                f"Recovered stale scan after exceeding {stale_minutes} minute heartbeat timeout."
            )
        if stale_rows:
            self.db.commit()
        return stale_rows
