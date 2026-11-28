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
| `GET` | `/api/v1/dashboard/summary` | Admin | No | Optional query params: `website_id`, `category_id`. Returns Phase 1 + Phase 2.1 counts (active websites, categories, total/extracted contents, homepage/page/game_page/blog_index/blog_post/other breakdown, failed/pending counts, completed/failed/incomplete scans), recent scans, infrastructure health, and explicit Phase 3–6 `not_implemented` modules. |

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
| `GET` | `/api/v1/contents/stats` | Admin | No | Live database tab counts (`total_discovered`, `homepage_count`, `page_count`, `game_page_count`, `blog_post_count`, `blog_index_count`, `other_count`, `pending_count`, `failed_count`, `updated_count`, `excluded_count`) filterable by `website_id` and `category_id`. |
| `GET` | `/api/v1/contents` | Admin | No | Paginated (`page`, `page_size`), filterable (`website_id`, `category_id`, `tab`, `content_type`, `extraction_status`, `language`, `tag_or_category`, `status`, `change_filter`, `search`, `include_excluded`, `sort_by`, `sort_dir`) listing of `website_contents` alongside live `stats`. |
| `GET` | `/api/v1/contents/{content_id}` | Admin | No | Full content record (`original_content`, `extracted_content`, `markdown_content`, `optimized_context`, `structured_data_json`, `classification_method`, `manual_classification_override`, `http_status`, `extraction_error`, hashes, media, revisions). |
| `PATCH` | `/api/v1/contents/{content_id}` | Admin | **Yes** | Manually reclassify `content_type` (sets `manual_classification_override=true` so scans never overwrite it), toggle `is_excluded`, update status, tags, categories, or language. |
| `POST` | `/api/v1/contents/{content_id}/reprocess` | Admin | **Yes** | SSRF-validated single-URL re-fetch and content-type-aware extraction, preserving `manual_classification_override`, updating failure status or creating a `content_revisions` snapshot on changes. |
| `GET` | `/api/v1/contents/{content_id}/revisions` | Admin | No | Chronological revision history (`content_revisions`) whenever extracted `content_hash` changes. |
| `GET` | `/api/v1/media` | Admin | No | Paginated (`page`, `page_size`), filterable by `website_id` listing of `media_assets`. |
| `GET` | `/api/v1/media/{media_id}` | Admin | No | Single media asset metadata. |
| `GET` | `/api/v1/media/{media_id}/file` | Admin | No | Streams locally stored image asset with validated `Content-Type` and strict path confinement. |

## 4. Phase 3 Endpoints — Social Profiles, Gemini AI Engine & Draft Management

All Phase 3 endpoints require an authenticated administrator session (`401` otherwise) and CSRF validation on mutations (`403` otherwise).

### Platforms & Website-Owned Social Profiles

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/platforms` | Admin | No | Lists enabled platform capabilities (char limits, X 23-char URL counting rule, credential field definitions). |
| `GET` | `/api/v1/social-profiles` | Admin | No | Lists all social destination profiles, optionally filtered by `website_id`. Returns masked credentials (`Cache-Control: no-store`). |
| `GET` | `/api/v1/websites/{website_id}/social-profiles` | Admin | No | Lists all configured social profiles belonging to a website (multiple per platform supported). |
| `POST` | `/api/v1/websites/{website_id}/social-profiles` | Admin | **Yes** | Create a manual or API-ready social profile under a website (`201 Created`; `auto_publish_enabled=true` rejected `422`). |
| `GET` | `/api/v1/social-profiles/{profile_id}` | Admin | No | Fetch single social profile with masked credential status. |
| `PATCH` | `/api/v1/social-profiles/{profile_id}` | Admin | **Yes** | Update profile rules, language, hashtags/CTA/instructions, or selectively update/clear Fernet credentials. |
| `DELETE` | `/api/v1/social-profiles/{profile_id}` | Admin | **Yes** | Delete a social profile (`409` if blocked or cascades cleanup per constraints). |

### Gemini Provider Configuration, Testing & Models

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/ai/providers` | Admin | No | Lists saved Gemini configurations with masked API keys (`Cache-Control: no-store`) and billing disclaimer. |
| `POST` | `/api/v1/ai/providers` | Admin | **Yes** | Create Gemini provider config (`201 Created`); API key encrypted at rest via Fernet; `allow_paid_fallback` locked `false`. |
| `PATCH` | `/api/v1/ai/providers/{provider_id}` | Admin | **Yes** | Update selected model, temperature, quotas, toggles, default status, or replace/clear API key. |
| `POST` | `/api/v1/ai/providers/{provider_id}/test` | Admin | **Yes** | Tests Gemini connectivity (and optional live probe if `verify_generation=true`), sanitizing any API errors. |
| `GET` | `/api/v1/ai/providers/{provider_id}/models` | Admin | No | Lists/refreshes (`refresh=true`) compatible Gemini models ranked Flash-Lite / Flash first. |

### Website Knowledge Profiles & Sandboxed Prompt Manager

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/websites/{website_id}/knowledge-profile` | Admin | No | Retrieve website knowledge profile, per-field provenance, manual overrides, and live `is_outdated` status. |
| `PATCH` | `/api/v1/websites/{website_id}/knowledge-profile` | Admin | **Yes** | Save manual overrides (`admin` provenance) and optionally approve (`approve=true`), creating a version snapshot. |
| `POST` | `/api/v1/websites/{website_id}/knowledge-profile/generate` | Admin | **Yes** | Synthesize compact knowledge profile via Gemini (`preserve_manual_overrides=true` default). |
| `GET` | `/api/v1/websites/{website_id}/knowledge-profile/revisions` | Admin | No | Version history snapshots for a website knowledge profile. |
| `GET` | `/api/v1/ai/prompts` | Admin | No | List Jinja2 prompt templates (filterable by `task_type`, `website_id`, `social_profile_id`). |
| `POST` | `/api/v1/ai/prompts` | Admin | **Yes** | Create custom scoped prompt template (`201 Created`; validates against `ALLOWED_PROMPT_VARIABLES` & dunder rules). |
| `PATCH` | `/api/v1/ai/prompts/{prompt_id}` | Admin | **Yes** | Update prompt instructions/body cleanly, incrementing version & appending a revision snapshot. |
| `POST` | `/api/v1/ai/prompts/{prompt_id}/preview` | Admin | **Yes** | Render prompt offline against real/sample website content with ZERO Gemini API calls (`estimated_input_tokens`). |
| `GET` | `/api/v1/ai/prompts/{prompt_id}/revisions` | Admin | No | Prompt revision history. |

### Content Destination Resolution, Generation Jobs, Usage, Cache & Draft Queue

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/contents/{content_id}/social-destinations` | Admin | No | Preview automatically selected active, generation-enabled social profiles (or friendly empty-profile guard message). |
| `POST` | `/api/v1/contents/{content_id}/generate-social` | Admin | **Yes** | Enqueue background social generation job (`202 Accepted`; zero platform selection parameters needed). |
| `GET` | `/api/v1/contents/{content_id}/social-posts` | Admin | No | List social drafts generated from a specific `website_contents` item. |
| `GET` | `/api/v1/ai/jobs` / `GET /api/v1/ai/jobs/{job_id}` | Admin | No | Inspect MySQL AI background generation jobs (`queued`, `processing`, `deferred`, `completed`, `partially_completed`, `failed`, `cancelled`). |
| `POST` | `/api/v1/ai/jobs/{job_id}/retry` / `.../cancel` | Admin | **Yes** | Re-queue failed/deferred job (`202`) or cancel an active/deferred job. |
| `GET` | `/api/v1/ai/usage` | Admin | No | Daily/monthly usage, measured vs `unknown` tokens, cache hit rate, quota status, and website/model/task breakdowns (`estimated_cost_usd_month` remains `null`). |
| `GET` | `/api/v1/ai/history` / `GET /api/v1/ai/history/export` | Admin | No | Filterable invocation log list and UTF-8 CSV download. |
| `GET` | `/api/v1/ai/cache/stats` / `POST /api/v1/ai/cache/invalidate` | Admin | No / **Yes** | Inspect cached SHA-256 responses and selectively invalidate expired, website-scoped, or selected entries. |
| `GET` | `/api/v1/social-posts` / `GET /api/v1/social-posts/{post_id}` | Admin | No | Filterable (`website_id`, `social_profile_id`, `platform_id`, `status`, `website_content_id`) draft queue with live status tab totals. |
| `PATCH` | `/api/v1/social-posts/{post_id}` | Admin | **Yes** | Manually edit caption/title/hashtags/CTA, recalculate `assembled_content` & platform-aware char count, mark `is_manually_edited=true`, and add a revision. |
| `POST` | `/api/v1/social-posts/{post_id}/{approve|reject|archive}` | Admin | **Yes** | Review status transitions (note: live external `/publish` remains unimplemented until Phase 4). |
| `POST` | `/api/v1/social-posts/{post_id}/regenerate` | Admin | **Yes** | Enqueue targeted single-draft regeneration (`202 Accepted`) preserving prior manual/AI revisions. |
| `GET` | `/api/v1/social-posts/{post_id}/revisions` | Admin | No | Draft version history snapshots. |

### Content Approval, Inline SEO Keyword Mapping & Reusable Keyword Map

| Method | Path | Auth | CSRF | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/content-approvals` | Admin | No | Paginated review queue (`awaiting_extraction`, `pending_review`, `needs_rereview`, `approved`, `rejected`) with stats & cannibalization counts. |
| `GET` | `/api/v1/content-approvals/stats` | Admin | No | Queue totals (website/category filterable) used for Dashboard & Sidebar live notification badge. |
| `GET` | `/api/v1/content-approvals/{content_id}` | Admin | No | Full review detail with extracted content, YAKE terms, cannibalization warnings, keyword revisions & approval audit history. |
| `PATCH` | `/api/v1/content-approvals/{content_id}/keywords` | Admin | **Yes** | Edit focus keyphrase, secondary keywords, anchor variations, image alt suggestions & content classification; increments keyword version & locks from scan overwrite. |
| `POST` | `/api/v1/content-approvals/{content_id}/keywords/suggest-ai` | Admin | **Yes** | Optional admin-triggered Gemini SEO refinement (never auto-called per URL during scans; never fabricates volume/CPC/KD/ranking). |
| `POST` | `/api/v1/content-approvals/{content_id}/approve` | Admin | **Yes** | Approve extracted content + keywords, accepting inline keyword & content-type edits in the same action; triggers auto social draft generation **once** for newly published non-baseline blog posts. |
| `POST` | `/api/v1/content-approvals/bulk-approve` | Admin | **Yes** | Bulk approve selected extracted records with optional per-item inline overrides. |
| `POST` | `/api/v1/content-approvals/{content_id}/reject` | Admin | **Yes** | Reject content cleanly (blocks AI generation and prevents repeated approval prompts on unchanged rescans). |
| `POST` | `/api/v1/content-approvals/{content_id}/reopen` | Admin | **Yes** | Return item to `needs_rereview`. |
| `GET` | `/api/v1/content-approvals/keyword-map` | Admin | No | Website/type/search filterable Keyword Map overview with cannibalization conflict counts. |
| `GET` | `/api/v1/content-approvals/websites/{website_id}/approved-keywords` | Admin | No | Reusable `KeywordReuseService` endpoint returning approved `{website_id, content_id, canonical_url, title, content_type, focus_keyphrase, secondary_keywords, anchor_text_variations, approval_status}`. |

## 5. Planned Future API Namespaces (Phases 4–6)

- Phase 4: External publishing adapters, OAuth callbacks, `/api/v1/calendar`
- Phase 5: `/api/v1/editorial/keywords`, `/api/v1/editorial/topics`, `/api/v1/editorial/plans`, `/api/v1/editorial/articles`
- Phase 6: `/api/v1/automation/jobs`, `/api/v1/automation/rules`, `/api/v1/analytics`, `/api/v1/backups`
