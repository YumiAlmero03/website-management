from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.database import reset_engine
from app.routers import (
    articles,
    auth,
    brands,
    dashboard,
    health,
    logs,
    media,
    scans,
    websites,
)
from app.routers import settings as settings_router

logger = get_logger("main")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    cfg = get_settings()
    configure_logging(debug=cfg.app_debug)
    logger.info("ContentHub AI backend starting (env=%s, version=%s)", cfg.app_env, cfg.app_version)
    if cfg.is_root_db_user:
        logger.warning("DB_USER is configured as 'root'; switch to a least-privilege MySQL user.")
    yield
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
    app.include_router(brands.router, prefix=api_prefix)
    app.include_router(websites.router, prefix=api_prefix)
    app.include_router(scans.router, prefix=api_prefix)
    app.include_router(articles.router, prefix=api_prefix)
    app.include_router(media.router, prefix=api_prefix)

    return app


app = create_app()
