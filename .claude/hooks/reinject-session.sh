#!/bin/bash
# Hook: SessionStart (compact)
# Re-injects active session context after context compaction so Claude
# doesn't lose track of the session ID, task, and tracked files.

PROJECT_DIR="/home/superdev/projects/OpenMates"
SESSIONS_FILE="$PROJECT_DIR/.claude/sessions.json"

if [ ! -f "$SESSIONS_FILE" ]; then
  echo "No active sessions.py session found."
  exit 0
fi

# Find the most recently active session
SESSION_DATA=$(jq -r '
  .sessions | to_entries |
  sort_by(.value.last_active) | last //empty |
  if . == "" then empty else
  "SESSION CONTEXT (re-injected after compaction):\n" +
  "  Session ID: \(.key)\n" +
  "  Mode: \(.value.mode // "unknown")\n" +
  "  Task: \(.value.task // "unknown")\n" +
  "  Tags: \(.value.tags // [] | join(", "))\n" +
  "  Task ID: \(.value.task_id // "none")\n" +
  "  Tracked files (\(.value.modified_files | length)):\n" +
  (.value.modified_files[:20] | map("    - " + .) | join("\n")) +
  if (.value.modified_files | length) > 20 then "\n    ... and \(.value.modified_files | length - 20) more" else "" end +
  "\n\nREMINDER: Use session ID \(.key) for all sessions.py commands (track, deploy, end)."
  end
' "$SESSIONS_FILE" 2>/dev/null)

if [ -n "$SESSION_DATA" ]; then
  echo -e "$SESSION_DATA"
else
  echo "No active sessions.py session found."
fi

exit 0
