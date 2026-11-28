export interface ApiErrorPayload {
  detail: string
  code?: string
}

export interface AdminUser {
  id: number
  email: string
  display_name: string
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

export interface AuthSession {
  user: AdminUser
  csrf_token: string
  expires_at: string
}

export interface AuthStatus {
  admin_initialized: boolean
  authenticated: boolean
  app_name: string
  database_connected: boolean
  registration_enabled: boolean
}

export interface DatabaseHealth {
  connected: boolean
  status: string
  database_name: string
  host: string
  port: number
  user: string
  uses_root_user: boolean
  server_version: string | null
  character_set: string | null
  innodb_available: boolean | null
  latency_ms: number | null
  pool_size: number
  max_overflow: number
  pool_recycle: number
  error: string | null
}

export interface ResourceThresholds {
  cpu_warning_percent: number
  cpu_critical_percent: number
  ram_warning_percent: number
  load_avg_threshold: number
  max_concurrent_generation: number
  max_concurrent_browsers: number
  recheck_interval_minutes: number
}

export interface SystemResources {
  cpu_percent: number
  cpu_cores: number
  ram_percent: number
  ram_used_mb: number
  ram_total_mb: number
  load_avg_1m: number | null
  load_avg_5m: number | null
  load_avg_15m: number | null
  disk_percent: number
  disk_free_gb: number
  guardian_status: 'normal' | 'warning' | 'critical' | string
  guardian_reasons: string[]
  thresholds: ResourceThresholds
}

export interface StoragePathStatus {
  name: string
  path: string
  exists: boolean
  writable: boolean
}

export interface SystemHealth {
  status: 'ok' | 'warning' | 'degraded' | string
  app_name: string
  version: string
  environment: string
  timezone: string
  timestamp: string
  database: DatabaseHealth
  resources: SystemResources
  storage_root: string
  storage_paths: StoragePathStatus[]
}

export interface ActivityLogItem {
  id: number
  user_id: number | null
  actor_type: string
  category: string
  action: string
  level: string
  message: string
  metadata: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

export interface PaginationMeta {
  page: number
  page_size: number
  total_items: number
  total_pages: number
}

export interface ActivityLogListResponse {
  items: ActivityLogItem[]
  meta: PaginationMeta
}

export interface PhaseModuleStatus {
  key: string
  label: string
  route: string
  phase: number
  status: 'active' | 'not_implemented' | string
  summary: string
}

export interface Phase1Counts {
  active_sessions: number
  configured_settings: number
  activity_events_total: number
}

export interface Phase2Metrics {
  active_websites: number
  total_categories: number
  total_contents: number
  total_extracted: number
  homepage_count: number
  page_count: number
  game_page_count?: number
  blog_post_count: number
  blog_index_count: number
  other_count: number
  pending_extractions: number
  failed_extractions: number
  contents_discovered_today: number
  updated_contents: number
  completed_scans: number
  failed_scans: number
  incomplete_scans: number
  websites_due_for_scan: number
  pending_content_approvals?: number
  approved_keywords_count?: number
}

export interface ScanLog {
  id: number
  website_id: number
  website_name: string | null
  scan_method: string
  scan_mode: 'full' | 'incremental' | 'resume' | 'retry_failed' | 'discover_only' | string
  trigger_type: string
  urls_found: number
  articles_processed: number
  urls_pending_extraction: number
  new_articles: number
  updated_articles: number
  unchanged_articles: number
  skipped_articles: number
  failed_articles: number
  excluded_count: number
  homepage_count: number
  page_count: number
  blog_post_count: number
  other_count: number
  current_source: string | null
  current_url: string | null
  discovered_sitemaps: string[]
  sources_completed: Array<Record<string, unknown>>
  sources_failed: Array<Record<string, unknown>>
  status:
    | 'pending'
    | 'processing'
    | 'completed'
    | 'partially_completed'
    | 'incomplete'
    | 'paused'
    | 'failed'
    | 'cancelled'
    | string
  error_message: string | null
  duration_ms: number | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface ScanLogListResponse {
  items: ScanLog[]
  meta: PaginationMeta
}

export interface ScanItem {
  id: number
  scan_log_id: number
  website_id: number
  content_id: number | null
  url: string
  normalized_url: string
  content_type: string
  discovery_sources: string[]
  discovered_title: string | null
  status: string
  http_status: number | null
  failure_reason: string | null
  error_detail: string | null
  processed_at: string | null
  created_at: string
}

export interface ScanItemListResponse {
  items: ScanItem[]
  meta: PaginationMeta
}

export interface DashboardSummary {
  generated_at: string
  timezone: string
  current_phase: number
  filtered_website_id: number | null
  filtered_category_id: number | null
  database: DatabaseHealth
  resources: SystemResources
  phase1_counts: Phase1Counts
  phase2_metrics: Phase2Metrics
  recent_scans: ScanLog[]
  modules: PhaseModuleStatus[]
  recent_activities: ActivityLogItem[]
}

export interface SettingItem {
  key: string
  category: string
  label: string
  description: string
  value_type: 'string' | 'integer' | 'number' | 'boolean' | 'enum' | 'timezone' | 'secret' | string
  value: unknown
  is_secret: boolean
  has_value: boolean
  default_value: unknown
  updated_at: string | null
}

export interface SettingsListResponse {
  categories: string[]
  items: SettingItem[]
}

// Phase 2.1 — Website Categories, Website-Centric Brand Profiles, Discovery Sources, URL Rules & Contents
export interface WebsiteCategory {
  id: number
  name: string
  slug: string
  description: string | null
  is_archived: boolean
  sort_order: number
  website_count: number
  created_at: string
  updated_at: string
}

export interface WebsiteCategoryListResponse {
  items: WebsiteCategory[]
}

export interface ContentBreakdownCounts {
  total_discovered: number
  total_extracted: number
  homepage: number
  page: number
  game_page?: number
  blog_index: number
  blog_post: number
  category: number
  tag: number
  archive: number
  custom: number
  pending: number
  failed: number
  updated: number
  excluded: number
}

export interface Website {
  id: number
  category_id: number | null
  category_name: string | null
  name: string
  brand_name: string
  brand_slug: string | null
  logo_url: string | null
  brand_description: string | null
  target_audience: string | null
  target_country: string | null
  primary_language: string
  secondary_languages: string[]
  tone: string | null
  target_keywords: string[]
  keyword_bank: string[]
  restricted_keywords: string[]
  default_hashtags: string[]
  default_cta: string | null
  writing_guidelines: string | null
  ai_instructions: string | null
  domain: string
  website_type: string
  discovery_method: string
  single_source_only: boolean
  rss_url: string | null
  sitemap_url: string | null
  llms_url: string | null
  api_endpoint: string | null
  article_url_patterns: string[]
  excluded_url_patterns: string[]
  scan_interval_minutes: number
  crawl_batch_size: number
  crawl_max_urls_per_run: number
  auto_scan: boolean
  auto_generate: boolean
  auto_generate_require_published_at: boolean
  auto_generate_context_mode: 'metadata_only' | 'optimized' | 'full' | string
  initial_scan_completed: boolean
  baseline_mode: string
  baseline_after_date: string | null
  baseline_limit: number | null
  last_scanned_at: string | null
  last_successful_scan_at: string | null
  next_scan_at: string | null
  status: string
  article_count: number
  content_counts: ContentBreakdownCounts
  created_at: string
  updated_at: string
}

export interface WebsiteListResponse {
  items: Website[]
  meta: PaginationMeta
}

export interface WebsiteConnectivity {
  reachable: boolean
  status_code: number | null
  final_url: string | null
  title: string | null
  detected_website_type: string | null
  error: string | null
}

export interface WebsiteDiscoverResult {
  reachable: boolean
  homepage_url: string
  detected_website_type: string | null
  rss_urls: string[]
  sitemap_urls: string[]
  llms_urls: string[]
  wordpress_api_url: string | null
  recommended_method: string
  notes: string[]
}

export interface WebsiteDiscoverySource {
  id: number
  website_id: number
  parent_source_id: number | null
  source_type: string
  endpoint_url: string
  is_enabled: boolean
  etag: string | null
  last_modified_header: string | null
  last_status_code: number | null
  last_urls_found: number
  last_checked_at: string | null
  last_success_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface WebsiteUrlRule {
  id: number
  website_id: number
  pattern: string
  target_content_type: 'blog_post' | 'blog_index' | 'page' | 'game_page' | 'category' | 'tag' | 'archive' | 'custom' | 'exclude' | string
  match_mode: 'prefix' | 'glob' | 'exact' | 'regex' | string
  priority: number
  is_enabled: boolean
  notes: string | null
  created_at: string
  updated_at: string
}

export interface MediaAsset {
  id: number
  website_id: number | null
  file_name: string
  file_path: string | null
  source_url: string | null
  mime_type: string | null
  file_size: number | null
  width: number | null
  height: number | null
  alt_text: string | null
  checksum: string | null
  created_at: string
}

export interface MediaAssetListResponse {
  items: MediaAsset[]
  meta: PaginationMeta
}

export interface ContentRevision {
  id: number
  content_id: number
  revision_number: number
  content_type: string | null
  title: string
  meta_description: string | null
  markdown_content: string | null
  content_hash: string
  created_at: string
}

export interface ContentStats {
  total_discovered: number
  total_extracted: number
  homepage_count: number
  page_count: number
  game_page_count?: number
  blog_post_count: number
  blog_index_count: number
  other_count: number
  pending_count: number
  failed_count: number
  updated_count: number
  excluded_count: number
  discovered_today_count: number
}

export type ContentType =
  | 'homepage'
  | 'page'
  | 'game_page'
  | 'blog_index'
  | 'blog_post'
  | 'category'
  | 'tag'
  | 'archive'
  | 'custom'
  | string

export interface ContentListItem {
  id: number
  website_id: number
  website_name: string | null
  website_domain: string | null
  website_category_name: string | null
  featured_media_id: number | null
  featured_image_url: string | null
  content_type: ContentType
  classification_method: string
  manual_classification_override: boolean
  is_excluded: boolean
  url: string
  canonical_url: string
  title: string
  author: string | null
  meta_description: string | null
  h1_text: string | null
  language: string | null
  categories: string[]
  tags: string[]
  keywords: string[]
  discovery_sources: string[]
  word_count: number
  http_status: number | null
  extraction_status: 'pending' | 'extracted' | 'failed' | string
  extraction_error: string | null
  status: string
  is_historical_baseline: boolean
  near_duplicate_of_id: number | null
  near_duplicate_score: number | null
  published_at: string | null
  source_updated_at: string | null
  first_discovered_at: string
  last_discovered_at: string
  last_checked_at: string
  approval_status?: ApprovalStatus | null
  keyword_approval_status?: ApprovalStatus | null
  focus_keyphrase?: string | null
  secondary_keywords?: string[]
  cannibalization_count?: number
}

export interface ContentDetail extends ContentListItem {
  url_hash: string
  content_hash: string
  original_content: string | null
  extracted_content: string | null
  markdown_content: string | null
  optimized_context: string | null
  structured_data_json: Record<string, unknown> | null
  featured_media: MediaAsset | null
  revision_count: number
  keyword_mapping?: ContentKeywordMapping | null
  content_approval?: ContentApprovalItem | null
  created_at: string
  updated_at: string
}

export interface ContentListResponse {
  items: ContentListItem[]
  meta: PaginationMeta
  stats: ContentStats
}

// Phase 3 — Social Profiles, Gemini AI Engine, Knowledge Profiles, Prompts, Cache & Drafts
export interface PlatformItem {
  id: number
  platform_key: string
  display_name: string
  category: string
  default_max_chars: number | null
  url_counts_as_chars: number | null
  supports_hashtags: boolean
  supports_cta: boolean
  supports_source_url: boolean
  supports_title: boolean
  supports_media: boolean
  supports_free_auto_publish: boolean
  credential_fields: string[]
  capabilities: Record<string, unknown>
  is_enabled: boolean
  sort_order: number
}

export interface CredentialFieldMask {
  field: string
  configured: boolean
  masked_value: string | null
}

export interface SocialProfileCredentialsPayload {
  api_key?: string | null
  api_secret?: string | null
  access_token?: string | null
  refresh_token?: string | null
  app_id?: string | null
  app_secret?: string | null
  token_expires_at?: string | null
  clear_fields?: string[]
}

export interface SocialProfileItem {
  id: number
  website_id: number
  website_name: string | null
  platform_id: number
  platform_key: string
  platform_display_name: string
  profile_name: string
  profile_url: string | null
  external_account_id: string | null
  profile_image_url: string | null
  is_active: boolean
  publishing_method: 'manual' | 'api' | string
  credential_status: string
  generation_enabled: boolean
  automatic_generation_enabled: boolean
  auto_publish_enabled: boolean
  auto_publish_available: boolean
  custom_language: string | null
  effective_language: string
  writing_tone: string | null
  platform_ai_instructions: string | null
  default_hashtags: string[]
  default_cta: string | null
  preferred_length: 'short' | 'medium' | 'long' | string | null
  character_limit: number | null
  effective_character_limit: number | null
  include_source_url: boolean
  include_hashtags: boolean
  include_emojis: boolean
  content_restrictions: string | null
  credential_masks: CredentialFieldMask[]
  has_credentials: boolean
  allowed_credential_fields: string[]
  token_expires_at: string | null
  credentials_updated_at: string | null
  created_at: string
  updated_at: string
}

export interface AiProviderModelInfo {
  name: string
  display_name: string
  description: string | null
  input_token_limit: number | null
  output_token_limit: number | null
  supported_actions: string[]
  is_flash_recommended: boolean
}

export interface AiProviderItem {
  id: number
  name: string
  provider_type: string
  base_url: string | null
  has_api_key: boolean
  masked_api_key: string | null
  selected_model: string
  available_models: AiProviderModelInfo[]
  default_temperature: number
  max_output_tokens: number
  request_timeout_seconds: number
  max_retry_attempts: number
  daily_request_limit: number
  daily_token_limit: number
  per_minute_request_limit: number
  generation_enabled: boolean
  response_caching_enabled: boolean
  token_optimization_enabled: boolean
  allow_paid_fallback: boolean
  is_default: boolean
  is_active: boolean
  last_test_status: string
  last_test_latency_ms: number | null
  last_test_error: string | null
  last_verified_at: string | null
  billing_disclaimer: string
  created_at: string
  updated_at: string
}

export interface AiProviderTestResult {
  connected: boolean
  provider_id: number
  selected_model: string
  model_available: boolean
  latency_ms: number | null
  discovered_model_count: number
  error_detail: string | null
  last_verified_at: string | null
  generation_probe_tokens: number | null
}

export interface AiProviderModelsResponse {
  provider_id: number
  selected_model: string
  models: AiProviderModelInfo[]
  fetched_live: boolean
}

export interface KnowledgeInternalLink {
  title: string
  url: string
  content_type: string
}

export interface KnowledgeSourceRef {
  content_id: number
  title: string
  url: string
  content_type: string
  content_hash: string
}

export interface KnowledgeProfile {
  id: number | null
  website_id: number
  website_name: string | null
  brand_name: string
  brand_description: string | null
  website_category: string | null
  business_overview: string | null
  products_and_services: string[]
  main_features: string[]
  target_audience: string | null
  target_country: string | null
  primary_language: string
  secondary_languages: string[]
  recommended_writing_tone: string | null
  main_keywords: string[]
  content_pillars: string[]
  important_internal_links: KnowledgeInternalLink[]
  relevant_publishing_restrictions: string | null
  source_content_references: KnowledgeSourceRef[]
  administrator_notes: string | null
  manual_overrides: Record<string, unknown>
  field_provenance: Record<string, string>
  content_fingerprint: string
  is_outdated: boolean
  profile_version: number
  last_generated_at: string | null
  last_reviewed_at: string | null
  approved_by: number | null
  status: string
  created_at: string | null
  updated_at: string | null
}

export interface KnowledgeProfileRevision {
  id: number
  knowledge_profile_id: number
  website_id: number
  profile_version: number
  snapshot_json: Record<string, unknown>
  content_fingerprint: string
  change_source: string
  created_by: number | null
  created_at: string
}

export interface PromptTemplateItem {
  id: number
  template_key: string
  scope_key: string
  name: string
  task_type: string
  platform_key: string | null
  website_id: number | null
  website_name: string | null
  social_profile_id: number | null
  social_profile_name: string | null
  system_instructions: string
  user_prompt_template: string
  available_variables: string[]
  response_schema_name: string
  version: number
  is_active: boolean
  is_system_default: boolean
  created_at: string
  updated_at: string
}

export interface PromptTemplateRevision {
  id: number
  prompt_template_id: number
  version: number
  system_instructions: string
  user_prompt_template: string
  change_note: string | null
  created_by: number | null
  created_at: string
}

export interface PromptPreviewResult {
  template_id: number
  scope_used: string
  system_prompt: string
  user_prompt: string
  context_mode: string
  estimated_input_tokens: number
  variables_used: Record<string, unknown>
}

export interface GenerateSocialDestinationProfile {
  id: number
  profile_name: string
  platform_key: string
  platform_display_name: string
  publishing_method: string
  language: string
  automatic_generation_enabled: boolean
  character_limit: number | null
}

export interface GenerateSocialDestinationsPreview {
  website_id: number
  website_name: string
  eligible_profiles: GenerateSocialDestinationProfile[]
  empty_message: string | null
  configure_url: string
}

export interface AiGenerationJob {
  id: number
  job_uuid: string
  job_type: string
  trigger_type: string
  website_id: number
  website_name: string | null
  website_content_id: number | null
  content_title: string | null
  target_profile_ids: number[]
  ai_provider_id: number | null
  context_mode: string
  force_regenerate: boolean
  regenerate_social_post_id: number | null
  idempotency_key: string
  status: string
  defer_reason: string | null
  attempt_count: number
  max_attempts: number
  next_retry_at: string | null
  worker_id: string | null
  heartbeat_at: string | null
  error_code: string | null
  error_message: string | null
  result_summary: Record<string, unknown> | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface AiGenerationJobListResponse {
  items: AiGenerationJob[]
  meta: PaginationMeta
}

export interface AiGenerationLogItem {
  id: number
  job_id: number | null
  ai_provider_id: number
  provider_name: string | null
  prompt_template_id: number | null
  website_id: number | null
  website_name: string | null
  website_content_id: number | null
  task_type: string
  model_name: string
  context_mode: string
  cache_hit: boolean
  cache_key_hash: string | null
  status: string
  estimated_input_tokens: number | null
  measured_input_tokens: number | null
  measured_output_tokens: number | null
  total_measured_tokens: number | null
  token_usage_status: string
  estimated_cost_usd: number | null
  latency_ms: number | null
  truncated_input: boolean
  truncation_note: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
}

export interface AiGenerationLogListResponse {
  items: AiGenerationLogItem[]
  meta: PaginationMeta
}

export interface CacheEntryItem {
  id: number
  cache_key_hash: string
  ai_provider_id: number
  website_id: number
  website_name: string | null
  website_content_id: number | null
  task_type: string
  model_name: string
  prompt_version: number
  context_mode: string
  language: string
  input_tokens: number | null
  output_tokens: number | null
  hit_count: number
  last_hit_at: string | null
  expires_at: string
  created_at: string
}

export interface CacheStatsResponse {
  total_entries: number
  active_entries: number
  expired_entries: number
  total_hits: number
  cache_hit_rate_percent: number
  entries: CacheEntryItem[]
}

export interface AiUsageBreakdownItem {
  key: string
  label: string
  requests: number
  cache_hits: number
  measured_tokens: number
}

export interface AiUsageSummary {
  requests_today: number
  requests_this_month: number
  estimated_input_tokens_today: number
  measured_input_tokens_today: number | null
  measured_output_tokens_today: number | null
  total_measured_tokens_today: number | null
  total_measured_tokens_month: number | null
  cache_hits_today: number
  cache_hit_rate_percent: number
  failed_requests_today: number
  deferred_jobs_count: number
  queued_jobs_count: number
  average_latency_ms: number | null
  active_provider_name: string | null
  active_model: string | null
  daily_request_limit: number | null
  daily_requests_remaining: number | null
  daily_token_limit: number | null
  daily_tokens_remaining: number | null
  quota_status: string
  estimated_cost_usd_month: number | null
  cost_note: string
  usage_by_website: AiUsageBreakdownItem[]
  usage_by_model: AiUsageBreakdownItem[]
  usage_by_task_type: AiUsageBreakdownItem[]
}

export interface SocialPostRevisionItem {
  id: number
  social_post_id: number
  version_number: number
  title: string | null
  caption: string
  assembled_content: string
  hashtags: string[]
  cta_text: string | null
  generation_model: string | null
  change_type: string
  edited_by: number | null
  notes: string | null
  created_at: string
}

export interface SocialPostItem {
  id: number
  website_id: number
  website_name: string | null
  website_content_id: number | null
  source_title: string | null
  source_content_type: string | null
  social_profile_id: number
  social_profile_name: string | null
  platform_id: number
  platform_key: string | null
  platform_display_name: string | null
  featured_media_id: number | null
  featured_image_url: string | null
  ai_generation_job_id: number | null
  ai_provider_id: number | null
  generation_model: string | null
  prompt_template_id: number | null
  title: string | null
  caption: string
  assembled_content: string
  hashtags: string[]
  cta_text: string | null
  source_url: string | null
  language: string
  character_count: number
  character_limit: number | null
  validation_warnings: string[]
  status: 'pending_review' | 'approved' | 'rejected' | 'generation_failed' | 'archived' | string
  is_manually_edited: boolean
  current_version: number
  error_message: string | null
  approved_by: number | null
  approved_at: string | null
  rejected_by: number | null
  rejected_at: string | null
  rejection_reason: string | null
  generated_at: string | null
  created_at: string
  updated_at: string
}

export interface SocialPostStats {
  total_drafts: number
  pending_review: number
  approved: number
  rejected: number
  generation_failed: number
  archived: number
}

export interface SocialPostListResponse {
  items: SocialPostItem[]
  meta: PaginationMeta
  stats: SocialPostStats
}

// Phase 3 Addendum — SEO Keyword Mapping & Content Approval
export type ApprovalStatus =
  | 'awaiting_extraction'
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'needs_rereview'
  | string

export interface ImageAltSuggestionItem {
  image_url: string | null
  current_alt: string | null
  suggested_alt: string
  context: string | null
}

export interface CannibalizationMatch {
  content_id: number
  title: string
  canonical_url: string
  content_type: string
  focus_keyphrase: string
  approval_status: ApprovalStatus
  similarity_score: number
  severity: 'high' | 'medium'
  reason: string
}

export interface ContentKeywordMapping {
  id: number
  website_id: number
  website_content_id: number
  focus_keyphrase: string
  secondary_keywords: string[]
  anchor_text_variations: string[]
  image_alt_suggestions: ImageAltSuggestionItem[]
  approval_status: ApprovalStatus
  suggestion_source: string
  keyword_generation_method: string
  keyword_generation_status: string
  keyword_evidence: Array<Record<string, unknown>>
  keyword_scores: Record<string, unknown>
  keyword_model: string | null
  keyword_input_hash: string | null
  keyword_generated_at: string | null
  game_name: string | null
  provider_name: string | null
  is_admin_locked: boolean
  version: number
  cannibalization_warnings: CannibalizationMatch[]
  last_reviewed_at: string | null
  approved_by: number | null
  approved_at: string | null
  created_at: string
  updated_at: string
}

export interface ContentKeywordRevision {
  id: number
  content_keyword_id: number
  revision_number: number
  focus_keyphrase: string
  secondary_keywords: string[]
  anchor_text_variations: string[]
  image_alt_suggestions: ImageAltSuggestionItem[]
  approval_status: string
  suggestion_source: string
  change_note: string | null
  changed_by: number | null
  created_at: string
}

export interface ContentApprovalHistoryItem {
  id: number
  content_approval_id: number
  from_status: string | null
  to_status: string
  content_type: string | null
  focus_keyphrase: string | null
  action: string
  note: string | null
  acted_by: number | null
  created_at: string
}

export interface ContentApprovalItem {
  approval_id: number | null
  website_id: number
  website_name: string | null
  website_domain: string | null
  content_id: number
  title: string
  url: string
  canonical_url: string
  content_type: string
  extraction_status: string
  extraction_error: string | null
  is_historical_baseline: boolean
  is_excluded: boolean
  word_count: number
  meta_title: string | null
  meta_description: string | null
  h1_text: string | null
  language: string | null
  optimized_context_preview: string | null
  featured_image_url: string | null
  published_at: string | null
  first_discovered_at?: string | null
  last_discovered_at?: string | null
  status: ApprovalStatus
  classified_content_type: string
  review_note: string | null
  rejection_reason: string | null
  auto_generation_triggered_at: string | null
  reviewed_by: number | null
  reviewed_at: string | null
  approved_at: string | null
  rejected_at: string | null
  keyword_mapping: ContentKeywordMapping | null
  cannibalization_warnings: CannibalizationMatch[]
  updated_at: string
  created_at: string
}

export interface ContentApprovalDetail extends ContentApprovalItem {
  markdown_content: string | null
  extracted_content: string | null
  yake_keywords: string[]
  keyword_revisions: ContentKeywordRevision[]
  approval_history: ContentApprovalHistoryItem[]
}

export interface ContentApprovalStats {
  total_eligible: number
  awaiting_extraction: number
  pending_review: number
  needs_rereview: number
  approved: number
  rejected: number
  cannibalization_flagged: number
}

export interface ContentApprovalListResponse {
  items: ContentApprovalItem[]
  meta: PaginationMeta
  stats: ContentApprovalStats
}

export interface ApproveContentResult {
  item: ContentApprovalDetail
  auto_generation_job_id: number | null
  auto_generation_note: string | null
  cannibalization_warnings: CannibalizationMatch[]
}

export interface BulkApproveResult {
  approved_content_ids: number[]
  skipped_items: Array<{ content_id: number; reason: string }>
  auto_generation_job_ids: number[]
  total_approved: number
  total_skipped: number
}

export interface AiKeywordSuggestionPreview {
  content_id: number
  focus_keyphrase: string
  secondary_keywords: string[]
  anchor_text_variations: string[]
  image_alt_suggestions: ImageAltSuggestionItem[]
  suggestion_source: string
  provider_name: string | null
  applied: boolean
}

export interface ApprovedKeywordMapEntry {
  website_id: number
  website_name: string | null
  content_id: number
  canonical_url: string
  title: string
  content_type: string
  focus_keyphrase: string
  secondary_keywords: string[]
  anchor_text_variations: string[]
  image_alt_suggestions: ImageAltSuggestionItem[]
  approval_status: ApprovalStatus
  keyword_version: number
  last_reviewed_at: string | null
  cannibalization_warnings: CannibalizationMatch[]
}

export interface KeywordMapListResponse {
  items: ApprovedKeywordMapEntry[]
  meta: PaginationMeta
  total_cannibalization_conflicts: number
}
