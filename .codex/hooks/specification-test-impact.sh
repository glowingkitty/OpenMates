#!/bin/bash
# Hook: PostToolUse (Edit|Write|apply_patch) - Specification/test impact reminder.
# Edits remain fast and non-blocking; scripts/specifications.py and deploy own gates.

set -u

INPUT=$(cat)
PROJECT_ROOT="${OPENMATES_PROJECT_ROOT:-/home/superdev/projects/OpenMates}"
FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // .tool_input.path // empty')
[ -n "$FILE" ] || exit 0

case "$FILE" in
  */.openmates-agent-worktrees/*/*)
    REL="${FILE#*/.openmates-agent-worktrees/}"
    REL="${REL#*/}"
    ;;
  */.openmates-agent-worktrees/*)
    REL="${FILE#*/.openmates-agent-worktrees/}"
    REL="${REL#*/}"
    ;;
  "$PROJECT_ROOT"/*) REL="${FILE#$PROJECT_ROOT/}" ;;
  *) exit 0 ;;
esac

emit_context() {
  local message="$1"
  printf '%s\n' "$message" >&2
  jq -nc --arg msg "$message" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$msg}}'
}

case "$REL" in
  specifications/generated/*)
    ;;
  specifications/*)
    SESSION_ID="${OPENMATES_SESSION_ID:-${SESSION_ID:-<session-id>}}"
    BUNDLE="${REL%/*}"
    MESSAGE="[OpenMates Specification approval required] The session worktree is the proposal boundary. Do not deploy this specification.yml or examples.yml change until explicit user confirmation is recorded for the exact bundle hash. For a new Specification, quote the complete specification.yml in chat. For an existing Specification, quote every explicit specification.yml and examples.yml change in chat. Ask for explicit user confirmation, then run: python3 scripts/specifications.py approve ${BUNDLE} --session ${SESSION_ID} --confirmation explicit_user_confirmation. Any later bundle edit invalidates approval and requires confirmation again."
    emit_context "$MESSAGE"
    ;;
  *.spec.ts|*.test.ts|*.spec.tsx|*.test.tsx|*.spec.js|*.test.js|test_*.py|*_test.py|*Tests.swift)
    HOOK_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
    case "$REL" in
      frontend/apps/web_app/tests/*.spec.ts)
        if ! PROOF_OUTPUT=$(python3 "$HOOK_ROOT/scripts/audit_playwright_proof_metadata.py" "$FILE" 2>&1); then
          MESSAGE="[OpenMates proof-video backfill] Changed Playwright spec is missing proof-video metadata or an explicit not-required classification: ${REL}. Add defineVideoProof(...) with transcript/assertions/checkpoints/devices when the spec proves visible user behavior, or add a top-of-file comment like // proof-video: not_required reason=non_visual_setup. ${PROOF_OUTPUT}"
          emit_context "$MESSAGE"
        fi
        ;;
    esac
    FILE_ROOT=$(git -C "$(dirname "$FILE")" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PROJECT_ROOT")
    if ! OUTPUT=$(python3 "$HOOK_ROOT/scripts/specifications.py" check-test "$FILE" --specifications-root "$FILE_ROOT/specifications" 2>&1); then
      MESSAGE="[OpenMates Specification backfill] Changed test has unresolved Specification metadata: ${REL}. Run: python3 scripts/specifications.py check-test ${REL}. First search existing Specifications and link applicable assertions. If none defines the intended behavior, invoke the define-specification skill, quote the required Specification content, and wait for explicit approval. The edit is allowed now, but deploy will block while this changed test remains unresolved. ${OUTPUT}"
      emit_context "$MESSAGE"
    fi
    ;;
esac

exit 0
