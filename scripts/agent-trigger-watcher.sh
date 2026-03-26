#!/usr/bin/env bash
# =============================================================================
# OpenMates Agent Trigger Watcher
#
# Host-side service that polls scripts/.agent-triggers/ for JSON trigger files
# written by the admin sidecar (Docker). For each trigger file found, it runs
# a claude plan-mode investigation session on the host where the claude
# binary is installed.
#
# Architecture:
#   1. Admin submits issue report with "Submit to agent" toggle ON.
#   2. API container calls admin sidecar POST /admin/claude-investigate.
#   3. Sidecar writes a JSON trigger file to the bind-mounted project dir
#      at scripts/.agent-triggers/<issue_id>.json.
#   4. THIS script (running on the host) detects the file, reads the prompt,
#      runs claude, logs the session ID, and moves the file to done/.
#
# Install as a systemd user service:
#   cp scripts/agent-trigger-watcher.service ~/.config/systemd/user/
#   systemctl --user daemon-reload
#   systemctl --user enable --now agent-trigger-watcher.service
#
# Or run manually:
#   ./scripts/agent-trigger-watcher.sh
#
# Env vars (sourced from .env automatically):
#   None required — claude uses its own config.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRIGGER_DIR="$PROJECT_ROOT/scripts/.agent-triggers"
DONE_DIR="$TRIGGER_DIR/done"
LOG_FILE="$PROJECT_ROOT/logs/agent-investigations.log"
POLL_INTERVAL=5  # seconds between polls

# Ensure directories exist
mkdir -p "$TRIGGER_DIR" "$DONE_DIR" "$(dirname "$LOG_FILE")"

# Source .env if present (for any env vars claude may need)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Ensure claude is on PATH
export PATH="/home/superdev/.local/bin:/home/superdev/.npm-global/bin:$PATH"

log() {
    local msg="[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $1"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

process_trigger() {
    local trigger_file="$1"
    local filename
    filename="$(basename "$trigger_file")"

    log "[agent-watcher] Processing trigger: $filename"

    # Extract fields from JSON using python3 (always available)
    local issue_id prompt session_title
    issue_id="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['issue_id'])" "$trigger_file" 2>/dev/null)" || {
        log "[agent-watcher] ERROR: Failed to parse trigger file: $filename"
        mv "$trigger_file" "$DONE_DIR/${filename}.error"
        return
    }
    session_title="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['session_title'])" "$trigger_file")"
    prompt="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['prompt'])" "$trigger_file")"

    # Extract Linear issue UUID (empty string for non-Linear triggers from admin sidecar)
    linear_issue_id="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('linear_issue_id',''))" "$trigger_file" 2>/dev/null)" || true

    log "[agent-watcher] Starting claude investigation (issue_id=$issue_id, title=$session_title)"

    # Write prompt to temp file to avoid MAX_ARG_STRLEN limit
    local tmp_file="$PROJECT_ROOT/scripts/.tmp/claude-trigger-$issue_id.txt"
    mkdir -p "$(dirname "$tmp_file")"
    echo "$prompt" > "$tmp_file"

    # Run claude plan-mode session with a 15 minute timeout
    local output exit_code=0
    output="$(timeout 900 claude \
        -p "Read scripts/.tmp/claude-trigger-$issue_id.txt in full and follow all the instructions precisely." \
        --model "claude-sonnet-4-6" \
        --name "$session_title" \
        --permission-mode plan \
        --output-format json 2>&1)" || exit_code=$?

    # Clean up temp file
    rm -f "$tmp_file"

    if [[ $exit_code -eq 124 ]]; then
        log "[agent-watcher] WARNING: claude timed out after 15 minutes (issue_id=$issue_id)"
    elif [[ $exit_code -ne 0 ]]; then
        log "[agent-watcher] WARNING: claude exited with code $exit_code (issue_id=$issue_id)"
    fi

    # Extract session ID from JSON output
    local session_id=""
    session_id="$(echo "$output" | python3 -c "import json,sys; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)" || true

    if [[ -n "$session_id" ]]; then
        log "[agent-watcher] claude session completed: $session_id (issue_id=$issue_id)"
    else
        log "[agent-watcher] claude ran but no session ID found in output (issue_id=$issue_id)"
    fi

    # Move trigger file to done/
    mv "$trigger_file" "$DONE_DIR/$filename"
    log "[agent-watcher] Trigger processed and moved to done/: $filename"

    # Post investigation results back to Linear (if this was a Linear-triggered issue)
    if [[ -n "$linear_issue_id" && -n "$session_id" ]]; then
        log "[agent-watcher] Updating Linear issue $linear_issue_id with session $session_id"
        LINEAR_API_KEY="$(grep '^LINEAR_API_KEY=' "$PROJECT_ROOT/.env" 2>/dev/null | cut -d= -f2-)" \
        python3 "$PROJECT_ROOT/scripts/linear-update-issue.py" \
            --issue-id "$linear_issue_id" \
            --session-id "$session_id" \
            2>&1 | while read -r line; do log "[linear-update] $line"; done || {
            log "[agent-watcher] WARNING: Failed to update Linear issue $linear_issue_id"
        }
    fi
}

log "[agent-watcher] Starting agent trigger watcher (polling $TRIGGER_DIR every ${POLL_INTERVAL}s)"

while true; do
    # Find all pending .json trigger files (not in done/)
    shopt -s nullglob
    trigger_files=("$TRIGGER_DIR"/*.json)
    shopt -u nullglob

    for trigger_file in "${trigger_files[@]}"; do
        process_trigger "$trigger_file"
    done

    sleep "$POLL_INTERVAL"
done
