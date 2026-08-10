#!/bin/bash
# Hook: PostToolUse (Edit|Write|apply_patch) - contract/test impact reminder.
# Edits remain fast and non-blocking; scripts/contracts.py and deploy own gates.

set -u

INPUT=$(cat)
PROJECT_ROOT="${OPENMATES_PROJECT_ROOT:-/home/superdev/projects/OpenMates}"
FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // .tool_input.path // empty')
[ -n "$FILE" ] || exit 0

case "$FILE" in
  "$PROJECT_ROOT"/*) REL="${FILE#$PROJECT_ROOT/}" ;;
  */.openmates-agent-worktrees/*)
    REL="${FILE#*/.openmates-agent-worktrees/*/}"
    ;;
  *) exit 0 ;;
esac

emit_context() {
  local message="$1"
  printf '%s\n' "$message" >&2
  jq -nc --arg msg "$message" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$msg}}'
}

case "$REL" in
  contracts/generated/*)
    ;;
  contracts/*)
    SESSION_ID="${OPENMATES_SESSION_ID:-${SESSION_ID:-<session-id>}}"
    BUNDLE="${REL%/*}"
    MESSAGE="[OpenMates contract approval required] The session worktree is the proposal boundary. Do not deploy this contract.yml or examples.yml change until explicit user confirmation is recorded for the exact bundle hash. For a new contract, quote the complete contract.yml in chat. For an existing contract, quote every explicit contract.yml and examples.yml change in chat. Ask for explicit user confirmation, then run: python3 scripts/contracts.py approve ${BUNDLE} --session ${SESSION_ID} --confirmation explicit_user_confirmation. Any later bundle edit invalidates approval and requires confirmation again."
    emit_context "$MESSAGE"
    ;;
  *.spec.ts|*.test.ts|*.spec.tsx|*.test.tsx|*.spec.js|*.test.js|test_*.py|*_test.py|*Tests.swift)
    HOOK_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
    FILE_ROOT=$(git -C "$(dirname "$FILE")" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PROJECT_ROOT")
    if ! OUTPUT=$(python3 "$HOOK_ROOT/scripts/contracts.py" check-test "$FILE" --contracts-root "$FILE_ROOT/contracts" 2>&1); then
      MESSAGE="[OpenMates contract backfill] Changed test has unresolved contract metadata: ${REL}. Run: python3 scripts/contracts.py check-test ${REL}. First search existing contracts and link applicable assertions. If none defines the intended behavior, invoke the define-contract skill, quote the required contract content, and wait for explicit approval. The edit is allowed now, but deploy will block while this changed test remains unresolved. ${OUTPUT}"
      emit_context "$MESSAGE"
    fi
    ;;
esac

exit 0
