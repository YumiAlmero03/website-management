from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Query, Request, UploadFile, status

from app.core.dependencies import (
    extract_client_ip,
    get_scan_executor_service,
    get_website_service,
    require_admin,
    require_csrf,
)
from app.schemas.common import MessageResponse
from app.schemas.website import (
    ScanLogListResponse,
    ScanLogResponse,
    ScanTriggerRequest,
    WebsiteConnectivityResponse,
    WebsiteCreateRequest,
    WebsiteDiscoverResponse,
    WebsiteDiscoverySourceResponse,
    WebsiteDiscoverySourceUpdateRequest,
    WebsiteListResponse,
    WebsiteResponse,
    WebsiteUpdateRequest,
    WebsiteUrlRuleCreateRequest,
    WebsiteUrlRuleResponse,
    WebsiteUrlRuleUpdateRequest,
)
from app.services.auth_service import AuthenticatedSession
from app.services.scan_executor import ScanExecutorService
from app.services.website_service import WebsiteService

router = APIRouter(prefix="/websites", tags=["Websites"])


@router.get("", response_model=WebsiteListResponse)
def list_websites(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category_id: int | None = Query(default=None, ge=1),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    website_type: str | None = Query(default=None, max_length=32),
    search: str | None = Query(default=None, max_length=120),
) -> WebsiteListResponse:
    return website_service.list_websites(
        page=page,
        page_size=page_size,
        category_id=category_id,
        status=status_filter,
        website_type=website_type,
        search=search,
    )


@router.post("", response_model=WebsiteResponse, status_code=status.HTTP_201_CREATED)
def create_website(
    payload: WebsiteCreateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> WebsiteResponse:
    return website_service.create_website(
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/{website_id}", response_model=WebsiteResponse)
def get_website(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> WebsiteResponse:
    return website_service.get_website(website_id)


@router.get("/{website_id}/keyword-bank", response_model=list[str])
def get_website_keyword_bank(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> list[str]:
    return website_service.get_keyword_bank(website_id)


@router.patch("/{website_id}", response_model=WebsiteResponse)
def update_website(
    website_id: int,
    payload: WebsiteUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> WebsiteResponse:
    return website_service.update_website(
        website_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.delete("/{website_id}", response_model=MessageResponse)
def delete_website(
    website_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> MessageResponse:
    website_service.delete_website(
        website_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
    return MessageResponse(message=f"Website #{website_id} deleted.")


@router.post("/{website_id}/logo", response_model=WebsiteResponse)
async def upload_website_logo(
    website_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
    file: UploadFile = File(...),
) -> WebsiteResponse:
    file_bytes = await file.read()
    return website_service.upload_logo(
        website_id,
        filename=file.filename or "logo.png",
        file_bytes=file_bytes,
        content_type=file.content_type,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/{website_id}/test", response_model=WebsiteConnectivityResponse)
def test_website_connectivity(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> WebsiteConnectivityResponse:
    return website_service.test_connectivity(website_id)


@router.post("/{website_id}/discover", response_model=WebsiteDiscoverResponse)
def discover_website_sources(
    website_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
    apply: bool = Query(default=False),
) -> WebsiteDiscoverResponse:
    return website_service.discover_sources(
        website_id,
        apply_detected=apply,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/{website_id}/sources", response_model=list[WebsiteDiscoverySourceResponse])
def list_website_sources(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> list[WebsiteDiscoverySourceResponse]:
    return website_service.list_sources(website_id)


@router.patch(
    "/{website_id}/sources/{source_id}",
    response_model=WebsiteDiscoverySourceResponse,
)
def update_website_source(
    website_id: int,
    source_id: int,
    payload: WebsiteDiscoverySourceUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> WebsiteDiscoverySourceResponse:
    return website_service.update_source(
        website_id,
        source_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/{website_id}/rules", response_model=list[WebsiteUrlRuleResponse])
def list_website_rules(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> list[WebsiteUrlRuleResponse]:
    return website_service.list_rules(website_id)


@router.post(
    "/{website_id}/rules",
    response_model=WebsiteUrlRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_website_rule(
    website_id: int,
    payload: WebsiteUrlRuleCreateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> WebsiteUrlRuleResponse:
    return website_service.create_rule(
        website_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.patch("/{website_id}/rules/{rule_id}", response_model=WebsiteUrlRuleResponse)
def update_website_rule(
    website_id: int,
    rule_id: int,
    payload: WebsiteUrlRuleUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> WebsiteUrlRuleResponse:
    return website_service.update_rule(
        website_id,
        rule_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.delete("/{website_id}/rules/{rule_id}", response_model=MessageResponse)
def delete_website_rule(
    website_id: int,
    rule_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    website_service: Annotated[WebsiteService, Depends(get_website_service)],
) -> MessageResponse:
    website_service.delete_rule(
        website_id,
        rule_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
    return MessageResponse(message=f"URL classification rule #{rule_id} deleted.")


@router.post(
    "/{website_id}/scan",
    response_model=ScanLogResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_website_scan(
    website_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    scan_service: Annotated[ScanExecutorService, Depends(get_scan_executor_service)],
    payload: ScanTriggerRequest | None = Body(default=None),
) -> ScanLogResponse:
    req = payload or ScanTriggerRequest()
    return scan_service.enqueue_scan(
        website_id,
        scan_mode=req.scan_mode,
        trigger_type="manual",
        max_urls_override=req.max_urls,
        batch_size_override=req.batch_size,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
        dispatch=True,
    )


@router.get("/{website_id}/scan-logs", response_model=ScanLogListResponse)
def list_website_scan_logs(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    scan_service: Annotated[ScanExecutorService, Depends(get_scan_executor_service)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ScanLogListResponse:
    return scan_service.list_website_scans(website_id, page=page, page_size=page_size)
