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
  target_content_type: 'blog_post' | 'blog_index' | 'page' | 'category' | 'tag' | 'archive' | 'custom' | 'exclude' | string
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
  created_at: string
  updated_at: string
}

export interface ContentListResponse {
  items: ContentListItem[]
  meta: PaginationMeta
  stats: ContentStats
}
