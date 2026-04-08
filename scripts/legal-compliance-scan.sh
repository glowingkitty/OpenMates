#!/usr/bin/env bash
# =============================================================================
# OpenMates Twice-Weekly Legal & Compliance Scan
#
# Runs a deep legal/compliance scan using the `legal-compliance-auditor` agent
# to produce a ranked Top 10 of legal & compliance recommendations across
# GDPR, EU AI Act, ePrivacy/DDG, consumer protection, DPIA triggers, and more.
#
# Schedule (via system crontab — Mon + Thu, NEVER on weekends):
#   # Monday 03:00 UTC — full deep scan
#   0 3 * * 1 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/legal-compliance-scan.sh full' >> /path/to/logs/legal-compliance.log 2>&1
#   # Thursday 03:00 UTC — commit-delta scan
#   0 3 * * 4 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/legal-compliance-scan.sh delta' >> /path/to/logs/legal-compliance.log 2>&1
#
# Manual invocation:
#   ./scripts/legal-compliance-scan.sh full           # Monday-style full scan
#   ./scripts/legal-compliance-scan.sh delta          # Thursday-style delta scan
#   ./scripts/legal-compliance-scan.sh full --dry-run # print prompt only
#   ./scripts/legal-compliance-scan.sh delta --dry-run
#
# Output files (all overwritten each run):
#   logs/nightly-reports/legal-compliance.json           — daily meeting feed
#   docs/architecture/compliance/top-10-recommendations.md
#   scripts/.legal-compliance-state.json                 — state for next run
#
# Related files:
#   scripts/_legal_compliance_helper.py                  — Python orchestrator
#   scripts/prompts/legal-compliance-full.md             — Monday prompt
#   scripts/prompts/legal-compliance-delta.md            — Thursday prompt
#   .claude/agents/legal-compliance-auditor.md           — agent definition
#   docs/architecture/compliance/acknowledgments.yml     — justified exceptions
#   docs/architecture/compliance/gdpr-audit.md           — baseline audit
#
# The daily meeting helper (_daily_meeting_helper.py) auto-discovers the
# nightly report JSON and surfaces the Top 10 in the Monday + Thursday
# morning meetings automatically — no additional integration needed.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCKFILE="/tmp/openmates-legal-compliance-scan.lock"

# Ensure npm-global bin is on PATH (cron runs with minimal PATH)
export PATH="/home/superdev/.local/bin:/home/superdev/.npm-global/bin:$PATH"

# Source .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

# --- Parse CLI args ---
SCAN_TYPE=""
DRY_RUN=false

show_help() {
  sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    full|delta) SCAN_TYPE="$1"; shift ;;
    --dry-run)  DRY_RUN=true; shift ;;
    --help|-h)  show_help; exit 0 ;;
    *) echo "Unknown option: $1"; echo "Usage: $0 <full|delta> [--dry-run]"; exit 1 ;;
  esac
done

if [[ -z "$SCAN_TYPE" ]]; then
  echo "ERROR: scan type required. Usage: $0 <full|delta> [--dry-run]"
  exit 1
fi

# Refuse to run on weekends (defensive — crontab should already prevent this)
DOW=$(date -u '+%u')  # 1=Mon ... 7=Sun
if [[ "$DOW" == "6" || "$DOW" == "7" ]]; then
  if [[ "$DRY_RUN" != "true" ]]; then
    echo "[legal-compliance] Refusing to run on weekend (DOW=$DOW). Use --dry-run to override for testing."
    exit 0
  fi
fi

echo "[legal-compliance] Starting $SCAN_TYPE scan at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Prevent double-runs
exec 200>"$LOCKFILE"
if ! flock -n 200; then
  echo "[legal-compliance] Another instance is already running (lockfile: $LOCKFILE). Exiting."
  exit 0
fi

export DRY_RUN
export PROJECT_ROOT
export TODAY_DATE
TODAY_DATE=$(date -u '+%Y-%m-%d')
export STATE_FILE="$SCRIPT_DIR/.legal-compliance-state.json"
export FULL_PROMPT_PATH="$SCRIPT_DIR/prompts/legal-compliance-full.md"
export DELTA_PROMPT_PATH="$SCRIPT_DIR/prompts/legal-compliance-delta.md"
export ACKNOWLEDGMENTS_PATH="$PROJECT_ROOT/docs/architecture/compliance/acknowledgments.yml"

if [[ "$SCAN_TYPE" == "full" ]]; then
  if [[ "$DRY_RUN" == "true" ]]; then
    python3 "$SCRIPT_DIR/_legal_compliance_helper.py" dry-run-full
  else
    python3 "$SCRIPT_DIR/_legal_compliance_helper.py" run-full-scan
  fi
elif [[ "$SCAN_TYPE" == "delta" ]]; then
  if [[ "$DRY_RUN" == "true" ]]; then
    python3 "$SCRIPT_DIR/_legal_compliance_helper.py" dry-run-delta
  else
    python3 "$SCRIPT_DIR/_legal_compliance_helper.py" run-delta-scan
  fi
fi

echo "[legal-compliance] $SCAN_TYPE scan complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
