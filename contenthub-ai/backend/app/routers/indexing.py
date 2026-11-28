from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import (
    get_indexing_service,
    require_admin,
    require_csrf,
)
from app.schemas.indexing import IndexingStatusResponse
from app.services.auth_service import AuthenticatedSession
from app.services.indexing_service import IndexingService

router = APIRouter(prefix="/indexing", tags=["Google Indexing"])


@router.post("/websites/{website_id}/run", response_model=IndexingStatusResponse)
def run_indexing(
    website_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[IndexingService, Depends(get_indexing_service)],
) -> IndexingStatusResponse:
    return IndexingStatusResponse(**service.start(website_id))


@router.post("/run-all", response_model=IndexingStatusResponse)
def run_all_indexing(
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[IndexingService, Depends(get_indexing_service)],
) -> IndexingStatusResponse:
    return IndexingStatusResponse(**service.run_daily_indexing(execute_inline=False))


@router.get("/websites/{website_id}/status", response_model=IndexingStatusResponse)
def indexing_status(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[IndexingService, Depends(get_indexing_service)],
) -> IndexingStatusResponse:
    return IndexingStatusResponse(**service.get_status(website_id))
