#!/bin/bash
# Hook: PostToolUse (Edit|Write)
# Auto-tracks edited/written files in the active sessions.py session.
# Runs async so it doesn't slow down edits.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Skip if no file path (shouldn't happen for Edit/Write, but be safe)
[ -z "$FILE" ] && exit 0

# Skip non-project files (e.g. /tmp, /home/.claude/plans)
PROJECT_DIR="/home/superdev/projects/OpenMates"
case "$FILE" in
  "$PROJECT_DIR"/*) ;;
  *) exit 0 ;;
esac

# Skip plan files and session files themselves
case "$FILE" in
  */.claude/plans/*|*/.claude/sessions*|*/.claude/hooks/*) exit 0 ;;
esac

# Track the file (--file without --session auto-selects most recent session)
python3 "$PROJECT_DIR/scripts/sessions.py" track --file "$FILE" 2>/dev/null

exit 0
