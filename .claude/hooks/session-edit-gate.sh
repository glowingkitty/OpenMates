#!/bin/bash
# Hook: PreToolUse (Edit|Write|MultiEdit|NotebookEdit)
# Blocks repository edits that bypass the sessions.py workspace workflow:
#   - tracked files in the canonical checkout (the checkout stays on `dev`);
#   - files in another task's session worktree;
#   - files in a session worktree when this conversation owns no session.
# Allowed: files outside the repository, gitignored/private files (for example
# FOCUS.md) and this conversation's own session worktree.
# Fails open when jq or the sessions file is unavailable.
# Related: CLAUDE.md "Workflow", .claude/hooks/lib/current-session.sh

set -u

INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' 2>/dev/null)
[ -n "$FILE" ] || exit 0

PROJECT_ROOT="${OPENMATES_PROJECT_ROOT:-/home/superdev/projects/OpenMates}"
SESSIONS_FILE="$PROJECT_ROOT/.claude/sessions.json"
WORKTREES="$PROJECT_ROOT/.openmates-agent-worktrees"

case "$FILE" in
  "$PROJECT_ROOT"/*) ;;
  *) exit 0 ;; # outside the repository
esac

deny() {
  printf 'BLOCKED: %s\n' "$1" >&2
  exit 2
}

START_HINT='Start your own workspace first: python3 scripts/sessions.py start --mode <bug|feature|docs|testing> --task "<outcome>", then edit only in the returned worktree.'

case "$FILE" in
  "$WORKTREES"/*)
    [ -f "$SESSIONS_FILE" ] || exit 0
    # shellcheck source=lib/current-session.sh
    source "$(dirname "$0")/lib/current-session.sh"
    CLAUDE_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty')
    CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')
    CURRENT=$(current_session_id "${CLAUDE_ID:-${CLAUDE_CODE_SESSION_ID:-}}" "$CWD" "$SESSIONS_FILE")
    OWNER=$(jq -r --arg file "$FILE" '
      [(.sessions // {}) | to_entries[]
        | select((.value.worktree.path // "") as $p | $p != "" and ($file | startswith($p + "/")))
        | .key] | if length == 1 then .[0] else empty end
    ' "$SESSIONS_FILE" 2>/dev/null)
    [ -n "$OWNER" ] || exit 0 # not a registered session worktree: cannot judge
    if [ -z "$CURRENT" ]; then
      deny "this conversation owns no sessions.py session, but $FILE is in session $OWNER's worktree. Never borrow another task's workspace. $START_HINT"
    fi
    if [ "$CURRENT" != "$OWNER" ]; then
      deny "$FILE belongs to session $OWNER, this conversation owns session $CURRENT. Never borrow another task's workspace; edit in your own worktree."
    fi
    exit 0
    ;;
esac

# Canonical checkout: private/ignored files are fine, tracked work is not.
REL="${FILE#"$PROJECT_ROOT"/}"
if git -C "$PROJECT_ROOT" check-ignore -q -- "$REL" 2>/dev/null; then
  exit 0
fi
deny "$REL is in the canonical checkout, which stays on dev and is only changed by sessions.py deploy. $START_HINT"
