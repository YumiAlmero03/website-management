# ContentHub AI — aaPanel Deployment Guide

> **Safety Notice:** Never modify unrelated production websites, existing Docker services on the server, or global aaPanel configurations. ContentHub AI runs natively with aaPanel Nginx, PM2, Supervisor, Cron, and existing MySQL.

## Server Paths & Ports

| Item | Value |
|---|---|
| App Directory | `/www/wwwroot/webtracker.com/contenthub-ai` (or `/www/wwwroot/contenthub-ai`) |
| Persistent Storage | `/www/wwwroot/.contenthub-storage` (or `/www/contenthub-storage`, outside app folder) |
| Frontend (PM2) | `127.0.0.1:3100` |
| Backend API (Supervisor) | `127.0.0.1:8100` |
| MySQL | Existing aaPanel MySQL (`127.0.0.1:3306`, dedicated DB & non-root user) |

---

## Step-by-Step aaPanel Installation

### 1. Enable `supervisor` in Python Manager *(aaPanel UI)*
1. Go to **aaPanel → Website → Python Project → Version Management**.
2. Click **Module** next to **Python 3.12.x**, type `supervisor`, and click **Install**.

### 2. Create a Dedicated MySQL Database *(aaPanel UI)*
1. Go to **aaPanel → Databases → MySQL → Add DB**.
2. Create an empty `utf8mb4` database (e.g., `contenthub_ai_local`) with a dedicated local user and strong password.

### 3. Run Initial Setup *(One-Time Terminal Step)*
1. Open **aaPanel → Terminal** and run:
```bash
export PATH="/www/server/pyporject_evn/versions/3.12.3/bin:/www/server/nodejs/v22.12.0/bin:$PATH"
cd /www/wwwroot/webtracker.com/contenthub-ai
APP_DIR="$PWD" STORAGE_ROOT=/www/wwwroot/.contenthub-storage bash setup-aapanel.sh
```
2. Follow the prompts to enter your site URL, database credentials, and initial Administrator account.

### 4. Add Nginx Reverse Proxy *(aaPanel UI)*
1. Go to **aaPanel → Website → PHP Project** and create/open your site (`Pure Static`, empty public root folder such as `/www/wwwroot/contenthub-public`).
2. Open **Config** and add inside `server { ... }`:
   - `location /api/` → `proxy_pass http://127.0.0.1:8100;`
   - `location /` → `proxy_pass http://127.0.0.1:3100;`
3. Save and open `/login` in your browser.

### 5. Add Scheduled Scanning in Cron *(aaPanel UI)*
1. Go to **aaPanel → Cron**, choose **Shell Script**, set **N Minutes = 5**, and add:
```bash
cd /www/wwwroot/webtracker.com/contenthub-ai/backend
runuser -u www -- /www/wwwroot/webtracker.com/contenthub-ai/backend/.venv/bin/python -m app.cli run-due-scans >> /www/wwwroot/.contenthub-storage/logs/cron-scanner.log 2>&1
```
*(Uses a MySQL `GET_LOCK` advisory lock and `psutil` Resource Guardian so overlapping or high-load runs exit safely.)*

---

## Backup & Rollback Summary

1. **View Logs (UI):** Open **aaPanel → Files** → `/www/wwwroot/.contenthub-storage/logs/`.
2. **Database Backup (UI):** Use **aaPanel → Databases → Backup** (or **Cron → Backup Database**) before applying new database migrations.
3. **Rollback:** Revert to the previous Git commit, run `setup-aapanel.sh --resume` from **aaPanel → Cron**, and restore the database backup in **aaPanel → Databases** only if a schema migration must be reverted.
