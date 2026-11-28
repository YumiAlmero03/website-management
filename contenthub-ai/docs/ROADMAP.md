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
- Deterministic URL classifier (`website_url_rules` + `classifier.py`) supporting `homepage`, `page`, `game_page`, `blog_index`, `blog_post`, `category`, `tag`, `archive`, `custom` + manual override pinning
- Redesigned Universal Content Library (`/content-library` -> `/api/v1/contents`) with 7 live-count tabs, per-URL failure inspection/retry, and 5-tab Website Detail Workspace (`/websites/[id]`)

## Phase 3 — Gemini AI Engine and Social Profile Management *(Completed — Ready for Review)*
- Official `google-genai` SDK integration (`ai_providers`) with Fernet-encrypted API keys, connection/probe tests, dynamic model refresh ranked Flash/Flash-Lite first, and zero silent paid fallback
- Website-owned Social Profiles (`platforms`, `social_profiles`) supporting multiple profiles per platform per website, manual vs API readiness modes (`auto_publish_enabled` locked `false`), and dynamic Fernet-encrypted credentials
- Reusable Website Knowledge Profiles (`website_knowledge_profiles` + revisions) synthesized from compact prioritized core pages with admin override preservation, field provenance, and stale fingerprinting
- Prompt Manager (`prompt_templates` + revisions) using restricted Jinja2 `SandboxedEnvironment`, explicit `ALLOWED_PROMPT_VARIABLES`, offline prompt preview without Gemini calls, and multi-tier scope precedence
- Python-first Token Optimization (`metadata_only` / `optimized` / `full`) and website-scoped SHA-256 `ai_response_cache`, paired with `ai_generation_jobs`, `ai_generation_logs`, CLI workers (`run-ai-job`, `run-pending-ai-jobs`), Resource Guardian protection, and post-baseline `blog_post` auto-scan generation hooks
- Multi-profile Social Draft Management (`social_posts`, `social_post_revisions`, `/social-media`, `/ai-management`, and 7-tab `/websites/[id]`) with zero manual platform checkboxes during generation, platform-aware length checks (X 23-char URL counting), edit/approve/reject/archive/regenerate workflows, and copy/download media helpers
- SEO Keyword Mapping & Content Approval Gate (`20261127_0005` — `content_keywords`, `content_approvals`, `/content-approval`, Keyword Map, `KeywordReuseService`, cannibalization detection): Python-first focus/secondary/anchor/image-alt suggestions, inline keyword editing during approval, single & bulk approve/reject/reopen workflows preserving approved keywords across scans, and automatic social generation strictly gated on approved post-baseline content & keywords

### Phase 3 Acceptance Criteria
- Newly discovered homepages, pages, game pages, and blog posts automatically enter the Content Approval queue (`awaiting_extraction` → `pending_review`) with Python-extracted focus keyphrase, secondary keywords, clickable link anchor variations, and factual image alt suggestions (never auto-approved; zero Gemini calls required per URL; zero fabricated search metrics).
- Administrators can review URL, extracted content preview, meta description, publication/discovery dates, and edit content classification, focus keyphrase, secondary keywords, anchors, and image alt text inline via always-open text boxes in `/content-approval` (without an Edit toggle) and `/content-library/[id]`.
- Approved keywords remain locked (`is_admin_locked`) across subsequent website scans, unchanged duplicates do not create duplicate approval requests, rejected URLs stay excluded from AI generation & unchanged rescans, and meaningful content updates transition to `needs_rereview`.
- Non-blocking cannibalization warnings highlight same-website focus keyphrase overlaps without auto-deleting/merging; `KeywordReuseService` serves approved mappings (`website_id`, `content_id`, `canonical_url`, `title`, `content_type`, `focus_keyphrase`, `secondary_keywords`, `anchor_text_variations`, `approval_status`).
- Automatic social draft generation runs **once** only when website auto-generation is active, social profiles are eligible, and newly published non-baseline `blog_post` content and keywords are both approved, injecting approved keywords/links into prompts & cache fingerprints while preserving already approved drafts.

## Phase 4 — Social Media Publishing *(Next)*
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
