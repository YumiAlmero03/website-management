# ContentHub AI — Development Roadmap

Development proceeds strictly one phase at a time. Each phase ends with validation and Engineering Lead review before advancing.

---

## Phase 1 — Project Foundation *(Completed)*
- Monorepo documentation (`AGENTS.md`, `README.md`, `docs/*`), `.gitignore`, `.env.example`
- Nuxt 4 + TypeScript + Tailwind CSS v4 + Nuxt UI v4 + Pinia + Lucide Icons
- FastAPI + SQLAlchemy 2 + PyMySQL + Alembic + Argon2id + Fernet + `psutil`
- Initial MySQL migration (`20261126_0001`: `users`, `sessions`, `application_settings`, `activity_logs`)
- Single-administrator CLI initializer (`init-admin`) and DB checker (`check-db`)
- Secure login/logout, session cookies, CSRF protection, login rate limiting, protected routes

## Phase 2.1 — Website-Centric Refinement, Aggregated Discovery & Classifier *(Completed — Ready for Review)*
- Merged Brand identity & guidelines directly into Website Management (`websites` table; removed separate `/brands` sidebar/routes/API; kept global website selector; moved `media_assets` ownership to `website_id`)
- Administrator-defined Custom Website Categories under Settings (`website_categories` CRUD, archive, delete-when-unused guard, inline category creation)
- Simplified 5-field Register Website flow with expandable Advanced Settings (`website_type`, brand voice, custom endpoints, `crawl_batch_size`, `crawl_max_urls_per_run`, `single_source_only`)
- Fixed scanner bugs: replaced first-success-only discovery with true multi-source aggregation (`WebsiteDiscoveryManager`), isolated per-endpoint `ETag`/`Last-Modified` in `website_discovery_sources` (304 no longer drops items or halts sitemaps), supported recursive/custom `.php`/`.xml.gz` sitemaps detected by XML body, lifted 100-URL truncation via two-phase discovery (`website_scan_items`) + resumable batched extraction (`Discover URLs`, `Full Scan`, `Check New Content`, `Retry Failed URLs`, `Resume Incomplete Scan`)
- Deterministic URL classifier (`website_url_rules` + `classifier.py`) supporting `homepage`, `page`, `blog_index`, `blog_post`, `category`, `tag`, `archive`, `custom` + manual override pinning
- Redesigned Universal Content Library (`/content-library` -> `/api/v1/contents`) with 7 live-count tabs, per-URL failure inspection/retry, and 5-tab Website Detail Workspace (`/websites/[id]`)

## Phase 3 — Gemini AI Engine *(Next)*
- Official Google Gen AI SDK provider configuration as the **sole** AI generation provider (encrypted API keys, dynamic model listing & availability check)
- Python-first Token Optimization Engine (clean Markdown, extractive summarization, compact structured context)
- Prompt Template management & structured Pydantic JSON output validation
- MySQL `ai_response_cache` keyed by model, prompt version, settings, brand instructions, and source hash
- Daily request/token quota guard (no automatic fallback to paid tiers) and token usage reporting
- Multi-platform social caption generation in batched requests

## Phase 4 — Social Media Publishing
- Social Post editor (captions, variants, hashtags, UTM builder, character limits, language & brand guidelines)
- Modular Publisher Adapter interface + Priority 1 integrations: Facebook Pages Graph API & Manual Publishing fallback
- Post approval workflow (Manual / Semi-automatic default / Automatic rules)
- FullCalendar Standard Publishing Calendar (Month/Week/Day, drag-and-drop rescheduling, UTC storage -> `Asia/Manila` display)
- Publishing history & status verification

## Phase 5 — Editorial Planner & Article Editor
- Keyword research & Google Search Console / Google Trends RSS integration
- Content gap analysis, topic clustering, content pillars, weekly/monthly editorial plans
- Topic-first approval workflow before outline or full article generation
- Tiptap free/open-source Article Editor with configurable non-blocking SEO guideline warnings, revisions, and Markdown/HTML/JSON export
- Priority 1 article publishers: WordPress REST API & Blogger API (+ manual fallback)

## Phase 6 — Automation, Resource Guardian & Analytics
- MySQL persistent job queue (`publishing_jobs`, `scheduled_tasks`) with transactional claiming, idempotency keys, retries, backoff, heartbeats, stale job recovery, and ambiguous publish verification
- Separate Python background worker (`backend/workers/`) supervised by Supervisor
- Active Resource Guardian enforcement via `psutil`
- Automated daily database backups with retention policy
- Analytics module (distinguishing measured data from estimates/unavailable metrics) and Chart.js visualizations

## Phase 7 — QA, Security and Deployment
- Expanded automated, security, SSRF, and resource-pressure test suites
- Production `deploy/` configs (`nginx.conf`, `supervisor.conf`, `ecosystem.config.cjs`)
- Non-destructive `scripts/` (`setup.sh`, `deploy.sh`, `cron.sh`, `backup.sh`, `restore.sh`, `health-check.sh`)
- End-to-end backup/recovery drills and aaPanel rollout verification
