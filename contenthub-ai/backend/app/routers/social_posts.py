from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, status

from app.core.dependencies import (
    extract_client_ip,
    get_ai_generation_service,
    get_social_post_service,
    require_admin,
    require_csrf,
)
from app.schemas.ai import AiGenerationJobResponse
from app.schemas.social_post import (
    SocialPostListResponse,
    SocialPostRegenerateRequest,
    SocialPostRejectRequest,
    SocialPostResponse,
    SocialPostRevisionResponse,
    SocialPostUpdateRequest,
)
from app.services.ai.generation_service import AiGenerationService
from app.services.auth_service import AuthenticatedSession
from app.services.social_post_service import SocialPostService

router = APIRouter(prefix="/social-posts", tags=["Social Drafts"])


@router.get("", response_model=SocialPostListResponse)
def list_social_posts(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[SocialPostService, Depends(get_social_post_service)],
    website_id: int | None = Query(default=None, ge=1),
    social_profile_id: int | None = Query(default=None, ge=1),
    platform_id: int | None = Query(default=None, ge=1),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    publishing_status: str | None = Query(default=None, max_length=32),
    view: str | None = Query(default=None, max_length=32),
    website_content_id: int | None = Query(default=None, ge=1),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> SocialPostListResponse:
    return service.list_posts(
        website_id=website_id,
        social_profile_id=social_profile_id,
        platform_id=platform_id,
        status=status_filter,
        publishing_status=publishing_status,
        view=view,
        website_content_id=website_content_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/{post_id}", response_model=SocialPostResponse)
def get_social_post(
    post_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[SocialPostService, Depends(get_social_post_service)],
) -> SocialPostResponse:
    return service.get_post(post_id)


@router.patch("/{post_id}", response_model=SocialPostResponse)
def update_social_post(
    post_id: int,
    payload: SocialPostUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[SocialPostService, Depends(get_social_post_service)],
) -> SocialPostResponse:
    return service.update_post(
        post_id, payload, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.post("/{post_id}/approve", response_model=SocialPostResponse)
def approve_social_post(
    post_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[SocialPostService, Depends(get_social_post_service)],
) -> SocialPostResponse:
    return service.approve_post(
        post_id, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.post("/{post_id}/reject", response_model=SocialPostResponse)
def reject_social_post(
    post_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[SocialPostService, Depends(get_social_post_service)],
    payload: Annotated[SocialPostRejectRequest | None, Body()] = None,
) -> SocialPostResponse:
    return service.reject_post(
        post_id,
        payload or SocialPostRejectRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/{post_id}/archive", response_model=SocialPostResponse)
def archive_social_post(
    post_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[SocialPostService, Depends(get_social_post_service)],
) -> SocialPostResponse:
    return service.archive_post(
        post_id, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.post(
    "/{post_id}/regenerate",
    response_model=AiGenerationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_social_post(
    post_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    generation_service: Annotated[AiGenerationService, Depends(get_ai_generation_service)],
    payload: Annotated[SocialPostRegenerateRequest | None, Body()] = None,
) -> AiGenerationJobResponse:
    return generation_service.enqueue_regeneration_for_post(
        post_id,
        payload or SocialPostRegenerateRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/{post_id}/revisions", response_model=list[SocialPostRevisionResponse])
def list_social_post_revisions(
    post_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[SocialPostService, Depends(get_social_post_service)],
) -> list[SocialPostRevisionResponse]:
    return service.list_revisions(post_id)
