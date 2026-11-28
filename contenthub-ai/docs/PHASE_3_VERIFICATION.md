# ContentHub AI — Phase 3 Comprehensive QA & Verification Report

- **Verification Date:** 2026-11-28 (`Asia/Manila`)
- **Repository Commit Audited:** `b867872` (`phase 3 done`), plus current workspace verification & fixes
- **Working-Tree Notice:** The local workspace already contains uncommitted **Phase 4** additions/modifications layered on top of `b867872` (including migration `20261128_0008`, `publishing_*` services/routers/UI, `test_phase3_ai.py:859`, and `frontend/tests/phase3.test.ts:20`). Production/dev database `contenthub_ai` (`alembic current = 20261128_0008`, 1 website, 1,037 content rows, 1 Gemini provider, 0 social posts) was **never reset or mutated**; all destructive, live E2E, and authenticated browser checks ran against isolated test MySQL database `contenthub_ai_test` (`8.0.45`).
- **Overall Phase 3 Verdict:** **PASS** *(ready for formal Phase 4 review/sign-off once uncommitted working-tree Phase 4 changes vs `b867872` are reconciled by the Engineering Lead).*

---

## Status Legend

- `PASS` — Verified directly against live code, runtime execution, or automated tests without blocking defects.
- `PARTIAL` — Core implementation verified, with minor scope caveats or environment configuration notes documented explicitly.
- `FAIL` — Reproducible defect remains unresolved.
- `NOT IMPLEMENTED` — Functionality does not exist.
- `NOT TESTED` — Not executed during this audit.
- `BLOCKED` — Execution prevented by external environment constraint.

---

## Executive Summary & Phase 4 Readiness

Phase 3 deliverables — Gemini AI Engine (`google-genai==3.6.1`), LocalAI Keyword Refinement (`http://127.0.0.1:8081/v1`), Python-first SEO Keyword Mapping & Content Approval (`/content-approval`), Website-Owned Social Profiles & Knowledge Profiles (`/websites/[id]`), Sandboxed Prompt Manager & SHA-256 MySQL Response Cache (`/ai-management`), and Multi-Profile Social Draft Generation & Review (`/social-media`) — are **implemented, integrated end-to-end, and verified cleanly across automated tests, live MySQL (`8.0.45`), live Gemini API calls, live LocalAI calls, and authenticated headless Google Chrome**.

During audit execution on this host, two real bugs were identified and fixed immediately:
1. **`LocalAiProvider` reasoning-channel JSON extraction & schema key normalization (`backend/app/services/ai/localai.py`, `backend/app/services/content_approval_service.py`):** Live probing against LocalAI (`127.0.0.1:8081`, model `qwen3.5-4b-claude-4.6-opus-reasoning-distilled`) showed valid JSON emitted inside `choices[0].message.reasoning` with empty `message.content` and key `"primary_focus_keyphrase"`, previously triggering `LOCALAI_INVALID_RESPONSE` and falling back to `python_only`. Fixed cleanly without altering Python keyword logic or game templates; re-verified live returning `suggestion_source="localai_assisted"`.
2. **Manual-archive `dedupe_key` clearing (`backend/app/services/social_post_service.py`):** While `POST /social-posts/{id}/archive` already cleared `dedupe_key=None`, archiving via `PATCH /social-posts/{id}` with `{"status": "archived"}` previously kept `dedupe_key` populated, which could block subsequent non-forced draft regeneration on MySQL `uq_social_posts_dedupe_key`. Fixed `update_post()` to set `publishing_status="archived"` and `dedupe_key=None` consistently.

**Ready for Phase 4?** **Yes** — Phase 3 components satisfy acceptance requirements. Before advancing/committing Phase 4 officially, the Engineering Lead should review the existing uncommitted Phase 4 working-tree files on top of commit `b867872`, optionally add a `LocalAI` provider record pointing to `http://127.0.0.1:8081/v1` in AI Management if live LocalAI refinement is desired in dev (default `:8080` hits local Apache `httpd`), and note the offline-only `alembic --sql` caveat on Phase 2.1 migration `20261127_0003`.

---

## Section 1 — Gemini AI Verification

| Check | Status | Verification Method | Evidence & Recorded Details |
|---|---|---|---|
| Gemini API key encryption & masking | PASS | Live DB + API Service + Headless Chrome | Fernet (`APP_ENCRYPTION_KEY`) encryption verified (`backend/app/core/security.py`); `AiManagementService._to_provider_response()` returns `masked_api_key` (`••••••••....`) with `Cache-Control: no-store`; zero plaintext leakage in `/ai-management` DOM or responses. |
| API connectivity (`list_models` + probe) | PASS | **Live Gemini API** | `GeminiSdkProvider.test_connection(verify_generation=True)` on `gemini-3.5-flash-lite`: `connected=True`, `model_available=True`, `latency_ms=1146 ms` (isolated E2E: `1419 ms`), `generation_probe_tokens=7`. |
| Compatible model discovery & selection | PASS | **Live Gemini API** + Unit Tests | `list_models()` returned `14` models in `188 ms`, Flash/Flash-Lite ranked first (`sort_models_free_first`). |
| Minimal live structured JSON generation | PASS | **Live Gemini API** | `generate_structured(model='gemini-3.5-flash-lite')` returned valid JSON in `743 ms` (`wall=762 ms`): `measured_input_tokens=25`, `measured_output_tokens=62`, `total_measured_tokens=87`, `raw_usage_available=True`. |
| Website knowledge profile generation | PASS | **Live Gemini API** + Isolated MySQL | `KnowledgeProfileService.generate_profile()` synthesized v1 (`status='generated'`) in `1477 ms`: `estimated_input_tokens=560`, `measured_input_tokens=521`, `measured_output_tokens=232`, `total_measured_tokens=753`. Manual overrides preserved (`field_provenance` marked `admin`). |
| Prompt template rendering & overrides | PASS | Live Service + Unit Tests | Jinja2 `SandboxedEnvironment` (`globals.clear()`, restricted filters, strict undefined, whitelist) renders prompts; rejects SSTI `{{ brand_name.__class__ }}` with `PromptSecurityError`; multi-tier scope resolution tested cleanly. |
| Python context optimization | PASS | Live Service + Automated Tests | `context_mode="optimized"` reuses Phase 2.1 compressed context (`prepare_article_context`) and compact prioritized knowledge selection (`select_knowledge_sources`) without calling AI. |
| Structured JSON response validation | PASS | **Live Gemini API** + Unit Tests | Pydantic validation (`parse_structured_response`, `validate_multi_profile_batch`) validates `MultiProfileSocialBatchOutput` against expected website-owned `social_profile_id` values before persisting or caching. |
| MySQL response caching (`ai_response_cache`) | PASS | **Live MySQL (`contenthub_ai_test`)** | Archiving active drafts and re-running identical non-forced request yielded `cache_hits=1`, `api_calls=0`, materialized 3 drafts, and logged `status='succeeded'`, `cache_hit=True`, `token_usage_status='cached'`, `latency_ms=0`. |
| API request & token tracking | PASS | **Live Gemini API** + Isolated MySQL | `AiGenerationLog` distinguishes `estimated_input_tokens` vs provider `measured_input_tokens`, `measured_output_tokens`, `total_measured_tokens`, and `token_usage_status` (`measured`, `cached`, `unknown`). |
| Application quota enforcement | PASS | Mocked Integration Tests | `QuotaManager` enforces `Asia/Manila` midnight daily request/token caps & RPM caps pre-call; `test_phase3_ai.py` verifies `quota_blocked` deferral without silent paid-tier fallback or key rotation. |
| Timeout & error handling | PASS | Unit / Integration Tests | Maps HTTP 400/401/403/404/429/5xx, `TimeoutException`, and `TransportError` (`gemini.py`); invalid JSON triggers `AI_RESPONSE_VALIDATION_ERROR` without writing cache. *(Note: intentional bad-key live call was not forced against dev key; tested via mocked handlers & earlier QA logs.)* |
| Background generation jobs | PASS | Isolated MySQL + Live Resource Guardian | `AiGenerationJob` claiming via `FOR UPDATE`, stale recovery, retry backoff, cancellation (`cancel_job`), and live Resource Guardian deferral verified (`status='deferred'` triggered automatically on host `RAM=90.8%, load=15.57`). |

---

## Section 2 — Keyword Management & Content Approval Verification

| Check | Status | Verification Method | Evidence & Recorded Details |
|---|---|---|---|
| Python metadata phrase analysis | PASS | Unit Tests + Live Service | Deterministically scores title, URL slug, H1/H2/H3, meta description, structured data, YAKE keywords, and knowledge profile without invoking Gemini. Author attribution stripping verified (`Maria Santos` tests). |
| LocalAI keyword selection | PASS | **Live LocalAI (`127.0.0.1:8081`)** | After reasoning-channel & key normalization fix, `suggest_keywords_with_ai` succeeded live against `qwen3.5-4b-claude-4.6-opus-reasoning-distilled` (~`12.06s`): `suggestion_source="localai_assisted"`, valid synced anchors. *(Note: `qwen3.8-9b-q4` timed out at `25s`; default `.env` `:8080` hits Apache `httpd` unless configured to `:8081`.)* |
| Primary focus keyphrase & secondary relevance | PASS | Live Service + Automated Tests | `Bygame QA` blog post produced `"Fixed Odds vs Dynamic Odds"` + factual secondary phrases derived from headings/meta/YAKE without fabricated metrics. |
| Exact `game_page` keyword templates | PASS | Unit Tests + Live MySQL + Chrome | `"Gates of Olympus"` + provider `"Pragmatic Play"` + website `"Bygame"` produced focus `"Gates of Olympus slots"` and exact secondary/synced anchor list (`test_exact_game_template_and_anchor_sync`, isolated MySQL E2E, and Chrome `/content-approval`). |
| Python-only fallback when LocalAI unavailable | PASS | Live Unreachable Port Test + Unit Tests | Calling unreachable LocalAI endpoint (`127.0.0.1:19999/v1`) caught error gracefully and returned `suggestion_source="python_only"` with valid focus/secondary keywords. |
| Keyword editing, sync & preservation | PASS | API Tests + Isolated MySQL + Chrome | `anchor_text_variations` kept synced to `[focus] + secondary`; always-open `<textarea>` inline boxes verified in Chrome; locked/approved mappings (`is_admin_locked=True`) survive rescans without overwriting. |
| Mapping to website & canonical URL | PASS | Isolated MySQL + `KeywordReuseService` | `content_keywords` and `content_approvals` bind to `website_id`, `website_content_id`, and canonical URL; internal link & cannibalization helpers verified. |
| Content approval workflow & duplicate guard | PASS | Automated Tests + Live MySQL | Single & bulk approval, reject, reopen (`needs_rereview`), unchanged rescan skipping, auto-generation strictly gated on approved post-baseline `blog_post` + approved keywords (`is_historical_baseline=False`), and duplicate URL protection verified. |

**Keyword refinement update (2026-11-28):** The administrator-triggered LocalAI request now contains only the canonical page link and main-keyword exclusion instruction; it no longer sends page titles, metadata, headings, excerpts, or Python-generated candidate lists. The model returns secondary keywords only, and Python removes normalized duplicates of the main keyword. The earlier live audit above documents the prior implementation; the new URL-only prompt and filtering behavior is covered by mocked tests.

---

## Section 3 — Social Profiles, Draft Generation, Security & Frontend Audits

### Individual Completion Summaries (All 9 Modules)

1. **Gemini AI (`PASS`):** `google-genai==3.6.1` SDK client using `interactions.create` + `models.list` + `count_tokens`, Fernet-encrypted keys, Flash/Flash-Lite preference ranking, strict Free-First quota limits, and live measured token telemetry verified (`1146 ms` probe, `743 ms` minimal JSON gen, `1477 ms` knowledge synthesis, `2253 ms` 3-profile draft batch).
2. **LocalAI (`PASS`):** OpenAI-compatible HTTP client restricted solely to `select_keywords` / `list_models` / `test_connection`. Fixed reasoning-channel (`message.reasoning`) and `"primary_focus_keyphrase"` parsing so local reasoning model `qwen3.5-4b-claude-4.6-opus-reasoning-distilled` on `:8081` returns `localai_assisted`, while unreachable endpoints cleanly fall back to `python_only`.
3. **Keyword Management (`PASS`):** Existing Python-first analysis, exact `game_page` slot/provider templates, synced `[focus] + secondary` anchor text variations, cannibalization detection, and `KeywordReuseService` preserved intact with zero Gemini calls per URL.
4. **Content Approval (`PASS`):** Multi-state queue (`awaiting_extraction`, `pending_review`, `needs_rereview`, `approved`, `rejected`), inline always-open `<textarea>` editing without toggle buttons, `game_page` classification option, bulk approve, revision history, and strict AI auto-gen gating verified in Python tests, MySQL, and headless Chrome.
5. **Social Profiles (`PASS`):** Website-owned multi-profile-per-platform model verified (`Bygame FB Main`, `Bygame FB Community`, `Bygame PH X`, plus disabled profile exclusion), dynamic credential encryption & masking (`••••••••9988`, `••••••••1122`), and per-profile language/length/CTA/hashtag overrides verified end-to-end.
6. **Social Draft Generation (`PASS`):** Automatic website destination discovery (no manual checkboxes, excludes inactive/disabled profiles), single-batch multi-profile Gemini call (`1534` total tokens, `2253 ms`), duplicate draft prevention (`api_calls=0` on repeat non-forced request), MySQL SHA-256 `ai_response_cache` hit after archiving active drafts (`cache_hits=1`, `api_calls=0`), manual edit (`v2`) + approval (`publishing_status='approved'`), and `PATCH` archive `dedupe_key` cleanup verified with zero external publishing.
7. **Security (`PASS`):** Fernet encryption at rest (`APP_ENCRYPTION_KEY`), `Cache-Control: no-store`, masked secrets + redacted logs (`redact_text`), Jinja2 `SandboxedEnvironment` prompt injection/SSTI blocking (`PromptSecurityError`), untrusted scraped XML delimiter stripping (`sanitize_untrusted_text`), SSRF defenses (`test_scanner_ssrf.py`), CSRF & Argon2id session authentication verified.
8. **Database (`PARTIAL` — minor offline SQL caveat):** Live MySQL `8.0.45` (`InnoDB`, `utf8mb4`) migrations `20261126_0001 -> 20261128_0008 (head)`, downgrade & re-upgrade drills (`pytest -m mysql -q` 4 passed), and repository locking (`SELECT ... FOR UPDATE`) passed cleanly; `dev DB contenthub_ai` remained completely untouched. Caveat: offline full-chain `alembic upgrade head --sql` fails at Phase 2.1 migration `20261127_0003` because that data migration executes online `conn.execute(...).fetchall()`; offline Phase 3 range (`20261127_0003:20261127_0006 --sql`) succeeds.
9. **Frontend (`PASS`):** Nuxt `typecheck`, `vitest run` (`7` files, `22` tests), production `nuxt build`, and live authenticated headless Google Chrome (`158.0.8127.88`) CDP verification across `/login`, `/`, `/ai-management`, `/content-approval`, `/content-library`, `/content-library/2` (`Generate Social` modal), `/websites/1` (`Social Profiles` + `AI Settings`), and `/social-media` (`Draft Version History` modal `v2`/`v1`) passed with **0 console errors, 0 JS page exceptions, and 0 HTTP `>= 400` responses**.

---

## Section 4 — Isolated End-to-End Live Run Summary (`contenthub_ai_test`)

- **Test Website:** `Bygame QA` (`qa-bygame.example.com`, `Taglish`, `Philippines`, `auto_generate=True`, `initial_scan_completed=True`)
- **Live Gemini Provider:** `Live Gemini E2E` (`gemini-3.5-flash-lite`, `latency_ms=1419 ms`, `generation_probe_tokens=7`)
- **Live Knowledge Synthesis (`v1`):** `521` input tokens, `232` output tokens, `753` total tokens, `1477 ms`; manual admin override saved as `v2` (`approved`, provenance `admin`)
- **Live Draft Batch Generation (Job #1, 3 enabled profiles / 1 disabled excluded):**
  - `api_calls=1`, `cache_hits=0`, `measured_input_tokens=974`, `measured_output_tokens=560`, `total_measured_tokens=1534`, `latency_ms=2253 ms`
  - Drafts persisted: X/Twitter (`231/280` chars, Taglish), FB Community (`319` chars, `en`), FB Main (`424` chars, Taglish)
- **Duplicate Prevention Check (Job #2):** `force_regenerate=False` with active drafts present completed cleanly with `api_calls=0`, `updated_draft_ids=[1, 2, 3]` (total drafts remained `3`).
- **Resource Guardian Live Deferral (Job #4):** Triggered naturally under host load (`RAM 90.8% / 1m load 15.57`), deferring job without calling Gemini (`defer_reason` recorded).
- **MySQL Response Cache Hit (Job #4 resumed):** After archiving active drafts, identical non-forced batch hit `ai_response_cache` cleanly (`cache_hits=1`, `api_calls=0`, `latency_ms=0`, `token_usage_status='cached'`, drafts `[5, 6, 7]` created).
- **Draft Edit & Approval (Post #7):** Edited (`current_version=2`, `is_manually_edited=True`) and approved (`status='approved'`, `publishing_status='approved'`); **zero external posts sent**.

---

## Section 5 — Automated, Security & Browser Validation Results (Post-Final-Edit)

| Check Command | Scope | Result | Notes |
|---|---|---|---|
| `cd backend && .venv/bin/ruff check .` | Backend Python lint/formatting | **PASS** | `All checks passed!` (`0` errors) |
| `cd backend && .venv/bin/pytest -q` | Full backend unit + integration + live MySQL suite | **PASS** | `86 passed, 3 warnings` in `51.91s` (`ai` & HTTP transport mocked cleanly where offline; includes 4 live MySQL tests) |
| `cd backend && .venv/bin/pytest -m mysql -q` | Live MySQL `8.0.45` migrations & locking (`contenthub_ai_test`) | **PASS** | `4 passed, 82 deselected, 2 warnings` in `27.79s` |
| `cd backend && .venv/bin/alembic upgrade 20261127_0003:20261127_0006 --sql > /dev/null` | Offline Phase 3 SQL script generation | **PASS** | Generates valid SQL cleanly *(Note: full `head --sql` from empty fails at historical `20261127_0003` online query check)* |
| `cd frontend && npm run typecheck` | Nuxt 4 TypeScript check | **PASS** | `Type check passed in 4361ms.` (`0` errors) |
| `cd frontend && npx vitest run` | Frontend Vitest unit suite | **PASS** | `Test Files 7 passed (7)`, `Tests 22 passed (22)` |
| `cd frontend && npm run build` | Production Nitro + Vite SSR build | **PASS** | Built cleanly (`dist` + `.output/server/index.mjs`) |
| Headless Google Chrome `158.0.8127.88` CDP QA (`:13103` -> `:18103`) | Authenticated end-to-end UI & network check (`contenthub_ai_test`) | **PASS** | Verified login, `/`, `/ai-management`, `/content-approval`, `/content-library`, `/content-library/2` Generate modal, `/websites/1` Social & AI tabs, `/social-media` + Revision History (`v2`/`v1`). **0 console errors, 0 JS exceptions, 0 HTTP `>=400` responses**. *(Chrome DevTools MCP remote-debugging on user's desktop Chrome was unavailable because `DevToolsActivePort` was disabled.)* |

---

## Section 6 — Verification Limitations & Scope Boundaries

1. **Simulated/Mocked Cases in `pytest -q`:** Intentional invalid Gemini API key error mapping (`400`), quota-exhausted daily cap deferral (`quota_blocked`), auto-scan remote HTML crawl + background worker subprocess execution (`ScanExecutorService -> AiGenerationJob`), and Phase 4 external social publishing HTTP requests are verified with mocked provider/HTTP clients (`FakeGeminiProviderClient`, `MockTransport`) rather than executing live remote crawls or hitting real external social networks.
2. **Database Isolation Confirmed:** Read-only row-count verification on dev `contenthub_ai` post-test confirmed zero mutations (`users=1`, `websites=1`, `website_contents=1037`, `content_approvals=1036`, `content_keywords=1036`, `ai_providers=1`, `social_profiles=1`, `social_posts=0`, `ai_generation_jobs=0`, `ai_response_cache=0`).
