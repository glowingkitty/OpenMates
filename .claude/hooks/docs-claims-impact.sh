#!/bin/bash
# Hook: PostToolUse (Edit|Write|apply_patch) — docs-claims-impact
# Surfaces documentation/test claim context without blocking agent work.

INPUT=$(cat)
PROJECT_ROOT="/home/superdev/projects/OpenMates"

FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // .tool_input.path // empty')
[ -z "$FILE" ] && exit 0

case "$FILE" in
  "$PROJECT_ROOT"/*) REL="${FILE#$PROJECT_ROOT/}" ;;
  /*) exit 0 ;;
  *) REL="$FILE" ;;
esac

case "$REL" in
  docs/*|*.spec.ts|*.test.ts|backend/tests/*.py|backend/tests/**/*.py|scripts/tests/*.py|scripts/tests/**/*.py) ;;
  *) exit 0 ;;
esac

OUTPUT=$(cd "$PROJECT_ROOT" && python3 scripts/docs_claims_impact.py "$REL" 2>/dev/null)
if [ -n "$OUTPUT" ]; then
  echo "$OUTPUT" >&2
  jq -nc --arg msg "$OUTPUT" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$msg}}'
fi

exit 0
