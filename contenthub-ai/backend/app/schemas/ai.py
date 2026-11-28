from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import PaginationMeta


# ==============================================================================
# Gemini Provider Configuration & Connectivity
# ==============================================================================
class AiProviderModelInfo(BaseModel):
    name: str
    display_name: str
    description: str | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    supported_actions: list[str] = Field(default_factory=list)
    is_flash_recommended: bool = False


class AiProviderCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    provider_type: str = Field(default="gemini", pattern="^(gemini|localai)$")
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=8, max_length=512)
    selected_model: str = Field(default="gemini-3.5-flash-lite", min_length=3, max_length=120)
    default_temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=1500, ge=64, le=8192)
    request_timeout_seconds: int = Field(default=45, ge=5, le=300)
    max_retry_attempts: int = Field(default=2, ge=0, le=5)
    daily_request_limit: int = Field(default=100, ge=1, le=50000)
    daily_token_limit: int = Field(default=250000, ge=1000, le=50_000_000)
    per_minute_request_limit: int = Field(default=10, ge=1, le=1000)
    generation_enabled: bool = True
    response_caching_enabled: bool = True
    token_optimization_enabled: bool = True
    allow_paid_fallback: bool = False
    is_default: bool = True
    is_active: bool = True


class AiProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    provider_type: str | None = Field(default=None, pattern="^(gemini|localai)$")
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    clear_api_key: bool = False
    selected_model: str | None = Field(default=None, min_length=3, max_length=120)
    default_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=64, le=8192)
    request_timeout_seconds: int | None = Field(default=None, ge=5, le=300)
    max_retry_attempts: int | None = Field(default=None, ge=0, le=5)
    daily_request_limit: int | None = Field(default=None, ge=1, le=50000)
    daily_token_limit: int | None = Field(default=None, ge=1000, le=50_000_000)
    per_minute_request_limit: int | None = Field(default=None, ge=1, le=1000)
    generation_enabled: bool | None = None
    response_caching_enabled: bool | None = None
    token_optimization_enabled: bool | None = None
    allow_paid_fallback: bool | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class AiProviderResponse(BaseModel):
    id: int
    name: str
    provider_type: str = "gemini"
    base_url: str | None = None
    has_api_key: bool = False
    masked_api_key: str | None = None
    selected_model: str
    available_models: list[AiProviderModelInfo] = Field(default_factory=list)
    default_temperature: float
    max_output_tokens: int
    request_timeout_seconds: int
    max_retry_attempts: int
    daily_request_limit: int
    daily_token_limit: int
    per_minute_request_limit: int
    generation_enabled: bool
    response_caching_enabled: bool
    token_optimization_enabled: bool
    allow_paid_fallback: bool = False
    is_default: bool
    is_active: bool
    last_test_status: str
    last_test_latency_ms: int | None = None
    last_test_error: str | None = None
    last_verified_at: datetime | None = None
    billing_disclaimer: str = (
        "Application quotas help limit spend locally; actual free-tier eligibility "
        "and billing depend on your Google Cloud / Gemini API project."
    )
    created_at: datetime
    updated_at: datetime


class AiProviderTestRequest(BaseModel):
    verify_generation: bool = False


class AiProviderTestResponse(BaseModel):
    connected: bool
    provider_id: int
    selected_model: str
    model_available: bool = False
    latency_ms: int | None = None
    discovered_model_count: int = 0
    error_detail: str | None = None
    last_verified_at: datetime | None = None
    generation_probe_tokens: int | None = None


class AiProviderModelsResponse(BaseModel):
    provider_id: int
    selected_model: str
    models: list[AiProviderModelInfo] = Field(default_factory=list)
    fetched_live: bool = False


# ==============================================================================
# Website Knowledge Profiles
# ==============================================================================
class KnowledgeInternalLink(BaseModel):
    title: str
    url: str
    content_type: str = "page"


class KnowledgeSourceRef(BaseModel):
    content_id: int
    title: str
    url: str
    content_type: str
    content_hash: str


class KnowledgeProfileUpdateRequest(BaseModel):
    brand_name: str | None = Field(default=None, min_length=1, max_length=150)
    brand_description: str | None = Field(default=None, max_length=5000)
    website_category: str | None = Field(default=None, max_length=100)
    business_overview: str | None = Field(default=None, max_length=8000)
    products_and_services: list[str] | None = None
    main_features: list[str] | None = None
    target_audience: str | None = Field(default=None, max_length=255)
    target_country: str | None = Field(default=None, max_length=64)
    primary_language: str | None = Field(default=None, max_length=32)
    secondary_languages: list[str] | None = None
    recommended_writing_tone: str | None = Field(default=None, max_length=120)
    main_keywords: list[str] | None = None
    content_pillars: list[str] | None = None
    important_internal_links: list[KnowledgeInternalLink] | None = None
    relevant_publishing_restrictions: str | None = Field(default=None, max_length=5000)
    administrator_notes: str | None = Field(default=None, max_length=5000)
    approve: bool = False


class KnowledgeProfileGenerateRequest(BaseModel):
    provider_id: int | None = Field(default=None, ge=1)
    force_refresh: bool = False
    preserve_manual_overrides: bool = True


class KnowledgeProfileResponse(BaseModel):
    id: int | None = None
    website_id: int
    website_name: str | None = None
    brand_name: str
    brand_description: str | None = None
    website_category: str | None = None
    business_overview: str | None = None
    products_and_services: list[str] = Field(default_factory=list)
    main_features: list[str] = Field(default_factory=list)
    target_audience: str | None = None
    target_country: str | None = None
    primary_language: str = "en"
    secondary_languages: list[str] = Field(default_factory=list)
    recommended_writing_tone: str | None = None
    main_keywords: list[str] = Field(default_factory=list)
    content_pillars: list[str] = Field(default_factory=list)
    important_internal_links: list[KnowledgeInternalLink] = Field(default_factory=list)
    relevant_publishing_restrictions: str | None = None
    source_content_references: list[KnowledgeSourceRef] = Field(default_factory=list)
    administrator_notes: str | None = None
    manual_overrides: dict[str, Any] = Field(default_factory=dict)
    field_provenance: dict[str, str] = Field(default_factory=dict)
    content_fingerprint: str = ""
    is_outdated: bool = False
    profile_version: int = 0
    last_generated_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    approved_by: int | None = None
    status: str = "not_generated"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KnowledgeProfileRevisionResponse(BaseModel):
    id: int
    knowledge_profile_id: int
    website_id: int
    profile_version: int
    snapshot_json: dict[str, Any]
    content_fingerprint: str
    change_source: str
    created_by: int | None = None
    created_at: datetime


# ==============================================================================
# Prompt Templates
# ==============================================================================
class PromptTemplateCreateRequest(BaseModel):
    template_key: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=2, max_length=150)
    task_type: str = Field(min_length=2, max_length=64)
    platform_key: str | None = Field(default=None, max_length=64)
    website_id: int | None = Field(default=None, ge=1)
    social_profile_id: int | None = Field(default=None, ge=1)
    system_instructions: str = Field(min_length=5, max_length=8000)
    user_prompt_template: str = Field(min_length=5, max_length=12000)
    response_schema_name: str = Field(default="MultiProfileSocialBatchOutput", max_length=100)
    is_active: bool = True


class PromptTemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    system_instructions: str | None = Field(default=None, min_length=5, max_length=8000)
    user_prompt_template: str | None = Field(default=None, min_length=5, max_length=12000)
    is_active: bool | None = None
    change_note: str | None = Field(default=None, max_length=255)


class PromptPreviewRequest(BaseModel):
    website_id: int | None = Field(default=None, ge=1)
    website_content_id: int | None = Field(default=None, ge=1)
    social_profile_id: int | None = Field(default=None, ge=1)
    context_mode: str = Field(default="optimized", max_length=32)
    system_instructions_override: str | None = None
    user_prompt_template_override: str | None = None


class PromptPreviewResponse(BaseModel):
    template_id: int
    scope_used: str
    system_prompt: str
    user_prompt: str
    context_mode: str
    estimated_input_tokens: int
    variables_used: dict[str, Any] = Field(default_factory=dict)


class PromptTemplateResponse(BaseModel):
    id: int
    template_key: str
    scope_key: str
    name: str
    task_type: str
    platform_key: str | None = None
    website_id: int | None = None
    website_name: str | None = None
    social_profile_id: int | None = None
    social_profile_name: str | None = None
    system_instructions: str
    user_prompt_template: str
    available_variables: list[str] = Field(default_factory=list)
    response_schema_name: str
    version: int
    is_active: bool
    is_system_default: bool
    created_at: datetime
    updated_at: datetime


class PromptTemplateRevisionResponse(BaseModel):
    id: int
    prompt_template_id: int
    version: int
    system_instructions: str
    user_prompt_template: str
    change_note: str | None = None
    created_by: int | None = None
    created_at: datetime


# ==============================================================================
# Cache, Generation Jobs, Usage & History
# ==============================================================================
class GenerateSocialRequest(BaseModel):
    provider_id: int | None = Field(default=None, ge=1)
    context_mode: str = Field(default="optimized", max_length=32)
    force_regenerate: bool = False
    trigger_type: str = Field(default="manual", max_length=32)


class GenerateSocialDestinationsPreview(BaseModel):
    website_id: int
    website_name: str
    eligible_profiles: list[dict[str, Any]] = Field(default_factory=list)
    empty_message: str | None = None
    configure_url: str


class AiGenerationJobResponse(BaseModel):
    id: int
    job_uuid: str
    job_type: str
    trigger_type: str
    website_id: int
    website_name: str | None = None
    website_content_id: int | None = None
    content_title: str | None = None
    target_profile_ids: list[int] = Field(default_factory=list)
    ai_provider_id: int | None = None
    context_mode: str
    force_regenerate: bool
    regenerate_social_post_id: int | None = None
    idempotency_key: str
    status: str
    defer_reason: str | None = None
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None = None
    worker_id: str | None = None
    heartbeat_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_summary: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AiGenerationJobListResponse(BaseModel):
    items: list[AiGenerationJobResponse]
    meta: PaginationMeta


class AiGenerationLogResponse(BaseModel):
    id: int
    job_id: int | None = None
    ai_provider_id: int
    provider_name: str | None = None
    provider_type: str | None = None
    prompt_template_id: int | None = None
    website_id: int | None = None
    website_name: str | None = None
    website_content_id: int | None = None
    task_type: str
    model_name: str
    context_mode: str
    cache_hit: bool
    cache_key_hash: str | None = None
    status: str
    estimated_input_tokens: int | None = None
    measured_input_tokens: int | None = None
    measured_output_tokens: int | None = None
    total_measured_tokens: int | None = None
    token_usage_status: str
    estimated_cost_usd: float | None = None
    latency_ms: int | None = None
    truncated_input: bool = False
    truncation_note: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime


class AiGenerationLogListResponse(BaseModel):
    items: list[AiGenerationLogResponse]
    meta: PaginationMeta


class AiPromptLogDetailResponse(BaseModel):
    capture_status: str = "not_captured"
    system_instruction: str | None = None
    user_prompt: str | None = None
    response: str | None = None
    truncated: bool = False


class CacheEntryResponse(BaseModel):
    id: int
    cache_key_hash: str
    ai_provider_id: int
    website_id: int
    website_name: str | None = None
    website_content_id: int | None = None
    task_type: str
    model_name: str
    prompt_version: int
    context_mode: str
    language: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    hit_count: int
    last_hit_at: datetime | None = None
    expires_at: datetime
    created_at: datetime


class CacheStatsResponse(BaseModel):
    total_entries: int = 0
    active_entries: int = 0
    expired_entries: int = 0
    total_hits: int = 0
    cache_hit_rate_percent: float = 0.0
    entries: list[CacheEntryResponse] = Field(default_factory=list)


class CacheInvalidateRequest(BaseModel):
    website_id: int | None = Field(default=None, ge=1)
    cache_ids: list[int] | None = None
    expired_only: bool = False


class AiUsageBreakdownItem(BaseModel):
    key: str
    label: str
    requests: int = 0
    cache_hits: int = 0
    measured_tokens: int = 0


class AiUsageSummaryResponse(BaseModel):
    requests_today: int = 0
    requests_this_month: int = 0
    estimated_input_tokens_today: int = 0
    measured_input_tokens_today: int | None = None
    measured_output_tokens_today: int | None = None
    total_measured_tokens_today: int | None = None
    total_measured_tokens_month: int | None = None
    cache_hits_today: int = 0
    cache_hit_rate_percent: float = 0.0
    failed_requests_today: int = 0
    deferred_jobs_count: int = 0
    queued_jobs_count: int = 0
    average_latency_ms: float | None = None
    active_provider_name: str | None = None
    active_model: str | None = None
    daily_request_limit: int | None = None
    daily_requests_remaining: int | None = None
    daily_token_limit: int | None = None
    daily_tokens_remaining: int | None = None
    quota_status: str = "unconfigured"
    estimated_cost_usd_month: float | None = None
    cost_note: str = (
        "Estimated cost stays unavailable (null) unless verified provider pricing is configured."
    )
    usage_by_website: list[AiUsageBreakdownItem] = Field(default_factory=list)
    usage_by_model: list[AiUsageBreakdownItem] = Field(default_factory=list)
    usage_by_task_type: list[AiUsageBreakdownItem] = Field(default_factory=list)
