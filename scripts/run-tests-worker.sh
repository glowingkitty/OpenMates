#!/usr/bin/env bash
# =============================================================================
# Playwright Worker Script
#
# Called by run-tests.sh for each worker slot. Runs assigned spec files
# sequentially in a Docker container with the slot's test account credentials.
#
# Arguments:
#   $1 - Slot number (1-5)
#   $2 - Pipe-separated list of spec filenames (e.g. "chat-flow.spec.ts|login.spec.ts")
#   $3 - Work directory for result output
#   $4 - Project root directory
#
# Abort-on-first-failure behaviour:
#   All workers share a single $WORK_DIR/abort_signal file. The first worker to
#   record a failure writes this file. Every worker checks it before starting
#   each new spec: if it exists, the spec is recorded as "not_started" and
#   skipped rather than launched. Already-running specs are never interrupted --
#   they always run to completion.
#
# Output:
#   Writes $WORK_DIR/pw_result_<slot>.json with an array of test results.
# =============================================================================
set -euo pipefail

SLOT="$1"
SPECS_RAW="$2"
WORK_DIR="$3"
PROJECT_ROOT="$4"

# Shared abort signal file. Written atomically by the first worker that records
# a failure. All workers check this before starting the next spec.
ABORT_SIGNAL="$WORK_DIR/abort_signal"

# Split pipe-separated specs into an array
IFS='|' read -ra SPECS <<< "$SPECS_RAW"

RESULTS=()

for spec in "${SPECS[@]}"; do
  # --- Abort check: if any earlier spec (on any slot) failed, don't start new ones ---
  if [[ -f "$ABORT_SIGNAL" ]]; then
    abort_reason="$(cat "$ABORT_SIGNAL")"
    echo "    [Slot $SLOT] - $spec -- not started ($abort_reason)"

    result="$(python3 -c "
import json, sys
entry = {
    'file': sys.argv[1],
    'slot': int(sys.argv[2]),
    'status': 'not_started',
    'duration_seconds': 0,
    'skip_reason': sys.argv[3],
}
print(json.dumps(entry))
" "$spec" "$SLOT" "$abort_reason")"

    RESULTS+=("$result")
    continue
  fi

  echo "    [Slot $SLOT] Running: $spec"
  local_start="$(date +%s)"

  # Run the spec in the Playwright Docker container with the slot's credentials.
  # The PLAYWRIGHT_WORKER_SLOT env var tells getTestAccount() which account to use.
  spec_output=""
  spec_exit=0
  spec_output="$(
    cd "$PROJECT_ROOT" && \
    docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
      -e "PLAYWRIGHT_WORKER_SLOT=$SLOT" \
      -e "PLAYWRIGHT_TEST_FILE=$spec" \
      -e SIGNUP_TEST_EMAIL_DOMAINS \
      -e MAILOSAUR_API_KEY \
      -e MAILOSAUR_SERVER_ID \
      playwright 2>&1
  )" || spec_exit=$?

  local_dur=$(( $(date +%s) - local_start ))

  # Determine pass/fail and extract error if any
  if [[ $spec_exit -eq 0 ]]; then
    status="passed"
    error=""
  else
    status="failed"
    # Extract the last meaningful error lines from Playwright output
    error="$(echo "$spec_output" | grep -E '(Error|FAIL|Timeout|expect\.|error)' | tail -5 | head -c 500)"
    if [[ -z "$error" ]]; then
      error="Exit code $spec_exit"
    fi

    # Write the abort signal so all other workers stop launching new specs.
    # Use a temp-file + mv -n for an atomic create -- only the first writer's
    # message is kept; subsequent attempts silently discard their temp file.
    if [[ ! -f "$ABORT_SIGNAL" ]]; then
      abort_tmp="$(mktemp "$WORK_DIR/abort_signal.XXXXXX")"
      echo "aborted: $spec failed on slot $SLOT" > "$abort_tmp"
      mv -n "$abort_tmp" "$ABORT_SIGNAL" 2>/dev/null || rm -f "$abort_tmp"
    fi
  fi

  # Truncate stdout for LLM readability
  if [[ ${#spec_output} -gt 5000 ]]; then
    spec_output="${spec_output:0:4900}...[truncated, ${#spec_output} chars total]"
  fi

  # Build JSON result for this spec
  result="$(python3 -c "
import json, sys
entry = {
    'file': sys.argv[1],
    'slot': int(sys.argv[2]),
    'status': sys.argv[3],
    'duration_seconds': int(sys.argv[4]),
}
if sys.argv[5]:
    entry['error'] = sys.argv[5]
entry['stdout'] = sys.argv[6]
print(json.dumps(entry))
" "$spec" "$SLOT" "$status" "$local_dur" "$error" "$spec_output")"

  RESULTS+=("$result")

  if [[ "$status" == "passed" ]]; then
    echo "    [Slot $SLOT] + $spec (${local_dur}s)"
  else
    echo "    [Slot $SLOT] x $spec (${local_dur}s)"
  fi
done

# Write all results for this slot to a single JSON file
RESULT_FILE="$WORK_DIR/pw_result_${SLOT}.json"
python3 -c "
import json, sys
out_path = sys.argv[1]
results = []
for arg in sys.argv[2:]:
    results.append(json.loads(arg))
with open(out_path, 'w') as f:
    json.dump(results, f)
" "$RESULT_FILE" "${RESULTS[@]}"
