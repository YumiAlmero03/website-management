#!/usr/bin/env bash
# Run manually, from aaPanel Cron, or as the post-pull Git Manager script.
# All functions are parsed before main runs, so a fast-forward can update this file.
set -Eeuo pipefail
umask 077

usage() {
  cat <<'HELP'
Usage: STORAGE_ROOT=/www/wwwroot/.contenthub-storage bash scripts/update-aapanel.sh

Run as root inside the Linux aaPanel server after initial setup. Requires a Git
clone, noninteractive read access to origin, and the setup script's prerequisites.
DEPLOY_BRANCH defaults to main; RUN_USER defaults to www. Use the same STORAGE_ROOT
and runtime PATH as initial setup. The script fetches only that branch, accepts
fast-forwards, stops this app, rebuilds, and restarts it. Brief downtime is expected.
Schema/migration changes require a separate reviewed database migration.
HELP
}

die() { printf 'Update stopped: %s\n' "$*" >&2; exit 1; }
as_app() { runuser -u "$RUN_USER" -- "$@" 9>&-; }

main() {
  if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then usage; return; fi
  (( $# == 0 )) || { usage; return 2; }
  [[ "$(uname -s)" == Linux && "$(id -u)" == 0 ]] || die 'Run as root inside Linux aaPanel.'
  local script_dir repo app runtime branch old target applied api_pid changed
  local python_bin pm2_bin supervisorctl_bin
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
  repo="$(cd -- "$script_dir/.." && pwd -P)"
  app="$repo/www/contenthub-ai"
  # Setup supports custom APP_DIR, but this updater owns this monorepo app only.
  export APP_DIR="$app"
  export STORAGE_ROOT="${STORAGE_ROOT:-/www/contenthub-storage}"
  export RUN_USER="${RUN_USER:-www}"
  branch="${DEPLOY_BRANCH:-main}"
  [[ "$branch" != -* ]] && git check-ref-format "refs/heads/$branch" >/dev/null || die 'Invalid DEPLOY_BRANCH.'
  for changed in git flock runuser; do command -v "$changed" >/dev/null || die "Install $changed first."; done
  cd -- "$repo"
  [[ "$(git rev-parse --show-toplevel 2>/dev/null)" == "$repo" ]] || die 'Use a Git clone at this directory, not a source archive.'
  [[ "$(git symbolic-ref --quiet --short HEAD)" == "$branch" ]] || die "Checkout the configured deployment branch ($branch) first."
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] || die 'The server checkout has local changes. Preserve/reconcile them before deploying.'
  [[ -f "$app/.env" && ! -L "$app/.env" ]] || die 'Complete initial setup with a private app .env first.'
  [[ ! -e "$app/backend/.env" ]] || die 'Remove the unexpected backend/.env override after preserving its settings.'

  # Reuse setup's runtime/path/user/storage validation, without changing anything.
  bash "$repo/scripts/setup-aapanel.sh" --check
  python_bin="${PYTHON_BIN:-$(command -v python3.12)}"
  pm2_bin="${PM2_BIN:-$(command -v pm2)}"
  supervisorctl_bin="${SUPERVISORCTL_BIN:-$(command -v supervisorctl)}"
  STORAGE_ROOT="$("$python_bin" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$STORAGE_ROOT")"
  export STORAGE_ROOT
  runtime="$STORAGE_ROOT/runtime"
  [[ -d "$runtime" && -f "$runtime/supervisord.conf" && -f "$runtime/ecosystem.config.json" ]] || die 'Initial setup/service configuration is incomplete.'
  (
    cd -- "$app/backend"
    as_app .venv/bin/python - "$STORAGE_ROOT" <<'PY'
from pathlib import Path
import sys
from app.config import get_settings

if get_settings().resolved_storage_root.resolve() != Path(sys.argv[1]).resolve():
    raise SystemExit("STORAGE_ROOT differs from this app's .env. No services were stopped.")
PY
  )
  # util-linux flock releases the lock even if a deployment exits or is interrupted.
  exec 9>"$runtime/deploy.lock"
  flock -n 9 || { printf 'Another update is running; skipped.\n'; return; }
  export GIT_TERMINAL_PROMPT=0
  export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes}"
  # Suppress transport output: an HTTPS remote URL may contain a credential.
  git fetch --quiet --no-tags origin "refs/heads/$branch:refs/remotes/origin/$branch" >/dev/null 2>&1 ||
    die 'Fetch failed. Check outbound network and noninteractive Git credentials for the root deployment account.'
  old="$(git rev-parse HEAD)"
  target="$(git rev-parse "refs/remotes/origin/$branch^{commit}")"
  applied="$(cat "$runtime/deployed-commit" 2>/dev/null || true)"
  [[ "$applied" =~ ^[0-9a-f]{40,64}$ ]] ||
    die 'Missing successful deployment baseline. On the known installed commit, complete setup --resume with this storage path before enabling automatic updates. See README.md.'
  if [[ "$old" == "$target" && "$applied" == "$target" ]]; then
    printf 'Already deployed %s.\n' "${target:0:12}"
    return
  fi
  git merge-base --is-ancestor "$old" "$target" || die 'Remote history diverged. Reconcile it manually; no reset or force checkout was performed.'

  # Never let Git replace the installed secrets with a newly tracked dotenv file.
  if git cat-file -e "$target:www/contenthub-ai/.env" 2>/dev/null ||
     git cat-file -e "$target:www/contenthub-ai/backend/.env" 2>/dev/null; then
    die 'The target commit tracks an app .env file. Remove secrets from Git before deploying.'
  fi
  # Use the last successful deployment as the comparison base on retries, including
  # after Git Manager has already pulled the new commit into the working tree.
  git cat-file -e "$applied^{commit}" 2>/dev/null || die 'Last deployed commit is missing. Review deployment history manually.'
  changed="$applied"
  [[ -z "$(git diff --name-only "$changed" "$target" -- www/contenthub-ai/backend/migrations www/contenthub-ai/backend/alembic.ini)" ]] ||
    die 'This update changes database migrations. Back up and migrate the dedicated app DB manually, then complete the deployment manually as described in README.md.'

  printf 'Deploying %s -> %s on %s.\n' "${old:0:12}" "${target:0:12}" "$branch"
  export PM2_HOME="$runtime/pm2"
  # Establish a known Node path for npm/PM2 before dropping privileges.
  export PATH="$(dirname "${NODE_BIN:-$(command -v node)}"):$(dirname "$pm2_bin"):$PATH"
  # Stop only processes in this app's private Supervisor instance and PM2 home.
  if as_app "$supervisorctl_bin" -c "$runtime/supervisord.conf" pid >/dev/null 2>&1; then
    api_pid="$(as_app "$supervisorctl_bin" -c "$runtime/supervisord.conf" pid contenthub-api)"
    if [[ "$api_pid" =~ ^[1-9][0-9]*$ ]]; then
      as_app "$supervisorctl_bin" -c "$runtime/supervisord.conf" stop contenthub-api
    fi
  fi
  if as_app "$pm2_bin" describe contenthub-web >/dev/null 2>&1; then
    as_app "$pm2_bin" stop contenthub-web
  fi
  # All following commands operate only on this app. A failed build remains stopped
  # and can be retried; recording success only after smoke checks avoids false skips.
  trap 'printf "Deployment failed. This app may be stopped; inspect the task log, fix the error, then rerun update-aapanel.sh. No automatic database changes or rollback were attempted.\n" >&2' ERR
  git merge --ff-only --quiet "$target" >/dev/null 2>&1 || die 'Fast-forward failed; app processes may be stopped. Preserve any conflicting local files.'
  bash "$repo/scripts/setup-aapanel.sh" --resume 9>&-
  printf '%s\n' "$target" > "$runtime/deployed-commit"
  printf 'Deployed %s; application smoke checks passed.\n' "${target:0:12}"
}

main "$@"
