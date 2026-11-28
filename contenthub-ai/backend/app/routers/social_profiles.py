from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.dependencies import (
    extract_client_ip,
    get_social_post_service,
    get_social_profile_service,
    require_admin,
    require_csrf,
)
from app.schemas.common import MessageResponse
from app.schemas.social_post import SocialPostResponse, SocialPostTestDraftRequest
from app.schemas.social_profile import (
    PlatformResponse,
    SocialProfileCreateRequest,
    SocialProfileResponse,
    SocialProfileUpdateRequest,
)
from app.services.auth_service import AuthenticatedSession
from app.services.social_post_service import SocialPostService
from app.services.social_profile_service import SocialProfileService

router = APIRouter(tags=["Social Profiles"])


@router.get("/platforms", response_model=list[PlatformResponse])
def list_platforms(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[SocialProfileService, Depends(get_social_profile_service)],
) -> list[PlatformResponse]:
    return service.list_platforms()


@router.get("/social-profiles", response_model=list[SocialProfileResponse])
def list_all_social_profiles(
    response: Response,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[SocialProfileService, Depends(get_social_profile_service)],
    website_id: int | None = Query(default=None, ge=1),
) -> list[SocialProfileResponse]:
    response.headers["Cache-Control"] = "no-store"
    return service.list_all(website_id=website_id)


@router.get("/websites/{website_id}/social-profiles", response_model=list[SocialProfileResponse])
def list_website_social_profiles(
    website_id: int,
    response: Response,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[SocialProfileService, Depends(get_social_profile_service)],
) -> list[SocialProfileResponse]:
    response.headers["Cache-Control"] = "no-store"
    return service.list_for_website(website_id)


@router.post(
    "/websites/{website_id}/social-profiles",
    response_model=SocialProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_social_profile(
    website_id: int,
    payload: SocialProfileCreateRequest,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[SocialProfileService, Depends(get_social_profile_service)],
) -> SocialProfileResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.create_profile(
        website_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/social-profiles/{profile_id}", response_model=SocialProfileResponse)
def get_social_profile(
    profile_id: int,
    response: Response,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[SocialProfileService, Depends(get_social_profile_service)],
) -> SocialProfileResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.get_profile(profile_id)


@router.post(
    "/social-profiles/{profile_id}/test-post",
    response_model=SocialPostResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an unpublished test draft for a social profile",
)
def create_social_profile_test_post(
    profile_id: int,
    payload: SocialPostTestDraftRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[SocialPostService, Depends(get_social_post_service)],
) -> SocialPostResponse:
    return service.create_test_draft(
        profile_id, payload, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.patch("/social-profiles/{profile_id}", response_model=SocialProfileResponse)
def update_social_profile(
    profile_id: int,
    payload: SocialProfileUpdateRequest,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[SocialProfileService, Depends(get_social_profile_service)],
) -> SocialProfileResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.update_profile(
        profile_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.delete("/social-profiles/{profile_id}", response_model=MessageResponse)
def delete_social_profile(
    profile_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[SocialProfileService, Depends(get_social_profile_service)],
) -> MessageResponse:
    service.delete_profile(
        profile_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
    return MessageResponse(message=f"Social profile #{profile_id} deleted.")
