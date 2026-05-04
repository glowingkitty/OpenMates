#!/bin/bash
# Hook: PreToolUse (Edit|Write) — css-selector-in-specs
# ------------------------------------------------------------------
# Test quality: .claude/rules/testing.md forbids CSS class / id selectors
# in Playwright specs. All element targeting MUST use data-testid.
#
# Detects new occurrences of:
#   page.locator('.foo'), page.locator('#foo'),
#   .locator(':has(.foo)')
# while allowing [data-testid=...], getByTestId, getByRole, getByText,
# [data-action=...], [data-authenticated=...], state-attribute locators.
#
# Strictness: WARN ONLY first iteration.
# Related: .claude/rules/testing.md, docs/contributing/guides/testing.md

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only inspect test spec files
case "$FILE" in
  *.spec.ts|*.spec.tsx|*.test.ts|*.test.tsx) ;;
  *) exit 0 ;;
esac

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

# Matches .locator('.foo') or .locator("#foo") or .locator(':has(.foo)')
# Excludes [data-...] bracket selectors and escaped patterns.
VIOLATIONS=$(echo "$NEW_CONTENT" | grep -nE "\.locator\(\s*[\"'][[:space:]]*[.#][a-zA-Z_-]" || true)

if [ -n "$VIOLATIONS" ]; then
  COUNT=$(echo "$VIOLATIONS" | wc -l)
  SAMPLE=$(echo "$VIOLATIONS" | head -3)
  MSG="⚠️  testing/css-selector-in-specs: found $COUNT CSS class/id selector(s) in $(basename "$FILE"). Project rule: all element targeting MUST use data-testid via getByTestId() or [data-testid=...]. CSS classes are styling concerns and break when CSS changes.

Sample:
$SAMPLE

Fix: replace with page.getByTestId('name') or page.locator('[data-testid=\"name\"]'). (warn-only, see .claude/rules/testing.md)"
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
