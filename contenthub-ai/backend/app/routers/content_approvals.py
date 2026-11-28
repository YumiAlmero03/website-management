from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request

from app.core.dependencies import (
    extract_client_ip,
    get_content_approval_service,
    require_admin,
    require_csrf,
)
from app.schemas.keyword_approval import (
    AiKeywordRefineRequest,
    AiKeywordSuggestionPreviewResponse,
    ApproveContentRequest,
    ApproveContentResultResponse,
    ApprovedKeywordMapEntryResponse,
    BulkApproveRequest,
    BulkApproveResultResponse,
    ContentApprovalDetailResponse,
    ContentApprovalListResponse,
    ContentApprovalStatsResponse,
    KeywordMapListResponse,
    KeywordMappingUpdateRequest,
    RejectContentRequest,
    ReopenReviewRequest,
)
from app.services.auth_service import AuthenticatedSession
from app.services.content_approval_service import ContentApprovalService

router = APIRouter(prefix="/content-approvals", tags=["Content Approval & Keywords"])


@router.get("", response_model=ContentApprovalListResponse)
def list_content_approvals(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
    website_id: int | None = Query(default=None, ge=1),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    content_type: str | None = Query(default=None, max_length=32),
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ContentApprovalListResponse:
    return service.list_approvals(
        website_id=website_id,
        status=status_filter,
        content_type=content_type,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=ContentApprovalStatsResponse)
def get_content_approval_stats(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
    website_id: int | None = Query(default=None, ge=1),
    category_id: int | None = Query(default=None, ge=1),
) -> ContentApprovalStatsResponse:
    return service.get_stats(website_id=website_id, category_id=category_id)


@router.get("/keyword-map", response_model=KeywordMapListResponse)
def list_keyword_map(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
    website_id: int | None = Query(default=None, ge=1),
    content_type: str | None = Query(default=None, max_length=32),
    search: str | None = Query(default=None, max_length=200),
    approved_only: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> KeywordMapListResponse:
    return service.list_keyword_map(
        website_id=website_id,
        content_type=content_type,
        search=search,
        approved_only=approved_only,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/websites/{website_id}/approved-keywords",
    response_model=list[ApprovedKeywordMapEntryResponse],
)
def get_website_approved_keywords(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
    content_type: str | None = Query(default=None, max_length=32),
) -> list[ApprovedKeywordMapEntryResponse]:
    return service.reuse_service.get_approved_keyword_map(
        website_id,
        content_type=content_type,
    )


@router.post("/bulk-approve", response_model=BulkApproveResultResponse)
def bulk_approve_contents(
    payload: BulkApproveRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
) -> BulkApproveResultResponse:
    return service.bulk_approve(
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/{content_id}", response_model=ContentApprovalDetailResponse)
def get_content_approval_detail(
    content_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
) -> ContentApprovalDetailResponse:
    return service.get_approval_detail(content_id)


@router.patch("/{content_id}/keywords", response_model=ContentApprovalDetailResponse)
def update_content_keywords(
    content_id: int,
    payload: KeywordMappingUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
) -> ContentApprovalDetailResponse:
    return service.update_keywords_inline(
        content_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/{content_id}/keywords/suggest-ai", response_model=AiKeywordSuggestionPreviewResponse)
def suggest_keywords_with_ai(
    content_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
    payload: Annotated[AiKeywordRefineRequest | None, Body()] = None,
) -> AiKeywordSuggestionPreviewResponse:
    return service.suggest_keywords_with_ai(
        content_id,
        payload or AiKeywordRefineRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/{content_id}/approve", response_model=ApproveContentResultResponse)
def approve_content(
    content_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
    payload: Annotated[ApproveContentRequest | None, Body()] = None,
) -> ApproveContentResultResponse:
    return service.approve_content(
        content_id,
        payload or ApproveContentRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/{content_id}/reject", response_model=ContentApprovalDetailResponse)
def reject_content(
    content_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
    payload: Annotated[RejectContentRequest | None, Body()] = None,
) -> ContentApprovalDetailResponse:
    return service.reject_content(
        content_id,
        payload or RejectContentRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/{content_id}/reopen", response_model=ContentApprovalDetailResponse)
def reopen_content_for_review(
    content_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
    payload: Annotated[ReopenReviewRequest | None, Body()] = None,
) -> ContentApprovalDetailResponse:
    return service.reopen_for_review(
        content_id,
        payload or ReopenReviewRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
