# ContentHub AI — REST API Specification

## 1. Conventions

- **Base Path:** `/api/v1`
- **Format:** JSON (`application/json`), UTF-8.
- **Timestamps:** ISO 8601 UTC (`2026-11-26T10:30:00Z`).
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
| `GET` | `/api/v1/health` | Public | No | Lightweight liveness check (`status`, `app_name`, `version`, `environment`, `timestamp`). Does not expose DB credentials or host metrics. |
| `GET` | `/api/v1/health/db` | Admin | No | Live MySQL connectivity check, server version, InnoDB/`utf8mb4` verification, round-trip latency, and connection pool configuration. |
| `GET` | `/api/v1/health/system` | Admin | No | Combined application health, MySQL diagnostics, `psutil` CPU/RAM/Load/Disk metrics, Resource Guardian status (`normal`/`warning`/`critical`), and storage path writability. |

### Administrator Authentication

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/auth/status` | Public | No | Returns `{ "admin_initialized": bool, "authenticated": bool, "app_name": str }` so the login UI can show CLI initialization guidance before the first admin exists without revealing credentials. |
| `POST` | `/api/v1/auth/login` | Public (Rate-limited) | No | Validates email + password against Argon2id hash, creates hashed MySQL session, sets `HttpOnly` session cookie, returns `{ "user", "csrf_token", "expires_at" }`. |
| `GET` | `/api/v1/auth/me` | Admin | No | Returns current authenticated administrator, active session `csrf_token`, and `expires_at`. |
| `POST` | `/api/v1/auth/logout` | Admin | **Yes** | Revokes server-side session in MySQL, clears session cookie, records audit event. |

### Dashboard

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/dashboard/summary` | Admin | No | Optional query params: `brand_id`, `website_id`. Returns real Phase 1 + Phase 2 counts (brands, monitored websites, indexed articles, active/failed scans, articles updated in 24h, active sessions, settings, activity logs), recent scans, live database & server resource health, recent activity logs, and explicit `not_implemented` readiness descriptors for Phases 3–6. |

### Application Settings

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/settings` | Admin | No | Returns all configurable application settings grouped by category (`general`, `publishing`, `resource_guardian`, `seo`, `backups`), masking secret values (`has_value` flag only). |
| `PUT` | `/api/v1/settings` | Admin | **Yes** | Validates and upserts setting updates, encrypting secret entries via Fernet, and writes a redacted audit entry to `activity_logs`. |

### Activity Logs

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/logs/activity` | Admin | No | Paginated (`page`, `page_size`), filterable (`category`, `level`, `search`) listing of redacted `activity_logs` ordered newest-first. |

## 3. Phase 2 Endpoints — Website Monitoring, Content Library & Media

All Phase 2 endpoints require an authenticated administrator session (`401` otherwise). All mutating endpoints (`POST`, `PATCH`, `DELETE`) additionally enforce `X-CSRF-Token` validation (`403` otherwise).

### Brand Management

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/brands` | Admin | No | Paginated (`page`, `page_size`), filterable (`search`, `is_active`, `language`) list of brands with website and article counts. |
| `POST` | `/api/v1/brands` | Admin | **Yes** | Create a brand with language profile (English, Filipino, Taglish, pt-BR, etc.), target audience, tone, keywords, hashtags, CTA, writing guidelines, and AI instructions. Auto-generates unique slug when omitted. |
| `GET` | `/api/v1/brands/{brand_id}` | Admin | No | Retrieve full brand details and counts. |
| `PATCH` | `/api/v1/brands/{brand_id}` | Admin | **Yes** | Partial update of brand metadata, status, or guidelines. |
| `DELETE` | `/api/v1/brands/{brand_id}` | Admin | **Yes** | Delete brand. Blocked with `409 Conflict` while associated websites exist (`ON DELETE RESTRICT`); deactivate via `PATCH` (`is_active: false`) instead. |
| `POST` | `/api/v1/brands/{brand_id}/logo` | Admin | **Yes** | Multipart upload (`file`) for brand logo. Validated via Pillow (magic bytes, dimensions, size limit), stored under `STORAGE_ROOT/images/`, deduplicated by SHA-256, and linked to `media_assets` + `brands.logo_url`. |

### Website Management & Discovery

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/websites` | Admin | No | Paginated (`page`, `page_size`), filterable (`brand_id`, `status`, `website_type`, `search`) list of websites with brand info, article counts, and latest scan status. |
| `POST` | `/api/v1/websites` | Admin | **Yes** | Register a website under a brand. Validates SSRF-safe domain/URLs, `website_type` (`wordpress`, `nuxt`, `nextjs`, `custom_php`, `static_html`, `other_cms`, `custom_rest_api`), `discovery_method` (`auto`, `rest_api`, `wordpress`, `rss`, `sitemap`, `llms_txt`, `html`, `playwright`), `baseline_mode` (`import_existing`, `after_date`, `latest_n`, `new_only`), include/exclude URL glob patterns, and scan schedule. |
| `GET` | `/api/v1/websites/{website_id}` | Admin | No | Retrieve website configuration, article count, and schedule timestamps. |
| `PATCH` | `/api/v1/websites/{website_id}` | Admin | **Yes** | Partial update of website settings, URL patterns, endpoints, baseline settings, auto-scan flag, or schedule interval. |
| `DELETE` | `/api/v1/websites/{website_id}` | Admin | **Yes** | Delete a website. Blocked with `409 Conflict` while associated `source_articles` exist (`ON DELETE RESTRICT`); archive via `PATCH` (`status: "archived"`) instead. |
| `POST` | `/api/v1/websites/{website_id}/test` | Admin | **Yes** | SSRF-hardened connectivity test probing domain reachability, HTTP status, final URL, page title, and detected website type. |
| `POST` | `/api/v1/websites/{website_id}/discover` | Admin | **Yes** | Non-destructive source auto-discovery inspecting HTML `<link>` tags, `robots.txt`, `/wp-json/wp/v2/posts`, common RSS/sitemap paths, and `/llms.txt`. Pass query parameter `?apply=true` to persist discovered endpoints. |

### Website Scans & Scan History

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `POST` | `/api/v1/websites/{website_id}/scan` | Admin | **Yes** | Non-blocking scan trigger (`202 Accepted`). Enforces single active scan per website (`409 Conflict` if already `pending` or `processing`), inserts a durable `website_scan_logs` row (`status=pending`), and spawns detached worker `python -m app.cli run-scan --scan-id <id>`. |
| `GET` | `/api/v1/websites/{website_id}/scan-logs` | Admin | No | Paginated (`page`, `page_size`) scan history for a website ordered newest-first. |
| `GET` | `/api/v1/scans/{scan_id}` | Admin | No | Live scan progress and status (`pending`, `processing`, `completed`, `partially_completed`, `failed`, `cancelled`) including `urls_found`, `articles_processed`, `new_articles`, `updated_articles`, `unchanged_articles`, `skipped_articles`, `failed_articles`, `duration_ms`, and `error_message`. |
| `POST` | `/api/v1/scans/{scan_id}/retry` | Admin | **Yes** | Re-queues a `failed` or `partially_completed` scan as a new durable `website_scan_logs` execution (`202 Accepted`) if no scan is currently active for that website. |

### Content Library & Article Revisions

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/articles` | Admin | No | Server-side paginated (`page`, `page_size`), filterable (`brand_id`, `website_id`, `language`, `category`, `status`, `date_from`, `date_to`, `search`, `change_filter`) listing of extracted `source_articles`. |
| `GET` | `/api/v1/articles/{article_id}` | Admin | No | Full article detail including `original_content` (XSS-sanitized), `markdown_content`, `optimized_context`, YAKE `keywords`, `categories`, `tags`, `word_count`, `url_hash`, `content_hash`, advisory near-duplicate link/score, featured media summary, and `revision_count`. |
| `GET` | `/api/v1/articles/{article_id}/revisions` | Admin | No | Chronological revision history (`source_article_revisions`) showing prior snapshots whenever `content_hash` changed across rescans. |
| `POST` | `/api/v1/articles/{article_id}/reprocess` | Admin | **Yes** | Re-fetches (SSRF-validated) and re-extracts the article's canonical URL using Trafilatura/BeautifulSoup, updating content/markdown/context/keywords and creating a new revision snapshot if `content_hash` changed. |
| `PATCH` | `/api/v1/articles/{article_id}` | Admin | **Yes** | Update article status (`discovered`, `extracted`, `optimized`, `updated`, `archived`, `error`), `categories`, `tags`, or `language`. |

### Media Assets

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/media` | Admin | No | Paginated (`page`, `page_size`), filterable (`brand_id`) listing of `media_assets`. |
| `GET` | `/api/v1/media/{media_id}` | Admin | No | Metadata details for a single media asset (`file_name`, `file_path`, `source_url`, `mime_type`, `file_size`, `width`, `height`, `alt_text`, `checksum`). |
| `GET` | `/api/v1/media/{media_id}/file` | Admin | No | Streams locally stored image asset (`file_path`) with validated `Content-Type`, global `X-Content-Type-Options: nosniff` header, and strict path-traversal confinement within `STORAGE_ROOT`. Returns `404` for `url_only` assets without a local file. |

## 4. Planned Future API Namespaces (Phases 3–6)

- Phase 3: `/api/v1/ai/providers`, `/api/v1/ai/prompts`, `/api/v1/ai/usage`, `/api/v1/ai/generate` (Google Gemini API as the sole AI generation provider)
- Phase 4: `/api/v1/accounts`, `/api/v1/social-posts`, `/api/v1/calendar`
- Phase 5: `/api/v1/editorial/keywords`, `/api/v1/editorial/topics`, `/api/v1/editorial/plans`, `/api/v1/editorial/articles`
- Phase 6: `/api/v1/automation/jobs`, `/api/v1/automation/rules`, `/api/v1/analytics`, `/api/v1/backups`
