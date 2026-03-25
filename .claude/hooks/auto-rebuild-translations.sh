#!/bin/bash
# Hook: PostToolUse (Edit|Write)
# Auto-rebuilds translation JSON when a .yml source file is edited.
# Runs async so it doesn't block edits.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only trigger for .yml files under i18n/sources/
case "$FILE" in
  */i18n/sources/*.yml|*/i18n/sources/**/*.yml) ;;
  *) exit 0 ;;
esac

PROJECT_DIR="/home/superdev/projects/OpenMates"
UI_DIR="$PROJECT_DIR/frontend/packages/ui"

# Rebuild translations (this regenerates the JSON files from YAML sources)
cd "$UI_DIR" && npm run build:translations >/dev/null 2>&1

exit 0
