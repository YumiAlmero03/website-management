from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_dashboard_service, require_admin
from app.schemas.dashboard import DashboardSummaryResponse
from app.services.auth_service import AuthenticatedSession
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
    brand_id: int | None = Query(default=None, ge=1),
    website_id: int | None = Query(default=None, ge=1),
) -> DashboardSummaryResponse:
    return dashboard_service.get_summary(brand_id=brand_id, website_id=website_id)
