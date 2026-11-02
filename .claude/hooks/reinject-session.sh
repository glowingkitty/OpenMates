#!/bin/bash
# Hook: SessionStart (compact)
# Re-injects this conversation's sessions.py context after compaction so Claude
# keeps the right session ID, task and worktree. Silent when none is bound.

INPUT=$(cat)
PROJECT_DIR="/home/superdev/projects/OpenMates"
SESSIONS_FILE="$PROJECT_DIR/.claude/sessions.json"
# shellcheck source=lib/current-session.sh
source "$(dirname "$0")/lib/current-session.sh"

CLAUDE_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
SID=$(current_session_id "${CLAUDE_ID:-$CLAUDE_CODE_SESSION_ID}" "$CWD" "$SESSIONS_FILE")
[ -z "$SID" ] && exit 0

jq -r --arg sid "$SID" '
  .sessions[$sid] as $s |
  "SESSION CONTEXT (re-injected after compaction):\n" +
  "  Session ID: \($sid)\n" +
  "  Mode: \($s.mode // "unknown")\n" +
  "  Task: \($s.task // "unknown")\n" +
  "  Workspace: \($s.worktree.path // "canonical checkout")\n" +
  "Edit only in that workspace; pass --session \($sid) when a command cannot infer it."
' "$SESSIONS_FILE" 2>/dev/null
exit 0
