#!/usr/bin/env bash
# Ingest the existing red-team snapshot through the digest adapter.
# Retains collection/reporting and existing manual arguments.
# Automatic agent launches were removed under TASK-7543.
# Dry runs do not persist security ledger reports. Existing schedules remain off.
# Future workflow requirements: TASK-8338. No replacement scheduler is installed.
# Architecture: docs/architecture/infrastructure/cronjobs.md
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
