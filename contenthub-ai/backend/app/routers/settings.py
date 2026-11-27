from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.core.dependencies import (
    extract_client_ip,
    get_settings_service,
    require_admin,
    require_csrf,
)
from app.schemas.settings import SettingsBulkUpdateRequest, SettingsListResponse
from app.services.auth_service import AuthenticatedSession
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=SettingsListResponse)
def list_settings(
    response: Response,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
) -> SettingsListResponse:
    response.headers["Cache-Control"] = "no-store"
    return settings_service.list_settings()


@router.put("", response_model=SettingsListResponse)
def update_settings(
    payload: SettingsBulkUpdateRequest,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
) -> SettingsListResponse:
    response.headers["Cache-Control"] = "no-store"
    return settings_service.bulk_update(
        updates=payload.items,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
