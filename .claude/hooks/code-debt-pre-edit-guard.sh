#!/bin/bash
# Hook: PreToolUse (Edit|Write)
# Non-blocking maintainability reminder when editing large source files.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0
[ ! -f "$FILE" ] && exit 0

case "$FILE" in
  *.py|*.ts|*.tsx|*.svelte|*.js|*.mjs|*.swift) ;;
  *) exit 0 ;;
esac

LINES=$(wc -l < "$FILE" | tr -d ' ')
PROJECT_DIR="/home/superdev/projects/OpenMates"
REL_FILE="${FILE#$PROJECT_DIR/}"

if [ "$LINES" -ge 4000 ]; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"additionalContext\":\"MAINTAINABILITY WARNING: $REL_FILE is $LINES lines. Prefer a behavior-preserving extraction seam instead of adding more responsibilities inline. If you must edit it, keep the diff minimal and verify related tests.\"}}"
elif [ "$LINES" -ge 2500 ]; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"additionalContext\":\"Maintainability note: $REL_FILE is $LINES lines. Consider extracting helpers/components/services rather than expanding the file.\"}}"
fi

exit 0
