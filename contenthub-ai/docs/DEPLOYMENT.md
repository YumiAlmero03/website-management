# ContentHub AI — aaPanel Deployment Guide

> **Safety Notice:** Phases 1–2 implement local development and deployment documentation only. Production automation scripts (`scripts/`, `deploy/`) will be finalized and tested in **Phase 7 — QA, Security and Deployment**. Never modify unrelated production websites, existing Docker services on the server, or global aaPanel configurations.

## 1. Target Server Layout

| Item | Suggested Value | Notes |
|---|---|---|
| Application Root | `/www/wwwroot/contenthub-ai` | Replaceable build/release directory |
| Persistent Storage | `/www/contenthub-storage` | Outside app root (`images/`, `cache/`, `exports/`, `backups/`, `logs/`) |
| Nuxt Frontend Port | `127.0.0.1:3100` | Check availability with `ss -tulpn \| grep 3100` |
| FastAPI Backend Port | `127.0.0.1:8100` | Check availability with `ss -tulpn \| grep 8100` |
| Database | Existing aaPanel MySQL (`127.0.0.1:3306`) | Dedicated DB `contenthub_ai` & user `contenthub_user` |
| Timezone | `Asia/Manila` | Stored in UTC in MySQL, rendered in `APP_TIMEZONE` |

## 2. Process Supervision Topology

- **Nginx (aaPanel Site Config):**
  - `/` -> proxy to `http://127.0.0.1:3100` (Nuxt 4 SSR via PM2)
  - `/api/` -> proxy to `http://127.0.0.1:8100` (FastAPI via Supervisor)
  - Enforce HTTPS, `SESSION_COOKIE_SECURE=true`, and private access control (VPN / IP allowlist / basic auth layer).
- **PM2:** Runs the built Nuxt 4 server (`frontend/.output/server/index.mjs`) on `127.0.0.1:3100` with conservative memory restart limit (`max_memory_restart: '512M'`).
- **Supervisor (Process 1 — API):** Runs `uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 2` from `backend/.venv`.
- **Supervisor (Process 2 — Worker, Phase 6):** Runs the persistent Python background worker reading from MySQL under Resource Guardian thresholds.
- **aaPanel Cron (Phase 6):** Triggers lightweight enqueue endpoints/CLI commands for scheduled scans, publishing checks, cache cleanup, and daily MySQL backups.
- **No Docker Requirement:** ContentHub AI runs natively under aaPanel (Nginx, PM2, Supervisor, Cron, and existing MySQL) without requiring Docker. Do not modify existing Docker services on the server.

## 3. Phase 2 Example aaPanel Cron Configuration (Scheduled Website Scanning)

Do **not** modify production aaPanel Cron automatically during development. When deploying, add a shell cron task in aaPanel Cron running every 5 minutes:

```cron
*/5 * * * * cd /www/wwwroot/contenthub-ai/backend && /www/wwwroot/contenthub-ai/backend/.venv/bin/python -m app.cli run-due-scans >> /www/contenthub-storage/logs/cron-scanner.log 2>&1
```

Safety built into `python -m app.cli run-due-scans`:
- Acquires a non-blocking MySQL advisory lock (`SELECT GET_LOCK('contenthub_due_scans_lock', 0)`) so overlapping cron invocations exit immediately.
- Checks the `psutil` Resource Guardian first and pauses nonessential scanning if CPU/RAM/Load exceeds configured thresholds.
- Recovers stale scan records before processing due websites sequentially and advancing `next_scan_at`.

## 4. Non-Destructive Deployment Checklist

1. Verify target ports `3100` and `8100` are unused.
2. Provision `/www/contenthub-storage/{images,cache,exports,backups,logs}` with least-privilege ownership.
3. Create MySQL database `contenthub_ai` (`utf8mb4_unicode_ci`) and user `contenthub_user` (never `root`).
4. Populate `/www/wwwroot/contenthub-ai/.env` (`chmod 600`) with generated `APP_SECRET_KEY`, `APP_ENCRYPTION_KEY`, `SESSION_COOKIE_SECURE=true`, and `STORAGE_ROOT=/www/contenthub-storage`.
5. Take a pre-migration MySQL backup (`mysqldump --single-transaction --routines --triggers contenthub_ai | gzip > ...`).
6. Validate DB connectivity (`python -m app.cli check-db`) and run `alembic upgrade head`.
7. Initialize the single administrator account once (`python -m app.cli init-admin`).
8. Build Nuxt (`cd frontend && npm ci && npm run build`).
9. Reload Supervisor (`contenthub-api`, and `contenthub-worker` in Phase 6) and PM2 (`contenthub-web`), then verify `GET /api/v1/health`.

## 5. Rollback & Recovery Strategy

- **Application Rollback:** Keep the previous Git commit/tag recorded; revert code, rebuild frontend, reload PM2/Supervisor. Persistent storage in `/www/contenthub-storage` remains intact.
- **Database Recovery:** Restore the pre-deploy compressed `mysqldump` snapshot into `contenthub_ai` before restarting services. Daily automated backups and restore verification scripts will be implemented in Phases 6 and 7.
