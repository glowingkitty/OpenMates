#!/bin/bash
# Hook: PreToolUse (Edit|Write) — settings-canonical-elements
# ------------------------------------------------------------------
# Warns when editing settings pages with raw HTML elements instead of
# the 29 canonical settings/elements components. Catches bare <button>,
# <input>, <h3>, <h2>, inline style= attributes, and hardcoded colors
# in settings Svelte files.
#
# Only fires for files under: components/settings/**/*.svelte
# Excludes: components/settings/elements/** (the canonical components themselves)
#
# Strictness: WARN ONLY — does not block the edit.
# Related: .claude/rules/settings-ui.md, docs/design-guide/settings-ui.md

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only check settings page files, not the elements themselves
case "$FILE" in
  */components/settings/elements/*) exit 0 ;;
  */components/settings/*.svelte) ;;
  *) exit 0 ;;
esac

TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

ISSUES=""

# Bare <button> (should use SettingsButton)
BTN_HITS=$(echo "$NEW_CONTENT" | grep -nE '<button\b' | grep -v 'SettingsButton' | grep -v '<!--' || true)
[ -n "$BTN_HITS" ] && ISSUES="${ISSUES}
  - Bare <button>: use SettingsButton instead ($(echo "$BTN_HITS" | wc -l) hit(s))"

# Bare <input> (should use SettingsInput or SettingsTextarea)
INPUT_HITS=$(echo "$NEW_CONTENT" | grep -nE '<input\b' | grep -v 'SettingsInput' | grep -v '<!--' || true)
[ -n "$INPUT_HITS" ] && ISSUES="${ISSUES}
  - Bare <input>: use SettingsInput instead ($(echo "$INPUT_HITS" | wc -l) hit(s))"

# Bare <h2>/<h3> in template (should use SettingsSectionHeading)
H_HITS=$(echo "$NEW_CONTENT" | grep -nE '<h[23]\b' | grep -v 'SettingsSectionHeading' | grep -v '<!--' | grep -v '<script' || true)
[ -n "$H_HITS" ] && ISSUES="${ISSUES}
  - Bare <h2>/<h3>: use SettingsSectionHeading instead ($(echo "$H_HITS" | wc -l) hit(s))"

# Inline style= in template (should use CSS classes or design tokens)
STYLE_HITS=$(echo "$NEW_CONTENT" | grep -nE 'style="[^"]*"' | grep -v '<style' | grep -v '<!--' || true)
[ -n "$STYLE_HITS" ] && ISSUES="${ISSUES}
  - Inline style= attribute: use CSS classes or design tokens ($(echo "$STYLE_HITS" | wc -l) hit(s))"

# Hardcoded hex colors outside <style> block (should use CSS variables)
# Extract only the template portion (before <style>)
TEMPLATE_PART=$(echo "$NEW_CONTENT" | sed -n '1,/<style>/p')
COLOR_HITS=$(echo "$TEMPLATE_PART" | grep -nE '#[0-9a-fA-F]{3,8}\b' | grep -v '<!--' | grep -v 'data-testid' || true)
[ -n "$COLOR_HITS" ] && ISSUES="${ISSUES}
  - Hardcoded hex color in template: use var(--color-*) tokens ($(echo "$COLOR_HITS" | wc -l) hit(s))"

if [ -n "$ISSUES" ]; then
  MSG="⚠️  settings-canonical-elements: $(basename "$FILE") uses raw HTML elements instead of canonical settings components.

Detected:${ISSUES}

Available components: SettingsButton, SettingsInput, SettingsTextarea, SettingsDropdown, SettingsConsentToggle, SettingsSectionHeading, SettingsInfoBox, SettingsCard, SettingsGradientLink, SettingsItem, SettingsDivider, SettingsPageHeader, SettingsPageContainer, and more.
Full list: frontend/packages/ui/src/components/settings/elements/index.ts
Preview: /dev/preview/settings (warn-only, see .claude/rules/settings-ui.md)"
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
