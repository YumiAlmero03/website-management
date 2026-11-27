from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.dependencies import (
    extract_client_ip,
    get_category_service,
    require_admin,
    require_csrf,
)
from app.schemas.category import (
    WebsiteCategoryCreateRequest,
    WebsiteCategoryListResponse,
    WebsiteCategoryResponse,
    WebsiteCategoryUpdateRequest,
)
from app.schemas.common import MessageResponse
from app.services.auth_service import AuthenticatedSession
from app.services.category_service import WebsiteCategoryService

router = APIRouter(prefix="/website-categories", tags=["Website Categories"])


@router.get("", response_model=WebsiteCategoryListResponse)
def list_website_categories(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    category_service: Annotated[WebsiteCategoryService, Depends(get_category_service)],
    include_archived: bool = Query(default=False),
) -> WebsiteCategoryListResponse:
    return category_service.list_categories(include_archived=include_archived)


@router.post("", response_model=WebsiteCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_website_category(
    payload: WebsiteCategoryCreateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    category_service: Annotated[WebsiteCategoryService, Depends(get_category_service)],
) -> WebsiteCategoryResponse:
    return category_service.create_category(
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/{category_id}", response_model=WebsiteCategoryResponse)
def get_website_category(
    category_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    category_service: Annotated[WebsiteCategoryService, Depends(get_category_service)],
) -> WebsiteCategoryResponse:
    return category_service.get_category(category_id)


@router.patch("/{category_id}", response_model=WebsiteCategoryResponse)
def update_website_category(
    category_id: int,
    payload: WebsiteCategoryUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    category_service: Annotated[WebsiteCategoryService, Depends(get_category_service)],
) -> WebsiteCategoryResponse:
    return category_service.update_category(
        category_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.delete("/{category_id}", response_model=MessageResponse)
def delete_website_category(
    category_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    category_service: Annotated[WebsiteCategoryService, Depends(get_category_service)],
) -> MessageResponse:
    category_service.delete_category(
        category_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
    return MessageResponse(message=f"Website category #{category_id} deleted.")
