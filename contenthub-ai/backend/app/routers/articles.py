from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.dependencies import (
    extract_client_ip,
    get_article_service,
    require_admin,
    require_csrf,
)
from app.schemas.article import (
    ArticleDetailResponse,
    ArticleListResponse,
    ArticleRevisionResponse,
    ArticleUpdateRequest,
)
from app.services.article_service import ArticleService
from app.services.auth_service import AuthenticatedSession

router = APIRouter(prefix="/articles", tags=["Content Library"])


@router.get("", response_model=ArticleListResponse)
def list_articles(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    article_service: Annotated[ArticleService, Depends(get_article_service)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    brand_id: int | None = Query(default=None, ge=1),
    website_id: int | None = Query(default=None, ge=1),
    language: str | None = Query(default=None, max_length=32),
    category: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None, max_length=32),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    search: str | None = Query(default=None, max_length=160),
    change_filter: str | None = Query(default=None, max_length=32),
) -> ArticleListResponse:
    return article_service.list_articles(
        page=page,
        page_size=page_size,
        brand_id=brand_id,
        website_id=website_id,
        language=language,
        category=category,
        status=status,
        date_from=date_from,
        date_to=date_to,
        search=search,
        change_filter=change_filter,
    )


@router.get("/{article_id}", response_model=ArticleDetailResponse)
def get_article(
    article_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    article_service: Annotated[ArticleService, Depends(get_article_service)],
) -> ArticleDetailResponse:
    return article_service.get_article(article_id)


@router.get("/{article_id}/revisions", response_model=list[ArticleRevisionResponse])
def list_article_revisions(
    article_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    article_service: Annotated[ArticleService, Depends(get_article_service)],
) -> list[ArticleRevisionResponse]:
    return article_service.list_revisions(article_id)


@router.post("/{article_id}/reprocess", response_model=ArticleDetailResponse)
def reprocess_article(
    article_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    article_service: Annotated[ArticleService, Depends(get_article_service)],
) -> ArticleDetailResponse:
    return article_service.reprocess_article(
        article_id,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.patch("/{article_id}", response_model=ArticleDetailResponse)
def update_article(
    article_id: int,
    payload: ArticleUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    article_service: Annotated[ArticleService, Depends(get_article_service)],
) -> ArticleDetailResponse:
    return article_service.update_article(
        article_id,
        payload,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
