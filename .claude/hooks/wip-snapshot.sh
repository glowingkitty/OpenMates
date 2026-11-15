#!/bin/bash
# Hook: Stop
# At the end of every turn, commit this chat's dirty session worktree(s) to the
# session-owned WIP ref refs/openmates/wip/<session> (scripts/worktree_wip.py), so
# uncommitted work never lives only in a checkout. Runs detached and never blocks
# or fails the turn; the worktree, its index and HEAD are not touched.
INPUT=$(cat)
CHAT_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
CHAT_ID="${CHAT_ID:-$CLAUDE_CODE_SESSION_ID}"
[ -z "$CHAT_ID" ] && exit 0
SCRIPT="$(cd "$(dirname "$0")/../../scripts" 2>/dev/null && pwd)/worktree_wip.py"
[ -f "$SCRIPT" ] || exit 0
setsid nohup timeout 120 python3 "$SCRIPT" snapshot --chat "$CHAT_ID" --reason turn-end --quiet \
  >/dev/null 2>&1 < /dev/null &
exit 0
