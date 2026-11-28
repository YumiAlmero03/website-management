from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse

from app.core.dependencies import (
    extract_client_ip,
    get_publishing_connection_service,
    get_publishing_service,
    require_admin,
    require_csrf,
)
from app.schemas.publishing import (
    CalendarResponse,
    CancelScheduleRequest,
    ConnectAccountRequest,
    ConnectAccountResponse,
    DisconnectAccountRequest,
    MarkPublishedRequest,
    OAuthCompleteRequest,
    PublishingHistoryListResponse,
    PublishingJobListResponse,
    PublishingJobResponse,
    PublishingLogResponse,
    PublishingPreflightResponse,
    PublishingStatisticsResponse,
    PublishNowRequest,
    ReconcileJobRequest,
    SchedulePostRequest,
    SelectTargetRequest,
    SocialPostMediaAttachmentResponse,
    SocialPostMediaUpdateRequest,
    SocialProfileConnectionResponse,
)
from app.schemas.social_post import SocialPostResponse
from app.services.auth_service import AuthenticatedSession
from app.services.publishing_connection_service import PublishingConnectionService
from app.services.publishing_service import PublishingService

router = APIRouter(tags=["Social Publishing"])


# ==============================================================================
# Social Profile Connections & OAuth Management
# ==============================================================================
@router.get("/publishing/connections", response_model=list[SocialProfileConnectionResponse])
def list_all_connections(
    response: Response,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[
        PublishingConnectionService, Depends(get_publishing_connection_service)
    ],
    website_id: int | None = Query(default=None, ge=1),
) -> list[SocialProfileConnectionResponse]:
    response.headers["Cache-Control"] = "no-store"
    profiles = service.profile_repo.list_all(website_id=website_id)
    out: list[SocialProfileConnectionResponse] = []
    for p in profiles:
        plat = service.profile_repo.get_platform_by_id(p.platform_id)
        if plat is None:
            continue
        conn = service.get_or_init_connection(p, plat)
        out.append(service.to_response(p, plat, conn))
    return out


@router.get(
    "/social-profiles/{profile_id}/connection-status",
    response_model=SocialProfileConnectionResponse,
)
def get_profile_connection_status(
    profile_id: int,
    response: Response,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[
        PublishingConnectionService, Depends(get_publishing_connection_service)
    ],
) -> SocialProfileConnectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.get_connection_status(profile_id)


@router.post("/social-profiles/{profile_id}/connect", response_model=ConnectAccountResponse)
def connect_social_profile(
    profile_id: int,
    payload: ConnectAccountRequest,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[
        PublishingConnectionService, Depends(get_publishing_connection_service)
    ],
) -> ConnectAccountResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.connect_account(
        profile_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post(
    "/social-profiles/{profile_id}/oauth/complete",
    response_model=SocialProfileConnectionResponse,
)
def complete_profile_oauth(
    profile_id: int,
    payload: OAuthCompleteRequest,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[
        PublishingConnectionService, Depends(get_publishing_connection_service)
    ],
) -> SocialProfileConnectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.complete_oauth_callback(
        profile_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post(
    "/social-profiles/{profile_id}/select-target",
    response_model=SocialProfileConnectionResponse,
)
def select_profile_target(
    profile_id: int,
    payload: SelectTargetRequest,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[
        PublishingConnectionService, Depends(get_publishing_connection_service)
    ],
) -> SocialProfileConnectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.select_target(
        profile_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post(
    "/social-profiles/{profile_id}/disconnect",
    response_model=SocialProfileConnectionResponse,
)
def disconnect_social_profile(
    profile_id: int,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[
        PublishingConnectionService, Depends(get_publishing_connection_service)
    ],
    payload: Annotated[DisconnectAccountRequest | None, Body()] = None,
) -> SocialProfileConnectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.disconnect_account(
        profile_id,
        payload or DisconnectAccountRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post(
    "/social-profiles/{profile_id}/verify",
    response_model=SocialProfileConnectionResponse,
)
def verify_social_profile(
    profile_id: int,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[
        PublishingConnectionService, Depends(get_publishing_connection_service)
    ],
) -> SocialProfileConnectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.verify_connection(
        profile_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post(
    "/social-profiles/{profile_id}/refresh",
    response_model=SocialProfileConnectionResponse,
)
def refresh_social_profile(
    profile_id: int,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[
        PublishingConnectionService, Depends(get_publishing_connection_service)
    ],
) -> SocialProfileConnectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.refresh_connection(
        profile_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post(
    "/social-profiles/{profile_id}/paid-policy",
    response_model=SocialProfileConnectionResponse,
)
def update_profile_paid_policy(
    profile_id: int,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[
        PublishingConnectionService, Depends(get_publishing_connection_service)
    ],
    allow_paid_publishing: bool = Body(embed=True),
) -> SocialProfileConnectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.set_paid_publishing(
        profile_id,
        allow_paid_publishing=allow_paid_publishing,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


# ==============================================================================
# Post Preflight, Media, Publishing, Scheduling & Manual Recording
# ==============================================================================
@router.get("/social-posts/{post_id}/preflight", response_model=PublishingPreflightResponse)
def get_post_preflight(
    post_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
    confirm_paid_api: bool = Query(default=False),
) -> PublishingPreflightResponse:
    return service.preflight_post(post_id, confirm_paid_api=confirm_paid_api)


@router.get(
    "/social-posts/{post_id}/media",
    response_model=list[SocialPostMediaAttachmentResponse],
)
def list_post_media(
    post_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> list[SocialPostMediaAttachmentResponse]:
    return service.list_post_media(post_id)


@router.put(
    "/social-posts/{post_id}/media",
    response_model=list[SocialPostMediaAttachmentResponse],
)
def update_post_media(
    post_id: int,
    payload: SocialPostMediaUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> list[SocialPostMediaAttachmentResponse]:
    return service.update_post_media(
        post_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post(
    "/social-posts/{post_id}/publish",
    response_model=PublishingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def publish_social_post_now(
    post_id: int,
    payload: PublishNowRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> PublishingJobResponse:
    return service.publish_now(
        post_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/social-posts/{post_id}/schedule", response_model=SocialPostResponse)
def schedule_social_post(
    post_id: int,
    payload: SchedulePostRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> SocialPostResponse:
    return service.schedule_post(
        post_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/social-posts/{post_id}/cancel-schedule", response_model=SocialPostResponse)
def cancel_social_post_schedule(
    post_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
    payload: Annotated[CancelScheduleRequest | None, Body()] = None,
) -> SocialPostResponse:
    return service.cancel_schedule(
        post_id,
        payload or CancelScheduleRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/social-posts/{post_id}/mark-published", response_model=SocialPostResponse)
def mark_social_post_published(
    post_id: int,
    payload: MarkPublishedRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> SocialPostResponse:
    return service.mark_manually_published(
        post_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/social-posts/{post_id}/logs", response_model=list[PublishingLogResponse])
def list_social_post_logs(
    post_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> list[PublishingLogResponse]:
    return service.list_post_logs(post_id)


# ==============================================================================
# Publishing Jobs, Reconciliation, Calendar, History & Statistics
# ==============================================================================
@router.get("/publishing/jobs", response_model=PublishingJobListResponse)
def list_publishing_jobs(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
    website_id: int | None = Query(default=None, ge=1),
    social_profile_id: int | None = Query(default=None, ge=1),
    platform_key: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    social_post_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> PublishingJobListResponse:
    return service.list_jobs(
        website_id=website_id,
        social_profile_id=social_profile_id,
        platform_key=platform_key,
        status=status_filter,
        social_post_id=social_post_id,
        page=page,
        page_size=page_size,
    )


@router.get("/publishing/jobs/{job_id}", response_model=PublishingJobResponse)
def get_publishing_job(
    job_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> PublishingJobResponse:
    return service.get_job(job_id)


@router.post(
    "/publishing/jobs/{job_id}/retry",
    response_model=PublishingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_publishing_job(
    job_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> PublishingJobResponse:
    return service.retry_job(
        job_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.post("/publishing/jobs/{job_id}/reconcile", response_model=PublishingJobResponse)
def reconcile_publishing_job(
    job_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
    payload: Annotated[ReconcileJobRequest | None, Body()] = None,
) -> PublishingJobResponse:
    return service.reconcile_job(
        job_id,
        payload or ReconcileJobRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/publishing/calendar", response_model=CalendarResponse)
def get_publishing_calendar(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
    website_id: int | None = Query(default=None, ge=1),
    social_profile_id: int | None = Query(default=None, ge=1),
    platform_key: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
) -> CalendarResponse:
    return service.get_calendar(
        website_id=website_id,
        social_profile_id=social_profile_id,
        platform_key=platform_key,
        status=status_filter,
        start_utc=start,
        end_utc=end,
    )


@router.get("/publishing/history", response_model=PublishingHistoryListResponse)
def list_publishing_history(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
    website_id: int | None = Query(default=None, ge=1),
    social_profile_id: int | None = Query(default=None, ge=1),
    platform_key: str | None = Query(default=None, max_length=64),
    outcome: str | None = Query(default=None, max_length=32),
    publishing_method: str | None = Query(default=None, max_length=24),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> PublishingHistoryListResponse:
    return service.list_history(
        website_id=website_id,
        social_profile_id=social_profile_id,
        platform_key=platform_key,
        outcome=outcome,
        publishing_method=publishing_method,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.get("/publishing/history/export")
def export_publishing_history_csv(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
    website_id: int | None = Query(default=None, ge=1),
    social_profile_id: int | None = Query(default=None, ge=1),
    platform_key: str | None = Query(default=None, max_length=64),
    outcome: str | None = Query(default=None, max_length=32),
    publishing_method: str | None = Query(default=None, max_length=24),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> Response:
    csv_data = service.export_history_csv(
        website_id=website_id,
        social_profile_id=social_profile_id,
        platform_key=platform_key,
        outcome=outcome,
        publishing_method=publishing_method,
        date_from=date_from,
        date_to=date_to,
    )
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="contenthub-publishing-history.csv"'},
    )


@router.get("/publishing/statistics", response_model=PublishingStatisticsResponse)
def get_publishing_statistics(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PublishingService, Depends(get_publishing_service)],
    website_id: int | None = Query(default=None, ge=1),
    platform_id: int | None = Query(default=None, ge=1),
) -> PublishingStatisticsResponse:
    return service.get_statistics(website_id=website_id, platform_id=platform_id)


@router.get("/public-media/{token}")
def serve_scoped_public_media(
    token: str,
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> FileResponse:
    """Strictly scoped tokenized delivery for prepared images required by IG/Threads URLs."""
    file_path, media_type = service.resolve_public_media(token)
    return FileResponse(path=file_path, media_type=media_type)
