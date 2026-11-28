# ContentHub AI

Private, self-hosted, AI-powered Content Distribution and Editorial Automation System for a single administrator on aaPanel.

> **Current Milestone:** Phase 3 — Gemini AI Engine, Social Profiles & SEO Content Approval (complete & verified; ready for review before Phase 4).

---

## Architecture Summary

1. **Frontend (`frontend/`)** — Nuxt 4, TypeScript, Tailwind CSS v4, Nuxt UI v4, Pinia, Lucide Icons (`127.0.0.1:3100`).
2. **Backend (`backend/`)** — Python 3.12, FastAPI, SQLAlchemy 2, PyMySQL, Alembic, `google-genai`, Jinja2 Sandboxed Prompts, Argon2id, Fernet, `psutil` (`127.0.0.1:8100`).
3. **Background Execution (`backend/app/cli.py`, `backend/workers/`)** — Detached scan & AI generation workers (`run-scan`, `run-due-scans`, `run-ai-job`, `run-pending-ai-jobs`) and Cron scheduler.

- **Database:** Existing aaPanel MySQL (`InnoDB`, `utf8mb4`).
- **AI & Extraction:** Native Python extraction/summarization/context digest; Google Gemini API (`google-genai`) as sole AI provider (Free-First quota protection, zero silent paid fallback). No Redis, Celery, SQLite, OpenClaw, or Docker requirement.

---

## Quick aaPanel Installation (5 Steps)

Assuming Git, Nginx, MySQL, Python 3.12, Node 22.12+, and PM2 are already installed in aaPanel:

1. **Python Module (aaPanel UI):** Go to **Website → Python Project → Version Management → 3.12.x → Module** and install `supervisor`.
2. **Database (aaPanel UI):** Go to **Databases → MySQL → Add DB** and create an empty `utf8mb4` database + user.
3. **One-Time Setup (aaPanel Terminal):**
   ```bash
   export PATH="/www/server/pyporject_evn/versions/3.12.3/bin:/www/server/nodejs/v22.12.0/bin:$PATH"
   cd /www/wwwroot/webtracker.com/contenthub-ai
   APP_DIR="$PWD" STORAGE_ROOT=/www/wwwroot/.contenthub-storage bash setup-aapanel.sh
   ```
   Follow the prompts for your URL, MySQL database, and Admin login.
4. **Nginx Proxy (aaPanel UI):** In **Website → Site → Config**, proxy `/api/` to `http://127.0.0.1:8100` and `/` to `http://127.0.0.1:3100` (using an empty public root folder like `/www/wwwroot/contenthub-public`).
5. **Cron Tasks (aaPanel UI):** In **Cron → Shell Script**, add scheduled scans (`run-due-scans` every 5 minutes) and one-click service start/update tasks. See the root [aaPanel Setup Guide](../../README.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Local Mac Development (One-Command Runner)

1. **Ensure `.env` is configured:** Copy `.env.example` to `.env` (`chmod 600 .env`) pointing to an empty or migrated local MySQL dev database.
2. **Start both Backend (`:8100`) and Frontend (`:3100`) together:**
   ```bash
   cd "/Users/lanie/Sites/aapanel env v2/www/contenthub-ai"
   ./dev.sh
   ```
   - Automatically checks MySQL, runs `alembic upgrade head` on an empty DB, prompts to create your admin login if none exists, and starts both servers (`Ctrl+C` stops both).
   - Open **`http://127.0.0.1:3100`** in your browser.
3. **Run Preflight or Full Automated Tests:**
   ```bash
   ./dev.sh --check   # Check ports, .env, and MySQL schema status
   ./dev.sh --test    # Run ruff, pytest, nuxt typecheck, and vitest
   ```

---

## Documentation

1. [AGENTS.md](AGENTS.md) — Engineering rules & approved stack
2. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — System components & workflows
3. [docs/DATABASE.md](docs/DATABASE.md) — MySQL schema & Mermaid ERDs
4. [docs/API.md](docs/API.md) — Phase 1, Phase 2 & Phase 2.1 REST endpoints
5. [docs/SECURITY.md](docs/SECURITY.md) — Auth, CSRF, encryption & SSRF controls
6. [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Step-by-step aaPanel deployment
7. [docs/ROADMAP.md](docs/ROADMAP.md) — 7-phase roadmap
8. [docs/PROGRESS.md](docs/PROGRESS.md) — Progress & test results
