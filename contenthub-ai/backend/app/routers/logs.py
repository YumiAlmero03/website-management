from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_activity_log_repo, get_db_session, require_admin
from app.models.ai_generation_job import AiGenerationJob
from app.models.base import ensure_utc, utc_now
from app.models.indexing import IndexingJob
from app.models.publishing import PublishingJob
from app.models.website_scan_log import WebsiteScanLog
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.schemas.common import PaginationMeta
from app.schemas.logs import (
    ActivityLogItem,
    ActivityLogListResponse,
    BackgroundFunctionItem,
    BackgroundFunctionsResponse,
)
from app.services.auth_service import AuthenticatedSession

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get("/background", response_model=BackgroundFunctionsResponse)
def list_background_functions(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BackgroundFunctionsResponse:
    items: list[BackgroundFunctionItem] = []

    scan_statuses = ("pending", "processing", "paused", "incomplete")
    scan_count = int(
        db.execute(
            select(func.count(WebsiteScanLog.id)).where(WebsiteScanLog.status.in_(scan_statuses))
        ).scalar_one()
        or 0
    )
    items.append(
        BackgroundFunctionItem(
            function="Website scanning",
            status="running" if scan_count else "idle",
            count=scan_count,
            details="Discovery, extraction, media, and resumable scan worker",
        )
    )

    ai_statuses = ("queued", "processing", "deferred")
    ai_count = int(
        db.execute(
            select(func.count(AiGenerationJob.id)).where(AiGenerationJob.status.in_(ai_statuses))
        ).scalar_one()
        or 0
    )
    items.append(
        BackgroundFunctionItem(
            function="AI content generation",
            status="running" if ai_count else "idle",
            count=ai_count,
            details="Gemini/LocalAI draft jobs and prompt processing",
        )
    )

    publishing_statuses = ("queued", "processing", "deferred", "verification_required")
    publishing_count = int(
        db.execute(
            select(func.count(PublishingJob.id)).where(
                PublishingJob.status.in_(publishing_statuses)
            )
        ).scalar_one()
        or 0
    )
    items.append(
        BackgroundFunctionItem(
            function="Social publishing",
            status="running" if publishing_count else "idle",
            count=publishing_count,
            details="Scheduling, official publishing, reconciliation, and media preparation",
        )
    )

    indexing_statuses = ("queued", "processing", "deferred")
    indexing_count = int(
        db.execute(
            select(func.count(IndexingJob.id)).where(IndexingJob.status.in_(indexing_statuses))
        ).scalar_one()
        or 0
    )
    items.append(
        BackgroundFunctionItem(
            function="Google indexing",
            status="running" if indexing_count else "idle",
            count=indexing_count,
            details="URL Inspection, technical checks, and backlink verification",
        )
    )

    return BackgroundFunctionsResponse(items=items)


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
