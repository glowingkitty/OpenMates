#!/bin/bash
# Hook: PreToolUse (Edit|Write) — legal-text-lastupdated-bump
# ------------------------------------------------------------------
# GDPR/transparency: if Claude edits any canonical legal text file,
# warn if the canonical lastUpdated timestamp in
# frontend/packages/ui/src/legal/documents/privacy-policy.ts is not
# bumped to today's UTC date.
#
# Watched files:
#   - shared/docs/privacy_policy.yml
#   - frontend/packages/ui/src/i18n/sources/legal/privacy.yml
#   - frontend/packages/ui/src/i18n/sources/legal/terms.yml
#   - frontend/packages/ui/src/i18n/sources/legal/imprint.yml
#
# Strictness: WARN ONLY (exit 0 + additionalContext).
# Related: .claude/rules/privacy.md, GDPR Art. 13 transparency

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Is this one of the canonical legal files?
case "$FILE" in
  */shared/docs/privacy_policy.yml) ;;
  */i18n/sources/legal/privacy.yml) ;;
  */i18n/sources/legal/terms.yml) ;;
  */i18n/sources/legal/imprint.yml) ;;
  *) exit 0 ;;
esac

PROJECT_DIR="/home/superdev/projects/OpenMates"
PP_TS="$PROJECT_DIR/frontend/packages/ui/src/legal/documents/privacy-policy.ts"
[ -f "$PP_TS" ] || exit 0

TODAY=$(date -u +%Y-%m-%d)
CURRENT_TS=$(grep -oE 'lastUpdated:\s*"[^"]+"' "$PP_TS" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')

# If the timestamp already has today's date, nothing to do
if echo "$CURRENT_TS" | grep -q "^${TODAY}"; then
  exit 0
fi

MSG="⚠️  legal-text-lastupdated-bump: editing $(basename "$FILE") without bumping the canonical lastUpdated timestamp. Current value in privacy-policy.ts:49 is \"$CURRENT_TS\" — update it to \"${TODAY}T00:00:00Z\" in the same commit for GDPR Art. 13 transparency. (warn-only, see .claude/rules/privacy.md)"
echo "$MSG" >&2
jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'

exit 0
