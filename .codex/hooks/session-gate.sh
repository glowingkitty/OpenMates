#!/bin/bash
# Hook: UserPromptSubmit
# Checks for an active session and injects a warning if none exists.
# Replaces the old SessionStart "REMINDER" hook — this fires on every user message.

PROJECT_DIR="/home/superdev/projects/OpenMates"
SESSIONS_FILE="$PROJECT_DIR/.claude/sessions.json"

if [ ! -f "$SESSIONS_FILE" ]; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"UserPromptSubmit\",\"additionalContext\":\"WARNING: No active session. Run: python3 scripts/sessions.py start --mode <MODE> --task \\\"description\\\"\"}}"
  exit 0
fi

ACTIVE=$(jq '[.sessions | to_entries[]] | length' "$SESSIONS_FILE" 2>/dev/null)
if [ "$ACTIVE" = "0" ] || [ -z "$ACTIVE" ]; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"UserPromptSubmit\",\"additionalContext\":\"WARNING: No active session. Run: python3 scripts/sessions.py start --mode <MODE> --task \\\"description\\\"\"}}"
fi

exit 0
