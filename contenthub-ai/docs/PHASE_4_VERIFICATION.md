# Phase 4 — Social Media Publishing Verification

**Status:** COMPLETE — READY FOR ENGINEERING LEAD REVIEW

**Baseline:** Existing Phase 3 functionality preserved from commit `b867872`. Phase 4 work was reviewed on top of that baseline before further edits.

**Stopped boundary:** Do not proceed to Phase 5 without administrator approval.

## Requirements Comparison

The implementation matches the approved Phase 4 roadmap:

- Social Post editor, alternative captions, hashtags, UTM parameters, character limits, and media attachments.
- Modular publisher adapter registry with official Facebook, Instagram, Google Business, Threads, LinkedIn, Pinterest, and X/Twitter integrations, plus manual fallback.
- Human approval default with schedule, cancel, reconcile, manual published, logs, and publication-history workflows.
- FullCalendar month/week/day publishing calendar with UTC storage and Asia/Manila display.
- Social Media editor image generation through the configured default Gemini provider's Imagen model; generated files are validated, saved as website-scoped media assets, and selected as the draft's primary attachment.
- Publishing history, status verification, CSV export, and permanent publication snapshots.
- `FOR UPDATE` transactional publishing job claiming, retry/backoff, stale recovery, idempotency, and ambiguous timeout reconciliation.
- Resource Guardian integration and a single concurrent publishing worker limit.

## LocalAI Configuration

- Verified endpoint: `http://127.0.0.1:8081/v1`
- Verified lightweight reasoning model: `qwen3.5-4b-claude-4.6-opus-reasoning-distilled`
- Compatibility fix: JSON is accepted from `choices[].message.content`, `choices[].message.reasoning`, or `choices[].message.reasoning_content`; `<think>` blocks are removed and `primary_focus_keyphrase` is normalized to `focus_keyphrase`.
- Fallback: unavailable/invalid LocalAI responses return `suggestion_source="python_only"` and retain Python keyword extraction.
- Port `8081` is now the code and `.env.example` default. Port `8080` is not used as a fallback.

## Migration 20261128_0008

Migration `20261128_0008` adds Phase 4 publishing preferences and lifecycle columns, profile connections, OAuth state, post media, schedules, jobs, logs, and permanent publication records. It revises `20261128_0007` and is followed by `20261128_0009`.

Verified development database:

- Alembic revision: `20261128_0009 (head)`
- MySQL: `8.0.45`
- Character set: `utf8mb4`
- Engine: `InnoDB`
- Database connection: connected successfully

Preserved live record counts after verification:

| Record set | Count |
|---|---:|
| Websites | 1 |
| Website contents | 1037 |
| Content keywords | 1036 |
| Content approvals | 1036 |
| Social profiles | 2 |
| Social posts | 0 |
| Social profile connections | 1 |
| Publishing schedules | 0 |
| Publishing jobs | 0 |
| Publishing logs | 0 |
| Publication records | 0 |

No website, content, keyword, approval, or social profile records were deleted or replaced.

## Known Limitation

The historical offline Alembic SQL-generation caveat for migration `20261127_0003` remains recorded for Phase 7. It is not a reason to skip live MySQL upgrade verification.

## Test and Safety Evidence

- Backend lint: `ruff check .` passed.
- Backend tests: `94 passed`, `3` warnings.
- Publishing/connection tests: platform exchanges use `httpx.MockTransport`.
- Frontend: `npm run typecheck` passed.
- Frontend: 22 Vitest tests passed across 7 test files.
- Frontend: production Nuxt build passed.
- Live external publishing: not executed. No real content was published and no social credentials were used.
- Resource Guardian: publishing defers on critical host pressure and retains the lightweight one-concurrent-job limit.
- Test-post regression: verified that an unpublished test draft selects a recent website content item, stores its canonical URL, attaches a website media asset when available, and includes the source link in assembled Facebook/Twitter text.

## Phase 4.1 One-Click Indexing Acceptance

- Migration `20261128_0010` was applied successfully to the development MySQL database; Alembic now reports `20261128_0010 (head)`.
- Website Settings is the sole location for Run Indexing, with per-website progress, deferred/completed states, and a compact completion notification. The Content Library retains the Google Index status filter and table column.
- The worker selects at most 10 distinct eligible URLs, excludes confirmed indexed URLs, and prevents overlapping jobs for a website.
- Published permalink capture and background backlink checks are retained.
- Google URL Inspection is performed only for URLs inside the website's configured Search Console property.
- Indexed status is assigned only from an indexed coverage state plus a PASS inspection verdict. Request-ready/ready-to-request status never reports confirmed indexing.
- The restricted Google Indexing API is not used for ordinary pages.
- Website Settings now includes a “Google Index Checker — Articles & Posts” section for the authorized Search Console property and per-website service-account JSON upload/removal.
- Migration `20261128_0011` stores the service-account JSON in an encrypted website column. Upload validates the JSON, RSA private key, and fixed Google OAuth token endpoint; responses and audit logs never include credential contents. The existing server-level credential remains a fallback.
- Website Settings includes a deliberate “Test Account” action. It obtains a token with the read-only `webmasters.readonly` scope, calls Search Console `sites.list`, and marks the configuration verified only when the exact configured property is returned. Property changes or key replacement/removal clear verification. Indexing cannot start until this test succeeds.
- Development website #1 (`bygame.ph`) is configured with the supplied property `https://bygame.ph/`; its account verification timestamp remains unset until an administrator runs Test Account. Grant the uploaded service account access to this Search Console property.
- Indexing startup was repaired after reproducing two worker blockers: the eligibility query emitted MySQL-incompatible `NULLS LAST/FIRST`, and the worker called a nonexistent Resource Guardian method. Ordering now uses MySQL's native NULL ordering, and the worker calls `get_system_resources()`.
- Worker launch failures now mark the persistent job failed and restore content statuses; detached worker output is written to `indexing-worker.log`.
- The repaired eligibility query succeeds against the development MySQL database. Startup now requires the property, service account, and a successful account test before creating a job. No job was started; all Google responses in tests are mocked and no live Google API request was made during verification.
- Backend lint passed and the full backend suite passed: 106 tests, 3 dependency deprecation/optional-dependency warnings. Credential upload, encryption-at-rest, validation, removal, mocked token generation, mocked property-access success/mismatch, startup gating, and the CSRF-protected account-test route are covered without live Google calls.
- Social Media edit-post previews support both local media files and URL-only source images.
- Generate Image uses mocked Imagen responses in tests; image validation, local media persistence, website scope, provider configuration, and CSRF are verified. No live image-generation request or social publication was made.
- Activity & Audit Logs includes live background-worker status for website scanning, AI generation, social publishing, and Google indexing.
