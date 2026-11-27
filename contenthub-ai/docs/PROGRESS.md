# ContentHub AI — Development Progress Tracker

## Current Phase
- **Active Phase:** Phase 2.1 — Website Management Refinement & Scanner Bug Fixes
- **Status:** Complete — Ready for Review (stopped before Phase 3 per administrator instruction)
- **Last Updated:** 2026-11-27

## Completed Tasks
### Phase 1 — Project Foundation
- Nuxt 4 + TypeScript + Tailwind v4 + Nuxt UI v4 + Pinia + Lucide Icons, FastAPI + SQLAlchemy 2 + PyMySQL + Alembic (`20261126_0001`), Argon2id auth, SHA-256 sessions, CSRF, login rate limit, Fernet encryption, redaction, `check-db` & `init-admin` CLI, Dashboard/Health/Logs/Settings pages.

### Phase 2 & Phase 2.1 — Website-Centric Monitoring, Discovery & Universal Content Library
- **Merged Brand into Website Management:** Removed standalone `/brands` module, global brand selector, and `brands` table via incremental reversible Alembic migration `20261127_0003`. Each `Website` owns `brand_name`, `brand_slug`, `logo_url`, language profile, tone, keywords, hashtags, CTA, writing guidelines, and AI instructions, while retaining the global topbar website selector and moving `media_assets` ownership to `website_id`.
- **Custom Website Categories (`website_categories`):** Added Settings-managed CRUD, archiving, unused-only delete protection, initial 8 seeded categories (`Sports Web`, `Casino`, `Brand`, `Illegal Brand`, `Technology`, `E-commerce`, `News`, `Other`), inline `+ New Category` in Website Registration, and category filtering across Websites, Content Library, and Dashboard.
- **Simplified Registration & 5-Tab Website Workspace:** Reduced default Register Website form to 5 essential fields (`Website Name`, `Brand Name`, `Website URL`, `Category`, `Primary Language`) with expandable Advanced Settings; built 5-tab `/websites/[id]` workspace (`Overview`, `Content`, `Scanner & URL Rules`, `Scan History`, `Settings & Brand Profile`) with 5 scan actions (`Discover URLs`, `Full Scan`, `Check New Content`, `Retry Failed URLs`, `Resume Incomplete Scan`) and URL-level failure/exclusion diagnostics (`/api/v1/scans/{id}/items`).
- **Fixed Incomplete Discovery & Caching Bugs:** Refactored `WebsiteDiscoveryManager` to aggregate across all enabled sources (Homepage links, WordPress REST, custom REST, RSS/Atom, `robots.txt` Sitemaps, recursive `.xml`/`.php`/`.xml.gz` sitemaps detected by XML body, `llms.txt`, blog indexes, and optional Playwright fallback) and isolated `ETag` / `Last-Modified` headers per endpoint in `website_discovery_sources` so a 304 on one feed preserves existing items and never halts other sources.
- **Lifted 100-URL Limit with Two-Phase Resumable Batching:** Separated discovery (persisting ALL URLs into `website_scan_items` + `website_contents` up to 20,000) from extraction (configurable `crawl_batch_size` + `crawl_max_urls_per_run`, marking exceeded runs `incomplete` with `urls_pending_extraction` for clean continuation via `Resume Incomplete Scan`).
- **Deterministic URL Classification & Universal Content Library:** Added `website_url_rules` + `classifier.py` (`homepage`, `page`, `blog_index`, `blog_post`, `category`, `tag`, `archive`, `custom`) with specificity ordering, JSON-LD/OG evidence fallback, content-type-aware extraction, failed URL retention + retry, manual override pinning (`manual_classification_override`), and rebuilt `/content-library` -> `/api/v1/contents` with 7 live-count tabs (`All Content`, `Homepage`, `Pages`, `Blog Posts`, `Blog Indexes`, `Other`, `Failed Extraction`).
- **Updated Documentation & Mermaid Diagrams:** Updated `README.md`, `.env.example`, `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE.md`, `docs/ROADMAP.md`, and `docs/PROGRESS.md` while keeping historical migrations `20261126_0001` & `20261126_0002` unmodified.

## Pending Tasks
- Owner approval to run `alembic upgrade head` (`20261127_0003`) on dev DB `contenthub_ai` on `127.0.0.1:3309` (migration verified on isolated `contenthub_ai_test` preserving real `Bygame Casino` / `bygame.ph` sample rows with zero data loss).
- Engineering Lead review & sign-off of Phase 2.1 before proceeding to **Phase 3 — Gemini AI Engine**.

## Known Bugs
- None remaining in verified Phase 2.1 scope.

## Architectural Decisions
1. **Non-Destructive Incremental Schema Evolution (`20261127_0003`):** Migrates existing `brands`, `websites`, `media_assets`, `source_articles`, and `source_article_revisions` data in-place into website-centric `websites`, `website_contents`, and `content_revisions` while cleaning legacy default taxonomy exclusions cleanly.
2. **Per-Endpoint HTTP Conditional State (`website_discovery_sources`):** Decouples ETags/Last-Modified across homepage, feeds, sitemaps, child sitemaps, and APIs so partial 304 responses never erase or short-circuit multi-source discovery.
3. **Zero AI Calls in Phase 2.1:** Classification and content extraction remain 100% deterministic Python (`classifier.py`, Trafilatura, BeautifulSoup4, YAKE, RapidFuzz, Markdownify).

## Testing & Verification Results (2026-11-27)
- **Backend Lint (`cd backend && .venv/bin/ruff check .`):** Passed (`All checks passed!`, 0 errors).
- **Backend Test Suite (`cd backend && .venv/bin/pytest -v`):** **53 passed, 0 failed, 0 skipped** — covers all Phase 1 tests, Website Categories CRUD + delete guard, Website registration + SSRF literal IP blocking + logo upload + URL classification rules, all 22 Phase 2.1 regression scenarios (`test_phase2_1_regression.py` including RSS+Sitemap aggregation, 304 isolation, multiple/custom `.php`/nested/`.xml.gz` sitemaps, 160-URL and 1,050-URL resumable batched scanning, homepage/page/blog_index/blog_post/category/tag/archive classification, manual override preservation, metadata-less pages, failure retention+retry, 7-tab library stats, exact scan count reconciliation, revisions), AND live MySQL `8.0.45` Phase 2->2.1 data-preserving Alembic migration/downgrade/re-upgrade + repository CRUD on isolated `contenthub_ai_test`.
- **Frontend Typecheck (`cd frontend && npm run typecheck`):** Passed (0 TypeScript errors).
- **Frontend Unit Tests (`cd frontend && npm test`):** Passed (4 test files, 8 tests — `navigation`, `ui-store`, `auth-store`, `format`).
- **Frontend Production Build (`cd frontend && npm run build`):** Passed (`✨ Build complete!`).
- **Runtime SSR + Proxied End-to-End Smoke Test (Isolated `:8105` FastAPI + `:3105` Built Nuxt -> `contenthub_ai_test`):** Passed (`LIVE_NUXT_PROXY_SMOKE_ALL_PASSED`: verified unauthenticated redirects, `404` on legacy `/brands` and `/api/v1/brands` & `/api/v1/articles`, authenticated SSR rendering, Category & Website creation without live outbound DNS lookup, URL rule creation, Content Library tabs, scan failure inspection, manual reclassification, and cleanup).
- **Chrome DevTools Interactive Browser Limitation:** `chrome-devtools` MCP connection returned `DevToolsActivePort` ENOENT (remote debugging not enabled in local Chrome profile); automated runtime UI SSR + proxy CRUD flow verified via HTTP smoke suite against the built Nuxt server instead.
