#!/usr/bin/env bash
# Local aaPanel bootstrap. Requires existing server runtimes and a fresh dedicated DB.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="${APP_DIR:-$REPO_DIR/www/contenthub-ai}"
STORAGE_ROOT="${STORAGE_ROOT:-/www/contenthub-storage}"
RUN_USER="${RUN_USER:-www}"
MODE=setup
START_SERVICES=1

usage() {
  cat <<'HELP'
Usage: sudo bash scripts/setup-aapanel.sh [--check | --no-start | --start | --resume]

  --check     Read-only prerequisite checks; does not connect to or modify MySQL.
  --no-start  Configure, install, build, migrate a fresh DB, and create the admin.
  --start     Start/reload an already configured installation; no build/migration.
  --resume    Rebuild a fully migrated installation and finish admin setup if needed.

Run inside the Linux aaPanel server/container as root. The app processes and
dependency installation run as RUN_USER (default www), never as root.
Requires existing Python 3.12, Node >=22.12, npm, PM2, Supervisor, and MySQL.
Creates no database server, database, OS package, Nginx site, or global service.

Optional environment: APP_DIR, STORAGE_ROOT, RUN_USER, APP_URL; executable paths
PYTHON_BIN, NODE_BIN, NPM_BIN, PM2_BIN, SUPERVISORD_BIN, SUPERVISORCTL_BIN.
Keep APP_DIR and STORAGE_ROOT identical for setup and subsequent --start calls.
HELP
}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
note() { printf '\n%s\n' "$*"; }
trap 'printf "Setup stopped at line %s. No database reset was attempted.\n" "$LINENO" >&2' ERR

if (( $# > 1 )); then usage; exit 2; fi
case "${1:-}" in
  '') ;;
  --check) MODE=check ;;
  --no-start) START_SERVICES=0 ;;
  --start) MODE=start ;;
  --resume) MODE=resume ;;
  --help|-h) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac

[[ "$(uname -s)" == Linux ]] || die 'Run this inside the Linux aaPanel server/container, not macOS.'
[[ "$(id -u)" == 0 ]] || die 'Run as root; the script drops privileges to the app account.'
[[ "$RUN_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || die 'RUN_USER must be a simple Linux account name.'
id "$RUN_USER" >/dev/null 2>&1 || die "Create/install the aaPanel app account $RUN_USER first."
[[ "$(id -u "$RUN_USER")" != 0 ]] || die 'RUN_USER must not be root.'
RUN_GROUP="$(id -gn "$RUN_USER")"
command -v runuser >/dev/null || die 'runuser is required.'
command -v curl >/dev/null || die 'curl is required for runtime checks.'

as_app() { runuser -u "$RUN_USER" -- "$@"; }
resolve_tool() {
  local name="$1" fallback="$2" resolved
  resolved="${!name:-}"
  if [[ -z "$resolved" ]]; then resolved="$(command -v "$fallback" || true)"; fi
  [[ -n "$resolved" && -x "$resolved" && "$resolved" == /* ]] ||
    die "Install $fallback first or set $name to its absolute executable path."
  printf -v "$name" '%s' "$resolved"
}

resolve_tool PYTHON_BIN python3.12
resolve_tool NODE_BIN node
resolve_tool NPM_BIN npm
resolve_tool PM2_BIN pm2
resolve_tool SUPERVISORD_BIN supervisord
resolve_tool SUPERVISORCTL_BIN supervisorctl
# npm/PM2 use /usr/bin/env node; ensure the chosen Node is visible to the app user.
export PATH="$(dirname "$NODE_BIN"):$(dirname "$NPM_BIN"):$(dirname "$PM2_BIN"):$PATH"

[[ "$APP_DIR" == /* && -d "$APP_DIR/backend" && -d "$APP_DIR/frontend" ]] ||
  die 'APP_DIR must be an absolute path containing backend/ and frontend/.'
APP_DIR="$(cd -- "$APP_DIR" && pwd -P)"
[[ "$STORAGE_ROOT" == /* ]] || die 'STORAGE_ROOT must be an absolute directory.'
[[ ! -L "$STORAGE_ROOT" ]] || die 'STORAGE_ROOT must not be a symlink.'
STORAGE_ROOT="$("$PYTHON_BIN" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$STORAGE_ROOT")"
"$PYTHON_BIN" - "$STORAGE_ROOT" "$APP_DIR" "$REPO_DIR" <<'PY'
from pathlib import Path
import sys
storage, app, repo = (Path(value).resolve() for value in sys.argv[1:])
if any(storage == source or storage in source.parents or source in storage.parents for source in (app, repo)):
    raise SystemExit("STORAGE_ROOT must be a dedicated directory outside the repo, not its ancestor or descendant.")
allowed = {"images", "cache", "exports", "backups", "logs", "runtime"}
if storage.exists():
    if not storage.is_dir() or any(child.name not in allowed or child.is_symlink() or not child.is_dir() for child in storage.iterdir()):
        raise SystemExit("STORAGE_ROOT contains unrelated files or symlinks. Choose a dedicated app storage directory.")
PY
# Supervisor's ini interpolation and command parser require these characters escaped.
# Restrict only these rare path characters; paths containing spaces are supported.
for value in "$APP_DIR" "$STORAGE_ROOT" "$PYTHON_BIN" "$NODE_BIN" "$SUPERVISORD_BIN" "$SUPERVISORCTL_BIN"; do
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* && "$value" != *%* && "$value" != *\"* ]] ||
    die 'Paths must not contain newline, percent, or double-quote characters.'
done
case "$STORAGE_ROOT/" in "$APP_DIR/"*) die 'Persistent STORAGE_ROOT must be outside APP_DIR.' ;; esac
[[ ! -e "$APP_DIR/backend/.env" && ! -L "$APP_DIR/backend/.env" ]] ||
  die 'backend/.env overrides the app .env. Move its settings to the app-root .env before setup.'
[[ -f "$APP_DIR/backend/requirements.txt" && -f "$APP_DIR/frontend/package-lock.json" && -f "$APP_DIR/.env.example" ]] ||
  die 'Missing requirements.txt, frontend/package-lock.json, or .env.example; upload the complete tracked project.'

as_app "$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"'
as_app "$NODE_BIN" -e 'const [a,b]=process.versions.node.split(".").map(Number); if(a<22 || (a===22 && b<12)) { console.error("Node >=22.12 required"); process.exit(1) }'
as_app "$NPM_BIN" --version >/dev/null
# PM2 --version can create ~/.pm2; only test its executable in the read-only check.
for executable in "$PM2_BIN" "$SUPERVISORD_BIN" "$SUPERVISORCTL_BIN"; do
  as_app test -x "$executable" || die "$RUN_USER cannot execute $executable."
done
as_app "$SUPERVISORD_BIN" --version >/dev/null
as_app "$SUPERVISORCTL_BIN" --help >/dev/null

RUNTIME_DIR="$STORAGE_ROOT/runtime"
SUPERVISOR_CONFIG="$RUNTIME_DIR/supervisord.conf"
PM2_CONFIG="$RUNTIME_DIR/ecosystem.config.json"
export PM2_HOME="$RUNTIME_DIR/pm2"
export npm_config_cache="$RUNTIME_DIR/npm-cache"
export PIP_CACHE_DIR="$RUNTIME_DIR/pip-cache"
export XDG_CACHE_HOME="$RUNTIME_DIR/cache"

if [[ "$MODE" == check ]]; then
  note 'Prerequisites passed. No files, processes, or databases were changed.'
  printf 'Application: %s\nStorage: %s\nRun user: %s\n' "$APP_DIR" "$STORAGE_ROOT" "$RUN_USER"
  printf '%s\n' 'The setup step will validate the DB is empty before applying migrations.'
  exit 0
fi

check_ports() {
  "$PYTHON_BIN" - <<'PY'
import socket
for port in (3100, 8100):
    with socket.socket() as listener:
        # A just-stopped HTTP server can leave connections in TIME_WAIT.
        # Reuse permits a restart while an active listener still fails the bind.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"Port {port} is already in use. Stop only this app's old process or choose another server.")
PY
}

smoke_check() {
  local port status response ready=0
  for attempt in {1..20}; do
    if curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:3100/api/v1/health >/dev/null 2>&1 &&
       curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8100/api/v1/health >/dev/null 2>&1; then
      ready=1; break
    fi
    sleep 1
  done
  [[ "$ready" == 1 ]] || die "Services did not become healthy. Inspect logs in $STORAGE_ROOT/logs."
  for port in 3100 8100; do
    status="$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$port/api/v1/dashboard/summary")"
    [[ "$status" == 401 ]] || die "Protected dashboard on :$port returned $status; expected 401."
  done
  status="$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3100/login)"
  [[ "$status" == 200 ]] || die "Login returned $status; expected 200."
  response="$(curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:3100/api/v1/auth/status)"
  printf '%s' "$response" | "$PYTHON_BIN" -c 'import json,sys; d=json.load(sys.stdin); assert d.get("database_connected") is True and d.get("admin_initialized") is True, "DB/admin is not ready"'
  note 'Runtime checks passed: API/proxy health, initialized DB/admin, login, and protected dashboard.'
}

start_services() {
  [[ -f "$APP_DIR/.env" && -x "$APP_DIR/backend/.venv/bin/python" && -f "$APP_DIR/frontend/.output/server/index.mjs" ]] ||
    die 'Installation is incomplete. Run setup first.'
  [[ -f "$SUPERVISOR_CONFIG" && -f "$PM2_CONFIG" ]] || die 'Runtime config is missing. Use the same STORAGE_ROOT as setup.'
  # A live socket identifies our private Supervisor instance, not aaPanel's daemon.
  if as_app "$SUPERVISORCTL_BIN" -c "$SUPERVISOR_CONFIG" pid >/dev/null 2>&1; then
    as_app "$SUPERVISORCTL_BIN" -c "$SUPERVISOR_CONFIG" reread
    as_app "$SUPERVISORCTL_BIN" -c "$SUPERVISOR_CONFIG" update
    as_app "$SUPERVISORCTL_BIN" -c "$SUPERVISOR_CONFIG" restart contenthub-api
  else
    as_app "$SUPERVISORD_BIN" -c "$SUPERVISOR_CONFIG"
  fi
  as_app "$PM2_BIN" startOrReload "$PM2_CONFIG" --only contenthub-web --update-env
  as_app "$PM2_BIN" save --force
  smoke_check
}

if [[ "$MODE" == start ]]; then
  start_services
  exit 0
fi

check_ports
[[ ! -L "$APP_DIR/.env" ]] || die 'App .env must be a regular private file, not a symlink.'
if [[ "$MODE" == resume && ! -f "$APP_DIR/.env" ]]; then die '--resume requires the original app .env.'; fi
if [[ -e "$APP_DIR/backend/.venv" ]]; then
  as_app "$APP_DIR/backend/.venv/bin/python" -c 'import sys; assert sys.platform == "linux" and sys.version_info[:2] == (3, 12)' >/dev/null 2>&1 ||
    die 'Existing backend/.venv is not usable Linux Python 3.12. Move it aside and let setup rebuild it; do not upload a macOS venv.'
fi
if [[ -e "$APP_DIR/.env" ]]; then
  [[ -f "$APP_DIR/.env" ]] || die 'App .env is not a regular file.'
  note 'Preserving the existing app .env and encryption key.'
fi

note "Preparing app-owned dependencies and persistent storage for $RUN_USER."
# Only this app and its dedicated storage are touched, never other websites.
mkdir -p -- "$STORAGE_ROOT"/{images,cache,exports,backups,logs,runtime}
chown -R -- "$RUN_USER:$RUN_GROUP" "$APP_DIR"
chown -- "$RUN_USER:$RUN_GROUP" "$STORAGE_ROOT" "$STORAGE_ROOT"/{images,cache,exports,backups,logs,runtime}
chmod 700 -- "$RUNTIME_DIR" "$STORAGE_ROOT/backups" "$STORAGE_ROOT/logs"
if [[ -f "$APP_DIR/.env" ]]; then chmod 600 -- "$APP_DIR/.env"; fi
as_app "$PYTHON_BIN" -m venv "$APP_DIR/backend/.venv"
as_app "$APP_DIR/backend/.venv/bin/python" -m pip install -r "$APP_DIR/backend/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
  [[ -t 0 ]] || die 'First setup needs an interactive terminal to configure the DB.'
  note 'Enter the existing dedicated MySQL database connection. No database will be created or reset.'
  read -r -p "Browser URL [${APP_URL:-http://127.0.0.1:3100}]: " SETUP_APP_URL
  SETUP_APP_URL="${SETUP_APP_URL:-${APP_URL:-http://127.0.0.1:3100}}"
  read -r -p 'MySQL host [127.0.0.1]: ' SETUP_DB_HOST
  SETUP_DB_HOST="${SETUP_DB_HOST:-127.0.0.1}"
  read -r -p 'MySQL port [3306]: ' SETUP_DB_PORT
  SETUP_DB_PORT="${SETUP_DB_PORT:-3306}"
  read -r -p 'Dedicated database [contenthub_ai]: ' SETUP_DB_NAME
  SETUP_DB_NAME="${SETUP_DB_NAME:-contenthub_ai}"
  read -r -p 'Dedicated database user [contenthub_user]: ' SETUP_DB_USER
  SETUP_DB_USER="${SETUP_DB_USER:-contenthub_user}"
  read -r -s -p 'Database password: ' SETUP_DB_PASSWORD
  printf '\n'
  export SETUP_APP_URL SETUP_DB_HOST SETUP_DB_PORT SETUP_DB_NAME SETUP_DB_USER SETUP_DB_PASSWORD
  as_app "$APP_DIR/backend/.venv/bin/python" - "$APP_DIR" "$STORAGE_ROOT" <<'PY'
import json
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlsplit
from cryptography.fernet import Fernet

root, storage = map(Path, sys.argv[1:])
values = {
    "APP_ENV": "development", "APP_DEBUG": "false", "APP_TIMEZONE": "Asia/Manila",
    "APP_URL": os.environ["SETUP_APP_URL"], "API_BASE_URL": "http://127.0.0.1:8100",
    "CORS_ORIGINS": os.environ["SETUP_APP_URL"].rstrip("/"),
    "APP_SECRET_KEY": secrets.token_hex(32), "APP_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "DB_HOST": os.environ["SETUP_DB_HOST"], "DB_PORT": os.environ["SETUP_DB_PORT"],
    "DB_NAME": os.environ["SETUP_DB_NAME"], "DB_USER": os.environ["SETUP_DB_USER"],
    "DB_PASSWORD": os.environ["SETUP_DB_PASSWORD"], "STORAGE_ROOT": str(storage),
    "NUXT_API_PROXY_TARGET": "http://127.0.0.1:8100",
}
url = urlsplit(values["APP_URL"])
if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.query or url.fragment or url.path not in {"", "/"}:
    raise SystemExit("Browser URL must be an http(s) origin, without credentials/path/query.")
values["SESSION_COOKIE_SECURE"] = "true" if url.scheme == "https" else "false"
if not values["DB_USER"] or values["DB_USER"].lower() == "root" or not values["DB_PASSWORD"]:
    raise SystemExit("A non-root MySQL user and nonempty password are required.")
if not re.fullmatch(r"[A-Za-z0-9_]+", values["DB_NAME"]):
    raise SystemExit("Use a database name containing only letters, digits, and underscores.")
if not values["DB_PORT"].isdigit() or not 1 <= int(values["DB_PORT"]) <= 65535:
    raise SystemExit("Invalid MySQL port.")
if any("\n" in v or "\r" in v or "${" in v for v in values.values()):
    raise SystemExit("Settings must not contain newlines or ${...} dotenv substitutions.")
text = (root / ".env.example").read_text()
for key, value in values.items():
    line = key + "=" + json.dumps(value, ensure_ascii=False)
    pattern = re.compile(r"^" + re.escape(key) + r"=.*$", re.MULTILINE)
    text = pattern.sub(lambda _: line, text) if pattern.search(text) else text + "\n" + line + "\n"
with (root / ".env").open("x") as handle:
    handle.write(text)
os.chmod(root / ".env", 0o600)
print("Created private app .env with generated application keys.")
PY
  unset SETUP_DB_PASSWORD SETUP_APP_URL SETUP_DB_HOST SETUP_DB_PORT SETUP_DB_NAME SETUP_DB_USER
fi

note 'Checking dedicated DB and configuration without exposing credentials.'
DB_STATE="$(
  cd -- "$APP_DIR/backend"
  as_app .venv/bin/python - "$STORAGE_ROOT" "$MODE" <<'PY'
from pathlib import Path
import sys
from alembic.migration import MigrationContext
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet
from sqlalchemy import inspect, text
from app.config import get_settings
from app.database import create_mysql_engine
from app.models import Base

cfg = get_settings()
if cfg.is_root_db_user or not cfg.has_configured_db_password:
    raise SystemExit("Configure a dedicated non-root DB user and password in app .env.")
if len(cfg.app_secret_key) < 32 or cfg.app_secret_key.startswith("CHANGE_ME"):
    raise SystemExit("Configure a strong APP_SECRET_KEY in app .env.")
try:
    Fernet(cfg.app_encryption_key.encode())
except Exception:
    raise SystemExit("APP_ENCRYPTION_KEY is invalid; preserve the original key for restored data.")
if cfg.resolved_storage_root.resolve() != Path(sys.argv[1]).resolve():
    raise SystemExit("Existing .env STORAGE_ROOT differs. Re-run with matching STORAGE_ROOT; no files were moved.")
engine = create_mysql_engine(cfg)
try:
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()" )).scalar_one()
        if count:
            if sys.argv[2] != "resume":
                raise SystemExit("Database is not empty. Setup only migrates a fresh DB. Use --start for an installed app, or --resume to finish a fully migrated setup. For a duplicate, restore a separate DB plus the original encryption key/storage and follow the restore guide. No tables were changed.")
            heads = set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
            current = set(MigrationContext.configure(connection).get_current_heads())
            if current != heads:
                raise SystemExit("Resume requires DB revision to equal this code's Alembic head. The DB is older, unknown, or partially migrated. Restore a verified backup or use a new empty DB; no migration/reset was attempted.")
            inspector = inspect(connection)
            if not set(Base.metadata.tables).issubset(set(inspector.get_table_names())):
                raise SystemExit("Resume found missing application tables despite the Alembic revision. Restore a verified backup or choose a new empty DB.")
            for name, table in Base.metadata.tables.items():
                actual_columns = {column["name"] for column in inspector.get_columns(name)}
                if not {column.name for column in table.columns}.issubset(actual_columns):
                    raise SystemExit("Resume found an incompatible application schema despite the Alembic revision. Use a new empty DB or a reviewed restore plan.")
            users = connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
            print("needs-admin" if users == 0 else "initialized")
        elif sys.argv[2] == "resume":
            raise SystemExit("Resume requires a fully migrated DB; run normal setup for an empty DB.")
        else:
            print("fresh")
except SystemExit:
    raise
except Exception:
    raise SystemExit("Cannot inspect the configured DB. Check MySQL, database/user access, host, and port in .env. Credentials were not printed.")
finally:
    engine.dispose()
PY
 )"
note "Database setup state: $DB_STATE."
(
  cd -- "$APP_DIR/backend"
  as_app .venv/bin/python -m app.cli check-db
)

note 'Building the locked frontend dependencies.'
(
  cd -- "$APP_DIR/frontend"
  as_app "$NPM_BIN" ci --include=dev
  as_app "$NPM_BIN" run build
)

as_app "$PYTHON_BIN" - "$APP_DIR" "$STORAGE_ROOT" "$NODE_BIN" <<'PY'
import json
from pathlib import Path
import shlex
import sys

app, storage = map(Path, sys.argv[1:3])
node = sys.argv[3]
runtime = storage / "runtime"
backend = app / "backend"
command = shlex.join([str(backend / ".venv/bin/python"), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8100", "--workers", "2"])
config = f"""[unix_http_server]
file={runtime}/supervisor.sock
chmod=0700

[supervisord]
logfile={storage}/logs/supervisord.log
logfile_maxbytes=10MB
logfile_backups=3
pidfile={runtime}/supervisord.pid
childlogdir={storage}/logs

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://{runtime}/supervisor.sock

[program:contenthub-api]
directory={backend}
command={command}
autostart=true
autorestart=unexpected
startsecs=3
stopasgroup=true
killasgroup=true
redirect_stderr=true
stdout_logfile={storage}/logs/api.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
environment=PYTHONUNBUFFERED="1",TZ="Asia/Manila"
"""
(runtime / "supervisord.conf").write_text(config)
ecosystem = {"apps": [{
    "name": "contenthub-web", "cwd": str(app / "frontend"),
    "script": ".output/server/index.mjs", "interpreter": node,
    "instances": 1, "exec_mode": "fork", "max_memory_restart": "512M",
    "out_file": str(storage / "logs/frontend-out.log"),
    "error_file": str(storage / "logs/frontend-error.log"),
    "env": {"NODE_ENV": "production", "NITRO_HOST": "127.0.0.1", "NITRO_PORT": "3100",
            "NUXT_API_PROXY_TARGET": "http://127.0.0.1:8100", "TZ": "Asia/Manila"},
}]}
(runtime / "ecosystem.config.json").write_text(json.dumps(ecosystem, indent=2) + "\n")
print("Generated private app-only Supervisor and PM2 configs.")
PY

if [[ "$DB_STATE" == fresh ]]; then
  note 'Applying initial schema to the verified empty DB.'
  (
    cd -- "$APP_DIR/backend"
    as_app .venv/bin/alembic upgrade head
  )
fi
if [[ "$DB_STATE" == fresh || "$DB_STATE" == needs-admin ]]; then
  note 'Creating the single administrator. If interrupted, re-run with --resume.'
  (
    cd -- "$APP_DIR/backend"
    as_app .venv/bin/python -m app.cli init-admin
  )
fi

if [[ "$START_SERVICES" == 1 ]]; then
  start_services
  # Record only a clean Git checkout after its build/DB/runtime checks succeeded.
  # Archive installs remain usable but must become a clone before automatic updates.
  if command -v git >/dev/null &&
     [[ "$(git -C "$REPO_DIR" rev-parse --show-toplevel 2>/dev/null || true)" == "$REPO_DIR" ]] &&
     [[ -z "$(git -C "$REPO_DIR" status --porcelain --untracked-files=all)" ]]; then
    git -C "$REPO_DIR" rev-parse HEAD > "$RUNTIME_DIR/deployed-commit"
  fi
fi
note 'Local app setup completed.'
printf '%s\n' 'Add the aaPanel Nginx site/proxy described in README.md. Reboot startup is a separate step.'
printf 'Private service configs: %s\nLogs: %s\n' "$RUNTIME_DIR" "$STORAGE_ROOT/logs"
