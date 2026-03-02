#!/usr/bin/env bash
# =============================================================================
# Sequential Test Runner with Progress Tracking
#
# Runs Playwright E2E specs one at a time, tracking results in a text file.
# Designed for an iterative debug workflow: run a test → if it passes, move
# to the next; if it fails, debug with Firecrawl, fix, re-run.
#
# Usage:
#   ./scripts/run-tests-sequential.sh <command> [options]
#
# Commands:
#   --next               Run the next unprocessed spec (auto-advances on pass)
#   --spec <name>        Run a specific spec file (e.g. chat-flow.spec.ts)
#   --status             Show progress: passed/failed/remaining counts and lists
#   --reset              Clear all progress and start over
#   --mark <name> <result>  Manually mark a spec as passed|failed|skipped
#   --help               Show this help message
#
# Options:
#   --slot N             Worker slot / test account to use (1-5, default: 1)
#
# Progress file:
#   test-results/progress.txt
#   Format: STATUS SPEC_NAME  (e.g. "PASSED chat-flow.spec.ts")
#
# Debug workflow (on failure):
#   1. Use Firecrawl browser to manually walk through the failing user flow
#   2. Identify what's broken (UI change, backend issue, stale selector, etc.)
#   3. Fix the app code or the spec
#   4. Re-run:  ./scripts/run-tests-sequential.sh --spec <name>
#   5. Once it passes, move on:  ./scripts/run-tests-sequential.sh --next
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="$PROJECT_ROOT/test-results"
PROGRESS_FILE="$RESULTS_DIR/progress.txt"
SPEC_DIR="$PROJECT_ROOT/frontend/apps/web_app/tests"

# --- Defaults ---
COMMAND=""
SPEC_NAME=""
MARK_RESULT=""
SLOT=1

# --- Parse CLI args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --next)     COMMAND="next"; shift ;;
    --spec)     COMMAND="spec"; SPEC_NAME="$2"; shift 2 ;;
    --status)   COMMAND="status"; shift ;;
    --reset)    COMMAND="reset"; shift ;;
    --mark)     COMMAND="mark"; SPEC_NAME="$2"; MARK_RESULT="$3"; shift 3 ;;
    --slot)     SLOT="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1. Use --help for usage."; exit 1 ;;
  esac
done

if [[ -z "$COMMAND" ]]; then
  echo "No command specified. Use --help for usage."
  exit 1
fi

# --- Ensure results dir and progress file exist ---
mkdir -p "$RESULTS_DIR"
touch "$PROGRESS_FILE"

# =============================================================================
# Helpers
# =============================================================================

# Get all spec file names, sorted alphabetically
get_all_specs() {
  find "$SPEC_DIR" -name '*.spec.ts' -type f -exec basename {} \; | sort
}

# Get specs that are already in the progress file (any status)
get_processed_specs() {
  if [[ -s "$PROGRESS_FILE" ]]; then
    awk '{print $2}' "$PROGRESS_FILE" | sort
  fi
}

# Get specs NOT yet in the progress file
get_remaining_specs() {
  comm -23 <(get_all_specs) <(get_processed_specs)
}

# Get the next unprocessed spec (first one not in progress file)
get_next_spec() {
  get_remaining_specs | head -1
}

# Check if a spec name is valid
validate_spec() {
  local spec="$1"
  if [[ ! -f "$SPEC_DIR/$spec" ]]; then
    echo "ERROR: Spec file not found: $spec"
    echo "Available specs:"
    get_all_specs | sed 's/^/  /'
    exit 1
  fi
}

# Record a result in the progress file
# If the spec already has an entry, replace it; otherwise append.
record_result() {
  local spec="$1"
  local result="$2"  # PASSED, FAILED, or SKIPPED

  # Remove any existing entry for this spec
  if grep -q " ${spec}$" "$PROGRESS_FILE" 2>/dev/null; then
    local tmp
    tmp="$(grep -v " ${spec}$" "$PROGRESS_FILE")"
    echo "$tmp" > "$PROGRESS_FILE"
  fi

  # Append the new result
  echo "$result $spec" >> "$PROGRESS_FILE"
}

# Print a colored status line
print_status_line() {
  local status="$1" spec="$2"
  case "$status" in
    PASSED)  printf "  \033[32m%-8s\033[0m %s\n" "$status" "$spec" ;;
    FAILED)  printf "  \033[31m%-8s\033[0m %s\n" "$status" "$spec" ;;
    SKIPPED) printf "  \033[33m%-8s\033[0m %s\n" "$status" "$spec" ;;
    *)       printf "  %-8s %s\n" "$status" "$spec" ;;
  esac
}

# =============================================================================
# Run a single spec via Docker
# =============================================================================
run_spec() {
  local spec="$1"
  local slot="$2"

  validate_spec "$spec"

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Running: $spec (slot $slot)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  local start_time
  start_time="$(date +%s)"
  local spec_exit=0
  local spec_output=""

  spec_output="$(
    cd "$PROJECT_ROOT" && \
    docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
      -e "PLAYWRIGHT_WORKER_SLOT=$slot" \
      -e "PLAYWRIGHT_TEST_FILE=$spec" \
      -e SIGNUP_TEST_EMAIL_DOMAINS \
      -e MAILOSAUR_API_KEY \
      -e MAILOSAUR_SERVER_ID \
      playwright 2>&1
  )" || spec_exit=$?

  local duration=$(( $(date +%s) - start_time ))

  # Print output (truncated for readability)
  if [[ ${#spec_output} -gt 8000 ]]; then
    echo "${spec_output:0:4000}"
    echo ""
    echo "... [output truncated, ${#spec_output} chars total] ..."
    echo ""
    echo "${spec_output: -3000}"
  else
    echo "$spec_output"
  fi

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if [[ $spec_exit -eq 0 ]]; then
    printf "  \033[32mPASSED\033[0m  %s  (%ds)\n" "$spec" "$duration"
    record_result "$spec" "PASSED"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Show what's next
    local next
    next="$(get_next_spec)"
    if [[ -n "$next" ]]; then
      local done_count remaining_count
      done_count="$(wc -l < "$PROGRESS_FILE" | tr -d ' ')"
      remaining_count="$(get_remaining_specs | wc -l | tr -d ' ')"
      echo ""
      echo "  Progress: $done_count done, $remaining_count remaining"
      echo "  Next up:  $next"
      echo "  Run:      ./scripts/run-tests-sequential.sh --next"
    else
      echo ""
      echo "  All specs processed!"
    fi
    return 0
  else
    printf "  \033[31mFAILED\033[0m  %s  (%ds, exit code %d)\n" "$spec" "$duration" "$spec_exit"
    record_result "$spec" "FAILED"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Debug workflow:"
    echo "  ─────────────────────────────────────────────────"
    echo "  1. Open Firecrawl browser session to reproduce the user flow:"
    echo "     → firecrawl_browser_create"
    echo "     → agent-browser open https://app.dev.openmates.org"
    echo "     → Walk through the test steps manually"
    echo ""
    echo "  2. Identify the issue (UI change, selector stale, backend error, etc.)"
    echo ""
    echo "  3. Fix the app code or the spec.ts file"
    echo ""
    echo "  4. Re-run this spec:"
    echo "     → ./scripts/run-tests-sequential.sh --spec $spec"
    echo ""
    echo "  5. Once it passes, continue to next:"
    echo "     → ./scripts/run-tests-sequential.sh --next"
    echo ""
    return 1
  fi
}

# =============================================================================
# Commands
# =============================================================================

case "$COMMAND" in

  # --- STATUS ---
  status)
    total="$(get_all_specs | wc -l | tr -d ' ')"
    passed=0
    failed=0
    skipped=0

    if [[ -s "$PROGRESS_FILE" ]]; then
      passed="$(grep -c '^PASSED ' "$PROGRESS_FILE" 2>/dev/null || echo 0)"
      failed="$(grep -c '^FAILED ' "$PROGRESS_FILE" 2>/dev/null || echo 0)"
      skipped="$(grep -c '^SKIPPED ' "$PROGRESS_FILE" 2>/dev/null || echo 0)"
    fi

    processed=$(( passed + failed + skipped ))
    remaining=$(( total - processed ))

    echo ""
    echo "╔══════════════════════════════════════════════════╗"
    echo "║  Sequential Test Progress                       ║"
    echo "╠══════════════════════════════════════════════════╣"
    printf "║  Total:     %-37s║\n" "$total specs"
    printf "║  Passed:    %-37s║\n" "$passed"
    printf "║  Failed:    %-37s║\n" "$failed"
    printf "║  Skipped:   %-37s║\n" "$skipped"
    printf "║  Remaining: %-37s║\n" "$remaining"
    echo "╚══════════════════════════════════════════════════╝"

    # Show failed specs if any
    if [[ $failed -gt 0 ]]; then
      echo ""
      echo "Failed:"
      grep '^FAILED ' "$PROGRESS_FILE" | while read -r status spec; do
        print_status_line "$status" "$spec"
      done
    fi

    # Show next up
    if [[ $remaining -gt 0 ]]; then
      next="$(get_next_spec)"
      echo ""
      echo "Next: $next"
      echo "Run:  ./scripts/run-tests-sequential.sh --next"
    else
      echo ""
      echo "All specs have been processed!"
      if [[ $failed -gt 0 ]]; then
        echo "Re-run failed specs with: --spec <name>"
      fi
    fi

    # Show remaining list
    remaining_list="$(get_remaining_specs)"
    if [[ -n "$remaining_list" ]]; then
      echo ""
      echo "Remaining specs:"
      echo "$remaining_list" | while read -r spec; do
        echo "  - $spec"
      done
    fi
    ;;

  # --- NEXT ---
  next)
    next_spec="$(get_next_spec)"
    if [[ -z "$next_spec" ]]; then
      echo "All specs have been processed!"
      echo "Use --status to see results, or --reset to start over."
      exit 0
    fi
    run_spec "$next_spec" "$SLOT"
    ;;

  # --- SPEC ---
  spec)
    if [[ -z "$SPEC_NAME" ]]; then
      echo "ERROR: --spec requires a spec file name."
      exit 1
    fi
    # Allow shorthand without .spec.ts extension
    if [[ "$SPEC_NAME" != *.spec.ts ]]; then
      SPEC_NAME="${SPEC_NAME}.spec.ts"
    fi
    run_spec "$SPEC_NAME" "$SLOT"
    ;;

  # --- RESET ---
  reset)
    if [[ -f "$PROGRESS_FILE" ]]; then
      local_count="$(wc -l < "$PROGRESS_FILE" | tr -d ' ')"
      > "$PROGRESS_FILE"
      echo "Progress reset. Cleared $local_count entries."
    else
      echo "No progress file to reset."
    fi
    echo "Run --next to start from the beginning."
    ;;

  # --- MARK ---
  mark)
    if [[ -z "$SPEC_NAME" ]]; then
      echo "ERROR: --mark requires a spec name and result."
      echo "Usage: --mark <spec-name> passed|failed|skipped"
      exit 1
    fi
    # Allow shorthand without .spec.ts extension
    if [[ "$SPEC_NAME" != *.spec.ts ]]; then
      SPEC_NAME="${SPEC_NAME}.spec.ts"
    fi
    validate_spec "$SPEC_NAME"

    case "$MARK_RESULT" in
      passed|PASSED)   MARK_RESULT="PASSED" ;;
      failed|FAILED)   MARK_RESULT="FAILED" ;;
      skipped|SKIPPED) MARK_RESULT="SKIPPED" ;;
      *)
        echo "ERROR: Result must be passed, failed, or skipped."
        exit 1
        ;;
    esac

    record_result "$SPEC_NAME" "$MARK_RESULT"
    print_status_line "$MARK_RESULT" "$SPEC_NAME"
    echo "  (manually recorded)"
    ;;

  *)
    echo "Unknown command: $COMMAND. Use --help for usage."
    exit 1
    ;;
esac
