#!/usr/bin/env bash
# =============================================================================
# OpenMates Nightly Dead Code Removal
#
# Runs the dead code detector (scripts/find_dead_code.py), takes up to MAX_FINDINGS
# matches, builds a prompt, and delegates to claude (build mode) to safely remove
# the dead code. Runs 1 hour before the daily test suite (03:00 UTC) so any
# breakage is caught immediately by tests.
#
# Processing logic:
#   1. Run find_dead_code.py --json --limit MAX_FINDINGS_PER_CAT (100) to get candidates
#   2. Skip run if total findings == 0 (nothing to do)
#   3. Skip run if HEAD SHA unchanged since last run (no new commits → no new dead code)
#   4. Cap to MAX_FINDINGS total (prefer high-confidence items first)
#   5. Build a structured prompt with the findings + project context
#   6. Run claude in build mode to remove the dead code
#   7. Update state file (.dead-code-removal-state.json)
#
# Triggered by system crontab (runs 1 hour before tests at 03:00 UTC):
#   0 2 * * * bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/nightly-dead-code-removal.sh' >> /path/to/logs/dead-code-removal.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/nightly-dead-code-removal.sh
#   ./scripts/nightly-dead-code-removal.sh --dry-run   # show what would be sent, no claude
#   ./scripts/nightly-dead-code-removal.sh --force     # skip SHA-unchanged guard
#   ./scripts/nightly-dead-code-removal.sh --category python   # only one category
#
# No env vars required beyond standard PATH.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$SCRIPT_DIR/.dead-code-removal-state.json"
PROMPT_TEMPLATE="$SCRIPT_DIR/prompts/dead-code-removal.md"

MAX_FINDINGS_PER_CAT=100  # per-category limit fed to find_dead_code.py
MAX_FINDINGS_TOTAL=300    # hard cap on items sent to claude in one session

# Source .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

# --- Parse CLI args ---
DRY_RUN=false
FORCE=false
CATEGORY="all"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --force)   FORCE=true;   shift ;;
    --category) CATEGORY="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "[dead-code] Starting nightly dead code removal at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# --- SHA-unchanged guard ---
CURRENT_SHA=$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
LAST_SHA=""
if [[ -f "$STATE_FILE" ]]; then
  LAST_SHA=$(python3 -c "
import json, sys
try:
  d = json.load(open('$STATE_FILE'))
  print(d.get('last_run_sha', ''))
except Exception:
  print('')
" 2>/dev/null || echo "")
fi

if [[ "$FORCE" != "true" && -n "$LAST_SHA" && "$LAST_SHA" == "$CURRENT_SHA" ]]; then
  echo "[dead-code] HEAD SHA unchanged since last run ($CURRENT_SHA) — skipping (use --force to override)."
  exit 0
fi

echo "[dead-code] HEAD SHA: $CURRENT_SHA"

# --- Run dead code detector ---
echo "[dead-code] Running find_dead_code.py (limit: $MAX_FINDINGS_PER_CAT per category, category: $CATEGORY)..."

export STATE_FILE_PATH="$STATE_FILE"
export PROJECT_ROOT
export DRY_RUN
export PROMPT_TEMPLATE_PATH="$PROMPT_TEMPLATE"
export MAX_FINDINGS_TOTAL
export MAX_FINDINGS_PER_CAT
export CATEGORY
export CURRENT_SHA
TODAY_DATE=$(date -u '+%Y-%m-%d')
export TODAY_DATE

# Collect JSON output from find_dead_code.py and write to temp file
# (avoids ARG_MAX / env-var size limits when findings count is large)
FINDINGS_TMP="$SCRIPT_DIR/.tmp/dead-code-findings-$$.json"
mkdir -p "$SCRIPT_DIR/.tmp"
python3 "$SCRIPT_DIR/find_dead_code.py" \
  --json \
  --limit "$MAX_FINDINGS_PER_CAT" \
  $( [[ "$CATEGORY" != "all" ]] && echo "--category $CATEGORY" || true ) \
  > "$FINDINGS_TMP"

export FINDINGS_FILE="$FINDINGS_TMP"
# Clear the old base64 env var transport path
unset FINDINGS_JSON_B64

python3 "$SCRIPT_DIR/_dead_code_removal_helper.py" run
rm -f "$FINDINGS_TMP"

echo "[dead-code] Nightly dead code removal complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
