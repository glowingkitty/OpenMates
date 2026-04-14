#!/bin/bash
# Hook: PreToolUse (Edit|Write) — donation-language-guard
# ------------------------------------------------------------------
# OpenMates does not use "donation" / "donate" language anywhere.
# Support contributions are called "support contributions" or "support payments".
# This hook warns (does NOT block) when the word "donation" or "donate"
# appears in the content being written.
#
# Strictness: WARN ONLY (exit 0). Never blocks.
# Related: .claude/rules/*, CLAUDE.md

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Skip binary and lock files
case "$FILE" in
  *.png|*.jpg|*.jpeg|*.gif|*.svg|*.ico|*.woff|*.woff2|*.ttf|*.eot) exit 0 ;;
  *.lock|package-lock.json) exit 0 ;;
esac

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

# Match "donation", "donations", "donate", "donated" — case-insensitive
# Ignore lines that are comments in .py/.sh (# ...) only if the word appears in a URL context
VIOLATIONS=$(echo "$NEW_CONTENT" | grep -in "\bdonat\(ion\|ions\|e\|ed\|ing\)\b" || true)

if [ -n "$VIOLATIONS" ]; then
  COUNT=$(echo "$VIOLATIONS" | wc -l)
  SAMPLE=$(echo "$VIOLATIONS" | head -3)
  MSG="⚠️  donation-language-guard: found $COUNT occurrence(s) of 'donation/donate' in $(basename "$FILE").

OpenMates does not use donation language anywhere. Use instead:
  • 'support contribution' or 'support payment' (user-facing copy)
  • 'support_contribution' (code/API identifiers)
  • 'supporter' (for the person making a contribution)

Sample:
$SAMPLE

(warn-only — fix before committing)"
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
