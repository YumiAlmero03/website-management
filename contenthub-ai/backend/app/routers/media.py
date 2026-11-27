from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.core.dependencies import get_media_service, require_admin
from app.schemas.media import MediaAssetListResponse, MediaAssetResponse
from app.services.auth_service import AuthenticatedSession
from app.services.media_service import MediaService

router = APIRouter(prefix="/media", tags=["Media"])


@router.get("", response_model=MediaAssetListResponse)
def list_media(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    media_service: Annotated[MediaService, Depends(get_media_service)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    brand_id: int | None = Query(default=None, ge=1),
) -> MediaAssetListResponse:
    return media_service.list_media(page=page, page_size=page_size, brand_id=brand_id)


@router.get("/{media_id}", response_model=MediaAssetResponse)
def get_media(
    media_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    media_service: Annotated[MediaService, Depends(get_media_service)],
) -> MediaAssetResponse:
    return media_service.get_media(media_id)


@router.get("/{media_id}/file")
def get_media_file(
    media_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    media_service: Annotated[MediaService, Depends(get_media_service)],
) -> FileResponse:
    file_path, media_type = media_service.resolve_local_file(media_id)
    return FileResponse(path=file_path, media_type=media_type)
