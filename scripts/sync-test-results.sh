#!/usr/bin/env bash
# =============================================================================
# OpenMates Test Results Sync
#
# Downloads the latest playwright-spec.yml workflow results from GitHub Actions
# and writes them to test-results/ so the /status page and sessions.py
# can read fresh data.
#
# NOTE: Per-spec failure screenshots are archived by run_tests.py during batch
# execution (to test-results/screenshots/{date}/{spec-name}/). This script only
# syncs the aggregated JSON results artifact.
#
# Two modes:
#   1. --wait: Trigger + wait for a running workflow, then download results.
#      Used by the crontab entry after dispatching playwright-spec.yml.
#   2. --latest: Download results from the most recent completed run.
#      Used for ad-hoc syncs.
#
# Crontab usage:
#   0 3 * * * /path/to/scripts/sync-test-results.sh --wait >> logs/daily-tests-sync.log 2>&1
#
# Architecture: docs/architecture/github-actions-ci.md
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="$PROJECT_ROOT/test-results"
REPO="glowingkitty/OpenMates"
WORKFLOW="playwright-spec.yml"

# Max wait: 40 minutes (tests typically take ~20 min)
MAX_WAIT_SECONDS=2400
POLL_INTERVAL=30

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

# Get the latest run ID for the workflow
get_latest_run() {
    local status_filter="${1:-completed}"
    gh run list \
        --repo "$REPO" \
        --workflow "$WORKFLOW" \
        --limit 1 \
        --json databaseId,status,conclusion,createdAt \
        --jq ".[0] // empty" 2>/dev/null
}

# Wait for a running workflow to complete
wait_for_completion() {
    local waited=0
    log "Waiting for $WORKFLOW to complete (max ${MAX_WAIT_SECONDS}s)..."

    while [ "$waited" -lt "$MAX_WAIT_SECONDS" ]; do
        local run_json
        run_json=$(get_latest_run)

        if [ -z "$run_json" ]; then
            log "No runs found for $WORKFLOW — waiting..."
            sleep "$POLL_INTERVAL"
            waited=$((waited + POLL_INTERVAL))
            continue
        fi

        local status conclusion run_id
        status=$(echo "$run_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
        conclusion=$(echo "$run_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('conclusion',''))")
        run_id=$(echo "$run_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('databaseId',''))")

        if [ "$status" = "completed" ]; then
            log "Run $run_id completed with conclusion: $conclusion"
            echo "$run_id"
            return 0
        fi

        log "Run $run_id status: $status (waited ${waited}s)..."
        sleep "$POLL_INTERVAL"
        waited=$((waited + POLL_INTERVAL))
    done

    log "ERROR: Timed out waiting for workflow to complete"
    return 1
}

# Download and install results from a completed run
download_results() {
    local run_id="$1"
    local tmp_dir
    tmp_dir=$(mktemp -d -t test-results-sync-XXXXXX)

    log "Downloading aggregated-results artifact from run $run_id..."

    if ! gh run download "$run_id" \
        --repo "$REPO" \
        --name aggregated-results \
        --dir "$tmp_dir" 2>/dev/null; then
        log "ERROR: Failed to download aggregated-results artifact from run $run_id"
        rm -rf "$tmp_dir"
        return 1
    fi

    local src="$tmp_dir/last-run.json"
    if [ ! -f "$src" ]; then
        log "ERROR: last-run.json not found in downloaded artifact"
        rm -rf "$tmp_dir"
        return 1
    fi

    # Validate JSON
    if ! python3 -c "import json; json.load(open('$src'))" 2>/dev/null; then
        log "ERROR: Downloaded last-run.json is not valid JSON"
        rm -rf "$tmp_dir"
        return 1
    fi

    # Read summary for logging
    local summary
    summary=$(python3 -c "
import json
d = json.load(open('$src'))
s = d.get('summary', {})
print(f\"{s.get('total',0)} tests: {s.get('passed',0)} passed, {s.get('failed',0)} failed, {s.get('skipped',0)} skipped\")
" 2>/dev/null || echo "unknown")

    # Install results
    mkdir -p "$RESULTS_DIR"
    cp "$src" "$RESULTS_DIR/last-run.json"
    log "Updated last-run.json ($summary)"

    # Create daily archive
    local today
    today=$(date -u +%Y-%m-%d)
    cp "$src" "$RESULTS_DIR/daily-run-${today}.json"
    log "Archived to daily-run-${today}.json"

    # Prune old archives (keep last 30)
    local count=0
    for old in $(ls -1t "$RESULTS_DIR"/daily-run-*.json 2>/dev/null | tail -n +31); do
        rm -f "$old"
        count=$((count + 1))
    done
    [ "$count" -gt 0 ] && log "Pruned $count old daily archive(s)"

    # Also download flaky-history if it exists in any playwright artifact
    # (aggregate_results.py writes it alongside last-run.json)
    if [ -f "$tmp_dir/flaky-history.json" ]; then
        cp "$tmp_dir/flaky-history.json" "$RESULTS_DIR/flaky-history.json"
        log "Updated flaky-history.json"
    fi

    rm -rf "$tmp_dir"
    log "Sync complete for run $run_id"
    return 0
}

# --- Main ---

MODE="${1:---latest}"

case "$MODE" in
    --wait)
        log "Mode: wait for running workflow, then sync"
        # Give GitHub Actions a moment to register the run
        sleep 10
        RUN_ID=$(wait_for_completion) || exit 1
        download_results "$RUN_ID"
        ;;
    --latest)
        log "Mode: sync latest completed run"
        RUN_JSON=$(get_latest_run)
        if [ -z "$RUN_JSON" ]; then
            log "ERROR: No completed runs found for $WORKFLOW"
            exit 1
        fi
        RUN_ID=$(echo "$RUN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('databaseId',''))")
        STATUS=$(echo "$RUN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
        if [ "$STATUS" != "completed" ]; then
            log "Latest run $RUN_ID is still $STATUS — use --wait to wait for it"
            exit 1
        fi
        download_results "$RUN_ID"
        ;;
    --run)
        if [ -z "${2:-}" ]; then
            echo "Usage: $0 --run <run_id>" >&2
            exit 1
        fi
        log "Mode: sync specific run $2"
        download_results "$2"
        ;;
    *)
        echo "Usage: $0 [--wait | --latest | --run <run_id>]" >&2
        echo "  --wait    Wait for running workflow to complete, then download results"
        echo "  --latest  Download results from the most recent completed run"
        echo "  --run ID  Download results from a specific run ID"
        exit 1
        ;;
esac
