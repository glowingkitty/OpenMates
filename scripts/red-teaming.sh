#!/usr/bin/env bash
# =============================================================================
# OpenMates Twice-Weekly Red Team Probe
#
# Simulates an external attacker probing app.dev.openmates.org and
# api.dev.openmates.org. Reads source code to identify attack vectors, then
# uses curl to non-destructively probe live endpoints.
#
# Runs in opencode plan mode for safety — can read files and run curl, but
# cannot modify code or data. Capped at 20 minutes.
#
# Features:
#   - Source code analysis to identify attack vectors
#   - Non-destructive endpoint probing (GET/HEAD/OPTIONS only)
#   - Strict guardrails: no admin tools, no localhost, no destructive requests
#   - Deduplication: skips previously reported findings
#   - 20-minute hard timeout
#
# Triggered by system crontab (Wed + Sat at 02:30 UTC):
#   30 2 * * 3,6 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/red-teaming.sh' >> /path/to/logs/red-teaming.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/red-teaming.sh
#   ./scripts/red-teaming.sh --dry-run   # print prompt without running opencode
#
# State files (.claude/ — gitignored):
#   .claude/security-audit-state.json      — shared with security-audit.sh
#   .claude/security-acknowledged.json     — shared with security-audit.sh
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

echo "[red-teaming] Starting red team probe at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

export DRY_RUN
export PROJECT_ROOT
export TODAY_DATE
TODAY_DATE=$(date -u '+%Y-%m-%d')
export JOB_TYPE="redteam"
export PROMPT_TEMPLATE_PATH="$SCRIPT_DIR/prompts/redteam-probe.md"

python3 "$SCRIPT_DIR/_security_helper.py" run-redteam

echo "[red-teaming] Red team probe complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
