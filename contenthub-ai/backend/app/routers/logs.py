from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_activity_log_repo, require_admin
from app.models.base import ensure_utc, utc_now
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.logs import ActivityLogItem, ActivityLogListResponse
from app.services.auth_service import AuthenticatedSession

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get("/activity", response_model=ActivityLogListResponse)
def list_activity_logs(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None, max_length=64),
    level: str | None = Query(default=None, max_length=16),
    search: str | None = Query(default=None, max_length=120),
) -> ActivityLogListResponse:
    rows, total = activity_repo.list_paginated(
        page=page,
        page_size=page_size,
        category=category.strip() if category else None,
        level=level.strip() if level else None,
        search=search.strip() if search else None,
    )
    now = utc_now()
    items = [
        ActivityLogItem(
            id=row.id,
            user_id=row.user_id,
            actor_type=row.actor_type,
            category=row.category,
            action=row.action,
            level=row.level,
            message=row.message,
            metadata=row.metadata_json,
            ip_address=row.ip_address,
            created_at=ensure_utc(row.created_at) or now,
        )
        for row in rows
    ]
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return ActivityLogListResponse(
        items=items,
        meta=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=total_pages,
        ),
    )
