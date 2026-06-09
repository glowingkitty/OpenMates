#!/bin/bash
# Hook: PostToolUse (Edit|Write|apply_patch) — skill/embed registry guard
# ------------------------------------------------------------------
# When backend app metadata changes, ensure every executable app skill has a
# matching app-skill-use embed registration. This prevents new skills from
# falling into unknown/placeholder frontend rendering paths.

if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)

[ -z "$FILE" ] && exit 0

PROJECT_DIR="/home/superdev/projects/OpenMates"

case "$FILE" in
  "$PROJECT_DIR"/backend/apps/*/app.yml|backend/apps/*/app.yml) ;;
  *) exit 0 ;;
esac

case "$FILE" in
  /*) TARGET_FILE="$FILE" ;;
  *) TARGET_FILE="$PROJECT_DIR/$FILE" ;;
esac

if [ ! -f "$TARGET_FILE" ]; then
  exit 0
fi

cd "$PROJECT_DIR" || exit 0

if ! OUTPUT=$(python3 scripts/audit_skill_embed_registry.py "$TARGET_FILE" 2>&1); then
  echo "BLOCKED: app skill/embed registry contract failed." >&2
  echo "$OUTPUT" >&2
  echo "Add an app-skill-use entry under embed_types for every new skill, or document a justified exception in scripts/audit_skill_embed_registry.py." >&2
  exit 2
fi

exit 0
