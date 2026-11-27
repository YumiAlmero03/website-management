from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import PaginationMeta

ALLOWED_WEBSITE_TYPES: tuple[str, ...] = (
    "wordpress",
    "nuxt",
    "nextjs",
    "custom_php",
    "static_html",
    "other_cms",
    "custom_rest_api",
)

ALLOWED_DISCOVERY_METHODS: tuple[str, ...] = (
    "auto",
    "rest_api",
    "wordpress",
    "rss",
    "sitemap",
    "llms_txt",
    "html",
    "playwright",
)

ALLOWED_BASELINE_MODES: tuple[str, ...] = (
    "import_existing",
    "after_date",
    "latest_n",
    "new_only",
)

ALLOWED_WEBSITE_STATUSES: tuple[str, ...] = (
    "active",
    "paused",
    "error",
    "archived",
)


class WebsiteCreateRequest(BaseModel):
    brand_id: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=150)
    domain: str = Field(min_length=3, max_length=255)
    website_type: str = Field(default="wordpress", max_length=32)
    discovery_method: str = Field(default="auto", max_length=32)
    rss_url: str | None = Field(default=None, max_length=500)
    sitemap_url: str | None = Field(default=None, max_length=500)
    llms_url: str | None = Field(default=None, max_length=500)
    api_endpoint: str | None = Field(default=None, max_length=500)
    article_url_patterns: list[str] = Field(default_factory=list)
    excluded_url_patterns: list[str] = Field(default_factory=list)
    scan_interval_minutes: int = Field(default=360, ge=15, le=43200)
    auto_scan: bool = True
    auto_generate: bool = False
    baseline_mode: str = Field(default="import_existing", max_length=32)
    baseline_after_date: datetime | None = None
    baseline_limit: int | None = Field(default=None, ge=1, le=500)
    status: str = Field(default="active", max_length=32)


class WebsiteUpdateRequest(BaseModel):
    brand_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=150)
    domain: str | None = Field(default=None, min_length=3, max_length=255)
    website_type: str | None = Field(default=None, max_length=32)
    discovery_method: str | None = Field(default=None, max_length=32)
    rss_url: str | None = Field(default=None, max_length=500)
    sitemap_url: str | None = Field(default=None, max_length=500)
    llms_url: str | None = Field(default=None, max_length=500)
    api_endpoint: str | None = Field(default=None, max_length=500)
    article_url_patterns: list[str] | None = None
    excluded_url_patterns: list[str] | None = None
    scan_interval_minutes: int | None = Field(default=None, ge=15, le=43200)
    auto_scan: bool | None = None
    auto_generate: bool | None = None
    baseline_mode: str | None = Field(default=None, max_length=32)
    baseline_after_date: datetime | None = None
    baseline_limit: int | None = Field(default=None, ge=1, le=500)
    status: str | None = Field(default=None, max_length=32)


class WebsiteResponse(BaseModel):
    id: int
    brand_id: int
    brand_name: str | None = None
    name: str
    domain: str
    website_type: str
    discovery_method: str
    rss_url: str | None = None
    sitemap_url: str | None = None
    llms_url: str | None = None
    api_endpoint: str | None = None
    article_url_patterns: list[str] = Field(default_factory=list)
    excluded_url_patterns: list[str] = Field(default_factory=list)
    scan_interval_minutes: int
    auto_scan: bool
    auto_generate: bool
    initial_scan_completed: bool
    baseline_mode: str
    baseline_after_date: datetime | None = None
    baseline_limit: int | None = None
    last_scanned_at: datetime | None = None
    last_successful_scan_at: datetime | None = None
    next_scan_at: datetime | None = None
    status: str
    article_count: int = 0
    created_at: datetime
    updated_at: datetime


class WebsiteListResponse(BaseModel):
    items: list[WebsiteResponse]
    meta: PaginationMeta


class WebsiteConnectivityResponse(BaseModel):
    reachable: bool
    status_code: int | None = None
    final_url: str | None = None
    title: str | None = None
    detected_website_type: str | None = None
    error: str | None = None


class WebsiteDiscoverResponse(BaseModel):
    reachable: bool
    homepage_url: str
    rss_urls: list[str] = Field(default_factory=list)
    sitemap_urls: list[str] = Field(default_factory=list)
    llms_urls: list[str] = Field(default_factory=list)
    wordpress_api_url: str | None = None
    recommended_method: str
    notes: list[str] = Field(default_factory=list)


class ScanLogResponse(BaseModel):
    id: int
    website_id: int
    website_name: str | None = None
    scan_method: str
    trigger_type: str
    urls_found: int
    articles_processed: int
    new_articles: int
    updated_articles: int
    unchanged_articles: int
    skipped_articles: int
    failed_articles: int
    status: str
    error_message: str | None = None
    duration_ms: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ScanLogListResponse(BaseModel):
    items: list[ScanLogResponse]
    meta: PaginationMeta
