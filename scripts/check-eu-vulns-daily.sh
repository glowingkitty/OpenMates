#!/usr/bin/env bash
# Query OSV/NVD and report dependency observations with query coverage.
# Retains collection/reporting and existing manual arguments.
# Automatic agent launches were removed under TASK-7543.
# Dry runs do not persist security ledger reports. Existing schedules remain off.
# Future workflow requirements: TASK-8338. No replacement scheduler is installed.
# Architecture: docs/architecture/infrastructure/cronjobs.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRACKING_SEED="$SCRIPT_DIR/eu-vuln-processed.json"
TRACKING_FILE="$PROJECT_ROOT/logs/eu-vuln-processed.json"
DEPENDABOT_TRACKING_SEED="$SCRIPT_DIR/dependabot-processed.json"
DEPENDABOT_TRACKING_RUNTIME="$PROJECT_ROOT/logs/dependabot-processed.json"
DEPENDABOT_TRACKING="$DEPENDABOT_TRACKING_SEED"
LOCK_FILE="$PROJECT_ROOT/logs/eu-vuln-scanner.lock"
PROMPT_TEMPLATE="$SCRIPT_DIR/prompts/eu-vuln-analysis.md"

# Re-dispatch threshold: re-dispatch if still unresolved after this many days
REDISPATCH_AFTER_DAYS=7

# --- Parse CLI args ---
DRY_RUN=false
SUMMARY_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --summary) SUMMARY_ONLY=true; shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ "$DRY_RUN" != "true" && "$SUMMARY_ONLY" != "true" ]]; then
  # One persistent scanner instance owns its runtime state at a time.
  mkdir -p "$(dirname "$LOCK_FILE")"
  exec 200>"$LOCK_FILE"
  if ! flock -n 200; then
    echo "[eu-vulns] Another instance is already running. Exiting."
    exit 0
  fi
  if [[ ! -f "$TRACKING_FILE" ]]; then
    if [[ -f "$TRACKING_SEED" ]]; then
      cp "$TRACKING_SEED" "$TRACKING_FILE"
    else
      printf '{"last_run":"","processed":[]}\n' > "$TRACKING_FILE"
    fi
  fi
elif [[ ! -f "$TRACKING_FILE" ]]; then
  TRACKING_FILE="$TRACKING_SEED"
fi

if [[ -f "$DEPENDABOT_TRACKING_RUNTIME" ]]; then
  DEPENDABOT_TRACKING="$DEPENDABOT_TRACKING_RUNTIME"
fi

echo "[eu-vulns] Starting EU vulnerability source check at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

export TRACKING_FILE_PATH="$TRACKING_FILE"
export DEPENDABOT_TRACKING_PATH="$DEPENDABOT_TRACKING"
export PROJECT_ROOT
export REDISPATCH_AFTER_DAYS
export DRY_RUN
export SUMMARY_ONLY
export PROMPT_TEMPLATE_PATH="$PROMPT_TEMPLATE"
TODAY_DATE=$(date -u '+%Y-%m-%d')
export TODAY_DATE
# NVD_API_KEY is optional and inherited only when explicitly exported by the caller.

python3 "$SCRIPT_DIR/_eu_vuln_helper.py" check-vulns

echo "[eu-vulns] EU vulnerability check complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
