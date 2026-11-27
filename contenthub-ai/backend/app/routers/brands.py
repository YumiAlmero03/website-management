from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status

from app.core.dependencies import (
    extract_client_ip,
    get_brand_service,
    require_admin,
    require_csrf,
)
from app.schemas.brand import (
    BrandCreateRequest,
    BrandDetailResponse,
    BrandListResponse,
    BrandResponse,
    BrandUpdateRequest,
)
from app.schemas.common import MessageResponse
from app.services.auth_service import AuthenticatedSession
from app.services.brand_service import BrandService

router = APIRouter(prefix="/brands", tags=["Brands"])


@router.get("", response_model=BrandListResponse)
def list_brands(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    brand_service: Annotated[BrandService, Depends(get_brand_service)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=120),
    is_active: bool | None = Query(default=None),
    language: str | None = Query(default=None, max_length=32),
) -> BrandListResponse:
    return brand_service.list_brands(
        page=page,
        page_size=page_size,
        search=search,
        is_active=is_active,
        language=language,
    )


@router.post("", response_model=BrandResponse, status_code=status.HTTP_201_CREATED)
def create_brand(
    payload: BrandCreateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    brand_service: Annotated[BrandService, Depends(get_brand_service)],
) -> BrandResponse:
    return brand_service.create_brand(
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/{brand_id}", response_model=BrandDetailResponse)
def get_brand(
    brand_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    brand_service: Annotated[BrandService, Depends(get_brand_service)],
) -> BrandDetailResponse:
    return brand_service.get_brand_detail(brand_id)


@router.patch("/{brand_id}", response_model=BrandResponse)
def update_brand(
    brand_id: int,
    payload: BrandUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    brand_service: Annotated[BrandService, Depends(get_brand_service)],
) -> BrandResponse:
    return brand_service.update_brand(
        brand_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.delete("/{brand_id}", response_model=MessageResponse)
def delete_brand(
    brand_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    brand_service: Annotated[BrandService, Depends(get_brand_service)],
) -> MessageResponse:
    brand_service.delete_brand(
        brand_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
    return MessageResponse(message=f"Brand #{brand_id} deleted.")


@router.post("/{brand_id}/logo", response_model=BrandResponse)
async def upload_brand_logo(
    brand_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    brand_service: Annotated[BrandService, Depends(get_brand_service)],
    file: UploadFile = File(...),
) -> BrandResponse:
    content = await file.read()
    return brand_service.upload_logo(
        brand_id,
        file_bytes=content,
        declared_mime=file.content_type,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
