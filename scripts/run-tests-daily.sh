#!/usr/bin/env bash
# =============================================================================
# OpenMates Daily Automated Test Runner
#
# Runs all tests once per day (only if git commits were made in the last 24h),
# saves separate pass/fail log files, then dispatches a single summary email
# via the existing Celery email infrastructure (Brevo/Mailjet — no SMTP needed).
#
# Called by the Celery Beat scheduled task (e2e_test_tasks.run_daily_all_tests).
# Can also be invoked manually:
#   ./scripts/run-tests-daily.sh
#   ./scripts/run-tests-daily.sh --force   # skip the commit-activity check
#
# Environment variables required:
#   ADMIN_NOTIFY_EMAIL   — recipient for the summary email
#
# Output files (always written to test-results/):
#   last-run.json              — full run data (written by run-tests.sh)
#   last-passed-tests.json     — passing tests only from the latest run
#   last-failed-tests.json     — failing tests only from the latest run
#   daily-run-<YYYY-MM-DD>.json — per-day archive; pruned to keep last 30
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="$PROJECT_ROOT/test-results"

# --- Parse CLI args ---
FORCE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true; shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# --- Commit-activity gate ---
# Skip the run entirely when no commits were made in the last 24 hours.
# This avoids running the full suite on days with no code changes.
if [[ "$FORCE" == "false" ]]; then
  COMMITS_IN_24H=$(git -C "$PROJECT_ROOT" log --oneline --since="24 hours ago" 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$COMMITS_IN_24H" -eq 0 ]]; then
    echo "[daily-runner] No git commits in the last 24 hours — skipping test run."
    echo "[daily-runner] Use --force to run regardless of commit activity."
    exit 0
  fi
  echo "[daily-runner] Found $COMMITS_IN_24H commit(s) in the last 24 hours — proceeding."
fi

# --- Run the full test suite ---
echo "[daily-runner] Starting full test run at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
mkdir -p "$RESULTS_DIR"

# run-tests.sh exits 1 on any test failure — we capture that gracefully here.
set +e
"$SCRIPT_DIR/run-tests.sh" --all
RUN_EXIT_CODE=$?
set -e

LAST_RUN="$RESULTS_DIR/last-run.json"
if [[ ! -f "$LAST_RUN" ]]; then
  echo "[daily-runner] ERROR: run-tests.sh did not produce $LAST_RUN — aborting."
  exit 1
fi

# --- Save split pass/fail log files for easy Claude consumption ---
export RESULTS_DIR
python3 "$SCRIPT_DIR/_daily_runner_helper.py" split-results

# --- Archive daily result (one file per calendar day, UTC) ---
TODAY="$(date -u '+%Y-%m-%d')"
DAILY_ARCHIVE="$RESULTS_DIR/daily-run-${TODAY}.json"
cp "$LAST_RUN" "$DAILY_ARCHIVE"
echo "[daily-runner] Archived result to $DAILY_ARCHIVE"

# --- Prune old daily archives: keep only the most recent 30 ---
ls -1t "$RESULTS_DIR"/daily-run-*.json 2>/dev/null | tail -n +31 | xargs -r rm -f
echo "[daily-runner] Pruned old daily archives (keeping last 30)"

# --- Dispatch summary email via internal API ---
ADMIN_EMAIL="${ADMIN_NOTIFY_EMAIL:-}"
if [[ -z "$ADMIN_EMAIL" ]]; then
  echo "[daily-runner] WARNING: ADMIN_NOTIFY_EMAIL not set — skipping email dispatch."
  exit 0
fi

echo "[daily-runner] Dispatching test run summary email to $ADMIN_EMAIL..."
export ADMIN_NOTIFY_EMAIL="$ADMIN_EMAIL"

python3 "$SCRIPT_DIR/_daily_runner_helper.py" dispatch-email

echo "[daily-runner] Daily test run complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
exit $RUN_EXIT_CODE
