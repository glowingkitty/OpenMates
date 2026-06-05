#!/usr/bin/env bash
# =============================================================================
# OpenMates Weekly Technical Debt Scan
#
# Runs a deterministic read-only technical-debt scan, stores JSON/Markdown
# reports, then spawns a read-only OpenCode session to analyze the results and
# suggest the top 5 improvement steps with previous-run deltas considered.
#
# Triggered by system crontab (weekly on Sunday at 03:20 UTC):
#   20 3 * * 0 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/weekly-technical-debt.sh' >> /path/to/logs/technical-debt.log 2>&1
#
# Manual usage:
#   ./scripts/weekly-technical-debt.sh
#   ./scripts/weekly-technical-debt.sh --dry-run
#   ./scripts/weekly-technical-debt.sh --scan-only
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

DRY_RUN=false
SCAN_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --scan-only) SCAN_ONLY=true; shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

TODAY_DATE="$(date -u '+%Y-%m-%d')"
TECH_DEBT_JSON_REPORT="$PROJECT_ROOT/logs/nightly-reports/technical-debt.json"
TECH_DEBT_MARKDOWN_REPORT="$PROJECT_ROOT/logs/nightly-reports/technical-debt.md"
TECH_DEBT_STATE_FILE="$PROJECT_ROOT/scripts/.technical-debt-state.json"

export DRY_RUN PROJECT_ROOT TODAY_DATE TECH_DEBT_JSON_REPORT TECH_DEBT_MARKDOWN_REPORT
export PROMPT_TEMPLATE_PATH="$SCRIPT_DIR/prompts/technical-debt-analysis.md"

echo "[technical-debt] Starting weekly scan at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
SCAN_ARGS=(
  --json-output "$TECH_DEBT_JSON_REPORT"
  --markdown-output "$TECH_DEBT_MARKDOWN_REPORT"
  --state-file "$TECH_DEBT_STATE_FILE"
)
if [[ "$DRY_RUN" == "true" ]]; then
  SCAN_ARGS+=(--no-state-update)
fi

python3 "$SCRIPT_DIR/technical_debt_scan.py" \
  "${SCAN_ARGS[@]}"

if [[ "$SCAN_ONLY" == "true" ]]; then
  echo "[technical-debt] Scan-only mode complete."
  exit 0
fi

python3 "$SCRIPT_DIR/_technical_debt_helper.py" run-analysis
echo "[technical-debt] Weekly technical debt workflow complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
