#!/usr/bin/env bash
# =============================================================================
# OpenMates Nightly Quick-Wins Scanner
#
# Uses Claude (Haiku, plan mode) for deep codebase exploration to find quick-win
# improvements: performance issues, UX gaps, security gaps, and code quality.
# Does NOT scan for dead code/imports (covered by nightly-dead-code-removal.sh).
#
# Scope strategy:
#   - Always scans files changed in the last 7 days (highest value)
#   - Then explores one rotating sector with remaining time:
#     Mon: frontend components, Tue: backend services, Wed: embeds,
#     Thu: stores/services, Fri: full scan
#
# Output: logs/nightly-reports/quick-wins.json — top 5 recommendations
# Claude writes this file incrementally so a hard kill still produces output.
#
# Timeouts:
#   - 25 min soft limit (instruction in prompt — Claude wraps up and summarises)
#   - 30 min hard kill (process terminated, partial results already on disk)
#
# Triggered by system crontab (nightly at 02:15 UTC):
#   15 2 * * * bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/nightly-quick-wins.sh' >> /path/to/logs/quick-wins.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/nightly-quick-wins.sh
#   ./scripts/nightly-quick-wins.sh --dry-run   # show prompt without running Claude
#
# No env vars required beyond standard PATH.
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

echo "[quick-wins] Starting nightly quick-wins scan at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

export DRY_RUN
export PROJECT_ROOT
TODAY_DATE=$(date -u '+%Y-%m-%d')
export TODAY_DATE
export SCAN_TYPE="quick-wins"
export PROMPT_TEMPLATE_PATH="$SCRIPT_DIR/prompts/quick-wins-scan.md"

python3 "$SCRIPT_DIR/_nightly_scanner_helper.py" run-quick-wins

echo "[quick-wins] Nightly quick-wins scan complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
