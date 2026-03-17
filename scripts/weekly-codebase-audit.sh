#!/usr/bin/env bash
# =============================================================================
# OpenMates Twice-Weekly Codebase Health Audit
#
# Runs a "top 5 improvements" codebase audit using opencode, covering security,
# performance, reliability, code quality, and architecture. Only analyses files
# changed since the last audit — unchanged files are skipped to avoid noise.
#
# Triggered by system crontab (Mon + Thu at 02:00 UTC):
#   0 2 * * 1,4 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/weekly-codebase-audit.sh' >> /path/to/logs/codebase-audit.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/weekly-codebase-audit.sh
#   ./scripts/weekly-codebase-audit.sh --force   # ignore last-audit SHA, analyse all recent changes
#   ./scripts/weekly-codebase-audit.sh --dry-run # show what would be sent to opencode
#
# State file: scripts/.audit-state.json (committed to repo — tracks last audit SHA and date)
#
# No env vars required beyond what opencode itself needs.
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

# --- Parse CLI args ---
FORCE=false
DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "[audit] Starting codebase health audit at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

export FORCE
export DRY_RUN
export PROJECT_ROOT
export TODAY_DATE
TODAY_DATE=$(date -u '+%Y-%m-%d')
export AUDIT_STATE_FILE="$SCRIPT_DIR/.audit-state.json"
export PROMPT_TEMPLATE_PATH="$SCRIPT_DIR/prompts/codebase-audit.md"

python3 "$SCRIPT_DIR/_audit_helper.py" run-audit

echo "[audit] Codebase health audit complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
