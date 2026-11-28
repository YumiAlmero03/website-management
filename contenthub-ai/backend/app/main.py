from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.cli import run_daily_indexing
from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.database import reset_engine
from app.routers import (
    ai,
    auth,
    categories,
    content_approvals,
    contents,
    dashboard,
    health,
    indexing,
    logs,
    media,
    publishing,
    scans,
    social_posts,
    social_profiles,
    websites,
)
from app.routers import settings as settings_router

logger = get_logger("main")


async def _daily_indexing_scheduler_loop(cfg: Settings) -> None:
    """Trigger daily indexing at the configured local time (default 11:00 AM Asia/Manila)."""
    tz = ZoneInfo(cfg.app_timezone)
    last_triggered_date: str | None = None
    while True:
        try:
            now_local = datetime.now(tz)
            today_key = now_local.strftime("%Y-%m-%d")
            if (
                now_local.hour == cfg.indexing_daily_run_hour
                and now_local.minute == cfg.indexing_daily_run_minute
                and last_triggered_date != today_key
            ):
                last_triggered_date = today_key
                logger.info(
                    "Running scheduled daily indexing at %02d:%02d (%s)",
                    cfg.indexing_daily_run_hour,
                    cfg.indexing_daily_run_minute,
                    cfg.app_timezone,
                )
                await asyncio.to_thread(run_daily_indexing)
        except Exception as exc:  # pragma: no cover - defensive background loop guard
            logger.warning("Daily indexing scheduler check failed: %s", type(exc).__name__)
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    cfg = get_settings()
    configure_logging(debug=cfg.app_debug)
    logger.info("ContentHub AI backend starting (env=%s, version=%s)", cfg.app_env, cfg.app_version)
    if cfg.is_root_db_user:
        logger.warning("DB_USER is configured as 'root'; switch to a least-privilege MySQL user.")
    scheduler_task: asyncio.Task[None] | None = None
    if cfg.indexing_daily_schedule_enabled:
        scheduler_task = asyncio.create_task(_daily_indexing_scheduler_loop(cfg))
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scheduler_task
        reset_engine()
        logger.info("ContentHub AI backend shut down cleanly.")


def create_app(settings_override: Settings | None = None) -> FastAPI:
    cfg = settings_override or get_settings()
    app = FastAPI(
        title=cfg.app_name,
        version=cfg.app_version,
        docs_url="/api/docs" if cfg.app_debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if cfg.app_debug else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
            headers=exc.headers,
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("Database operation failed: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Database is currently unavailable. "
                    "Verify MySQL configuration and run Alembic migrations."
                ),
                "code": "DATABASE_UNAVAILABLE",
            },
        )

    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(dashboard.router, prefix=api_prefix)
    app.include_router(settings_router.router, prefix=api_prefix)
    app.include_router(logs.router, prefix=api_prefix)
    app.include_router(categories.router, prefix=api_prefix)
    app.include_router(websites.router, prefix=api_prefix)
    app.include_router(scans.router, prefix=api_prefix)
    app.include_router(contents.router, prefix=api_prefix)
    app.include_router(content_approvals.router, prefix=api_prefix)
    app.include_router(media.router, prefix=api_prefix)
    app.include_router(social_profiles.router, prefix=api_prefix)
    app.include_router(ai.router, prefix=api_prefix)
    app.include_router(social_posts.router, prefix=api_prefix)
    app.include_router(publishing.router, prefix=api_prefix)
    app.include_router(indexing.router, prefix=api_prefix)

    return app


app = create_app()
