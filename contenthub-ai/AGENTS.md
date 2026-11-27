# ContentHub AI — AI Coding Agent Guidelines (`AGENTS.md`)

This document is the authoritative operating guide for all human and AI engineers contributing to **ContentHub AI**. Follow every rule below strictly unless explicitly amended by the project owner.

---

## 1. Project Identity & Scope

- **Name:** ContentHub AI
- **Type:** Private, single-administrator, self-hosted AI Content Distribution and Editorial Automation System.
- **Not a SaaS:** Public registration, multi-tenancy, subscriptions, and billing are explicitly out of scope and prohibited.
- **Operating Environment:** Shared aaPanel Linux server (16 cores, 31 GB RAM, default timezone `Asia/Manila`) hosting existing production websites.
- **Cost Target:** PHP 0 additional monthly operating cost. Free-first tooling and Python-first processing before AI calls.

---

## 2. Approved Technology Stack

Do **not** change or add to this stack without explicit owner approval.

### Frontend (`frontend/`)
- **Framework:** Nuxt 4 (`app/` directory convention) + TypeScript
- **Styling & UI:** Tailwind CSS v4 + Nuxt UI v4 + Lucide Icons
- **State:** Pinia
- **Future-Phase UI Libraries (install only in their respective phase):**
  - Tiptap free/open-source extensions (Phase 5 — Article Editor)
  - FullCalendar Standard (Phase 4 — Publishing Calendar)
  - Chart.js (Phase 6+ — Analytics)

### Backend (`backend/`)
- **Runtime:** Python 3.12
- **Web Framework:** FastAPI + Uvicorn
- **Validation & Settings:** Pydantic v2 + `pydantic-settings`
- **Database:** SQLAlchemy 2 + PyMySQL + Alembic (connecting to existing aaPanel MySQL; InnoDB + `utf8mb4` + FULLTEXT)
- **Security:** `argon2-cffi` (Argon2id), `cryptography` (Fernet), SHA-256 hashed session tokens
- **HTTP & Templates:** HTTPX, Jinja2
- **Monitoring:** `psutil`
- **Quality:** Pytest, Ruff

### AI, Content & SEO (Phases 2–5)
- Google Gen AI SDK (`google-genai`) — **sole** AI generation provider (prefer configurable free-tier Flash / Flash-Lite models; never auto-fallback to paid tiers; do not add secondary AI agent frameworks)
- Native Python content extraction, extractive summarization, keyword extraction, and token optimization: Trafilatura, BeautifulSoup4, YAKE, RapidFuzz, Hashlib, Markdownify, Feedparser, defusedxml, Pillow
- Playwright as a strict fallback only (never bypass platform restrictions)
- Google Search Console API & Google Trends RSS (when available)

### Hosting & Operations
- aaPanel, Linux, Nginx (`/` -> Nuxt `:3100`, `/api/` -> FastAPI `:8100`)
- PM2 (Nuxt), Supervisor (FastAPI + Python background worker), aaPanel Cron
- Existing aaPanel MySQL service (never install a second database server)
- No Docker requirement for ContentHub AI (do not modify existing Docker services on the server)

---

## 3. Prohibited Technologies

Never introduce any of the following unless explicitly requested in writing:
- SQLite (including in automated tests — use in-memory repository fakes and/or an explicitly configured isolated MySQL test database via `CONTENTHUB_TEST_DATABASE_URL`)
- PostgreSQL, MongoDB, Redis, Celery
- Ollama, LangChain, LangGraph, external AI agent frameworks, Vector databases
- Kubernetes, Docker as an application dependency, Microservices architecture
- Paid SEO APIs, Paid publishing APIs, Paid UI components
- Browser automation / session-cookie hacks / unofficial endpoints for social media publishing

---

## 4. Architecture Rules

1. **Modular Monolith + Separate Worker:** Three independent components:
   - `frontend/` (Nuxt 4 admin UI)
   - `backend/` (FastAPI REST API)
   - `backend/workers/` (persistent MySQL-backed background worker — Phase 6)
2. **Strict Layering in Backend:**
   - `app/routers/`: thin HTTP/validation/auth adapters only. No business logic or raw ORM queries.
   - `app/services/`: domain business logic, authorization checks, orchestration, and redaction.
   - `app/repositories/`: all database queries and persistence operations behind clean repository interfaces (making unit tests fast and SQLite-free).
   - `app/models/`: SQLAlchemy ORM models (InnoDB, `utf8mb4`, explicit indexes/constraints).
   - `app/schemas/`: Pydantic v2 request/response contracts.
3. **Database Hygiene:**
   - Conservative pooling defaults: `DB_POOL_SIZE=3`, `DB_MAX_OVERFLOW=2`, `DB_POOL_RECYCLE=1800`, `pool_pre_ping=True`.
   - Never use the MySQL `root` user at runtime.
   - Verify the installed MySQL version before using version-specific SQL syntax.
   - Store all timestamps in UTC in the database; format in `APP_TIMEZONE` (`Asia/Manila` by default) for display.
4. **No Expensive Work in Web Requests:** Long-running scans, AI calls, and scheduled publishes belong in the background worker / job queue.
5. **Production Server Protection:** Never modify unrelated aaPanel websites, production databases, or global server configurations. Production storage must live outside the replaceable application directory (e.g., `/www/contenthub-storage/`).

---

## 5. Security Standards

- **Single-Admin Auth:** No public signup. Administrator accounts are created explicitly via CLI (`python -m app.cli init-admin`) with no default passwords.
- **Passwords:** Argon2id hashing (`argon2-cffi`).
- **Sessions:** Cryptographically random opaque tokens; store only SHA-256 hash in MySQL `sessions` table. Deliver via `HttpOnly`, `SameSite=Lax` (`Secure=true` in HTTPS production) cookies.
- **CSRF Protection:** Require session-bound `X-CSRF-Token` header on all state-mutating authenticated requests (`POST`, `PUT`, `PATCH`, `DELETE`).
- **Rate Limiting:** Sliding-window rate limit on login attempts with `Retry-After`.
- **Credential Encryption:** Encrypt sensitive settings/credentials using Fernet (`APP_ENCRYPTION_KEY` stored outside the database).
- **Redaction:** Never log passwords, API keys, session tokens, cookies, CSRF tokens, or decrypted credentials.
- **Untrusted Content & SSRF (Phase 2+):** Treat all scraped web content as untrusted data (never executable prompts/HTML). Block localhost, private/link-local/loopback IPs, cloud metadata endpoints, and unsafe schemes; validate DNS resolution and redirects.
- **Publishing Safety:** Semi-automatic (human approval before publishing) is the default mode. Official APIs only; fallback to manual publishing when APIs are unavailable.

---

## 6. Coding & Honesty Standards

- **Type Safety:** TypeScript everywhere in `frontend/`; Python type hints everywhere in `backend/`.
- **Honesty Over Mocks:** Never fabricate live statistics, never leave fake endpoints returning `200 OK` for unimplemented integrations. Unimplemented Phase 3–6 modules must explicitly display "Not Yet Implemented" status or return honest `501 Not Implemented` / explicit status markers.
- **No Silent Failures:** Handle errors explicitly, log structured context (redacted), and surface actionable errors to the administrator.
- **Phase Discipline:** Implement only the active roadmap phase. Stop at phase boundaries for review.
- **Progress Tracking:** Update `docs/PROGRESS.md` after every milestone with actual test results, blockers, and architectural decisions.

---

## 7. Development Workflow

1. Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/PROGRESS.md` before coding.
2. Preserve existing work and avoid unrelated edits.
3. Implement scoped changes following the layered architecture.
4. Validate before reporting completion:
   - Backend: `ruff check .` and `pytest` (plus `alembic upgrade head --sql` or live dev DB migration when configured).
   - Frontend: `npm run typecheck`, `npm test`, and `npm run build`.
   - Runtime smoke test: start FastAPI and Nuxt locally and verify health, auth protection, and UI rendering.
5. Never commit `.env`, credentials, SQL dumps, backups, or runtime storage artifacts.
