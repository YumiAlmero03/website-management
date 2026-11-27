from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import (
    get_health_service,
    get_settings_service,
    require_admin,
)
from app.schemas.health import DatabaseHealthInfo, HealthLiveResponse, SystemHealthResponse
from app.services.auth_service import AuthenticatedSession
from app.services.monitoring.health_service import HealthService
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthLiveResponse)
def health_liveness(
    health_service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthLiveResponse:
    """Public lightweight liveness endpoint (exposes no credentials or host metrics)."""
    return health_service.get_liveness()


@router.get("/db", response_model=DatabaseHealthInfo)
def health_database(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
) -> DatabaseHealthInfo:
    """Protected MySQL connectivity, version, InnoDB, utf8mb4, and pool diagnostics."""
    return health_service.get_database_health()


@router.get("/system", response_model=SystemHealthResponse)
def health_system(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
) -> SystemHealthResponse:
    """Protected combined application, MySQL, storage, and psutil Resource Guardian diagnostics."""
    effective_settings = settings_service.get_effective_map()
    return health_service.get_system_health(effective_settings=effective_settings)
