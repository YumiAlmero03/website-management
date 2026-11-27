from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.core.dependencies import (
    extract_client_ip,
    get_app_settings,
    get_auth_service,
    require_admin,
    require_csrf,
)
from app.models.base import ensure_utc, utc_now
from app.schemas.auth import (
    AdminUserResponse,
    AuthSessionResponse,
    AuthStatusResponse,
    LoginRequest,
    LogoutResponse,
)
from app.services.auth_service import AuthenticatedSession, AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _to_session_response(auth: AuthenticatedSession) -> AuthSessionResponse:
    now = utc_now()
    return AuthSessionResponse(
        user=AdminUserResponse(
            id=auth.user.id,
            email=auth.user.email,
            display_name=auth.user.display_name,
            is_active=auth.user.is_active,
            last_login_at=ensure_utc(auth.user.last_login_at),
            created_at=ensure_utc(auth.user.created_at) or now,
        ),
        csrf_token=auth.session.csrf_token,
        expires_at=ensure_utc(auth.session.expires_at) or now,
    )


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_app_settings)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthStatusResponse:
    """Public status probe so the login UI can show CLI setup guidance if uninitialized."""
    response.headers["Cache-Control"] = "no-store"
    raw_token = request.cookies.get(settings.session_cookie_name)
    try:
        initialized = auth_service.is_admin_initialized()
        authenticated = (
            auth_service.resolve_session(raw_token) is not None if initialized else False
        )
        return AuthStatusResponse(
            admin_initialized=initialized,
            authenticated=authenticated,
            app_name=settings.app_name,
            database_connected=True,
            registration_enabled=False,
        )
    except SQLAlchemyError:
        return AuthStatusResponse(
            admin_initialized=False,
            authenticated=False,
            app_name=settings.app_name,
            database_connected=False,
            registration_enabled=False,
        )


@router.post("/login", response_model=AuthSessionResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_app_settings)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthSessionResponse:
    response.headers["Cache-Control"] = "no-store"
    auth = auth_service.login(
        email=payload.email,
        password=payload.password,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    assert auth.raw_token is not None

    max_age = settings.session_ttl_minutes * 60
    response.set_cookie(
        key=settings.session_cookie_name,
        value=auth.raw_token,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,  # type: ignore[arg-type]
        path="/",
    )
    return _to_session_response(auth)


@router.get("/me", response_model=AuthSessionResponse)
def current_session(
    response: Response,
    auth: Annotated[AuthenticatedSession, Depends(require_admin)],
) -> AuthSessionResponse:
    response.headers["Cache-Control"] = "no-store"
    return _to_session_response(auth)


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_app_settings)],
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LogoutResponse:
    response.headers["Cache-Control"] = "no-store"
    auth_service.logout(auth, ip_address=extract_client_ip(request))
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,  # type: ignore[arg-type]
    )
    return LogoutResponse(message="Signed out successfully.")
