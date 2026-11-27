from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import constant_time_equals
from app.database import DatabaseDiagnostic, check_database_connection, get_session_factory
from app.repositories.activity_log_repo import (
    ActivityLogRepositoryProtocol,
    SQLAlchemyActivityLogRepository,
)
from app.repositories.article_repo import ArticleRepositoryProtocol, SQLAlchemyArticleRepository
from app.repositories.brand_repo import BrandRepositoryProtocol, SQLAlchemyBrandRepository
from app.repositories.media_repo import MediaRepositoryProtocol, SQLAlchemyMediaRepository
from app.repositories.scan_log_repo import ScanLogRepositoryProtocol, SQLAlchemyScanLogRepository
from app.repositories.session_repo import SessionRepositoryProtocol, SQLAlchemySessionRepository
from app.repositories.settings_repo import SettingsRepositoryProtocol, SQLAlchemySettingsRepository
from app.repositories.user_repo import SQLAlchemyUserRepository, UserRepositoryProtocol
from app.repositories.website_repo import SQLAlchemyWebsiteRepository, WebsiteRepositoryProtocol
from app.services.article_service import ArticleService
from app.services.auth_service import AuthenticatedSession, AuthService
from app.services.brand_service import BrandService
from app.services.dashboard_service import DashboardService
from app.services.media_service import MediaService
from app.services.monitoring.health_service import HealthService
from app.services.scan_executor import (
    ScanDispatcher,
    ScanExecutorService,
    default_subprocess_dispatcher,
)
from app.services.scanner.security import SafeHttpFetcher
from app.services.settings_service import SettingsService
from app.services.website_service import WebsiteService

_rate_limiter: SlidingWindowRateLimiter | None = None


def get_app_settings() -> Settings:
    return get_settings()


def get_login_rate_limiter(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SlidingWindowRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = SlidingWindowRateLimiter(
            max_attempts=settings.login_rate_limit_max_attempts,
            window_seconds=settings.login_rate_limit_window_seconds,
        )
    return _rate_limiter


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_user_repo(db: Annotated[Session, Depends(get_db_session)]) -> UserRepositoryProtocol:
    return SQLAlchemyUserRepository(db)


def get_session_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> SessionRepositoryProtocol:
    return SQLAlchemySessionRepository(db)


def get_settings_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> SettingsRepositoryProtocol:
    return SQLAlchemySettingsRepository(db)


def get_activity_log_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> ActivityLogRepositoryProtocol:
    return SQLAlchemyActivityLogRepository(db)


def get_brand_repo(db: Annotated[Session, Depends(get_db_session)]) -> BrandRepositoryProtocol:
    return SQLAlchemyBrandRepository(db)


def get_website_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> WebsiteRepositoryProtocol:
    return SQLAlchemyWebsiteRepository(db)


def get_article_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> ArticleRepositoryProtocol:
    return SQLAlchemyArticleRepository(db)


def get_scan_log_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> ScanLogRepositoryProtocol:
    return SQLAlchemyScanLogRepository(db)


def get_media_repo(db: Annotated[Session, Depends(get_db_session)]) -> MediaRepositoryProtocol:
    return SQLAlchemyMediaRepository(db)


def get_db_health_checker(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Callable[[], DatabaseDiagnostic]:
    return lambda: check_database_connection(settings=settings)


def get_http_fetcher(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SafeHttpFetcher:
    return SafeHttpFetcher(settings=settings)


def get_scan_dispatcher() -> ScanDispatcher:
    return default_subprocess_dispatcher


def get_auth_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    user_repo: Annotated[UserRepositoryProtocol, Depends(get_user_repo)],
    session_repo: Annotated[SessionRepositoryProtocol, Depends(get_session_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    rate_limiter: Annotated[SlidingWindowRateLimiter, Depends(get_login_rate_limiter)],
) -> AuthService:
    return AuthService(
        settings=settings,
        user_repo=user_repo,
        session_repo=session_repo,
        activity_repo=activity_repo,
        rate_limiter=rate_limiter,
    )


def get_settings_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    settings_repo: Annotated[SettingsRepositoryProtocol, Depends(get_settings_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
) -> SettingsService:
    return SettingsService(
        settings=settings,
        settings_repo=settings_repo,
        activity_repo=activity_repo,
    )


def get_health_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db_checker: Annotated[Callable[[], DatabaseDiagnostic], Depends(get_db_health_checker)],
) -> HealthService:
    return HealthService(settings=settings, db_checker=db_checker)


def get_dashboard_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
    session_repo: Annotated[SessionRepositoryProtocol, Depends(get_session_repo)],
    settings_repo: Annotated[SettingsRepositoryProtocol, Depends(get_settings_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    brand_repo: Annotated[BrandRepositoryProtocol, Depends(get_brand_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    article_repo: Annotated[ArticleRepositoryProtocol, Depends(get_article_repo)],
    scan_log_repo: Annotated[ScanLogRepositoryProtocol, Depends(get_scan_log_repo)],
) -> DashboardService:
    return DashboardService(
        settings=settings,
        health_service=health_service,
        settings_service=settings_service,
        session_repo=session_repo,
        settings_repo=settings_repo,
        activity_repo=activity_repo,
        brand_repo=brand_repo,
        website_repo=website_repo,
        article_repo=article_repo,
        scan_log_repo=scan_log_repo,
    )


def get_brand_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    brand_repo: Annotated[BrandRepositoryProtocol, Depends(get_brand_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    media_repo: Annotated[MediaRepositoryProtocol, Depends(get_media_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
) -> BrandService:
    return BrandService(
        settings=settings,
        brand_repo=brand_repo,
        website_repo=website_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
    )


def get_website_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    brand_repo: Annotated[BrandRepositoryProtocol, Depends(get_brand_repo)],
    article_repo: Annotated[ArticleRepositoryProtocol, Depends(get_article_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    fetcher: Annotated[SafeHttpFetcher, Depends(get_http_fetcher)],
) -> WebsiteService:
    return WebsiteService(
        settings=settings,
        website_repo=website_repo,
        brand_repo=brand_repo,
        article_repo=article_repo,
        activity_repo=activity_repo,
        fetcher=fetcher,
    )


def get_scan_executor_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    brand_repo: Annotated[BrandRepositoryProtocol, Depends(get_brand_repo)],
    article_repo: Annotated[ArticleRepositoryProtocol, Depends(get_article_repo)],
    scan_log_repo: Annotated[ScanLogRepositoryProtocol, Depends(get_scan_log_repo)],
    media_repo: Annotated[MediaRepositoryProtocol, Depends(get_media_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
    fetcher: Annotated[SafeHttpFetcher, Depends(get_http_fetcher)],
    dispatcher: Annotated[ScanDispatcher, Depends(get_scan_dispatcher)],
) -> ScanExecutorService:
    return ScanExecutorService(
        settings=settings,
        website_repo=website_repo,
        brand_repo=brand_repo,
        article_repo=article_repo,
        scan_log_repo=scan_log_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        health_service=health_service,
        settings_service=settings_service,
        fetcher=fetcher,
        dispatcher=dispatcher,
    )


def get_article_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    article_repo: Annotated[ArticleRepositoryProtocol, Depends(get_article_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    brand_repo: Annotated[BrandRepositoryProtocol, Depends(get_brand_repo)],
    media_repo: Annotated[MediaRepositoryProtocol, Depends(get_media_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    fetcher: Annotated[SafeHttpFetcher, Depends(get_http_fetcher)],
) -> ArticleService:
    return ArticleService(
        settings=settings,
        article_repo=article_repo,
        website_repo=website_repo,
        brand_repo=brand_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        fetcher=fetcher,
    )


def get_media_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    media_repo: Annotated[MediaRepositoryProtocol, Depends(get_media_repo)],
) -> MediaService:
    return MediaService(settings=settings, media_repo=media_repo)


def extract_client_ip(request: Request) -> str | None:
    direct_host = request.client.host if request.client else None
    if direct_host in {"127.0.0.1", "::1"}:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first_hop = forwarded.split(",")[0].strip()
            if first_hop:
                return first_hop[:64]
    return direct_host[:64] if direct_host else None


def require_admin(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedSession:
    raw_token = request.cookies.get(settings.session_cookie_name)
    auth = auth_service.resolve_session(raw_token)
    if auth is None:
        raise AuthenticationError("Authentication required.", code="UNAUTHORIZED")
    return auth


def require_csrf(
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_admin)],
) -> AuthenticatedSession:
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        provided = request.headers.get("x-csrf-token", "")
        if not provided or not constant_time_equals(auth.session.csrf_token, provided):
            raise AuthorizationError("Invalid or missing CSRF token.", code="CSRF_INVALID")
    return auth
