#!/bin/bash
# Hook: PostToolUse (Edit|Write) — testid-drift-detector
# ------------------------------------------------------------------
# Test quality: when a Svelte/TSX component is edited, check whether any
# data-testid values were removed. If removed testids are still referenced
# by specs in frontend/apps/web_app/tests/, warn with the list of affected
# specs so Claude updates them in the same commit.
#
# Evidence for this hook: 5+ commits in 60 days fixing exactly this pattern
# (pii-detection, chat-test-helpers, OPE-358 missing app-icon-circle).
#
# Strictness: WARN ONLY.
# Runs async to stay out of the edit critical path.
# Related: .claude/rules/testing.md

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only inspect component files
case "$FILE" in
  *.svelte|*.tsx|*.jsx) ;;
  *) exit 0 ;;
esac

[ -f "$FILE" ] || exit 0

PROJECT_DIR="/home/superdev/projects/OpenMates"
cd "$PROJECT_DIR" || exit 0

# Relative path for git
REL=$(realpath --relative-to="$PROJECT_DIR" "$FILE" 2>/dev/null)
[ -z "$REL" ] && exit 0

# Extract testids from the previous committed version (HEAD) and the current one.
BEFORE=$(git show "HEAD:$REL" 2>/dev/null | grep -oE 'data-testid=["'"'"'][^"'"'"']+["'"'"']' | sed -E 's/data-testid=["'"'"']([^"'"'"']+)["'"'"']/\1/' | sort -u)
AFTER=$(grep -oE 'data-testid=["'"'"'][^"'"'"']+["'"'"']' "$FILE" 2>/dev/null | sed -E 's/data-testid=["'"'"']([^"'"'"']+)["'"'"']/\1/' | sort -u)

[ -z "$BEFORE" ] && exit 0

REMOVED=$(comm -23 <(echo "$BEFORE") <(echo "$AFTER") 2>/dev/null)
[ -z "$REMOVED" ] && exit 0

TESTS_DIR="$PROJECT_DIR/frontend/apps/web_app/tests"
[ -d "$TESTS_DIR" ] || exit 0

AFFECTED=""
while IFS= read -r tid; do
  [ -z "$tid" ] && continue
  # Match getByTestId('tid'), getByTestId("tid"), [data-testid="tid"]
  HITS=$(grep -lE "getByTestId\(['\"]${tid}['\"]\)|data-testid=[\"']${tid}[\"']" "$TESTS_DIR" -r 2>/dev/null)
  if [ -n "$HITS" ]; then
    AFFECTED="${AFFECTED}  removed testid '$tid' still referenced in:
$(echo "$HITS" | sed 's|^|    - |')
"
  fi
done <<< "$REMOVED"

if [ -n "$AFFECTED" ]; then
  MSG="⚠️  testid-drift-detector: $(basename "$REL") removed data-testid value(s) still referenced by specs:

$AFFECTED
Update the affected specs in the same commit to avoid red CI. (warn-only, see .claude/rules/testing.md)"
  echo "$MSG" >&2
fi

exit 0
