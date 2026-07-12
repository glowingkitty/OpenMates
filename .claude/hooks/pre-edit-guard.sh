#!/bin/bash
# Hook: PreToolUse (Edit|Write)
# Guards against editing generated files and warns on concurrent session conflicts.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# --- Guard 1: Block edits to generated translation JSON files ---
if echo "$FILE" | grep -qE 'i18n/locales/.*\.json$'; then
  echo "BLOCKED: Never edit generated translation JSON files directly. Edit the .yml source files in frontend/packages/ui/src/i18n/sources/ instead, then run: cd frontend/packages/ui && npm run build:translations" >&2
  exit 2
fi

# --- Guard 2: Warn on concurrent session file conflicts ---
PROJECT_DIR="/home/superdev/projects/OpenMates"
SESSIONS_FILE="$PROJECT_DIR/.claude/sessions.json"

if [ -f "$SESSIONS_FILE" ]; then
  # Get relative path for matching against session tracked files
  REL_FILE="${FILE#$PROJECT_DIR/}"

  # OpenCode chats share one Zellij process, so their exact `ses_*` identity
  # must win. Claude sessions retain the legacy unique-Zellij fallback.
  if [ -n "$OPENCODE_SESSION_ID" ]; then
    CURRENT_SESSION=$(jq -r --arg id "$OPENCODE_SESSION_ID" \
      '[.sessions | to_entries[] | select(.value.opencode_session_id == $id) | .key] | if length == 1 then .[0] else empty end' \
      "$SESSIONS_FILE" 2>/dev/null)
  else
    CURRENT_SESSION=$(jq -r --arg z "$ZELLIJ_SESSION_NAME" \
      '[.sessions | to_entries[] | select(.value.zellij_session == $z) | .key] | if length == 1 then .[0] else empty end' \
      "$SESSIONS_FILE" 2>/dev/null)
  fi
  CONFLICTS=$(jq -r --arg file "$REL_FILE" --arg current "$CURRENT_SESSION" '
    [.sessions | to_entries[] |
     select(.key != $current) |
     select(.value.modified_files[]? == $file) |
     "\(.key) (\(.value.task // "unknown task"))"] | join(", ")
  ' "$SESSIONS_FILE" 2>/dev/null)

  if [ -n "$CONFLICTS" ] && [ "$CONFLICTS" != "" ]; then
    # Output as additional context (non-blocking warning)
    echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"additionalContext\":\"WARNING: File $REL_FILE is also tracked by session(s): $CONFLICTS. Coordinate to avoid merge conflicts.\"}}"
    exit 0
  fi
fi

exit 0
