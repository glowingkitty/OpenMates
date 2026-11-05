#!/bin/bash
# Hook: Stop
# Reminds about undeployed tracked files of THIS conversation's session.
# Non-blocking — only adds a short reminder.

INPUT=$(cat)
STOP_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$STOP_ACTIVE" = "true" ] && exit 0

PROJECT_DIR="/home/superdev/projects/OpenMates"
SESSIONS_FILE="$PROJECT_DIR/.claude/sessions.json"
# shellcheck source=lib/current-session.sh
source "$(dirname "$0")/lib/current-session.sh"

CLAUDE_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
SESSION_ID=$(current_session_id "${CLAUDE_ID:-$CLAUDE_CODE_SESSION_ID}" "$CWD" "$SESSIONS_FILE")
[ -z "$SESSION_ID" ] && exit 0

ROOT=$(jq -r --arg id "$SESSION_ID" '.sessions[$id].worktree.path // .sessions[$id].repo_root // empty' "$SESSIONS_FILE" 2>/dev/null)
[ -z "$ROOT" ] && ROOT="$PROJECT_DIR"
cd "$ROOT" 2>/dev/null || exit 0

DIRTY=$(git status --porcelain 2>/dev/null | head -10)
[ -z "$DIRTY" ] && exit 0
echo "REMINDER: session $SESSION_ID has undeployed changes in $ROOT:"
echo "$DIRTY"
echo "Deploy when done: python3 scripts/sessions.py deploy --session $SESSION_ID --title \"type: description\" --message \"why + verification\""
exit 0
