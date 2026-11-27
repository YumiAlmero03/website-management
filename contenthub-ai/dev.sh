#!/usr/bin/env bash
# ContentHub AI — Single-Command Local Development Runner (macOS & Linux)
# Starts both FastAPI (:8100) and Nuxt 4 (:3100) in one terminal; Ctrl+C stops both.
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$APP_DIR/backend"
FRONTEND_DIR="$APP_DIR/frontend"
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
ALEMBIC_BIN="$BACKEND_DIR/.venv/bin/alembic"
UVICORN_BIN="$BACKEND_DIR/.venv/bin/uvicorn"

MODE="${1:-run}"

usage() {
  cat <<'HELP'
Usage: ./dev.sh [--check | --test | --help]

  (no args)  Start both FastAPI (http://127.0.0.1:8100) and Nuxt (http://127.0.0.1:3100)
  --check    Verify .env, dependencies, ports, and MySQL database state without starting
  --test     Run backend (ruff + pytest) and frontend (typecheck + vitest) test suites
HELP
}

case "$MODE" in
  run|--check|--test) ;;
  --help|-h) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac

echo "==> ContentHub AI Local Dev Runner ($APP_DIR)"

# 1. Verify .env and local dependencies
if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "Error: Missing $APP_DIR/.env. Copy .env.example to .env first." >&2
  exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Installing backend virtualenv in backend/.venv ..."
  python3.12 -m venv "$BACKEND_DIR/.venv"
  "$BACKEND_DIR/.venv/bin/pip" install --upgrade pip
  "$BACKEND_DIR/.venv/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Installing frontend dependencies in frontend/node_modules ..."
  (cd "$FRONTEND_DIR" && npm install)
fi

# 2. Optional test mode
if [[ "$MODE" == "--test" ]]; then
  echo "==> Running backend lint & tests..."
  (cd "$BACKEND_DIR" && .venv/bin/ruff check . && .venv/bin/pytest)
  echo "==> Running frontend typecheck & unit tests..."
  (cd "$FRONTEND_DIR" && npm run typecheck && npm test)
  echo "==> All development checks passed!"
  exit 0
fi

# 3. Check ports 8100 & 3100 and inspect MySQL database state
DB_STATUS="$(
  cd "$BACKEND_DIR"
  "$VENV_PYTHON" - "$MODE" <<'PY'
import socket
import sys
from sqlalchemy import inspect, text
from app.config import get_settings
from app.database import check_database_connection, create_mysql_engine
from app.models import Base

mode = sys.argv[1]

for port, label in ((8100, "FastAPI backend"), (3100, "Nuxt frontend")):
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"Port {port} ({label}) is already in use. Stop the existing process first.")

cfg = get_settings()
diag = check_database_connection(settings=cfg)
if not diag.connected:
    raise SystemExit(
        f"MySQL unavailable ({cfg.db_user}@{cfg.db_host}:{cfg.db_port}/{cfg.db_name}): {diag.error}"
    )

engine = create_mysql_engine(cfg)
try:
    with engine.connect() as conn:
        insp = inspect(conn)
        tables = set(insp.get_table_names())
        if not tables:
            print("EMPTY_DB")
        else:
            # Verify schema compatibility (e.g., catch old legacy columns before runtime crash)
            if "users" in tables:
                user_cols = {c["name"] for c in insp.get_columns("users")}
                if "display_name" not in user_cols:
                    raise SystemExit(
                        f"Database '{cfg.db_name}' has an older incompatible table schema "
                        "(e.g. 'users' is missing 'display_name').\n"
                        "Fix in phpMyAdmin (http://localhost:8072/):\n"
                        f"  - Either drop the empty tables inside '{cfg.db_name}', OR\n"
                        "  - Create a new empty utf8mb4 database (and grant access to contenthub_user) "
                        "and update DB_NAME in .env."
                    )
            missing_tables = set(Base.metadata.tables.keys()) - tables
            if missing_tables:
                print("NEEDS_MIGRATION")
            else:
                admin_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
                print("NEEDS_ADMIN" if admin_count == 0 else "READY")
finally:
    engine.dispose()
PY
)"

echo "==> Database status: $DB_STATUS"

if [[ "$MODE" == "--check" ]]; then
  echo "==> Preflight check passed."
  exit 0
fi

# 4. Auto-migrate empty/behind DB & initialize admin if needed
if [[ "$DB_STATUS" == "EMPTY_DB" || "$DB_STATUS" == "NEEDS_MIGRATION" ]]; then
  echo "==> Applying Alembic migrations..."
  (cd "$BACKEND_DIR" && "$ALEMBIC_BIN" upgrade head)
  DB_STATUS="NEEDS_ADMIN"
fi

if [[ "$DB_STATUS" == "NEEDS_ADMIN" ]]; then
  if [[ -t 0 ]]; then
    echo "==> No administrator account found. Let's create your local admin login:"
    (cd "$BACKEND_DIR" && "$VENV_PYTHON" -m app.cli init-admin)
  else
    echo "Notice: No admin user exists yet. Run once: (cd backend && .venv/bin/python -m app.cli init-admin)"
  fi
fi

# 5. Start both FastAPI and Nuxt in parallel with clean Ctrl+C shutdown
API_PID=""
WEB_PID=""

cleanup() {
  trap - INT TERM EXIT
  echo ""
  echo "==> Stopping ContentHub AI dev servers..."
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "$WEB_PID" ]] && kill "$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "==> Starting FastAPI backend on http://127.0.0.1:8100 ..."
(
  cd "$BACKEND_DIR"
  exec "$UVICORN_BIN" app.main:app --host 127.0.0.1 --port 8100 --reload
) &
API_PID=$!

echo "==> Starting Nuxt 4 frontend on http://127.0.0.1:3100 ..."
(
  cd "$FRONTEND_DIR"
  exec npm run dev
) &
WEB_PID=$!

echo ""
echo "============================================================"
echo " ContentHub AI is running!"
echo "   Frontend UI : http://127.0.0.1:3100"
echo "   Backend API : http://127.0.0.1:8100/api/v1/health"
echo "   Press Ctrl+C to stop both servers."
echo "============================================================"
echo ""

# Portable polling loop (compatible with macOS Bash 3.2)
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done

cleanup
