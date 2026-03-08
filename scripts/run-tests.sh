#!/usr/bin/env bash
# =============================================================================
# OpenMates Test Runner
#
# Orchestrates all test suites (vitest, pytest, Playwright) and produces
# a single JSON results file at test-results/run-<timestamp>.json plus
# a copy at test-results/last-run.json (used by --only-failed).
#
# Usage:
#   ./scripts/run-tests.sh [options]
#
# Options:
#   --all            Also run pytest integration tests (default: unit only)
#   --only-failed    Rerun only tests that failed in the last run
#   --suite SUITE    Run only: vitest|pytest|playwright|all (default: all)
#   --workers N      Number of parallel Playwright workers/accounts (1-5, default: 5)
#   --help           Show this help message
#
# Output:
#   test-results/run-<ISO-timestamp>.json
#   test-results/last-run.json   (always overwritten)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="$PROJECT_ROOT/test-results"

# --- Defaults ---
SUITE="all"
UNIT_ONLY=true
ONLY_FAILED=false
MAX_WORKERS=5

# --- Parse CLI args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)        UNIT_ONLY=false; shift ;;
    --only-failed) ONLY_FAILED=true; shift ;;
    --suite)      SUITE="$2"; shift 2 ;;
    --workers)    MAX_WORKERS="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Validate --suite
case "$SUITE" in
  all|vitest|pytest|playwright) ;;
  *) echo "Invalid --suite value: $SUITE (must be all|vitest|pytest|playwright)"; exit 1 ;;
esac

# --- Setup ---
mkdir -p "$RESULTS_DIR"
RUN_ID="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
RUN_FILE="$RESULTS_DIR/run-${RUN_ID//:/}.json"
GIT_SHA="$(cd "$PROJECT_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
GIT_BRANCH="$(cd "$PROJECT_ROOT" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
START_TIME="$(date +%s)"

# Temporary directory for intermediate results from workers
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# --- Helpers ---
now_seconds() { date +%s; }

# Write a JSON test entry to a temp file for later aggregation.
# Usage: record_test <suite> <name> <status> <duration_s> [<error>] [<file>] [<slot>] [<stdout>]
record_test() {
  local suite="$1" name="$2" status="$3" dur="$4"
  local error="${5:-}" file="${6:-}" slot="${7:-}" stdout="${8:-}"
  local entry_file="$WORK_DIR/${suite}_$(date +%s%N).json"

  # Truncate stdout to ~5000 chars for LLM readability
  if [[ ${#stdout} -gt 5000 ]]; then
    stdout="${stdout:0:4900}...[truncated, ${#stdout} chars total]"
  fi

  python3 -c "
import json, sys
entry = {
    'name': sys.argv[1],
    'status': sys.argv[2],
    'duration_seconds': float(sys.argv[3]),
}
if sys.argv[4]: entry['error'] = sys.argv[4]
if sys.argv[5]: entry['file'] = sys.argv[5]
if sys.argv[6]: entry['slot'] = int(sys.argv[6])
if sys.argv[7]: entry['stdout'] = sys.argv[7]
print(json.dumps(entry))
" "$name" "$status" "$dur" "$error" "$file" "$slot" "$stdout" > "$entry_file"
}

# Collect all recorded tests for a suite into a JSON array string.
collect_suite_tests() {
  local suite="$1"
  local files=("$WORK_DIR"/${suite}_*.json)
  if [[ ! -e "${files[0]}" ]]; then
    echo "[]"
    return
  fi
  python3 -c "
import json, glob, sys
files = sorted(glob.glob(sys.argv[1]))
tests = [json.load(open(f)) for f in files]
print(json.dumps(tests))
" "$WORK_DIR/${suite}_*.json"
}

# --- Only-failed: load previous failures ---
FAILED_SPECS=()
if [[ "$ONLY_FAILED" == "true" ]]; then
  LAST_RUN="$RESULTS_DIR/last-run.json"
  if [[ ! -f "$LAST_RUN" ]]; then
    echo "ERROR: --only-failed requires test-results/last-run.json but it does not exist."
    echo "Run a full test suite first."
    exit 1
  fi
  # Extract failed test files/names from last run
  mapfile -t FAILED_SPECS < <(python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
for suite_name, suite_data in data.get('suites', {}).items():
    if isinstance(suite_data, dict):
        for t in suite_data.get('tests', []):
            if t.get('status') == 'failed':
                f = t.get('file', t.get('name', ''))
                if f:
                    print(f)
" "$LAST_RUN")
  if [[ ${#FAILED_SPECS[@]} -eq 0 ]]; then
    echo "No failed tests found in last run — nothing to rerun."
    exit 0
  fi
  echo "Rerunning ${#FAILED_SPECS[@]} previously failed test(s):"
  printf "  %s\n" "${FAILED_SPECS[@]}"
  echo ""
fi

# =============================================================================
# VITEST
# =============================================================================
run_vitest() {
  if [[ "$SUITE" != "all" && "$SUITE" != "vitest" ]]; then
    return
  fi

  echo "━━━ Vitest ━━━"
  local suite_start
  suite_start="$(now_seconds)"

  local vitest_dir="$PROJECT_ROOT/frontend/packages/ui"
  if [[ ! -f "$vitest_dir/vitest.simple.config.ts" ]]; then
    echo "  SKIP: vitest.simple.config.ts not found"
    echo '{"status":"skipped","reason":"config not found","duration_seconds":0,"tests":[]}' \
      > "$WORK_DIR/vitest_suite.json"
    return
  fi

  local vitest_output
  local vitest_exit=0
  vitest_output="$(cd "$vitest_dir" && npx vitest run --config vitest.simple.config.ts --reporter=json 2>&1)" || vitest_exit=$?

  local suite_dur=$(( $(now_seconds) - suite_start ))

  # Parse the JSON reporter output to extract individual test results
  python3 -c "
import json, sys

raw = sys.argv[1]
exit_code = int(sys.argv[2])
dur = int(sys.argv[3])
work_dir = sys.argv[4]

# Try to extract JSON from the output (vitest --reporter=json outputs JSON)
# The JSON may be mixed with other output, so find the JSON object
json_start = raw.find('{')
json_end = raw.rfind('}')
tests = []
suite_status = 'passed'

if json_start >= 0 and json_end > json_start:
    try:
        data = json.loads(raw[json_start:json_end+1])
        for tf in data.get('testResults', []):
            for ar in tf.get('assertionResults', []):
                name = ar.get('fullName', ar.get('title', 'unknown'))
                status = 'passed' if ar.get('status') == 'passed' else 'failed'
                test_dur = ar.get('duration', 0) / 1000.0
                error = ''
                if status == 'failed':
                    suite_status = 'failed'
                    msgs = ar.get('failureMessages', [])
                    error = msgs[0][:500] if msgs else 'unknown error'
                tests.append({
                    'name': name,
                    'status': status,
                    'duration_seconds': round(test_dur, 3),
                    **(({'error': error} if error else {}))
                })
    except json.JSONDecodeError:
        pass

if not tests and exit_code != 0:
    suite_status = 'failed'
    tests.append({
        'name': 'vitest-run',
        'status': 'failed',
        'duration_seconds': dur,
        'error': raw[:1000] if raw else 'vitest exited with code ' + str(exit_code)
    })
elif not tests:
    suite_status = 'passed'

suite = {
    'status': suite_status,
    'duration_seconds': dur,
    'tests': tests
}
with open(work_dir + '/vitest_suite.json', 'w') as f:
    json.dump(suite, f)

passed = sum(1 for t in tests if t['status'] == 'passed')
failed = sum(1 for t in tests if t['status'] == 'failed')
print(f'  {passed} passed, {failed} failed ({dur}s)')
" "$vitest_output" "$vitest_exit" "$suite_dur" "$WORK_DIR"
}

# =============================================================================
# PYTEST
# =============================================================================
run_pytest() {
  if [[ "$SUITE" != "all" && "$SUITE" != "pytest" ]]; then
    return
  fi

  echo "━━━ Pytest ━━━"
  local suite_start
  suite_start="$(now_seconds)"

  local pytest_bin="$PROJECT_ROOT/backend/.venv/bin/python3"
  if [[ ! -x "$pytest_bin" ]]; then
    # Fallback: try the system-level venv
    pytest_bin="/OpenMates/.venv/bin/python3"
  fi
  if [[ ! -x "$pytest_bin" ]]; then
    echo "  SKIP: Python venv not found"
    echo '{"status":"skipped","reason":"venv not found","duration_seconds":0,"tests":[]}' \
      > "$WORK_DIR/pytest_unit_suite.json"
    echo '{"status":"skipped","reason":"venv not found","duration_seconds":0,"tests":[]}' \
      > "$WORK_DIR/pytest_integration_suite.json"
    return
  fi

  # --- Unit tests ---
  # These are tests that don't hit live services (mocked/self-contained).
  local unit_tests=(
    "test_url_validator.py"
    "test_encryption_service.py"
    "test_toon_fake_tool_call_filter.py"
    "test_model_selection.py"
    "test_payment_provider_routing.py"
    "test_integration_encryption.py"
    "test_app_skills.py"
  )

  echo "  Running unit tests..."
  local unit_start
  unit_start="$(now_seconds)"
  local unit_output unit_exit=0

  # Build the test file args, filtering for --only-failed if needed
  local unit_args=()
  for t in "${unit_tests[@]}"; do
    if [[ "$ONLY_FAILED" == "true" ]]; then
      local found=false
      for f in "${FAILED_SPECS[@]}"; do
        if [[ "$f" == "$t" || "$f" == *"$t"* ]]; then
          found=true; break
        fi
      done
      [[ "$found" == "false" ]] && continue
    fi
    unit_args+=("tests/$t")
  done

  if [[ ${#unit_args[@]} -eq 0 ]]; then
    echo "  No unit tests to run (filtered by --only-failed)"
    echo '{"status":"skipped","reason":"no matching tests","duration_seconds":0,"tests":[]}' \
      > "$WORK_DIR/pytest_unit_suite.json"
  else
    unit_output="$($pytest_bin -m pytest --tb=short -q "${unit_args[@]}" 2>&1)" || unit_exit=$?
    local unit_dur=$(( $(now_seconds) - unit_start ))

    python3 -c "
import json, re, sys

raw = sys.argv[1]
exit_code = int(sys.argv[2])
dur = int(sys.argv[3])
work_dir = sys.argv[4]

tests = []
suite_status = 'passed' if exit_code == 0 else 'failed'

# Parse pytest -q output: lines like 'PASSED test_name' or 'FAILED test_name'
for line in raw.split('\n'):
    line = line.strip()
    if '::' in line and (' PASSED' in line or ' FAILED' in line):
        parts = line.rsplit(' ', 1)
        name = parts[0].strip()
        status = 'passed' if 'PASSED' in parts[-1] else 'failed'
        test_entry = {'name': name, 'status': status, 'duration_seconds': 0}
        if status == 'failed':
            test_entry['error'] = 'see pytest output'
        tests.append(test_entry)

if not tests:
    # Fallback: record the whole run as one entry
    tests.append({
        'name': 'pytest-unit-run',
        'status': suite_status,
        'duration_seconds': dur,
        **(({'error': raw[:1000]} if exit_code != 0 else {}))
    })

suite = {'status': suite_status, 'duration_seconds': dur, 'tests': tests}
with open(work_dir + '/pytest_unit_suite.json', 'w') as f:
    json.dump(suite, f)

passed = sum(1 for t in tests if t['status'] == 'passed')
failed = sum(1 for t in tests if t['status'] == 'failed')
print(f'  Unit: {passed} passed, {failed} failed ({dur}s)')
" "$unit_output" "$unit_exit" "$unit_dur" "$WORK_DIR"
  fi

  # --- Integration tests ---
  if [[ "$UNIT_ONLY" == "true" ]]; then
    echo "  Integration tests: skipped (use --all to include)"
    echo '{"status":"skipped","reason":"--unit-only","duration_seconds":0,"tests":[]}' \
      > "$WORK_DIR/pytest_integration_suite.json"
  else
    echo "  Running integration tests..."
    local integ_start
    integ_start="$(now_seconds)"
    local integ_output integ_exit=0
    local integ_tests=(
      "test_rest_api_ai.py"
      "test_rest_api_apps.py"
      "test_rest_api_core.py"
      "test_rest_api_images.py"
      "test_rest_api_media.py"
      "test_rest_api_web.py"
    )

    local integ_args=()
    for t in "${integ_tests[@]}"; do
      if [[ "$ONLY_FAILED" == "true" ]]; then
        local found=false
        for f in "${FAILED_SPECS[@]}"; do
          if [[ "$f" == "$t" || "$f" == *"$t"* ]]; then
            found=true; break
          fi
        done
        [[ "$found" == "false" ]] && continue
      fi
      integ_args+=("tests/$t")
    done

    if [[ ${#integ_args[@]} -eq 0 ]]; then
      echo "  No integration tests to run (filtered by --only-failed)"
      echo '{"status":"skipped","reason":"no matching tests","duration_seconds":0,"tests":[]}' \
        > "$WORK_DIR/pytest_integration_suite.json"
    else
      integ_output="$($pytest_bin -m pytest --tb=short -q "${integ_args[@]}" 2>&1)" || integ_exit=$?
      local integ_dur=$(( $(now_seconds) - integ_start ))

      python3 -c "
import json, sys
raw = sys.argv[1]
exit_code = int(sys.argv[2])
dur = int(sys.argv[3])
work_dir = sys.argv[4]
tests = []
suite_status = 'passed' if exit_code == 0 else 'failed'
for line in raw.split('\n'):
    line = line.strip()
    if '::' in line and (' PASSED' in line or ' FAILED' in line):
        parts = line.rsplit(' ', 1)
        name = parts[0].strip()
        status = 'passed' if 'PASSED' in parts[-1] else 'failed'
        test_entry = {'name': name, 'status': status, 'duration_seconds': 0}
        if status == 'failed':
            test_entry['error'] = 'see pytest output'
        tests.append(test_entry)
if not tests:
    tests.append({
        'name': 'pytest-integration-run',
        'status': suite_status,
        'duration_seconds': dur,
        **(({'error': raw[:1000]} if exit_code != 0 else {}))
    })
suite = {'status': suite_status, 'duration_seconds': dur, 'tests': tests}
with open(work_dir + '/pytest_integration_suite.json', 'w') as f:
    json.dump(suite, f)
passed = sum(1 for t in tests if t['status'] == 'passed')
failed = sum(1 for t in tests if t['status'] == 'failed')
print(f'  Integration: {passed} passed, {failed} failed ({dur}s)')
" "$integ_output" "$integ_exit" "$integ_dur" "$WORK_DIR"
    fi
  fi
}

# =============================================================================
# PLAYWRIGHT
# =============================================================================
run_playwright() {
  if [[ "$SUITE" != "all" && "$SUITE" != "playwright" ]]; then
    return
  fi

  echo "━━━ Playwright ━━━"
  local suite_start
  suite_start="$(now_seconds)"

  # Discover all spec files
  local spec_dir="$PROJECT_ROOT/frontend/apps/web_app/tests"
  local all_specs=()
  while IFS= read -r f; do
    all_specs+=("$(basename "$f")")
  done < <(find "$spec_dir" -name '*.spec.ts' -type f | sort)

  if [[ ${#all_specs[@]} -eq 0 ]]; then
    echo "  No spec files found."
    echo '{"status":"skipped","reason":"no specs found","duration_seconds":0,"workers":0,"tests":[]}' \
      > "$WORK_DIR/playwright_suite.json"
    return
  fi

  # Filter for --only-failed if applicable
  if [[ "$ONLY_FAILED" == "true" ]]; then
    local filtered=()
    for spec in "${all_specs[@]}"; do
      for f in "${FAILED_SPECS[@]}"; do
        if [[ "$f" == "$spec" || "$f" == *"$spec"* ]]; then
          filtered+=("$spec")
          break
        fi
      done
    done
    all_specs=("${filtered[@]}")
    if [[ ${#all_specs[@]} -eq 0 ]]; then
      echo "  No Playwright specs to rerun (filtered by --only-failed)"
      echo '{"status":"skipped","reason":"no matching tests","duration_seconds":0,"workers":0,"tests":[]}' \
        > "$WORK_DIR/playwright_suite.json"
      return
    fi
  fi

  echo "  ${#all_specs[@]} spec(s), $MAX_WORKERS worker(s)"

  # Round-robin assign specs to worker slots
  local -a slot_specs
  for ((i=0; i<MAX_WORKERS; i++)); do
    slot_specs[$i]=""
  done

  for ((i=0; i<${#all_specs[@]}; i++)); do
    local slot_idx=$(( i % MAX_WORKERS ))
    if [[ -n "${slot_specs[$slot_idx]}" ]]; then
      slot_specs[$slot_idx]="${slot_specs[$slot_idx]}|${all_specs[$i]}"
    else
      slot_specs[$slot_idx]="${all_specs[$i]}"
    fi
  done

  # Launch workers in parallel
  local pids=()
  for ((slot=0; slot<MAX_WORKERS; slot++)); do
    if [[ -z "${slot_specs[$slot]:-}" ]]; then
      continue
    fi
    local slot_num=$(( slot + 1 ))
    local specs_for_slot="${slot_specs[$slot]}"
    echo "  Slot $slot_num: $(echo "$specs_for_slot" | tr '|' '\n' | wc -l | tr -d ' ') spec(s)"

    # Launch worker in background
    "$SCRIPT_DIR/run-tests-worker.sh" \
      "$slot_num" \
      "$specs_for_slot" \
      "$WORK_DIR" \
      "$PROJECT_ROOT" &
    pids+=($!)
  done

  # Wait for all workers to finish
  local any_failed=false
  for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
      any_failed=true
    fi
  done

  local suite_dur=$(( $(now_seconds) - suite_start ))

  # Aggregate worker results into the suite JSON
  python3 -c "
import json, glob, sys

work_dir = sys.argv[1]
dur = int(sys.argv[2])
workers = int(sys.argv[3])

tests = []
for fpath in sorted(glob.glob(work_dir + '/pw_result_*.json')):
    with open(fpath) as f:
        tests.extend(json.load(f))

suite_status = 'passed'
for t in tests:
    if t.get('status') == 'failed':
        suite_status = 'failed'
        break

suite = {
    'status': suite_status,
    'duration_seconds': dur,
    'workers': workers,
    'tests': tests
}
with open(work_dir + '/playwright_suite.json', 'w') as f:
    json.dump(suite, f)

passed = sum(1 for t in tests if t['status'] == 'passed')
failed = sum(1 for t in tests if t['status'] == 'failed')
not_started = sum(1 for t in tests if t['status'] == 'not_started')
not_started_suffix = f', {not_started} not started' if not_started else ''
print(f'  Playwright: {passed} passed, {failed} failed{not_started_suffix} ({dur}s, {workers} workers)')
" "$WORK_DIR" "$suite_dur" "$MAX_WORKERS"
}

# =============================================================================
# RUN ALL SUITES
# =============================================================================
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  OpenMates Test Runner                                   ║"
echo "╠═══════════════════════════════════════════════════════════╣"
printf "║  Run ID:    %-45s║\n" "$RUN_ID"
printf "║  Git:       %-45s║\n" "$GIT_SHA ($GIT_BRANCH)"
printf "║  Suite:     %-45s║\n" "$SUITE"
printf "║  Unit only: %-45s║\n" "$UNIT_ONLY"
printf "║  Workers:   %-45s║\n" "$MAX_WORKERS"
if [[ "$ONLY_FAILED" == "true" ]]; then
  printf "║  Mode:      %-45s║\n" "rerun failed (${#FAILED_SPECS[@]} tests)"
fi
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Run suites in order: vitest (fastest) → pytest → playwright (slowest)
run_vitest
run_pytest
run_playwright

# =============================================================================
# AGGREGATE RESULTS
# =============================================================================
TOTAL_DURATION=$(( $(now_seconds) - START_TIME ))

python3 -c "
import json, sys, os

work_dir = sys.argv[1]
run_id = sys.argv[2]
git_sha = sys.argv[3]
git_branch = sys.argv[4]
unit_only = sys.argv[5] == 'true'
only_failed = sys.argv[6] == 'true'
suite_filter = sys.argv[7]
total_dur = int(sys.argv[8])
run_file = sys.argv[9]
results_dir = sys.argv[10]

suites = {}

# Load each suite's results
for suite_name, filename in [
    ('vitest', 'vitest_suite.json'),
    ('pytest_unit', 'pytest_unit_suite.json'),
    ('pytest_integration', 'pytest_integration_suite.json'),
    ('playwright', 'playwright_suite.json'),
]:
    fpath = os.path.join(work_dir, filename)
    if os.path.exists(fpath):
        with open(fpath) as f:
            suites[suite_name] = json.load(f)
    else:
        suites[suite_name] = {'status': 'skipped', 'reason': 'not run', 'duration_seconds': 0, 'tests': []}

# Compute summary
total = 0
passed = 0
failed = 0
skipped = 0
not_started = 0
for s in suites.values():
    for t in s.get('tests', []):
        total += 1
        st = t.get('status', '')
        if st == 'passed':
            passed += 1
        elif st == 'failed':
            failed += 1
        elif st == 'not_started':
            not_started += 1
        else:
            skipped += 1

result = {
    'run_id': run_id,
    'git_sha': git_sha,
    'git_branch': git_branch,
    'flags': {
        'unit_only': unit_only,
        'only_failed': only_failed,
        'suite': suite_filter,
    },
    'duration_seconds': total_dur,
    'summary': {
        'total': total,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'not_started': not_started,
    },
    'suites': suites,
}

# Write run file
with open(run_file, 'w') as f:
    json.dump(result, f, indent=2)

# Write last-run.json (always overwrite)
last_run = os.path.join(results_dir, 'last-run.json')
with open(last_run, 'w') as f:
    json.dump(result, f, indent=2)

# Print summary
print()
print('═══ Summary ═══')
not_started_part = f'  Not started: {not_started}' if not_started else ''
print(f'  Total: {total}  Passed: {passed}  Failed: {failed}  Skipped: {skipped}{not_started_part}')
print(f'  Duration: {total_dur}s')
print(f'  Results: {run_file}')
if failed > 0:
    print()
    print('Failed tests:')
    for sname, sdata in suites.items():
        for t in sdata.get('tests', []):
            if t.get('status') == 'failed':
                err = t.get('error', '')[:120]
                print(f'  [{sname}] {t.get(\"file\", t.get(\"name\", \"?\"))}: {err}')
    sys.exit(1)
" "$WORK_DIR" "$RUN_ID" "$GIT_SHA" "$GIT_BRANCH" "$UNIT_ONLY" "$ONLY_FAILED" "$SUITE" "$TOTAL_DURATION" "$RUN_FILE" "$RESULTS_DIR"
