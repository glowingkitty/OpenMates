#!/usr/bin/env bash
# =============================================================================
# OpenMates Twice-Weekly Security Audit
#
# Runs a focused security code review using claude in plan mode. Identifies
# the top 5 security issues, provides realistic risk assessments, and suggests
# fixes (without implementing them).
#
# Features:
#   - Deduplication: skips files unchanged since last audit
#   - Finding memory: does not re-report known issues
#   - Acknowledge support: manually suppress accepted risks
#   - Monthly full sweep: forces a complete review every 30 days
#
# Triggered by system crontab (Tue + Fri at 02:30 UTC):
#   30 2 * * 2,5 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/security-audit.sh' >> /path/to/logs/security-audit.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/security-audit.sh
#   ./scripts/security-audit.sh --dry-run   # print prompt without running claude
#
# State files (.claude/ — gitignored):
#   .claude/security-audit-state.json      — findings, file hashes, run history
#   .claude/security-acknowledged.json     — manually acknowledged risks
#
# No env vars required beyond what claude itself needs.
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

echo "[security-audit] Starting security audit at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

export DRY_RUN
export PROJECT_ROOT
export TODAY_DATE
TODAY_DATE=$(date -u '+%Y-%m-%d')
export JOB_TYPE="audit"
export PROMPT_TEMPLATE_PATH="$SCRIPT_DIR/prompts/security-audit.md"

python3 "$SCRIPT_DIR/_security_helper.py" run-audit

echo "[security-audit] Security audit complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
