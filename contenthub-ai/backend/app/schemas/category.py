from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WebsiteCategoryCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=255)
    sort_order: int = Field(default=100, ge=0, le=9999)


class WebsiteCategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    slug: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=255)
    is_archived: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=9999)


class WebsiteCategoryResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    is_archived: bool
    sort_order: int
    website_count: int = 0
    created_at: datetime
    updated_at: datetime


class WebsiteCategoryListResponse(BaseModel):
    items: list[WebsiteCategoryResponse]
