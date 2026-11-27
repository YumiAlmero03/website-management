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
  total_brands: number
  active_websites: number
  total_articles: number
  articles_discovered_today: number
  updated_articles: number
  completed_scans: number
  failed_scans: number
  websites_due_for_scan: number
}

export interface ScanLog {
  id: number
  website_id: number
  website_name: string | null
  scan_method: string
  trigger_type: string
  urls_found: number
  articles_processed: number
  new_articles: number
  updated_articles: number
  unchanged_articles: number
  skipped_articles: number
  failed_articles: number
  status: 'pending' | 'processing' | 'completed' | 'partially_completed' | 'failed' | 'cancelled' | string
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

export interface DashboardSummary {
  generated_at: string
  timezone: string
  current_phase: number
  filtered_brand_id: number | null
  filtered_website_id: number | null
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

// Phase 2 — Brands, Websites, Articles & Media
export interface BrandWebsiteSummary {
  id: number
  name: string
  domain: string
  website_type: string
  status: string
  last_successful_scan_at: string | null
}

export interface Brand {
  id: number
  name: string
  slug: string
  logo_url: string | null
  description: string | null
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
  is_active: boolean
  website_count: number
  created_at: string
  updated_at: string
}

export interface BrandDetail extends Brand {
  websites: BrandWebsiteSummary[]
}

export interface BrandListResponse {
  items: Brand[]
  meta: PaginationMeta
}

export interface Website {
  id: number
  brand_id: number
  brand_name: string | null
  name: string
  domain: string
  website_type: string
  discovery_method: string
  rss_url: string | null
  sitemap_url: string | null
  llms_url: string | null
  api_endpoint: string | null
  article_url_patterns: string[]
  excluded_url_patterns: string[]
  scan_interval_minutes: number
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
  rss_urls: string[]
  sitemap_urls: string[]
  llms_urls: string[]
  wordpress_api_url: string | null
  recommended_method: string
  notes: string[]
}

export interface MediaAsset {
  id: number
  brand_id: number | null
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

export interface ArticleRevision {
  id: number
  article_id: number
  revision_number: number
  title: string
  meta_description: string | null
  markdown_content: string | null
  content_hash: string
  created_at: string
}

export interface ArticleListItem {
  id: number
  website_id: number
  website_name: string | null
  brand_id: number | null
  brand_name: string | null
  featured_media_id: number | null
  featured_image_url: string | null
  title: string
  canonical_url: string
  author: string | null
  meta_description: string | null
  language: string | null
  categories: string[]
  tags: string[]
  keywords: string[]
  word_count: number
  status: string
  is_historical_baseline: boolean
  near_duplicate_of_id: number | null
  near_duplicate_score: number | null
  published_at: string | null
  source_updated_at: string | null
  discovered_at: string
  last_checked_at: string
}

export interface ArticleDetail extends ArticleListItem {
  url_hash: string
  content_hash: string
  original_content: string | null
  markdown_content: string | null
  optimized_context: string | null
  featured_media: MediaAsset | null
  revision_count: number
  created_at: string
  updated_at: string
}

export interface ArticleListResponse {
  items: ArticleListItem[]
  meta: PaginationMeta
}
