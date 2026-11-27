from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.dependencies import (
    extract_client_ip,
    get_content_service,
    require_admin,
    require_csrf,
)
from app.schemas.content import (
    ContentDetailResponse,
    ContentListResponse,
    ContentRevisionResponse,
    ContentStatsResponse,
    ContentUpdateRequest,
)
from app.services.auth_service import AuthenticatedSession
from app.services.content_service import ContentService

router = APIRouter(prefix="/contents", tags=["Content Library"])


@router.get("/stats", response_model=ContentStatsResponse)
def get_content_stats(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    content_service: Annotated[ContentService, Depends(get_content_service)],
    website_id: int | None = Query(default=None, ge=1),
    category_id: int | None = Query(default=None, ge=1),
) -> ContentStatsResponse:
    return content_service.get_stats(website_id=website_id, category_id=category_id)


@router.get("", response_model=ContentListResponse)
def list_contents(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    content_service: Annotated[ContentService, Depends(get_content_service)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    website_id: int | None = Query(default=None, ge=1),
    category_id: int | None = Query(default=None, ge=1),
    tab: str | None = Query(default=None, max_length=32),
    content_type: str | None = Query(default=None, max_length=32),
    extraction_status: str | None = Query(default=None, max_length=32),
    language: str | None = Query(default=None, max_length=32),
    tag_or_category: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    change_filter: str | None = Query(default=None, max_length=32),
    include_excluded: bool = Query(default=False),
    sort_by: str = Query(default="last_discovered_at", max_length=32),
    sort_dir: str = Query(default="desc", max_length=8),
) -> ContentListResponse:
    return content_service.list_contents(
        page=page,
        page_size=page_size,
        website_id=website_id,
        category_id=category_id,
        tab=tab,
        content_type=content_type,
        extraction_status=extraction_status,
        language=language,
        tag_or_category=tag_or_category,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        search=search,
        change_filter=change_filter,
        include_excluded=include_excluded,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.get("/{content_id}", response_model=ContentDetailResponse)
def get_content(
    content_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    content_service: Annotated[ContentService, Depends(get_content_service)],
) -> ContentDetailResponse:
    return content_service.get_content(content_id)


@router.patch("/{content_id}", response_model=ContentDetailResponse)
def update_content(
    content_id: int,
    payload: ContentUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    content_service: Annotated[ContentService, Depends(get_content_service)],
) -> ContentDetailResponse:
    return content_service.update_content(
        content_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/{content_id}/reprocess", response_model=ContentDetailResponse)
def reprocess_content(
    content_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    content_service: Annotated[ContentService, Depends(get_content_service)],
) -> ContentDetailResponse:
    return content_service.reprocess_content(
        content_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/{content_id}/revisions", response_model=list[ContentRevisionResponse])
def list_content_revisions(
    content_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    content_service: Annotated[ContentService, Depends(get_content_service)],
) -> list[ContentRevisionResponse]:
    return content_service.list_revisions(content_id)
