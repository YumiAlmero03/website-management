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
- Backend tests: `88 passed`, `3` warnings.
- Publishing/connection tests: platform exchanges use `httpx.MockTransport`.
- Frontend: `npm run typecheck` passed.
- Frontend: 22 Vitest tests passed across 7 test files.
- Frontend: production Nuxt build passed.
- Live external publishing: not executed. No real content was published and no social credentials were used.
- Resource Guardian: publishing defers on critical host pressure and retains the lightweight one-concurrent-job limit.
- Test-post regression: verified that an unpublished test draft selects a recent website content item, stores its canonical URL, attaches a website media asset when available, and includes the source link in assembled Facebook/Twitter text.
