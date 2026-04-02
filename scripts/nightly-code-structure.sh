#!/usr/bin/env bash
# =============================================================================
# OpenMates Nightly Code Structure Cleanup Scanner
#
# Uses Claude (Haiku, plan mode) to scan for code structure and repository
# hygiene issues: gitignore gaps, open-source readiness, folder organization,
# naming inconsistencies, and stale artifacts.
#
# Suggestions only — no code changes are made.
#
# Scope strategy:
#   - Always scans files changed in the last 7 days (highest value)
#   - Then explores one rotating sector with remaining time:
#     Mon: frontend components, Tue: backend services, Wed: embeds,
#     Thu: stores/services, Fri: full scan
#
# Output: logs/nightly-reports/code-structure.json — top 10 recommendations
# Claude writes this file incrementally so a hard kill still produces output.
#
# Timeouts:
#   - 25 min soft limit (instruction in prompt — Claude wraps up and summarises)
#   - 30 min hard kill (process terminated, partial results already on disk)
#
# Triggered by system crontab (nightly at 02:50 UTC):
#   50 2 * * * bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/nightly-code-structure.sh' >> /path/to/logs/code-structure.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/nightly-code-structure.sh
#   ./scripts/nightly-code-structure.sh --dry-run   # show prompt without running Claude
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

echo "[code-structure] Starting nightly code structure scan at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

export DRY_RUN
export PROJECT_ROOT
TODAY_DATE=$(date -u '+%Y-%m-%d')
export TODAY_DATE
export SCAN_TYPE="code-structure"
export PROMPT_TEMPLATE_PATH="$SCRIPT_DIR/prompts/code-structure-scan.md"

python3 "$SCRIPT_DIR/_nightly_scanner_helper.py" run-code-structure

echo "[code-structure] Nightly code structure scan complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
