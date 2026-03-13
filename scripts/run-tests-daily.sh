#!/usr/bin/env bash
# =============================================================================
# OpenMates Daily Automated Test Runner
#
# Runs all tests once per day (only if git commits were made in the last 24h),
# saves separate pass/fail log files, then dispatches a single summary email
# via the existing Celery email infrastructure (Brevo/Mailjet — no SMTP needed).
#
# Triggered by a system crontab entry (see `crontab -l`):
#   0 3 * * * . /path/to/.env && /path/to/scripts/run-tests-daily.sh
#
# Can also be invoked manually:
#   ./scripts/run-tests-daily.sh
#   ./scripts/run-tests-daily.sh --force   # skip the commit-activity check
#
# Environment variables (sourced from .env by the crontab entry):
#   ADMIN_NOTIFY_EMAIL        — recipient for the summary email (required)
#   INTERNAL_API_SHARED_TOKEN — auth token for internal API email dispatch
#
# Env-gate variables (set on dev server only — NOT on production):
#   E2E_DAILY_RUN_ENABLED     — must be "true" for this script to run at all.
#                               This script checks it directly so a manual
#                               invocation on the wrong server is a safe no-op.
#
# Prod smoke test (optional — runs from dev server against production URL):
#   E2E_PROD_TEST_ENABLED     — set to "true" to also run a smoke test against
#                               the production URL after the main dev suite.
#   E2E_PROD_TEST_BASE_URL    — production URL, e.g. "https://openmates.org"
#   OPENMATES_PROD_TEST_ACCOUNT_EMAIL    — prod test account email
#   OPENMATES_PROD_TEST_ACCOUNT_PASSWORD — prod test account password
#   OPENMATES_PROD_TEST_ACCOUNT_OTP_KEY  — prod test account OTP key
#
# Output files (always written to test-results/):
#   last-run.json              — full run data (written by run-tests.sh)
#   last-passed-tests.json     — passing tests only from the latest run
#   last-failed-tests.json     — failing tests only from the latest run
#   daily-run-<YYYY-MM-DD>.json — per-day archive; pruned to keep last 30
#
# Observability:
#   After each run, a normalized summary is forwarded to OpenObserve test-runs
#   stream via /internal/openobserve/push-test-run (best-effort, non-fatal).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="$PROJECT_ROOT/test-results"

# --- Source .env if present (makes manual invocation work without pre-exporting) ---
# The crontab entry also sources .env, but doing it here too means
# `./scripts/run-tests-daily.sh --force` works out of the box.
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

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

# --- Env gate ---
# If E2E_DAILY_RUN_ENABLED is not "true", exit silently.
# This prevents manual invocations on production from running tests.
if [[ "${E2E_DAILY_RUN_ENABLED:-}" != "true" ]]; then
  echo "[daily-runner] E2E_DAILY_RUN_ENABLED is not set — skipping test run."
  echo "[daily-runner] Set E2E_DAILY_RUN_ENABLED=true on the dev server to enable tests."
  exit 0
fi

# This script always runs in development mode. The "production" environment
# value is no longer used here — the prod smoke test is a separate phase
# controlled by E2E_PROD_TEST_ENABLED below.
ENVIRONMENT="development"
echo "[daily-runner] Environment: $ENVIRONMENT"

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

# Export environment so _daily_runner_helper.py can read it
export DAILY_RUN_ENVIRONMENT="$ENVIRONMENT"

# --- Notify admin that the run is starting ---
# Non-fatal: a failed email must not prevent the tests from running.
ADMIN_EMAIL_CHECK="${ADMIN_NOTIFY_EMAIL:-}"
if [[ -n "$ADMIN_EMAIL_CHECK" ]]; then
  echo "[daily-runner] Dispatching test run start notification email..."
  export ADMIN_NOTIFY_EMAIL="$ADMIN_EMAIL_CHECK"
  python3 "$SCRIPT_DIR/_daily_runner_helper.py" dispatch-start-email || \
    echo "[daily-runner] WARNING: could not send start email (non-fatal)"
fi

# --- Run the full dev test suite ---
echo "[daily-runner] Starting full test run at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
mkdir -p "$RESULTS_DIR"

# run-tests.sh exits 1 on any test failure — we capture that gracefully here.
set +e
"$SCRIPT_DIR/run-tests.sh" --all --environment "$ENVIRONMENT"
RUN_EXIT_CODE=$?
set -e

LAST_RUN="$RESULTS_DIR/last-run.json"
if [[ ! -f "$LAST_RUN" ]]; then
  echo "[daily-runner] ERROR: run-tests.sh did not produce $LAST_RUN — aborting."
  exit 1
fi

# Back up the dev run result before we potentially overwrite it with the prod smoke run
rm -f "$LAST_RUN.bak"
cp "$LAST_RUN" "$LAST_RUN.bak"

# --- Production smoke test (optional, runs from dev server against prod URL) ---
# Triggered when E2E_PROD_TEST_ENABLED=true. Runs chat-flow.spec.ts against
# E2E_PROD_TEST_BASE_URL using the dedicated prod test account credentials.
# Results are written to test-results/last-run-prod-smoke.json and merged into
# the summary email payload by _daily_runner_helper.py.
PROD_SMOKE_EXIT_CODE=0
if [[ "${E2E_PROD_TEST_ENABLED:-}" == "true" ]]; then
  PROD_URL="${E2E_PROD_TEST_BASE_URL:-}"
  if [[ -z "$PROD_URL" ]]; then
    echo "[daily-runner] WARNING: E2E_PROD_TEST_ENABLED=true but E2E_PROD_TEST_BASE_URL is not set — skipping prod smoke test."
  else
    echo "[daily-runner] Starting prod smoke test against $PROD_URL..."
    set +e
    "$SCRIPT_DIR/run-tests.sh" \
      --suite playwright \
      --workers 1 \
      --environment production \
      --base-url "$PROD_URL" \
      --prod-account
    PROD_SMOKE_EXIT_CODE=$?
    set -e

    PROD_SMOKE_RUN="$RESULTS_DIR/last-run.json"
    if [[ -f "$PROD_SMOKE_RUN" ]]; then
      rm -f "$RESULTS_DIR/last-run-prod-smoke.json"
      cp "$PROD_SMOKE_RUN" "$RESULTS_DIR/last-run-prod-smoke.json"
      echo "[daily-runner] Prod smoke test complete (exit=$PROD_SMOKE_EXIT_CODE)"
    else
      echo "[daily-runner] WARNING: prod smoke test did not produce last-run.json"
    fi

    # Restore the dev last-run.json (it was overwritten by the prod smoke run)
    rm -f "$LAST_RUN"
    cp "$LAST_RUN.bak" "$LAST_RUN" 2>/dev/null || true
  fi
fi

# --- Collect coverage metrics (informational, non-blocking) ---
echo "[daily-runner] Collecting coverage metrics..."
COVERAGE_DIR="$RESULTS_DIR/coverage"
mkdir -p "$COVERAGE_DIR"

# Frontend (vitest) coverage — writes JSON summary
VITEST_DIR="$PROJECT_ROOT/frontend/packages/ui"
if [[ -f "$VITEST_DIR/vitest.simple.config.ts" ]]; then
  echo "[daily-runner] Running vitest with coverage..."
  (cd "$VITEST_DIR" && npx vitest run --config vitest.simple.config.ts --coverage --coverage.reporter=json-summary 2>/dev/null) || true
  if [[ -f "$VITEST_DIR/coverage/coverage-summary.json" ]]; then
    cp "$VITEST_DIR/coverage/coverage-summary.json" "$COVERAGE_DIR/vitest-coverage.json"
    echo "[daily-runner] Vitest coverage saved."
  fi
fi

# Backend (pytest) coverage — requires pytest-cov
PYTEST_BIN="$PROJECT_ROOT/backend/.venv/bin/python3"
if [[ ! -x "$PYTEST_BIN" ]]; then
  PYTEST_BIN="/OpenMates/.venv/bin/python3"
fi
if [[ -x "$PYTEST_BIN" ]]; then
  echo "[daily-runner] Running pytest with coverage..."
  ($PYTEST_BIN -m pytest backend/tests/test_auth_endpoints.py \
    backend/tests/test_encryption_service.py \
    backend/tests/test_url_validator.py \
    backend/tests/test_model_selection.py \
    backend/tests/test_toon_fake_tool_call_filter.py \
    --cov=backend/core/api/app --cov-report=json:"$COVERAGE_DIR/pytest-coverage.json" \
    -q --tb=no -m "not integration" 2>/dev/null) || true
  if [[ -f "$COVERAGE_DIR/pytest-coverage.json" ]]; then
    echo "[daily-runner] Pytest coverage saved."
  fi
fi

echo "[daily-runner] Coverage collection complete."

# --- Save split pass/fail log files for easy Claude consumption ---
export RESULTS_DIR
python3 "$SCRIPT_DIR/_daily_runner_helper.py" split-results

# --- Push normalized test-run summary to OpenObserve (non-fatal) ---
# This writes one compact event per daily run into the OpenObserve test-runs
# stream so failures can be correlated with backend/container logs by git SHA,
# branch, environment, and run window.
echo "[daily-runner] Pushing test run summary to OpenObserve..."
python3 "$SCRIPT_DIR/_daily_runner_helper.py" dispatch-openobserve-test-run || \
  echo "[daily-runner] WARNING: could not push test run summary to OpenObserve (non-fatal)"

# --- Archive daily result (one file per calendar day, UTC) ---
TODAY="$(date -u '+%Y-%m-%d')"
DAILY_ARCHIVE="$RESULTS_DIR/daily-run-${TODAY}.json"
rm -f "$DAILY_ARCHIVE"
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

# Combine exit codes: fail the overall run if either the dev suite or prod smoke test failed
OVERALL_EXIT_CODE=$(( RUN_EXIT_CODE > PROD_SMOKE_EXIT_CODE ? RUN_EXIT_CODE : PROD_SMOKE_EXIT_CODE ))
echo "[daily-runner] Daily test run complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
exit $OVERALL_EXIT_CODE
