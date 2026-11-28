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
from app.repositories.ai_repo import AiRepositoryProtocol, SQLAlchemyAiRepository
from app.repositories.category_repo import (
    SQLAlchemyWebsiteCategoryRepository,
    WebsiteCategoryRepositoryProtocol,
)
from app.repositories.content_repo import (
    ContentRepositoryProtocol,
    SQLAlchemyContentRepository,
)
from app.repositories.keyword_approval_repo import (
    KeywordApprovalRepositoryProtocol,
    SQLAlchemyKeywordApprovalRepository,
)
from app.repositories.media_repo import MediaRepositoryProtocol, SQLAlchemyMediaRepository
from app.repositories.scan_log_repo import ScanLogRepositoryProtocol, SQLAlchemyScanLogRepository
from app.repositories.session_repo import SessionRepositoryProtocol, SQLAlchemySessionRepository
from app.repositories.settings_repo import SettingsRepositoryProtocol, SQLAlchemySettingsRepository
from app.repositories.social_post_repo import (
    SocialPostRepositoryProtocol,
    SQLAlchemySocialPostRepository,
)
from app.repositories.social_profile_repo import (
    SocialProfileRepositoryProtocol,
    SQLAlchemySocialProfileRepository,
)
from app.repositories.user_repo import SQLAlchemyUserRepository, UserRepositoryProtocol
from app.repositories.website_repo import SQLAlchemyWebsiteRepository, WebsiteRepositoryProtocol
from app.repositories.website_source_repo import (
    SQLAlchemyWebsiteSourceConfigRepository,
    WebsiteSourceConfigRepositoryProtocol,
)
from app.services.ai.gemini import GeminiSdkProvider
from app.services.ai.generation_service import (
    AiGenerationService,
    AiJobDispatcher,
    default_ai_job_dispatcher,
)
from app.services.ai.knowledge_service import KnowledgeProfileService
from app.services.ai.management_service import AiManagementService
from app.services.ai.prompt_service import PromptManagerService
from app.services.ai.provider import AiProviderClientProtocol
from app.services.auth_service import AuthenticatedSession, AuthService
from app.services.category_service import WebsiteCategoryService
from app.services.content_approval_service import ContentApprovalService
from app.services.content_service import ContentService
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
from app.services.social_post_service import SocialPostService
from app.services.social_profile_service import SocialProfileService
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


def get_category_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> WebsiteCategoryRepositoryProtocol:
    return SQLAlchemyWebsiteCategoryRepository(db)


def get_website_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> WebsiteRepositoryProtocol:
    return SQLAlchemyWebsiteRepository(db)


def get_website_source_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> WebsiteSourceConfigRepositoryProtocol:
    return SQLAlchemyWebsiteSourceConfigRepository(db)


def get_content_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> ContentRepositoryProtocol:
    return SQLAlchemyContentRepository(db)


def get_scan_log_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> ScanLogRepositoryProtocol:
    return SQLAlchemyScanLogRepository(db)


def get_media_repo(db: Annotated[Session, Depends(get_db_session)]) -> MediaRepositoryProtocol:
    return SQLAlchemyMediaRepository(db)


def get_ai_repo(db: Annotated[Session, Depends(get_db_session)]) -> AiRepositoryProtocol:
    return SQLAlchemyAiRepository(db)


def get_social_profile_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> SocialProfileRepositoryProtocol:
    return SQLAlchemySocialProfileRepository(db)


def get_social_post_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> SocialPostRepositoryProtocol:
    return SQLAlchemySocialPostRepository(db)


def get_keyword_approval_repo(
    db: Annotated[Session, Depends(get_db_session)],
) -> KeywordApprovalRepositoryProtocol:
    return SQLAlchemyKeywordApprovalRepository(db)


def get_ai_provider_client() -> AiProviderClientProtocol:
    return GeminiSdkProvider()


def get_ai_job_dispatcher() -> AiJobDispatcher:
    return default_ai_job_dispatcher


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


def get_category_service(
    category_repo: Annotated[WebsiteCategoryRepositoryProtocol, Depends(get_category_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
) -> WebsiteCategoryService:
    return WebsiteCategoryService(
        category_repo=category_repo,
        website_repo=website_repo,
        activity_repo=activity_repo,
    )


def get_dashboard_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
    session_repo: Annotated[SessionRepositoryProtocol, Depends(get_session_repo)],
    settings_repo: Annotated[SettingsRepositoryProtocol, Depends(get_settings_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    category_repo: Annotated[WebsiteCategoryRepositoryProtocol, Depends(get_category_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    content_repo: Annotated[ContentRepositoryProtocol, Depends(get_content_repo)],
    scan_log_repo: Annotated[ScanLogRepositoryProtocol, Depends(get_scan_log_repo)],
    keyword_approval_repo: Annotated[
        KeywordApprovalRepositoryProtocol, Depends(get_keyword_approval_repo)
    ],
) -> DashboardService:
    return DashboardService(
        settings=settings,
        health_service=health_service,
        settings_service=settings_service,
        session_repo=session_repo,
        settings_repo=settings_repo,
        activity_repo=activity_repo,
        category_repo=category_repo,
        website_repo=website_repo,
        content_repo=content_repo,
        scan_log_repo=scan_log_repo,
        keyword_approval_repo=keyword_approval_repo,
    )


def get_website_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    category_repo: Annotated[WebsiteCategoryRepositoryProtocol, Depends(get_category_repo)],
    source_config_repo: Annotated[
        WebsiteSourceConfigRepositoryProtocol, Depends(get_website_source_repo)
    ],
    content_repo: Annotated[ContentRepositoryProtocol, Depends(get_content_repo)],
    media_repo: Annotated[MediaRepositoryProtocol, Depends(get_media_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    fetcher: Annotated[SafeHttpFetcher, Depends(get_http_fetcher)],
) -> WebsiteService:
    return WebsiteService(
        settings=settings,
        website_repo=website_repo,
        category_repo=category_repo,
        source_config_repo=source_config_repo,
        content_repo=content_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        fetcher=fetcher,
    )


def get_social_profile_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    social_profile_repo: Annotated[
        SocialProfileRepositoryProtocol, Depends(get_social_profile_repo)
    ],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
) -> SocialProfileService:
    return SocialProfileService(
        settings=settings,
        social_profile_repo=social_profile_repo,
        website_repo=website_repo,
        activity_repo=activity_repo,
    )


def get_ai_management_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    ai_repo: Annotated[AiRepositoryProtocol, Depends(get_ai_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    provider_client: Annotated[AiProviderClientProtocol, Depends(get_ai_provider_client)],
) -> AiManagementService:
    return AiManagementService(
        settings=settings,
        ai_repo=ai_repo,
        website_repo=website_repo,
        activity_repo=activity_repo,
        provider_client=provider_client,
    )


def get_knowledge_profile_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    ai_repo: Annotated[AiRepositoryProtocol, Depends(get_ai_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    category_repo: Annotated[WebsiteCategoryRepositoryProtocol, Depends(get_category_repo)],
    content_repo: Annotated[ContentRepositoryProtocol, Depends(get_content_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    provider_client: Annotated[AiProviderClientProtocol, Depends(get_ai_provider_client)],
) -> KnowledgeProfileService:
    return KnowledgeProfileService(
        settings=settings,
        ai_repo=ai_repo,
        website_repo=website_repo,
        category_repo=category_repo,
        content_repo=content_repo,
        activity_repo=activity_repo,
        provider_client=provider_client,
    )


def get_prompt_manager_service(
    ai_repo: Annotated[AiRepositoryProtocol, Depends(get_ai_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    category_repo: Annotated[WebsiteCategoryRepositoryProtocol, Depends(get_category_repo)],
    social_profile_repo: Annotated[
        SocialProfileRepositoryProtocol, Depends(get_social_profile_repo)
    ],
    content_repo: Annotated[ContentRepositoryProtocol, Depends(get_content_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    keyword_approval_repo: Annotated[
        KeywordApprovalRepositoryProtocol, Depends(get_keyword_approval_repo)
    ],
) -> PromptManagerService:
    return PromptManagerService(
        ai_repo=ai_repo,
        website_repo=website_repo,
        category_repo=category_repo,
        social_profile_repo=social_profile_repo,
        content_repo=content_repo,
        activity_repo=activity_repo,
        keyword_approval_repo=keyword_approval_repo,
    )


def get_ai_generation_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    ai_repo: Annotated[AiRepositoryProtocol, Depends(get_ai_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    category_repo: Annotated[WebsiteCategoryRepositoryProtocol, Depends(get_category_repo)],
    content_repo: Annotated[ContentRepositoryProtocol, Depends(get_content_repo)],
    social_profile_repo: Annotated[
        SocialProfileRepositoryProtocol, Depends(get_social_profile_repo)
    ],
    social_post_repo: Annotated[SocialPostRepositoryProtocol, Depends(get_social_post_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
    provider_client: Annotated[AiProviderClientProtocol, Depends(get_ai_provider_client)],
    dispatcher: Annotated[AiJobDispatcher, Depends(get_ai_job_dispatcher)],
    keyword_approval_repo: Annotated[
        KeywordApprovalRepositoryProtocol, Depends(get_keyword_approval_repo)
    ],
) -> AiGenerationService:
    return AiGenerationService(
        settings=settings,
        ai_repo=ai_repo,
        website_repo=website_repo,
        category_repo=category_repo,
        content_repo=content_repo,
        social_profile_repo=social_profile_repo,
        social_post_repo=social_post_repo,
        activity_repo=activity_repo,
        health_service=health_service,
        settings_service=settings_service,
        provider_client=provider_client,
        dispatcher=dispatcher,
        keyword_approval_repo=keyword_approval_repo,
    )


def get_content_approval_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    keyword_approval_repo: Annotated[
        KeywordApprovalRepositoryProtocol, Depends(get_keyword_approval_repo)
    ],
    content_repo: Annotated[ContentRepositoryProtocol, Depends(get_content_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    media_repo: Annotated[MediaRepositoryProtocol, Depends(get_media_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    ai_repo: Annotated[AiRepositoryProtocol, Depends(get_ai_repo)],
    provider_client: Annotated[AiProviderClientProtocol, Depends(get_ai_provider_client)],
    ai_generation_service: Annotated[AiGenerationService, Depends(get_ai_generation_service)],
) -> ContentApprovalService:
    return ContentApprovalService(
        settings=settings,
        keyword_approval_repo=keyword_approval_repo,
        content_repo=content_repo,
        website_repo=website_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        ai_repo=ai_repo,
        provider_client=provider_client,
        ai_generation_service=ai_generation_service,
    )


def get_social_post_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    social_post_repo: Annotated[SocialPostRepositoryProtocol, Depends(get_social_post_repo)],
    social_profile_repo: Annotated[
        SocialProfileRepositoryProtocol, Depends(get_social_profile_repo)
    ],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    content_repo: Annotated[ContentRepositoryProtocol, Depends(get_content_repo)],
    media_repo: Annotated[MediaRepositoryProtocol, Depends(get_media_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
) -> SocialPostService:
    return SocialPostService(
        settings=settings,
        social_post_repo=social_post_repo,
        social_profile_repo=social_profile_repo,
        website_repo=website_repo,
        content_repo=content_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
    )


def get_scan_executor_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    source_config_repo: Annotated[
        WebsiteSourceConfigRepositoryProtocol, Depends(get_website_source_repo)
    ],
    content_repo: Annotated[ContentRepositoryProtocol, Depends(get_content_repo)],
    scan_log_repo: Annotated[ScanLogRepositoryProtocol, Depends(get_scan_log_repo)],
    media_repo: Annotated[MediaRepositoryProtocol, Depends(get_media_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
    fetcher: Annotated[SafeHttpFetcher, Depends(get_http_fetcher)],
    dispatcher: Annotated[ScanDispatcher, Depends(get_scan_dispatcher)],
    ai_generation_service: Annotated[AiGenerationService, Depends(get_ai_generation_service)],
    approval_service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
) -> ScanExecutorService:
    return ScanExecutorService(
        settings=settings,
        website_repo=website_repo,
        source_config_repo=source_config_repo,
        content_repo=content_repo,
        scan_log_repo=scan_log_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        health_service=health_service,
        settings_service=settings_service,
        fetcher=fetcher,
        dispatcher=dispatcher,
        ai_generation_service=ai_generation_service,
        approval_service=approval_service,
    )


def get_content_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    content_repo: Annotated[ContentRepositoryProtocol, Depends(get_content_repo)],
    website_repo: Annotated[WebsiteRepositoryProtocol, Depends(get_website_repo)],
    category_repo: Annotated[WebsiteCategoryRepositoryProtocol, Depends(get_category_repo)],
    source_config_repo: Annotated[
        WebsiteSourceConfigRepositoryProtocol, Depends(get_website_source_repo)
    ],
    media_repo: Annotated[MediaRepositoryProtocol, Depends(get_media_repo)],
    activity_repo: Annotated[ActivityLogRepositoryProtocol, Depends(get_activity_log_repo)],
    fetcher: Annotated[SafeHttpFetcher, Depends(get_http_fetcher)],
    keyword_approval_repo: Annotated[
        KeywordApprovalRepositoryProtocol, Depends(get_keyword_approval_repo)
    ],
    approval_service: Annotated[ContentApprovalService, Depends(get_content_approval_service)],
) -> ContentService:
    return ContentService(
        settings=settings,
        content_repo=content_repo,
        website_repo=website_repo,
        category_repo=category_repo,
        source_config_repo=source_config_repo,
        media_repo=media_repo,
        activity_repo=activity_repo,
        fetcher=fetcher,
        keyword_approval_repo=keyword_approval_repo,
        approval_service=approval_service,
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
