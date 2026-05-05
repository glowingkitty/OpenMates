#!/bin/bash
# Hook: PostToolUse (Edit|Write) — svelte-swift-counterpart-linker
# ------------------------------------------------------------------
# Non-blocking warning for bidirectional web<->native file linking.
# When editing a Svelte file with a known Swift counterpart (or vice
# versa), warns about the linked file(s) so both stay in sync.
#
# Reads mapping from: apple/SVELTE_SWIFT_COUNTERPARTS.md

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only trigger for Svelte components or Swift source files
IS_SVELTE=false
IS_SWIFT=false

case "$FILE" in
  */frontend/packages/ui/src/components/*.svelte) IS_SVELTE=true ;;
  */frontend/apps/web_app/src/*.svelte) IS_SVELTE=true ;;
  */apple/OpenMates/Sources/*.swift) IS_SWIFT=true ;;
  *) exit 0 ;;
esac

# Skip generated files
case "$FILE" in
  *generated.swift|*Tokens.swift) exit 0 ;;
esac

PROJECT_DIR=$(echo "$FILE" | sed 's|/frontend/.*||;s|/apple/.*||')
MAP_FILE="$PROJECT_DIR/apple/SVELTE_SWIFT_COUNTERPARTS.md"

[ ! -f "$MAP_FILE" ] && exit 0

# Extract the basename for matching
BASENAME=$(basename "$FILE")

# Search for the file in the mapping table
if $IS_SVELTE; then
  # Find Swift counterparts for this Svelte file
  # Table format: | svelte path | swift path |
  # Match in first column, extract second column
  COUNTERPARTS=$(grep -i "$BASENAME" "$MAP_FILE" | grep '|' | while IFS='|' read -r _ col1 col2 _; do
    echo "$col1" | grep -qi "$BASENAME" && echo "$col2" | sed 's/`//g'
  done | xargs 2>/dev/null || true)
elif $IS_SWIFT; then
  # Find Svelte counterparts for this Swift file
  # Match in second column, extract first column
  COUNTERPARTS=$(grep -i "$BASENAME" "$MAP_FILE" | grep '|' | while IFS='|' read -r _ col1 col2 _; do
    echo "$col2" | grep -qi "$BASENAME" && echo "$col1" | sed 's/`//g'
  done | xargs 2>/dev/null || true)
fi

if [ -n "$COUNTERPARTS" ] && [ "$COUNTERPARTS" != " " ]; then
  DIRECTION=""
  if $IS_SVELTE; then
    DIRECTION="Swift counterpart(s)"
  else
    DIRECTION="Svelte source(s)"
  fi

  MSG="svelte-swift-counterpart-linker: $(basename "$FILE") has linked ${DIRECTION}: ${COUNTERPARTS}
Keep both sides in sync. See apple/SVELTE_SWIFT_COUNTERPARTS.md for the full mapping."
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$msg}}'
fi

exit 0
