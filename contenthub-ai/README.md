# ContentHub AI

Private, self-hosted, AI-powered Content Distribution and Editorial Automation System built for a single administrator managing multiple websites, brands, social media accounts, and editorial workflows on shared aaPanel hosting.

> **Current Milestone:** Phase 2 — Website Monitoring (complete & verified; ready for review before Phase 3).

---

## Architecture Overview

ContentHub AI is a **modular monolith** with three independent components:

1. **Nuxt 4 Frontend (`frontend/`)** — TypeScript, Tailwind CSS v4, Nuxt UI v4, Pinia, Lucide Icons (`http://127.0.0.1:3100`).
2. **FastAPI Backend (`backend/`)** — Python 3.12, FastAPI, SQLAlchemy 2, PyMySQL, Alembic, Argon2id, Fernet, `psutil` (`http://127.0.0.1:8100`).
3. **Python Background Worker (`backend/workers/`)** — Persistent MySQL-backed worker process *(Phase 2 detached scan CLI; full worker in Phase 6)*.

Database: **Existing MySQL service** (InnoDB, `utf8mb4`, conservative connection pool). AI generation uses **Google Gemini API** exclusively (Phase 3+), with native Python for extraction, summarization, keyword extraction, and token optimization. No Redis, Celery, SQLite, PostgreSQL, extra database daemons, or Docker runtime requirements.

---

## Repository Layout

```text
contenthub-ai/
├── frontend/          # Nuxt 4 + TypeScript + Nuxt UI admin dashboard
├── backend/           # Python 3.12 + FastAPI + SQLAlchemy + Alembic + Pytest
├── storage/           # Local persistent storage (images, cache, exports, backups, logs)
├── scripts/           # Deployment & maintenance scripts (Phase 7)
├── deploy/            # Nginx, Supervisor, PM2 configs (Phase 7)
├── docs/              # Architecture, Database, API, Security, Deployment, Roadmap, Progress
├── .env.example       # Environment variable template
├── .gitignore
├── AGENTS.md          # Engineering standards & agent rules
└── README.md
```

---

## Prerequisites (Local Development)

- **Python:** 3.12 (`python3.12`)
- **Node.js:** 20+ (tested on Node 25.x) & `npm`
- **MySQL:** Existing MySQL 8.0+ / MariaDB 10.6+ instance (never use `root` as the runtime user; use an isolated dev database)

---

## Local Development Setup

### 1. Configure Environment Variables

Copy `.env.example` to `.env` in `contenthub-ai/` and fill in your local development values:

```bash
cd contenthub-ai
cp .env.example .env
chmod 600 .env
```

Generate strong secrets for `APP_SECRET_KEY` and `APP_ENCRYPTION_KEY`:

```bash
python3.12 -c "import secrets; print('APP_SECRET_KEY=' + secrets.token_hex(32))"
python3.12 -c "from cryptography.fernet import Fernet; print('APP_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```

### 2. Provision a Dedicated Development MySQL Database & User

Do **not** connect to a production database. Create a dedicated development database and least-privilege user in your local MySQL server:

```sql
CREATE DATABASE IF NOT EXISTS contenthub_ai
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'contenthub_user'@'127.0.0.1'
  IDENTIFIED BY 'REPLACE_WITH_STRONG_PASSWORD';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, REFERENCES
  ON contenthub_ai.* TO 'contenthub_user'@'127.0.0.1';

FLUSH PRIVILEGES;
```

Update `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` in `.env`.

### 3. Install Backend Dependencies

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Verify MySQL Connectivity & Run Alembic Migrations

```bash
cd backend
source .venv/bin/activate

# Verify MySQL connectivity, server version, InnoDB, and utf8mb4 support
python -m app.cli check-db

# Apply Phase 1 + Phase 2 schema migrations
alembic upgrade head
```

*(Optional offline SQL inspection without connecting to MySQL:)*

```bash
alembic upgrade head --sql
```

### 5. Scanner & Scheduled Monitoring CLI Commands (Phase 2)

```bash
cd backend
source .venv/bin/activate

# Execute a single queued scan by ID (spawned automatically by POST /api/v1/websites/{id}/scan)
python -m app.cli run-scan --scan-id 1

# Run all due auto_scan websites sequentially under a MySQL advisory lock (for aaPanel Cron)
python -m app.cli run-due-scans
```

Example aaPanel Cron entry (every 5 minutes):

```cron
*/5 * * * * cd /www/wwwroot/contenthub-ai/backend && /www/wwwroot/contenthub-ai/backend/.venv/bin/python -m app.cli run-due-scans >> /www/contenthub-storage/logs/cron-scanner.log 2>&1
```

### 6. Initialize the Single Administrator Account

Public registration is permanently disabled and no default password exists. Create the administrator interactively via CLI:

```bash
cd backend
source .venv/bin/activate
python -m app.cli init-admin --email admin@example.com --name "Site Administrator"
```

You will be prompted securely for a strong password (minimum 12 characters).

### 7. Install Frontend Dependencies

```bash
cd frontend
npm install
```

---

## Running the Application Locally

### Start the FastAPI Backend (`http://127.0.0.1:8100`)

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload
```

### Start the Nuxt 4 Frontend (`http://127.0.0.1:3100`)

In a separate terminal:

```bash
cd frontend
npm run dev
```

Nuxt automatically proxies `/api/**` requests to `http://127.0.0.1:8100` (configurable via `NUXT_API_PROXY_TARGET`).

Visit `http://127.0.0.1:3100`. Unauthenticated requests redirect to `/login`.

---

## Running Automated Tests & Quality Checks

### Backend

```bash
cd backend
source .venv/bin/activate
ruff check .
pytest
```

To also run the live MySQL integration test against an explicitly configured **isolated** test database:

```bash
CONTENTHUB_TEST_DATABASE_URL="mysql+pymysql://contenthub_user:PASSWORD@127.0.0.1:3306/contenthub_ai_test?charset=utf8mb4" \
  pytest -m mysql
```

### Frontend

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

---

## Documentation Index

- [AGENTS.md](AGENTS.md) — Engineering rules, approved stack, and prohibited technologies
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Modular monolith architecture & component boundaries
- [docs/DATABASE.md](docs/DATABASE.md) — MySQL design, normalized schema plan, pooling, and Alembic workflow
- [docs/API.md](docs/API.md) — REST API conventions, authentication/CSRF contract, and Phase 1–2 endpoints
- [docs/SECURITY.md](docs/SECURITY.md) — Threat model, authentication, encryption, redaction, and SSRF policy
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — aaPanel production deployment, Nginx, PM2, Supervisor, and backups
- [docs/ROADMAP.md](docs/ROADMAP.md) — 7-phase delivery plan and acceptance criteria
- [docs/PROGRESS.md](docs/PROGRESS.md) — Live milestone tracker, test results, and known limitations
