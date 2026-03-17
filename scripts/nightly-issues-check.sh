#!/usr/bin/env bash
# =============================================================================
# OpenMates Nightly Issues Checker
#
# Checks for open user-reported issues from the past 24 hours and determines
# whether each has been addressed in a git commit. For any unresolved issues,
# starts an opencode analysis session to investigate and suggest fixes.
#
# Triggered by a system crontab entry:
#   0 4 * * * bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/nightly-issues-check.sh' >> /path/to/logs/nightly-issues.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/nightly-issues-check.sh
#   ./scripts/nightly-issues-check.sh --all   # check all issues, not just last 24h
#
# Env vars (sourced from .env by the crontab entry):
#   ADMIN_API_KEY           — Bearer token for the admin debug API (required)
#   INTERNAL_API_URL        — base URL for the API (default: http://localhost:8000)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source .env if present (makes manual invocation work)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

echo "[nightly-issues] Starting nightly issues check at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Require ADMIN_API_KEY
if [[ -z "${ADMIN_API_KEY:-}" ]]; then
  echo "[nightly-issues] ERROR: ADMIN_API_KEY not set — cannot fetch issues. Exiting."
  exit 1
fi

# Run the Python checker
python3 "$SCRIPT_DIR/_issues_checker.py" check-issues

echo "[nightly-issues] Nightly issues check complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
