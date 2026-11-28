from __future__ import annotations

from datetime import datetime
from typing import Any

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

ALLOWED_SCAN_MODES: tuple[str, ...] = (
    "full",
    "incremental",
    "resume",
    "retry_failed",
    "discover_only",
)


class WebsiteCreateRequest(BaseModel):
    # Essential quick-registration fields
    name: str = Field(min_length=2, max_length=150)
    brand_name: str | None = Field(default=None, max_length=150)
    domain: str = Field(min_length=3, max_length=255)  # Accepts full URL or bare domain
    category_id: int | None = Field(default=None, ge=1)
    primary_language: str = Field(default="en", min_length=2, max_length=32)

    # Optional merged brand / editorial / SEO fields (under Advanced Settings)
    logo_url: str | None = Field(default=None, max_length=500)
    brand_description: str | None = Field(default=None, max_length=5000)
    target_audience: str | None = Field(default=None, max_length=255)
    target_country: str | None = Field(default=None, max_length=64)
    secondary_languages: list[str] = Field(default_factory=list)
    tone: str | None = Field(default=None, max_length=120)
    target_keywords: list[str] = Field(default_factory=list)
    keyword_bank: list[str] = Field(default_factory=list)
    restricted_keywords: list[str] = Field(default_factory=list)
    default_hashtags: list[str] = Field(default_factory=list)
    default_cta: str | None = Field(default=None, max_length=255)
    writing_guidelines: str | None = Field(default=None, max_length=8000)
    ai_instructions: str | None = Field(default=None, max_length=8000)

    # Optional technology, discovery & crawl configuration (auto-detected defaults)
    website_type: str = Field(default="wordpress", max_length=32)
    discovery_method: str = Field(default="auto", max_length=32)
    single_source_only: bool = False
    rss_url: str | None = Field(default=None, max_length=500)
    sitemap_url: str | None = Field(default=None, max_length=500)
    llms_url: str | None = Field(default=None, max_length=500)
    api_endpoint: str | None = Field(default=None, max_length=500)
    article_url_patterns: list[str] = Field(default_factory=list)
    excluded_url_patterns: list[str] = Field(default_factory=list)
    scan_interval_minutes: int = Field(default=1440, ge=15, le=43200)
    crawl_batch_size: int = Field(default=100, ge=1, le=1000)
    crawl_max_urls_per_run: int = Field(default=1000, ge=1, le=20000)
    auto_scan: bool = True
    auto_generate: bool = False
    auto_generate_require_published_at: bool = True
    auto_generate_context_mode: str = Field(default="optimized", max_length=32)
    baseline_mode: str = Field(default="import_existing", max_length=32)
    baseline_after_date: datetime | None = None
    baseline_limit: int | None = Field(default=None, ge=1, le=5000)
    status: str = Field(default="active", max_length=32)


class WebsiteUpdateRequest(BaseModel):
    category_id: int | None = Field(default=None, ge=1)
    clear_category: bool = False
    name: str | None = Field(default=None, min_length=2, max_length=150)
    brand_name: str | None = Field(default=None, max_length=150)
    domain: str | None = Field(default=None, min_length=3, max_length=255)
    logo_url: str | None = Field(default=None, max_length=500)
    brand_description: str | None = Field(default=None, max_length=5000)
    target_audience: str | None = Field(default=None, max_length=255)
    target_country: str | None = Field(default=None, max_length=64)
    primary_language: str | None = Field(default=None, min_length=2, max_length=32)
    secondary_languages: list[str] | None = None
    tone: str | None = Field(default=None, max_length=120)
    target_keywords: list[str] | None = None
    keyword_bank: list[str] | None = None
    restricted_keywords: list[str] | None = None
    default_hashtags: list[str] | None = None
    default_cta: str | None = Field(default=None, max_length=255)
    writing_guidelines: str | None = Field(default=None, max_length=8000)
    ai_instructions: str | None = Field(default=None, max_length=8000)
    website_type: str | None = Field(default=None, max_length=32)
    discovery_method: str | None = Field(default=None, max_length=32)
    single_source_only: bool | None = None
    rss_url: str | None = Field(default=None, max_length=500)
    sitemap_url: str | None = Field(default=None, max_length=500)
    llms_url: str | None = Field(default=None, max_length=500)
    api_endpoint: str | None = Field(default=None, max_length=500)
    article_url_patterns: list[str] | None = None
    excluded_url_patterns: list[str] | None = None
    scan_interval_minutes: int | None = Field(default=None, ge=15, le=43200)
    crawl_batch_size: int | None = Field(default=None, ge=1, le=1000)
    crawl_max_urls_per_run: int | None = Field(default=None, ge=1, le=20000)
    auto_scan: bool | None = None
    auto_generate: bool | None = None
    auto_generate_require_published_at: bool | None = None
    auto_generate_context_mode: str | None = Field(default=None, max_length=32)
    baseline_mode: str | None = Field(default=None, max_length=32)
    baseline_after_date: datetime | None = None
    baseline_limit: int | None = Field(default=None, ge=1, le=5000)
    status: str | None = Field(default=None, max_length=32)


class ContentBreakdownCounts(BaseModel):
    total_discovered: int = 0
    total_extracted: int = 0
    homepage: int = 0
    page: int = 0
    game_page: int = 0
    blog_index: int = 0
    blog_post: int = 0
    category: int = 0
    tag: int = 0
    archive: int = 0
    custom: int = 0
    pending: int = 0
    failed: int = 0
    updated: int = 0
    excluded: int = 0


class WebsiteResponse(BaseModel):
    id: int
    category_id: int | None = None
    category_name: str | None = None
    name: str
    brand_name: str
    brand_slug: str | None = None
    logo_url: str | None = None
    brand_description: str | None = None
    target_audience: str | None = None
    target_country: str | None = None
    primary_language: str
    secondary_languages: list[str] = Field(default_factory=list)
    tone: str | None = None
    target_keywords: list[str] = Field(default_factory=list)
    keyword_bank: list[str] = Field(default_factory=list)
    restricted_keywords: list[str] = Field(default_factory=list)
    default_hashtags: list[str] = Field(default_factory=list)
    default_cta: str | None = None
    writing_guidelines: str | None = None
    ai_instructions: str | None = None
    domain: str
    website_type: str
    discovery_method: str
    single_source_only: bool = False
    rss_url: str | None = None
    sitemap_url: str | None = None
    llms_url: str | None = None
    api_endpoint: str | None = None
    article_url_patterns: list[str] = Field(default_factory=list)
    excluded_url_patterns: list[str] = Field(default_factory=list)
    scan_interval_minutes: int
    crawl_batch_size: int = 100
    crawl_max_urls_per_run: int = 1000
    auto_scan: bool
    auto_generate: bool
    auto_generate_require_published_at: bool = True
    auto_generate_context_mode: str = "optimized"
    initial_scan_completed: bool
    baseline_mode: str
    baseline_after_date: datetime | None = None
    baseline_limit: int | None = None
    last_scanned_at: datetime | None = None
    last_successful_scan_at: datetime | None = None
    next_scan_at: datetime | None = None
    status: str
    article_count: int = 0
    content_counts: ContentBreakdownCounts = Field(default_factory=ContentBreakdownCounts)
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
    detected_website_type: str | None = None
    rss_urls: list[str] = Field(default_factory=list)
    sitemap_urls: list[str] = Field(default_factory=list)
    llms_urls: list[str] = Field(default_factory=list)
    wordpress_api_url: str | None = None
    recommended_method: str
    notes: list[str] = Field(default_factory=list)


class WebsiteDiscoverySourceResponse(BaseModel):
    id: int
    website_id: int
    parent_source_id: int | None = None
    source_type: str
    endpoint_url: str
    is_enabled: bool
    etag: str | None = None
    last_modified_header: str | None = None
    last_status_code: int | None = None
    last_urls_found: int = 0
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class WebsiteDiscoverySourceUpdateRequest(BaseModel):
    is_enabled: bool


class WebsiteUrlRuleCreateRequest(BaseModel):
    pattern: str = Field(min_length=1, max_length=255)
    target_content_type: str = Field(min_length=2, max_length=32)
    match_mode: str = Field(default="glob", max_length=24)
    priority: int = Field(default=100, ge=1, le=1000)
    is_enabled: bool = True
    notes: str | None = Field(default=None, max_length=255)


class WebsiteUrlRuleUpdateRequest(BaseModel):
    pattern: str | None = Field(default=None, min_length=1, max_length=255)
    target_content_type: str | None = Field(default=None, min_length=2, max_length=32)
    match_mode: str | None = Field(default=None, max_length=24)
    priority: int | None = Field(default=None, ge=1, le=1000)
    is_enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=255)


class WebsiteUrlRuleResponse(BaseModel):
    id: int
    website_id: int
    pattern: str
    target_content_type: str
    match_mode: str
    priority: int
    is_enabled: bool
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class ScanTriggerRequest(BaseModel):
    scan_mode: str = Field(
        default="full", max_length=32
    )  # full | incremental | resume | retry_failed
    max_urls: int | None = Field(default=None, ge=1, le=20000)
    batch_size: int | None = Field(default=None, ge=1, le=1000)


class ScanItemResponse(BaseModel):
    id: int
    scan_log_id: int
    website_id: int
    content_id: int | None = None
    url: str
    normalized_url: str
    content_type: str
    discovery_sources: list[str] = Field(default_factory=list)
    discovered_title: str | None = None
    status: str
    http_status: int | None = None
    failure_reason: str | None = None
    error_detail: str | None = None
    processed_at: datetime | None = None
    created_at: datetime


class ScanItemListResponse(BaseModel):
    items: list[ScanItemResponse]
    meta: PaginationMeta


class ScanLogResponse(BaseModel):
    id: int
    website_id: int
    website_name: str | None = None
    scan_method: str
    scan_mode: str = "full"
    trigger_type: str
    urls_found: int
    articles_processed: int
    urls_pending_extraction: int = 0
    new_articles: int
    updated_articles: int
    unchanged_articles: int
    skipped_articles: int
    failed_articles: int
    excluded_count: int = 0
    homepage_count: int = 0
    page_count: int = 0
    blog_post_count: int = 0
    other_count: int = 0
    current_source: str | None = None
    current_url: str | None = None
    discovered_sitemaps: list[str] = Field(default_factory=list)
    sources_completed: list[dict[str, Any]] = Field(default_factory=list)
    sources_failed: list[dict[str, Any]] = Field(default_factory=list)
    status: str
    error_message: str | None = None
    duration_ms: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ScanLogListResponse(BaseModel):
    items: list[ScanLogResponse]
    meta: PaginationMeta
