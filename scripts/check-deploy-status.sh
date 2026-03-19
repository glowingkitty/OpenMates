#!/usr/bin/env bash
# =============================================================================
# OpenMates Deploy Status Checker
#
# Runs every 2 minutes via cron. Checks if a local git commit was made in the
# last 5 minutes on the dev branch. If so, queries the Vercel API for the
# latest deployment status. If the deployment has ERRORed (and hasn't already
# been dispatched), runs an opencode build-mode session to investigate and fix.
#
# Logic:
#   1. Check local git log — any commit in the last 5 minutes? If not, exit 0.
#   2. Query Vercel API for the latest deployment on the dev branch.
#   3. If status is not ERROR/CANCELED, exit 0.
#   4. If this deploy ID was already dispatched (state file), exit 0.
#   5. Fetch the Vercel build log (errors + warnings).
#   6. Dispatch opencode in build mode with the log + commit context as prompt.
#   7. Record the deploy ID in state file to prevent re-dispatch.
#
# Crontab entry (add via: crontab -e):
#   */2 * * * * /home/superdev/projects/OpenMates/scripts/check-deploy-status.sh >> /home/superdev/projects/OpenMates/logs/deploy-checker.log 2>&1
#
# Can also be run manually:
#   ./scripts/check-deploy-status.sh
#   ./scripts/check-deploy-status.sh --dry-run   # show prompt, skip opencode
#   ./scripts/check-deploy-status.sh --force     # skip the recent-commit guard
#
# Env vars (sourced from .env automatically):
#   VERCEL_TOKEN   — required; Vercel personal/team access token
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

# Ensure opencode is on PATH
export PATH="/home/superdev/.npm-global/bin:$PATH"

# --- Parse CLI args ---
DRY_RUN=false
FORCE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --force)   FORCE=true;   shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

export DRY_RUN
export PROJECT_ROOT

echo "[deploy-checker] === Run at $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="

if [[ "$FORCE" == "true" ]]; then
  echo "[deploy-checker] --force: bypassing recent-commit guard (set via shell, not passed to Python)"
  # Temporarily make a dummy recent commit marker by passing a sentinel env var
  export DEPLOY_CHECKER_FORCE=true
fi

python3 "$SCRIPT_DIR/_deploy_checker_helper.py" run

echo "[deploy-checker] === Done at $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
