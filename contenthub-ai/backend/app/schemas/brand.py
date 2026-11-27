from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import PaginationMeta


class BrandCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    slug: str | None = Field(default=None, max_length=150)
    logo_url: str | None = Field(default=None, max_length=500)
    description: str | None = None
    target_audience: str | None = Field(default=None, max_length=255)
    target_country: str | None = Field(default=None, max_length=64)
    primary_language: str = Field(default="en", min_length=2, max_length=32)
    secondary_languages: list[str] = Field(default_factory=list)
    tone: str | None = Field(default=None, max_length=120)
    target_keywords: list[str] = Field(default_factory=list)
    restricted_keywords: list[str] = Field(default_factory=list)
    default_hashtags: list[str] = Field(default_factory=list)
    default_cta: str | None = Field(default=None, max_length=255)
    writing_guidelines: str | None = None
    ai_instructions: str | None = None
    is_active: bool = True


class BrandUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    slug: str | None = Field(default=None, max_length=150)
    logo_url: str | None = Field(default=None, max_length=500)
    description: str | None = None
    target_audience: str | None = Field(default=None, max_length=255)
    target_country: str | None = Field(default=None, max_length=64)
    primary_language: str | None = Field(default=None, min_length=2, max_length=32)
    secondary_languages: list[str] | None = None
    tone: str | None = Field(default=None, max_length=120)
    target_keywords: list[str] | None = None
    restricted_keywords: list[str] | None = None
    default_hashtags: list[str] | None = None
    default_cta: str | None = Field(default=None, max_length=255)
    writing_guidelines: str | None = None
    ai_instructions: str | None = None
    is_active: bool | None = None


class BrandWebsiteSummary(BaseModel):
    id: int
    name: str
    domain: str
    website_type: str
    status: str
    last_successful_scan_at: datetime | None = None


class BrandResponse(BaseModel):
    id: int
    name: str
    slug: str
    logo_url: str | None = None
    description: str | None = None
    target_audience: str | None = None
    target_country: str | None = None
    primary_language: str
    secondary_languages: list[str] = Field(default_factory=list)
    tone: str | None = None
    target_keywords: list[str] = Field(default_factory=list)
    restricted_keywords: list[str] = Field(default_factory=list)
    default_hashtags: list[str] = Field(default_factory=list)
    default_cta: str | None = None
    writing_guidelines: str | None = None
    ai_instructions: str | None = None
    is_active: bool
    website_count: int = 0
    created_at: datetime
    updated_at: datetime


class BrandDetailResponse(BrandResponse):
    websites: list[BrandWebsiteSummary] = Field(default_factory=list)


class BrandListResponse(BaseModel):
    items: list[BrandResponse]
    meta: PaginationMeta
