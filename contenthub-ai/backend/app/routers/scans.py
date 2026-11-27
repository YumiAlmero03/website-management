from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.dependencies import (
    extract_client_ip,
    get_scan_executor_service,
    require_admin,
    require_csrf,
)
from app.schemas.website import ScanItemListResponse, ScanLogResponse
from app.services.auth_service import AuthenticatedSession
from app.services.scan_executor import ScanExecutorService

router = APIRouter(prefix="/scans", tags=["Scans"])


@router.get("/{scan_id}", response_model=ScanLogResponse)
def get_scan(
    scan_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    scan_service: Annotated[ScanExecutorService, Depends(get_scan_executor_service)],
) -> ScanLogResponse:
    return scan_service.get_scan(scan_id)


@router.get("/{scan_id}/items", response_model=ScanItemListResponse)
def list_scan_items(
    scan_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    scan_service: Annotated[ScanExecutorService, Depends(get_scan_executor_service)],
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    failures_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ScanItemListResponse:
    return scan_service.list_scan_items(
        scan_id,
        status=status_filter,
        failures_or_excluded_only=failures_only,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{scan_id}/retry",
    response_model=ScanLogResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_scan(
    scan_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    scan_service: Annotated[ScanExecutorService, Depends(get_scan_executor_service)],
) -> ScanLogResponse:
    return scan_service.retry_scan(
        scan_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
        dispatch=True,
    )
