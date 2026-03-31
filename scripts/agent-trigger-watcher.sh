#!/usr/bin/env bash
# agent-trigger-watcher.sh
#
# Polls scripts/.agent-triggers/ for JSON trigger files written by the admin
# sidecar and starts Claude Code investigation sessions in Zellij.
#
# Each trigger file is a JSON object with:
#   issue_id, prompt, session_title, environment, domain, created_at
#
# The watcher:
#   1. Picks up *.json files from the trigger directory
#   2. Writes the prompt to a temp file
#   3. Spawns a new Claude session via sessions.py spawn-chat
#   4. Moves the trigger file to .processed/ so it isn't picked up again
#
# Install as systemd user service:
#   cp scripts/agent-trigger-watcher.service ~/.config/systemd/user/
#   systemctl --user daemon-reload
#   systemctl --user enable --now agent-trigger-watcher.service
#
# Or run directly: ./scripts/agent-trigger-watcher.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TRIGGER_DIR="$SCRIPT_DIR/.agent-triggers"
PROCESSED_DIR="$TRIGGER_DIR/.processed"
LOG_FILE="$PROJECT_DIR/logs/agent-investigations.log"
POLL_INTERVAL_SECONDS=30

# Ensure directories exist.
# The trigger dir may be owned by root (created by Docker bind-mount).
# The .processed/ subdir is created by us on the host, so it should succeed
# as long as the trigger dir has write permission for our user.
mkdir -p "$TRIGGER_DIR" "$(dirname "$LOG_FILE")"
mkdir -p "$PROCESSED_DIR" 2>/dev/null || {
    # If root owns the trigger dir, we can't create subdirs.
    # Fall back to a sibling directory we can create ourselves.
    PROCESSED_DIR="$SCRIPT_DIR/.agent-triggers-processed"
    mkdir -p "$PROCESSED_DIR"
}

log() {
    local timestamp
    timestamp="$(date -u '+%Y-%m-%d %H:%M:%S')"
    echo "[$timestamp] $*" | tee -a "$LOG_FILE"
}

process_trigger() {
    local trigger_file="$1"
    local filename
    filename="$(basename "$trigger_file")"

    # Parse JSON fields using python3 (always available on the host)
    local issue_id session_title prompt agent_action
    issue_id="$(python3 -c "import json,sys; print(json.load(sys.stdin)['issue_id'])" < "$trigger_file")"
    session_title="$(python3 -c "import json,sys; print(json.load(sys.stdin)['session_title'])" < "$trigger_file")"
    prompt="$(python3 -c "import json,sys; print(json.load(sys.stdin)['prompt'])" < "$trigger_file")"
    agent_action="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_action', 'fix'))" < "$trigger_file")"

    if [[ -z "$issue_id" || -z "$prompt" ]]; then
        log "ERROR: Trigger file $filename missing issue_id or prompt — skipping"
        mv "$trigger_file" "$PROCESSED_DIR/${filename}.invalid"
        return 1
    fi

    log "Processing trigger: issue_id=$issue_id title='$session_title' action=$agent_action"

    # Write prompt to a temp file for spawn-chat --prompt-file
    local prompt_file="$SCRIPT_DIR/.tmp/agent-prompt-${issue_id}.txt"
    mkdir -p "$SCRIPT_DIR/.tmp"
    echo "$prompt" > "$prompt_file"

    # Spawn a Claude Code session in a new Zellij tab
    # Use plan mode for research-only, execute mode for fix attempts
    local session_mode="execute"
    if [[ "$agent_action" == "research" ]]; then
        session_mode="plan"
    fi
    local session_name="investigate-${issue_id:0:8}"
    if python3 "$SCRIPT_DIR/sessions.py" spawn-chat \
        --prompt-file "$prompt_file" \
        --name "$session_name" \
        --mode "$session_mode" 2>&1 | tee -a "$LOG_FILE"; then
        log "Spawned session '$session_name' for issue $issue_id"
    else
        log "ERROR: Failed to spawn session for issue $issue_id (exit code $?)"
    fi

    # Move trigger file to processed (even on failure — avoid infinite retries)
    mv "$trigger_file" "$PROCESSED_DIR/$filename"
    log "Moved trigger to processed: $filename"

    # Clean up prompt file (session has already read it)
    rm -f "$prompt_file"
}

# ── Main loop ────────────────────────────────────────────────────────────────

log "Agent trigger watcher started (poll interval: ${POLL_INTERVAL_SECONDS}s)"
log "  Trigger dir: $TRIGGER_DIR"
log "  Processed dir: $PROCESSED_DIR"

while true; do
    # Find all .json trigger files (not in .processed/)
    trigger_files=()
    while IFS= read -r -d '' f; do
        trigger_files+=("$f")
    done < <(find "$TRIGGER_DIR" -maxdepth 1 -name '*.json' -type f -print0 2>/dev/null)

    if [[ ${#trigger_files[@]} -gt 0 ]]; then
        log "Found ${#trigger_files[@]} trigger file(s)"
        for trigger_file in "${trigger_files[@]}"; do
            process_trigger "$trigger_file" || true
        done
    fi

    sleep "$POLL_INTERVAL_SECONDS"
done
