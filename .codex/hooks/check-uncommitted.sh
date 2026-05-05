#!/bin/bash
# Hook: Stop
# Checks if the active session has tracked files with uncommitted changes.
# Non-blocking — just adds a reminder as context.

INPUT=$(cat)

# Avoid infinite loop: if stop_hook_active is true, we're in a re-run
STOP_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
if [ "$STOP_ACTIVE" = "true" ]; then
  exit 0
fi

PROJECT_DIR="/home/superdev/projects/OpenMates"
SESSIONS_FILE="$PROJECT_DIR/.claude/sessions.json"

if [ ! -f "$SESSIONS_FILE" ]; then
  exit 0
fi

# Get the most recent session's tracked files
SESSION_ID=$(jq -r '[.sessions | to_entries[] | .key] | last // empty' "$SESSIONS_FILE" 2>/dev/null)
[ -z "$SESSION_ID" ] && exit 0

TRACKED_FILES=$(jq -r --arg id "$SESSION_ID" '.sessions[$id].modified_files // [] | .[]' "$SESSIONS_FILE" 2>/dev/null)
[ -z "$TRACKED_FILES" ] && exit 0

# Check which tracked files are dirty in git
cd "$PROJECT_DIR" || exit 0
DIRTY_FILES=""
while IFS= read -r f; do
  if git diff --name-only HEAD 2>/dev/null | grep -qF "$f" || \
     git diff --name-only 2>/dev/null | grep -qF "$f" || \
     git status --porcelain 2>/dev/null | grep -qF "$f"; then
    DIRTY_FILES="$DIRTY_FILES  - $f\n"
  fi
done <<< "$TRACKED_FILES"

if [ -n "$DIRTY_FILES" ]; then
  echo -e "REMINDER: Session $SESSION_ID has uncommitted tracked files:\n$DIRTY_FILES\nRun: python3 scripts/sessions.py deploy --session $SESSION_ID --title \"type: description\" --end"
fi

exit 0
