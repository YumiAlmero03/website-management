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

## Phase 2 — Website Monitoring *(Completed — Ready for Review)*
- Incremental MySQL migration (`20261126_0002`: `brands`, `media_assets`, `websites`, `source_articles`, `source_article_revisions`, `website_scan_logs` + InnoDB `FULLTEXT`)
- Brand Management CRUD (multi-language, logo upload, keywords, hashtags, CTA, safe deletion guard)
- Website Management CRUD (7 website types, URL include/exclude patterns, connectivity test, auto-discovery, baseline modes)
- SSRF-hardened Website Scanner (REST -> WordPress -> RSS/Atom -> XML Sitemap/Index -> `llms.txt` -> HTML -> optional Playwright fallback)
- Python-first Content Extraction (Trafilatura + BS4, Markdownify, YAKE keywords, extractive token optimization prep, SHA-256 + RapidFuzz duplicate checks, revision history, Pillow media validation)
- Non-blocking durable scan executor, stale scan recovery, Resource Guardian integration, `run-scan` & `run-due-scans` CLI commands
- Live Brands, Websites, Scan Monitor, Content Library, Global Selectors, and updated Dashboard UI

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
