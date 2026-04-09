#!/bin/bash
# Hook: PostToolUse (Edit|Write) — auto-rebuild-translations
# ------------------------------------------------------------------
# Auto-rebuilds translation JSON when a .yml source file is edited.
#
# Fail-loud behaviour: captures stderr from `npm run build:translations`
# and echoes it back so Claude sees build failures instead of silently
# shipping stale JSON. Previously this hook redirected both streams to
# /dev/null which masked every failure. (Hook #10 in OPE-375 audit.)
#
# Exit codes:
#   0 — success, or file not under i18n/sources/
#   1 — build failed (stderr surfaced to Claude)

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
LOG="/tmp/openmates-i18n-build-$$.log"

# Rebuild translations, capturing combined output
if ( cd "$UI_DIR" && npm run build:translations ) >"$LOG" 2>&1; then
  rm -f "$LOG"
  exit 0
fi

# Build failed — surface the tail of the log to stderr so Claude sees it
echo "❌ i18n build FAILED after editing $(basename "$FILE") — translations were NOT regenerated." >&2
echo "Last 25 lines of output:" >&2
tail -25 "$LOG" >&2
echo "" >&2
echo "Fix the YAML error and re-save the file, or run manually:" >&2
echo "  cd frontend/packages/ui && npm run build:translations" >&2
rm -f "$LOG"
exit 1
