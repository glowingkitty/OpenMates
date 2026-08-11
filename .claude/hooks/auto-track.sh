#!/bin/bash
# Hook: PostToolUse (Edit|Write)
# Auto-tracks edited/written files in the active sessions.py session.
# Runs async so it doesn't slow down edits.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Skip if no file path (shouldn't happen for Edit/Write, but be safe)
[ -z "$FILE" ] && exit 0

PROJECT_DIR="/home/superdev/projects/OpenMates"
# Track the file. OpenCode provides an exact session id; resolve it to the
# short sessions.py id so concurrent chats do not attach files to each other.
if [ -n "$OPENCODE_SESSION_ID" ] && [ -f "$PROJECT_DIR/.claude/sessions.json" ]; then
  SESSION_ID=$(jq -r --arg id "$OPENCODE_SESSION_ID" \
    '[.sessions | to_entries[] | select(.value.opencode_session_id == $id) | .key] | if length == 1 then .[0] else empty end' \
    "$PROJECT_DIR/.claude/sessions.json" 2>/dev/null)
fi

SESSION_REPO_ROOT=""
if [ -n "$SESSION_ID" ] && [ -f "$PROJECT_DIR/.claude/sessions.json" ]; then
  SESSION_REPO_ROOT=$(jq -r --arg id "$SESSION_ID" '.sessions[$id].repo_root // empty' "$PROJECT_DIR/.claude/sessions.json" 2>/dev/null)
fi

# Skip non-project files (e.g. /tmp, /home/.claude/plans). Session worktrees and
# allowlisted sibling repos are canonicalized by sessions.py.
ALLOWED_FILE=""
case "$FILE" in
  "$PROJECT_DIR"/*|*/.openmates-agent-worktrees/*|*/.agent-worktrees/*) ALLOWED_FILE="1" ;;
esac
if [ -n "$SESSION_REPO_ROOT" ]; then
  case "$FILE" in
    "$SESSION_REPO_ROOT"/*) ALLOWED_FILE="1" ;;
  esac
fi
[ -z "$ALLOWED_FILE" ] && exit 0

# Skip plan files and session files themselves
case "$FILE" in
  */.claude/plans/*|*/.claude/sessions*|*/.claude/hooks/*) exit 0 ;;
esac

if [ -n "$SESSION_ID" ]; then
  python3 "$PROJECT_DIR/scripts/sessions.py" track --session "$SESSION_ID" --file "$FILE" 2>/dev/null
else
  python3 "$PROJECT_DIR/scripts/sessions.py" track --file "$FILE" 2>/dev/null
fi

exit 0
