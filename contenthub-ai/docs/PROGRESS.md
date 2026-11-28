# ContentHub AI — Development Progress Tracker

## Current Phase
- **Active Phase:** Phase 3 — Gemini AI Engine, Social Profiles & SEO Content Approval
- **Status:** Complete — Ready for Review (stopped before Phase 4 per administrator instruction)
- **Last Updated:** 2026-11-27

## Completed Tasks
### Phase 1 — Project Foundation
- Nuxt 4 + TypeScript + Tailwind CSS v4 + Nuxt UI v4 + Pinia + Lucide Icons, FastAPI + SQLAlchemy 2 + PyMySQL + Alembic (`20261126_0001`), Argon2id auth, SHA-256 sessions, CSRF, login rate limit, Fernet encryption, redaction, `check-db` & `init-admin` CLI, Dashboard/Health/Logs/Settings pages.

### Phase 2 & Phase 2.1 — Website-Centric Monitoring, Discovery & Universal Content Library
- **Merged Brand into Website Management (`20261127_0003`):** Website-owned brand profile, custom `website_categories`, isolated per-source conditional ETag/Last-Modified discovery caching, two-phase resumable scanning, deterministic URL classification + manual overrides, and 7-tab Universal Content Library (`/content-library`).

### Phase 3 — Gemini AI Engine, Social Profiles & SEO Content Approval
- **Incremental Schema & Seeds (`20261127_0004` + `20261127_0005`):**
  - `20261127_0004`: Added 12 InnoDB `utf8mb4` tables (`platforms`, `social_profiles`, `ai_providers`, `website_knowledge_profiles`, `website_knowledge_profile_revisions`, `prompt_templates`, `prompt_template_revisions`, `ai_response_cache`, `ai_generation_jobs`, `ai_generation_logs`, `social_posts`, `social_post_revisions`), seeded 8 default platforms & 9 baseline prompt templates, and added `auto_generate_require_published_at` and `auto_generate_context_mode` to `websites`.
  - `20261127_0005`: Added 4 InnoDB `utf8mb4` tables (`content_keywords`, `content_keyword_revisions`, `content_approvals`, `content_approval_history`) powering content review status (`awaiting_extraction`, `pending_review`, `needs_rereview`, `approved`, `rejected`), SEO keyword mapping, cannibalization checks, and single/bulk approval gating before AI auto-generation.
- **Website-Owned Social Profiles:** Multiple profiles per platform per website, manual vs API modes (`auto_publish_enabled` locked `false`), and per-platform Fernet-encrypted credentials masked in API responses (`Cache-Control: no-store`).
- **Gemini Provider & Quota Manager (`google-genai==3.6.1`):** Official Interactions API structured JSON generation, `client.models.list()` + `count_tokens()`, Flash/Flash-Lite preference sorting, Free-First daily request/token & RPM limits, and zero silent paid fallback or API key rotation.
- **Knowledge Profiles, Sandboxed Prompts & Caching:** Prioritized compact knowledge synthesis preserving admin overrides, versioned Jinja2 `SandboxedEnvironment` prompt templates with whitelist & offline zero-token preview, and website-scoped SHA-256 `ai_response_cache` storing only schema-validated responses (including `keyword_mapping_fingerprint`).
- **SEO Keyword Mapping & Content Approval (`/content-approval`):** Python-first focus/secondary/anchor/image-alt extraction, optional admin-triggered Gemini SEO refinement (`POST .../keywords/suggest-ai`), always-open inline `<textarea>` boxes and `game_page` classification editing right inside queue rows (plus modal/inspector editors), RapidFuzz focus cannibalization warnings, reusable `KeywordReuseService`, and scan-change re-review preserving locked approved keywords.
- **Automatic Destination Draft Generation & Background Queue:** Content Library **Generate Content** modal with automatic website destination lookup (zero platform checkboxes, friendly empty-profile guard), batched generation, transactional `FOR UPDATE` MySQL job claiming, retry/backoff/stale recovery, Resource Guardian deferral, `run-ai-job` / `run-pending-ai-jobs` CLI commands, and auto-generation strictly gated on approved post-baseline `blog_post` items.
- **Draft Review Queue & AI Console (`/social-media`, `/ai-management`, 7-Tab `/websites/[id]`):** Complete draft editing, approve/reject/archive/regenerate workflows, version history comparison modal, copy content & download media, plus 6-tab AI Management dashboard and CSV audit exports.

## Pending Tasks
- Owner approval to run `alembic upgrade head` (`20261127_0004` + `20261127_0005`) on dev DB `contenthub_ai` (migrations `0001 -> 0005` + downgrade/re-upgrade verified cleanly on isolated `contenthub_ai_test`).
- Configure a valid billing/free-tier Google Gemini API key in `.env` or **AI Management → Gemini Configuration** for live LLM draft generation.
- Engineering Lead review & sign-off before proceeding to **Phase 4 — Social Media Publishing**.

## Known Bugs / Limitations
- None in verified offline/mocked and live MySQL test coverage. Live Gemini connectivity was exercised against `generativelanguage.googleapis.com` where the workspace's placeholder `GEMINI_API_KEY` returned `400 INVALID_ARGUMENT (API_KEY_INVALID)` as handled cleanly by our error mapper; live Gemini text/draft generation outputs were verified using `FakeGeminiProviderClient` until a valid Gemini key is configured.

## Architectural Decisions
1. **Interactions API + Strict Validation Before Caching (`generation_service.py`):** Structured JSON output is schema-validated against website-owned `social_profile_id` values *before* writing into `ai_response_cache`, guaranteeing malformed or cross-website outputs are never cached.
2. **Self-Contained Destination Spec Header (`generation_service.py`):** Even single-platform prompt overrides automatically receive structured `social_profile_id=<id> | platform=<key>` destination specs so structured batch parsing stays deterministic.
3. **Approval Gate & Keyword Fingerprint Isolation (`content_approval_service.py`, `generation_service.py`):** Automatic social generation only enqueues after administrator content & keyword approval (`is_historical_baseline=false`, `blog_post`, first trigger), while `keyword_mapping_fingerprint` invalidates stale cached prompts when approved keywords change.
4. **Free-First Safeguard:** `allow_paid_fallback` is permanently `false` at both API validation and quota enforcement layers; exhausted quotas defer background jobs safely to MySQL rather than switching tiers or rotating keys.

## Testing & Verification Results (2026-11-27)
- **Backend Typecheck / Lint / Test Suite:** `.venv/bin/ruff check .` passed (`All checks passed!`, 0 errors); `.venv/bin/pytest -q` passed (**66 passed**, 3 warnings in 21.85s) — covers Phase 1–2.1 regressions including `/game/*` & `/games/*` `game_page` classifier rules, all 35 Phase 3 AI/Social scenarios (`tests/test_phase3_ai.py`), SEO Keyword Suggestion & Content Approval + `game_page` workflows (`tests/test_phase3_keywords_approvals.py`), and live MySQL `8.0.45` Phase 3 migrations/CRUD (`tests/test_phase3_mysql_live.py` on isolated `contenthub_ai_test`).
- **Frontend Typecheck (`cd frontend && npm run typecheck`):** Passed (`Type check passed in 3657ms.`, 0 TypeScript errors).
- **Frontend Unit Tests (`cd frontend && npx vitest run`):** Passed (**6 test files, 15 tests** — `approval-ui`, `phase3`, `navigation`, `format`, `ui-store`, `auth-store`).
- **Frontend Production Build (`cd frontend && npm run build`):** Passed (`✨ Build complete!` in 8.6s).
- **Isolated Runtime SSR & Nitro Proxy Check (`:8108` FastAPI + `:3108` Built Nuxt -> `contenthub_ai_test`):** Verified login + CSRF, SSR `GET /content-approval` (`200`), `PATCH /api/v1/content-approvals/{id}/keywords` + `POST .../approve` for `game_page`, `GET /api/v1/contents/stats` (`game_page_count`), and `GET /api/v1/contents?tab=game_pages`.
