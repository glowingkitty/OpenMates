#!/usr/bin/env bash
# =============================================================================
# DEPRECATED: Use python3 scripts/run_tests.py instead.
# This script is kept for backward compatibility but will be removed.
# =============================================================================
#
# OpenMates Test Runner (LEGACY)
#
# Orchestrates all test suites (vitest, pytest, Playwright) and produces
# a single JSON results file at test-results/run-<timestamp>.json plus
# a copy at test-results/last-run.json (used by --only-failed).
#
# Usage:
#   ./scripts/run-tests.sh [options]
#
# Options:
#   --all                Also run pytest integration tests (default: unit only)
#   --only-failed        Rerun only tests that failed in the last run
#   --suite SUITE        Run only: vitest|pytest|playwright|all (default: all)
#   --workers N          Number of parallel Playwright workers/accounts (1-5, default: 5)
#   --environment ENV    "development" (default) or "production"
#   --base-url URL       Override PLAYWRIGHT_TEST_BASE_URL for this run (prod smoke test)
#   --prod-account       Use OPENMATES_PROD_TEST_ACCOUNT_* creds instead of slot-based creds
#   --help               Show this help message
#
# Production mode (--environment production):
#   Limits tests to avoid LLM inference and third-party API costs:
#   - Playwright: only chat-flow.spec.ts (1 inference test)
#   - pytest integration: skipped entirely
#   - vitest + pytest unit: run in full (no cost)
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
# Read environment from CLI arg; fall back to DAILY_RUN_ENVIRONMENT env var
# (set by run-tests-daily.sh), then default to "development".
ENVIRONMENT="${DAILY_RUN_ENVIRONMENT:-development}"
# Optional: override PLAYWRIGHT_TEST_BASE_URL (used for prod smoke test)
PLAYWRIGHT_BASE_URL_OVERRIDE=""
# Optional: use OPENMATES_PROD_TEST_ACCOUNT_* creds instead of slot-based creds
USE_PROD_ACCOUNT=false

# --- Parse CLI args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)        UNIT_ONLY=false; shift ;;
    --only-failed) ONLY_FAILED=true; shift ;;
    --suite)      SUITE="$2"; shift 2 ;;
    --workers)    MAX_WORKERS="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --base-url)   PLAYWRIGHT_BASE_URL_OVERRIDE="$2"; shift 2 ;;
    --prod-account) USE_PROD_ACCOUNT=true; shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Normalise
ENVIRONMENT="${ENVIRONMENT,,}"
if [[ "$ENVIRONMENT" != "development" && "$ENVIRONMENT" != "production" ]]; then
  echo "WARNING: unknown --environment '$ENVIRONMENT' — defaulting to 'development'"
  ENVIRONMENT="development"
fi

# On production: force UNIT_ONLY so pytest integration tests are skipped
if [[ "$ENVIRONMENT" == "production" ]]; then
  UNIT_ONLY=true
fi

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

# Export for Playwright workers (api-reporter.ts reads these for OpenObserve tagging)
export RUN_ID GIT_BRANCH
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

  # Auto-detect vitest directories: find all frontend dirs that contain
  # *.test.ts files AND have vitest as a dependency (direct or dev).
  # Each dir is run with `npx vitest run` using the appropriate config.
  local vitest_dirs=()
  local vitest_configs=()

  # 1) packages/ui — has a dedicated vitest.simple.config.ts
  local ui_dir="$PROJECT_ROOT/frontend/packages/ui"
  if [[ -f "$ui_dir/vitest.simple.config.ts" ]]; then
    vitest_dirs+=("$ui_dir")
    vitest_configs+=("--config vitest.simple.config.ts")
  fi

  # 2) Auto-discover: any frontend dir with vitest in package.json AND *.test.ts files
  #    (excludes packages/ui which is handled above, and node_modules)
  while IFS= read -r pkg_json; do
    local pkg_dir
    pkg_dir="$(dirname "$pkg_json")"
    # Skip ui (already handled) and node_modules
    [[ "$pkg_dir" == "$ui_dir" ]] && continue
    # Check if vitest is in dependencies or devDependencies
    if python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
deps = {**d.get('dependencies',{}), **d.get('devDependencies',{})}
sys.exit(0 if 'vitest' in deps else 1)
" "$pkg_json" 2>/dev/null; then
      # Check if there are any .test.ts files in src/
      if find "$pkg_dir/src" -name "*.test.ts" -type f 2>/dev/null | grep -q .; then
        vitest_dirs+=("$pkg_dir")
        # Use vitest.config.ts if present, otherwise default
        if [[ -f "$pkg_dir/vitest.config.ts" ]]; then
          vitest_configs+=("--config vitest.config.ts")
        else
          vitest_configs+=("")
        fi
      fi
    fi
  done < <(find "$PROJECT_ROOT/frontend" -maxdepth 4 -name "package.json" -not -path "*/node_modules/*" | sort)

  if [[ ${#vitest_dirs[@]} -eq 0 ]]; then
    echo "  No vitest directories found"
    echo '{"status":"skipped","reason":"no vitest dirs","duration_seconds":0,"tests":[]}'       > "$WORK_DIR/vitest_suite.json"
    return
  fi

  echo "  Found ${#vitest_dirs[@]} vitest dir(s)"
  local all_vitest_tests="[]"
  local overall_vitest_status="passed"

  for ((idx=0; idx<${#vitest_dirs[@]}; idx++)); do
    local vdir="${vitest_dirs[$idx]}"
    local vconfig="${vitest_configs[$idx]}"
    local vname
    vname="$(python3 -c "import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$vdir" "$PROJECT_ROOT")"

    echo "  Running vitest in $vname..."
    local vitest_exit=0
    local vitest_tmp="$WORK_DIR/vitest_${idx}_raw_output.txt"
    # shellcheck disable=SC2086
    (cd "$vdir" && npx vitest run $vconfig --reporter=json 2>&1)       > "$vitest_tmp" || vitest_exit=$?

    # Parse the JSON reporter output and merge into all_vitest_tests
    all_vitest_tests=$(python3 -c "
import json, sys

output_file = sys.argv[1]
exit_code = int(sys.argv[2])
vname = sys.argv[3]
existing = json.loads(sys.argv[4])

with open(output_file, 'r', errors='replace') as fh:
    raw = fh.read()

json_start = raw.find('{')
json_end = raw.rfind('}')
tests = []
dir_status = 'passed'

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
                    dir_status = 'failed'
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
    dir_status = 'failed'
    tests.append({
        'name': f'{vname}/vitest-run',
        'status': 'failed',
        'duration_seconds': 0,
        'error': raw[:1000] if raw else f'vitest exited with code {exit_code}'
    })

passed = sum(1 for t in tests if t['status'] == 'passed')
failed = sum(1 for t in tests if t['status'] == 'failed')
print(json.dumps(existing + tests), file=sys.stderr)
print(f'    {vname}: {passed} passed, {failed} failed')
if dir_status == 'failed':
    print('FAILED', file=open('/dev/fd/3', 'w'))
" "$vitest_tmp" "$vitest_exit" "$vname" "$all_vitest_tests" 3>"$WORK_DIR/vitest_${idx}_status.txt" 2>"$WORK_DIR/vitest_${idx}_merged.json") || true

    # Read merged tests back
    if [[ -f "$WORK_DIR/vitest_${idx}_merged.json" ]]; then
      all_vitest_tests="$(cat "$WORK_DIR/vitest_${idx}_merged.json")"
    fi
    # Check status
    if [[ -f "$WORK_DIR/vitest_${idx}_status.txt" ]] && grep -q "FAILED" "$WORK_DIR/vitest_${idx}_status.txt" 2>/dev/null; then
      overall_vitest_status="failed"
    fi
  done

  local suite_dur=$(( $(now_seconds) - suite_start ))

  # Write final vitest_suite.json
  python3 -c "
import json, sys
tests = json.loads(sys.argv[1])
dur = int(sys.argv[2])
status = sys.argv[3]
if not tests:
    status = 'passed'
suite = {'status': status, 'duration_seconds': dur, 'tests': tests}
with open(sys.argv[4] + '/vitest_suite.json', 'w') as f:
    json.dump(suite, f)
passed = sum(1 for t in tests if t['status'] == 'passed')
failed = sum(1 for t in tests if t['status'] == 'failed')
print(f'  Vitest total: {passed} passed, {failed} failed ({dur}s)')
" "$all_vitest_tests" "$suite_dur" "$overall_vitest_status" "$WORK_DIR"
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
  # Auto-detected: all test_*.py files in backend/tests/, filtered by pytest
  # markers. Tests marked @pytest.mark.integration or @pytest.mark.benchmark
  # are excluded here and run separately in the integration phase (with --all).
  echo "  Discovering unit tests..."
  local unit_start
  unit_start="$(now_seconds)"
  local unit_output unit_exit=0

  # Build the test file args via auto-discovery
  local unit_args=()
  while IFS= read -r t; do
    local basename_t
    basename_t="$(basename "$t")"
    if [[ "$ONLY_FAILED" == "true" ]]; then
      local found=false
      for f in "${FAILED_SPECS[@]}"; do
        if [[ "$f" == "$basename_t" || "$f" == *"$basename_t"* ]]; then
          found=true; break
        fi
      done
      [[ "$found" == "false" ]] && continue
    fi
    unit_args+=("$t")
  done < <(find "$PROJECT_ROOT/backend/tests" -maxdepth 1 -name "test_*.py" -type f | sort)

  if [[ ${#unit_args[@]} -eq 0 ]]; then
    echo "  No unit tests to run (filtered by --only-failed)"
    echo '{"status":"skipped","reason":"no matching tests","duration_seconds":0,"tests":[]}' \
      > "$WORK_DIR/pytest_unit_suite.json"
  else
    # Write output to a temp file to avoid "Argument list too long" (execve limit).
    local unit_tmp="$WORK_DIR/pytest_unit_raw_output.txt"
    (cd "$PROJECT_ROOT" && $pytest_bin -m pytest --tb=short -q -m "not integration and not benchmark" "${unit_args[@]}" 2>&1) \
      > "$unit_tmp" || unit_exit=$?
    local unit_dur=$(( $(now_seconds) - unit_start ))

    python3 -c "
import json, re, sys

output_file = sys.argv[1]
exit_code = int(sys.argv[2])
dur = int(sys.argv[3])
work_dir = sys.argv[4]

with open(output_file, 'r', errors='replace') as fh:
    raw = fh.read()

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
" "$unit_tmp" "$unit_exit" "$unit_dur" "$WORK_DIR"
  fi

  # --- Integration tests ---
  # On production, UNIT_ONLY is forced true (set at top of script) to avoid
  # LLM inference and third-party API costs (ai, apps, web, images tests).
  if [[ "$UNIT_ONLY" == "true" ]]; then
    if [[ "$ENVIRONMENT" == "production" ]]; then
      echo "  Integration tests: skipped (production — no inference/API costs allowed)"
    else
      echo "  Integration tests: skipped (use --all to include)"
    fi
    echo '{"status":"skipped","reason":"--unit-only","duration_seconds":0,"tests":[]}' \
      > "$WORK_DIR/pytest_integration_suite.json"
  else
    echo "  Discovering integration tests..."
    local integ_start
    integ_start="$(now_seconds)"
    local integ_output integ_exit=0

    # Auto-detected: all test_*.py in backend/tests/ that have integration-marked tests
    local integ_args=()
    while IFS= read -r t; do
      local basename_t
      basename_t="$(basename "$t")"
      if [[ "$ONLY_FAILED" == "true" ]]; then
        local found=false
        for f in "${FAILED_SPECS[@]}"; do
          if [[ "$f" == "$basename_t" || "$f" == *"$basename_t"* ]]; then
            found=true; break
          fi
        done
        [[ "$found" == "false" ]] && continue
      fi
      integ_args+=("$t")
    done < <(find "$PROJECT_ROOT/backend/tests" -maxdepth 1 -name "test_*.py" -type f | sort)

    if [[ ${#integ_args[@]} -eq 0 ]]; then
      echo "  No integration tests to run (filtered by --only-failed)"
      echo '{"status":"skipped","reason":"no matching tests","duration_seconds":0,"tests":[]}' \
        > "$WORK_DIR/pytest_integration_suite.json"
    else
      # Write output to a temp file to avoid "Argument list too long" (execve limit).
      local integ_tmp="$WORK_DIR/pytest_integ_raw_output.txt"
      (cd "$PROJECT_ROOT" && $pytest_bin -m pytest --tb=short -q -m "integration and not benchmark" "${integ_args[@]}" 2>&1) \
        > "$integ_tmp" || integ_exit=$?
      local integ_dur=$(( $(now_seconds) - integ_start ))

      python3 -c "
import json, sys
output_file = sys.argv[1]
exit_code = int(sys.argv[2])
dur = int(sys.argv[3])
work_dir = sys.argv[4]
with open(output_file, 'r', errors='replace') as fh:
    raw = fh.read()
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
" "$integ_tmp" "$integ_exit" "$integ_dur" "$WORK_DIR"
    fi
  fi
}

# =============================================================================
# NODE UNIT (openmates-cli + secret-scanner)
# These packages use Node's built-in test runner (node --test) instead of
# vitest, so they are not picked up by the vitest config in packages/ui.
# =============================================================================
run_node_unit() {
  if [[ "$SUITE" != "all" && "$SUITE" != "vitest" ]]; then
    return
  fi

  echo "━━━ Node Unit (CLI + secret-scanner) ━━━"
  local suite_start
  suite_start="$(now_seconds)"

  # Auto-detect: find frontend packages whose "test" script uses node --test
  # (as opposed to vitest, which is handled by run_vitest).
  local packages=()
  while IFS= read -r pkg_json; do
    local pkg_rel
    pkg_rel="$(python3 -c "import os,sys; print(os.path.relpath(os.path.dirname(sys.argv[1]), sys.argv[2]))" "$pkg_json" "$PROJECT_ROOT")"
    packages+=("$pkg_rel")
  done < <(find "$PROJECT_ROOT/frontend/packages" -maxdepth 2 -name "package.json" -not -path "*/node_modules/*" -exec grep -l '"node --test' {} \;  | sort)

  local overall_status="passed"

  for pkg_rel in "${packages[@]}"; do
    local pkg_dir="$PROJECT_ROOT/$pkg_rel"
    if [[ ! -f "$pkg_dir/package.json" ]]; then
      echo "  SKIP: $pkg_rel (package.json not found)"
      continue
    fi

    local pkg_exit=0
    local pkg_tmp="$WORK_DIR/node_unit_$(basename "$pkg_rel")_raw.txt"
    local parsed_tmp="$WORK_DIR/node_unit_$(basename "$pkg_rel")_parsed.json"

    echo "  Running tests in $pkg_rel..."
    (cd "$pkg_dir" && npm test 2>&1) > "$pkg_tmp" || pkg_exit=$?

    python3 -c "
import re, sys, json

output_file, pkg_name, exit_code_s, out_file = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
exit_code = int(exit_code_s)
with open(output_file, 'r', errors='replace') as fh:
    raw = fh.read()
tests = []
lines = raw.split(chr(10))
i = 0
while i < len(lines):
    line = lines[i].strip()
    m = re.match(r'^(not ok|ok)\\s+\\d+\\s+-\\s+(.+)$', line)
    if m:
        passed_str, name = m.group(1), m.group(2).strip()
        typ, dur = None, 0.0
        for j in range(i+1, min(i+8, len(lines))):
            tl = lines[j].strip()
            tm = re.match(r\"type:\\s+'?([^']+)'?\", tl)
            dm = re.match(r'duration_ms:\\s+([0-9.]+)', tl)
            if tm: typ = tm.group(1)
            if dm: dur = round(float(dm.group(1)) / 1000.0, 4)
        if typ == 'test':
            status = 'passed' if passed_str == 'ok' else 'failed'
            entry = {'name': f'{pkg_name} > {name}', 'status': status, 'duration_seconds': dur}
            if status == 'failed': entry['error'] = 'see node --test output'
            tests.append(entry)
    i += 1
if not tests and exit_code != 0:
    tests.append({'name': f'{pkg_name} > run', 'status': 'failed', 'duration_seconds': 0, 'error': raw[:800] or f'npm test exited {exit_code}'})
elif not tests:
    tests.append({'name': f'{pkg_name} > run', 'status': 'passed', 'duration_seconds': 0})
with open(out_file, 'w') as f: json.dump(tests, f)
passed = sum(1 for t in tests if t['status'] == 'passed')
failed = sum(1 for t in tests if t['status'] == 'failed')
print(f'  {pkg_name}: {passed} passed, {failed} failed')
if failed > 0: sys.exit(1)
" "$pkg_tmp" "$(basename "$pkg_rel")" "$pkg_exit" "$parsed_tmp" || overall_status="failed"

  done

  local suite_dur=$(( $(now_seconds) - suite_start ))

  python3 -c "
import json, glob, sys, os
work_dir, dur = sys.argv[1], int(sys.argv[2])
all_tests = []
for fpath in sorted(glob.glob(os.path.join(work_dir, 'node_unit_*_parsed.json'))):
    with open(fpath) as f: all_tests.extend(json.load(f))
if not all_tests:
    suite = {'status': 'skipped', 'reason': 'no packages found', 'duration_seconds': dur, 'tests': []}
else:
    computed_status = 'failed' if any(t.get('status') == 'failed' for t in all_tests) else 'passed'
    suite = {'status': computed_status, 'duration_seconds': dur, 'tests': all_tests}
with open(os.path.join(work_dir, 'node_unit_suite.json'), 'w') as f: json.dump(suite, f)
passed = sum(1 for t in all_tests if t['status'] == 'passed')
failed = sum(1 for t in all_tests if t['status'] == 'failed')
print(f'  Node unit total: {passed} passed, {failed} failed ({dur}s)')
" "$WORK_DIR" "$suite_dur"
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

  # On production: limit to the single inference-safe smoke test.
  # This avoids LLM inference costs for every spec while still verifying the
  # core chat flow (login → send message → AI response → decrypt) on prod.
  if [[ "$ENVIRONMENT" == "production" ]]; then
    local prod_spec="chat-flow.spec.ts"
    if [[ " ${all_specs[*]} " == *" $prod_spec "* ]]; then
      echo "  [production] Limiting Playwright to $prod_spec (1 of ${#all_specs[@]} specs)"
      all_specs=("$prod_spec")
    else
      echo "  [production] WARNING: $prod_spec not found — running no Playwright specs"
      echo '{"status":"skipped","reason":"production: chat-flow.spec.ts not found","duration_seconds":0,"workers":0,"tests":[]}' \
        > "$WORK_DIR/playwright_suite.json"
      return
    fi
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
      "$PROJECT_ROOT" \
      "$PLAYWRIGHT_BASE_URL_OVERRIDE" \
      "$USE_PROD_ACCOUNT" &
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
printf "║  Environment: %-43s║\n" "$ENVIRONMENT"
printf "║  Suite:     %-45s║\n" "$SUITE"
printf "║  Unit only: %-45s║\n" "$UNIT_ONLY"
printf "║  Workers:   %-45s║\n" "$MAX_WORKERS"
if [[ -n "$PLAYWRIGHT_BASE_URL_OVERRIDE" ]]; then
  printf "║  Base URL:  %-45s║\n" "$PLAYWRIGHT_BASE_URL_OVERRIDE"
fi
if [[ "$USE_PROD_ACCOUNT" == "true" ]]; then
  printf "║  %-55s║\n" "Using prod test account credentials"
fi
if [[ "$ENVIRONMENT" == "production" ]]; then
  printf "║  %-55s║\n" "PRODUCTION: playwright limited to chat-flow.spec.ts"
  printf "║  %-55s║\n" "PRODUCTION: pytest integration skipped"
fi
if [[ "$ONLY_FAILED" == "true" ]]; then
  printf "║  Mode:      %-45s║\n" "rerun failed (${#FAILED_SPECS[@]} tests)"
fi
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Run suites in order: vitest (fastest) → node unit → pytest → playwright (slowest)
run_vitest
run_node_unit
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
    ('node_unit', 'node_unit_suite.json'),
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

# Helper: remove file first to avoid PermissionError when a previous run
# created the file as a different user (e.g. root via cron).
def safe_write_json(path, obj):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2)

# Write run file
safe_write_json(run_file, result)

# Write last-run.json (always overwrite)
last_run = os.path.join(results_dir, 'last-run.json')
safe_write_json(last_run, result)

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

# ─── Post-run: fetch E2E client-side logs from OpenObserve ───────────────────
# After Playwright specs complete, query OpenObserve for all browser console logs
# forwarded during the run (tagged with run_id via getE2EDebugUrl). These logs
# are appended to the run results JSON so failures can be diagnosed without
# re-running tests.
#
# Only runs when:
#   1. E2E specs were executed (not unit-only)
#   2. INTERNAL_API_SHARED_TOKEN is set (needed by debug.py)
#   3. docker exec api is available
if [[ "$UNIT_ONLY" != "true" && -n "${INTERNAL_API_SHARED_TOKEN:-}" ]]; then
  echo ""
  echo "━━━ E2E Client-Side Log Summary (run_id=${RUN_ID}) ━━━"
  SINCE_SECS=$(( $(date +%s) - $(date -d "${RUN_ID}" +%s 2>/dev/null || echo "$(date +%s)") + 60 ))
  # Cap at 600s to avoid overly broad queries
  [[ $SINCE_SECS -gt 600 ]] && SINCE_SECS=600

  CLIENT_LOG_OUTPUT=""
  if docker exec api true 2>/dev/null; then
    CLIENT_LOG_OUTPUT="$(
      docker exec api python /app/backend/scripts/debug.py logs --debug-id "$RUN_ID" --level error --since "$SINCE_SECS" 2>&1
    )" || true
  fi

  if [[ -n "$CLIENT_LOG_OUTPUT" ]]; then
    echo "$CLIENT_LOG_OUTPUT"
    # Save to results dir for the email summary and future analysis
    echo "$CLIENT_LOG_OUTPUT" > "$RESULTS_DIR/client-errors-${RUN_ID}.txt"
    echo "  Saved to: $RESULTS_DIR/client-errors-${RUN_ID}.txt"
  else
    echo "  No client-side errors found (or OpenObserve query timed out)."
    echo "  Tip: query manually with: debug.py logs --debug-id $RUN_ID"
  fi
fi
