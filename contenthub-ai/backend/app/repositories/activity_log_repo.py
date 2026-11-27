from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import redact_mapping, redact_text
from app.models.activity_log import ActivityLog
from app.models.base import utc_now_naive


class ActivityLogRepositoryProtocol(Protocol):
    def create(
        self,
        *,
        user_id: int | None,
        actor_type: str,
        category: str,
        action: str,
        level: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> ActivityLog: ...

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        category: str | None = None,
        level: str | None = None,
        search: str | None = None,
    ) -> tuple[list[ActivityLog], int]: ...

    def count_all(self) -> int: ...


class SQLAlchemyActivityLogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: int | None,
        actor_type: str,
        category: str,
        action: str,
        level: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> ActivityLog:
        entry = ActivityLog(
            user_id=user_id,
            actor_type=actor_type[:32],
            category=category[:64],
            action=action[:120],
            level=level[:16],
            message=redact_text(message)[:500],
            metadata_json=redact_mapping(metadata),
            ip_address=ip_address[:64] if ip_address else None,
            created_at=utc_now_naive(),
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        category: str | None = None,
        level: str | None = None,
        search: str | None = None,
    ) -> tuple[list[ActivityLog], int]:
        filters = []
        if category:
            filters.append(ActivityLog.category == category)
        if level:
            filters.append(ActivityLog.level == level)
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    ActivityLog.message.ilike(term),
                    ActivityLog.action.ilike(term),
                    ActivityLog.category.ilike(term),
                )
            )

        count_stmt = select(func.count()).select_from(ActivityLog)
        data_stmt = select(ActivityLog).order_by(
            ActivityLog.created_at.desc(), ActivityLog.id.desc()
        )
        if filters:
            count_stmt = count_stmt.where(*filters)
            data_stmt = data_stmt.where(*filters)

        total = int(self.db.execute(count_stmt).scalar_one())
        offset = (page - 1) * page_size
        rows = list(self.db.execute(data_stmt.offset(offset).limit(page_size)).scalars().all())
        return rows, total

    def count_all(self) -> int:
        return int(self.db.execute(select(func.count()).select_from(ActivityLog)).scalar_one())
