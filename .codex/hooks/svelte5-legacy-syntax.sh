#!/bin/bash
# Hook: PreToolUse (Edit|Write) — svelte5-legacy-syntax
# ------------------------------------------------------------------
# Frontend invariant: OpenMates is on Svelte 5. Mixing Svelte 4 reactive
# syntax ($:, export let, <slot/>) with Svelte 5 runes ($state, $derived,
# $effect, $props, {@render children()}) causes silent reactivity bugs
# that surface as "weird UI glitch" Linear tasks.
#
# Detects new additions of:
#   - $:  reactive statements
#   - export let  (instead of $props())
#   - <slot /> or <slot>  (instead of {@render children()})
#
# Strictness: WARN ONLY.
# Related: .claude/rules/frontend.md, docs/contributing/standards/frontend.md

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

case "$FILE" in
  *.svelte) ;;
  *) exit 0 ;;
esac

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

WARNINGS=()

# $: reactive statement (Svelte 4) — must start the line after optional whitespace
if echo "$NEW_CONTENT" | grep -qE '^\s*\$:\s'; then
  WARNINGS+=("\$: reactive statement → use \$derived() or \$effect()")
fi

# export let (Svelte 4 props) — must not be type export or export const
if echo "$NEW_CONTENT" | grep -qE '^\s*export\s+let\s+[a-zA-Z_]'; then
  WARNINGS+=("export let → use let { ... } = \$props()")
fi

# <slot /> or <slot> (Svelte 4 children)
if echo "$NEW_CONTENT" | grep -qE '<slot(\s|/|>)'; then
  WARNINGS+=("<slot/> → use {@render children()} + children: Snippet prop")
fi

if [ ${#WARNINGS[@]} -gt 0 ]; then
  JOINED=$(printf '  - %s\n' "${WARNINGS[@]}")
  MSG="⚠️  svelte5-legacy-syntax: $(basename "$FILE") — Svelte 4 syntax detected:
$JOINED
Project is on Svelte 5; mixing modes causes silent reactivity breakage. (warn-only, see .claude/rules/frontend.md)"
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
