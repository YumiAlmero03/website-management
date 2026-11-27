# ContentHub AI — REST API Specification

## 1. Conventions

- **Base Path:** `/api/v1`
- **Format:** JSON (`application/json`), UTF-8.
- **Timestamps:** ISO 8601 UTC (`2026-11-27T10:30:00Z`).
- **Authentication:** Server-side HTTP-only session cookie (`contenthub_session` by default).
- **CSRF Protection:** All mutating authenticated requests (`POST`, `PUT`, `PATCH`, `DELETE`) require the `X-CSRF-Token` header matching the active session's `csrf_token` returned by `/api/v1/auth/login` or `/api/v1/auth/me`.
- **Public Registration:** Permanently disabled (`404 Not Found` — no registration route exists).
- **Error Envelope:**
  ```json
  {
    "detail": "Human-readable error message",
    "code": "ERROR_CODE"
  }
  ```
- **Honest Unimplemented Behavior:** Endpoints or capabilities scheduled for Phases 3–6 are never mocked with fake success responses.

## 2. Phase 1 Endpoints (Preserved)

### Health & System Diagnostics

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/health` | Public | No | Lightweight liveness check (`status`, `app_name`, `version`, `environment`, `timestamp`). |
| `GET` | `/api/v1/health/db` | Admin | No | Live MySQL connectivity check, server version, InnoDB/`utf8mb4` verification, latency, and pool settings. |
| `GET` | `/api/v1/health/system` | Admin | No | Application health, MySQL diagnostics, `psutil` CPU/RAM/Load/Disk metrics, Resource Guardian status, and storage writability. |

### Administrator Authentication

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/auth/status` | Public | No | Returns `{ "admin_initialized": bool, "authenticated": bool, "app_name": str }`. |
| `POST` | `/api/v1/auth/login` | Public (Rate-limited) | No | Validates Argon2id credentials, creates hashed MySQL session, sets `HttpOnly` cookie, returns `{ "user", "csrf_token", "expires_at" }`. |
| `GET` | `/api/v1/auth/me` | Admin | No | Returns current administrator, `csrf_token`, and session expiry. |
| `POST` | `/api/v1/auth/logout` | Admin | **Yes** | Revokes server-side session in MySQL, clears cookie, logs audit event. |

### Dashboard

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/dashboard/summary` | Admin | No | Optional query params: `website_id`, `category_id`. Returns Phase 1 + Phase 2.1 counts (active websites, categories, total/extracted contents, homepage/page/blog_index/blog_post/other breakdown, failed/pending counts, completed/failed/incomplete scans), recent scans, infrastructure health, and explicit Phase 3–6 `not_implemented` modules. |

### Application Settings & Activity Logs

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/settings` | Admin | No | Returns configurable settings grouped by category (`general`, `publishing`, `resource_guardian`, `seo`, `backups`), masking secrets (`has_value`). |
| `PUT` | `/api/v1/settings` | Admin | **Yes** | Validates and updates settings, Fernet-encrypts secrets, writes redacted audit event. |
| `GET` | `/api/v1/logs/activity` | Admin | No | Paginated (`page`, `page_size`), filterable (`category`, `level`, `search`) redacted audit log listing. |

## 3. Phase 2.1 Endpoints — Website-Centric Monitoring, Categories, Scanner & Content Library

All Phase 2.1 endpoints require an authenticated administrator session (`401` otherwise). All mutating endpoints enforce `X-CSRF-Token` validation (`403` otherwise). Legacy `/api/v1/brands` and `/api/v1/articles` namespaces have been removed cleanly in favor of website-centric `/websites` and `/contents`.

### Custom Website Categories (Managed under Settings)

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/website-categories` | Admin | No | Lists administrator-defined categories (`include_archived=false` by default) with live `website_count` totals. |
| `POST` | `/api/v1/website-categories` | Admin | **Yes** | Create a custom website category (`name`, optional `slug`, `description`, `sort_order`). |
| `GET` | `/api/v1/website-categories/{category_id}` | Admin | No | Retrieve single category details. |
| `PATCH` | `/api/v1/website-categories/{category_id}` | Admin | **Yes** | Rename, edit description/sort order, or archive/restore (`is_archived`). |
| `DELETE` | `/api/v1/website-categories/{category_id}` | Admin | **Yes** | Delete an unused category (`409 Conflict` if websites are still assigned). |

### Website Management, Merged Brand Profile, Sources & URL Rules

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/websites` | Admin | No | Paginated (`page`, `page_size`), filterable (`category_id`, `status`, `website_type`, `search`) list with merged brand profile & live content breakdown counts. |
| `POST` | `/api/v1/websites` | Admin | **Yes** | Register website directly without pre-creating a brand. Accepts full URL or bare domain, SSRF-validates, assigns optional `category_id`, and stores merged brand/language/SEO/crawl configuration (`crawl_batch_size`, `crawl_max_urls_per_run`, `single_source_only`). |
| `GET` | `/api/v1/websites/{website_id}` | Admin | No | Full website details, brand guidelines, schedule state, and content breakdown counts. |
| `PATCH` | `/api/v1/websites/{website_id}` | Admin | **Yes** | Partial update of website metadata, category assignment, brand guidelines, endpoints, crawl limits, or status. |
| `DELETE` | `/api/v1/websites/{website_id}` | Admin | **Yes** | Delete website (`409 Conflict` while discovered `website_contents` exist; set `status="archived"` instead). |
| `POST` | `/api/v1/websites/{website_id}/logo` | Admin | **Yes** | Multipart upload (`file`) for the website's brand logo (Pillow-validated, stored under `STORAGE_ROOT/images/`, saved as `website.logo_url`). |
| `POST` | `/api/v1/websites/{website_id}/test` | Admin | **Yes** | SSRF-hardened connectivity test returning HTTP status, final URL, page title, and detected CMS/framework (`website_type`). |
| `POST` | `/api/v1/websites/{website_id}/discover` | Admin | **Yes** | Multi-source auto-discovery across homepage links, `robots.txt` Sitemaps, RSS/Atom feeds, WordPress REST API, and `/llms.txt`. Pass `?apply=true` to persist discovered endpoints into `websites` & `website_discovery_sources`. |
| `GET` | `/api/v1/websites/{website_id}/sources` | Admin | No | Lists tracked discovery endpoints (`website_discovery_sources`) with per-endpoint ETag, Last-Modified, HTTP status, `last_urls_found`, and errors. |
| `PATCH` | `/api/v1/websites/{website_id}/sources/{source_id}` | Admin | **Yes** | Enable or disable an individual discovery endpoint (`is_enabled`). |
| `GET` | `/api/v1/websites/{website_id}/rules` | Admin | No | Lists website-specific URL classification/exclusion rules (`website_url_rules`). |
| `POST` | `/api/v1/websites/{website_id}/rules` | Admin | **Yes** | Add a custom URL classification rule (`pattern`, `match_mode` = `glob`/`prefix`/`exact`/`regex`, `target_content_type`, `priority`, `notes`). |
| `PATCH` | `/api/v1/websites/{website_id}/rules/{rule_id}` | Admin | **Yes** | Update an existing URL classification rule. |
| `DELETE` | `/api/v1/websites/{website_id}/rules/{rule_id}` | Admin | **Yes** | Delete a URL classification rule. |

### Website Scans & URL-Level Diagnostics

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `POST` | `/api/v1/websites/{website_id}/scan` | Admin | **Yes** | Enqueue non-blocking scan (`202 Accepted`). Optional JSON body `{ "scan_mode": "full" | "incremental" | "resume" | "retry_failed" | "discover_only", "max_urls", "batch_size" }`. |
| `GET` | `/api/v1/websites/{website_id}/scan-logs` | Admin | No | Paginated scan history with per-type counts (`homepage_count`, `page_count`, `blog_post_count`, `other_count`), `urls_pending_extraction`, `discovered_sitemaps`, and source completion/failure logs. |
| `GET` | `/api/v1/scans/{scan_id}` | Admin | No | Live scan progress (`status`: `pending`, `processing`, `completed`, `partially_completed`, `incomplete`, `paused`, `failed`, `cancelled`, plus `current_source` / `current_url`). |
| `GET` | `/api/v1/scans/{scan_id}/items` | Admin | No | Paginated per-URL discovery/extraction diagnostics (`status`, `failures_only=true`) showing exact HTTP status, failure reason, and error detail. |
| `POST` | `/api/v1/scans/{scan_id}/retry` | Admin | **Yes** | Enqueue a `resume` (when pending URLs remain) or `retry_failed` scan (`202 Accepted`). |

### Universal Content Library & Media Assets

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/contents/stats` | Admin | No | Live database tab counts (`total_discovered`, `homepage_count`, `page_count`, `blog_post_count`, `blog_index_count`, `other_count`, `pending_count`, `failed_count`, `updated_count`, `excluded_count`) filterable by `website_id` and `category_id`. |
| `GET` | `/api/v1/contents` | Admin | No | Paginated (`page`, `page_size`), filterable (`website_id`, `category_id`, `tab`, `content_type`, `extraction_status`, `language`, `tag_or_category`, `status`, `change_filter`, `search`, `include_excluded`, `sort_by`, `sort_dir`) listing of `website_contents` alongside live `stats`. |
| `GET` | `/api/v1/contents/{content_id}` | Admin | No | Full content record (`original_content`, `extracted_content`, `markdown_content`, `optimized_context`, `structured_data_json`, `classification_method`, `manual_classification_override`, `http_status`, `extraction_error`, hashes, media, revisions). |
| `PATCH` | `/api/v1/contents/{content_id}` | Admin | **Yes** | Manually reclassify `content_type` (sets `manual_classification_override=true` so scans never overwrite it), toggle `is_excluded`, update status, tags, categories, or language. |
| `POST` | `/api/v1/contents/{content_id}/reprocess` | Admin | **Yes** | SSRF-validated single-URL re-fetch and content-type-aware extraction, preserving `manual_classification_override`, updating failure status or creating a `content_revisions` snapshot on changes. |
| `GET` | `/api/v1/contents/{content_id}/revisions` | Admin | No | Chronological revision history (`content_revisions`) whenever extracted `content_hash` changes. |
| `GET` | `/api/v1/media` | Admin | No | Paginated (`page`, `page_size`), filterable by `website_id` listing of `media_assets`. |
| `GET` | `/api/v1/media/{media_id}` | Admin | No | Single media asset metadata. |
| `GET` | `/api/v1/media/{media_id}/file` | Admin | No | Streams locally stored image asset with validated `Content-Type` and strict path confinement. |

## 4. Planned Future API Namespaces (Phases 3–6)

- Phase 3: `/api/v1/ai/providers`, `/api/v1/ai/prompts`, `/api/v1/ai/usage`, `/api/v1/ai/generate` (Google Gemini API as sole AI generation provider)
- Phase 4: `/api/v1/accounts`, `/api/v1/social-posts`, `/api/v1/calendar`
- Phase 5: `/api/v1/editorial/keywords`, `/api/v1/editorial/topics`, `/api/v1/editorial/plans`, `/api/v1/editorial/articles`
- Phase 6: `/api/v1/automation/jobs`, `/api/v1/automation/rules`, `/api/v1/analytics`, `/api/v1/backups`
