from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.core.dependencies import (
    extract_client_ip,
    get_scan_executor_service,
    require_admin,
    require_csrf,
)
from app.schemas.website import ScanLogResponse
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
