#!/usr/bin/env bash
# =============================================================================
# OpenMates Twice-Weekly Codebase Health Audit
#
# Runs a "top 5 improvements" codebase audit using opencode in plan mode.
# Uses recent git log (last 2 weeks) as context — opencode reads the actual
# files itself using its file tools.
#
# Triggered by system crontab (Mon + Thu at 02:00 UTC):
#   0 2 * * 1,4 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/weekly-codebase-audit.sh' >> /path/to/logs/codebase-audit.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/weekly-codebase-audit.sh
#   ./scripts/weekly-codebase-audit.sh --dry-run   # print prompt without running opencode
#
# State file: scripts/.audit-state.json (tracks last audit date and findings summary)
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
DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "[audit] Starting codebase health audit at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

export DRY_RUN
export PROJECT_ROOT
export TODAY_DATE
TODAY_DATE=$(date -u '+%Y-%m-%d')
export AUDIT_STATE_FILE="$SCRIPT_DIR/.audit-state.json"
export PROMPT_TEMPLATE_PATH="$SCRIPT_DIR/prompts/codebase-audit.md"

python3 "$SCRIPT_DIR/_audit_helper.py" run-audit

echo "[audit] Codebase health audit complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
