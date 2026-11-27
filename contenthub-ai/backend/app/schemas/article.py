from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import PaginationMeta
from app.schemas.media import MediaAssetResponse


class ArticleRevisionResponse(BaseModel):
    id: int
    article_id: int
    revision_number: int
    title: str
    meta_description: str | None = None
    markdown_content: str | None = None
    content_hash: str
    created_at: datetime


class ArticleListItemResponse(BaseModel):
    id: int
    website_id: int
    website_name: str | None = None
    brand_id: int | None = None
    brand_name: str | None = None
    featured_media_id: int | None = None
    featured_image_url: str | None = None
    title: str
    canonical_url: str
    author: str | None = None
    meta_description: str | None = None
    language: str | None = None
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    word_count: int
    status: str
    is_historical_baseline: bool = False
    near_duplicate_of_id: int | None = None
    near_duplicate_score: float | None = None
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    discovered_at: datetime
    last_checked_at: datetime


class ArticleDetailResponse(ArticleListItemResponse):
    url_hash: str
    content_hash: str
    original_content: str | None = None
    markdown_content: str | None = None
    optimized_context: str | None = None
    featured_media: MediaAssetResponse | None = None
    revision_count: int = 0
    created_at: datetime
    updated_at: datetime


class ArticleListResponse(BaseModel):
    items: list[ArticleListItemResponse]
    meta: PaginationMeta


class ArticleUpdateRequest(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    categories: list[str] | None = None
    tags: list[str] | None = None
    language: str | None = Field(default=None, max_length=32)
