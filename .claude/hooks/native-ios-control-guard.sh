#!/bin/bash
# Hook: PreToolUse (Edit|Write) — native-ios-control-guard
# ------------------------------------------------------------------
# Warns when Swift edits introduce forbidden native iOS controls that
# leak system chrome. Non-blocking — emits additionalContext warnings.
#
# Only fires for: apple/OpenMates/Sources/**/*.swift
# Skips: *generated.swift, *Tokens.swift

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only check Swift files under apple/OpenMates/Sources
case "$FILE" in
  */apple/OpenMates/Sources/*.swift) ;;
  *) exit 0 ;;
esac

# Skip generated token files
case "$FILE" in
  *generated.swift|*Tokens.swift) exit 0 ;;
esac

TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

WARNINGS=""

# Form { }
if echo "$NEW_CONTENT" | grep -qE '\bForm\s*\{'; then
  WARNINGS="${WARNINGS}
  - Form { }: use ScrollView + VStack + OMSettingsSection instead"
fi

# List { } (but not LazyVStack etc)
if echo "$NEW_CONTENT" | grep -qE '\bList\s*(\(|\{)'; then
  WARNINGS="${WARNINGS}
  - List { }: use ScrollView + LazyVStack + OMSettingsSection/OMSettingsRow instead"
fi

# Toggle (but not OMToggle)
if echo "$NEW_CONTENT" | grep -qE '\bToggle\(' && ! echo "$NEW_CONTENT" | grep -qE '\bOMToggle'; then
  WARNINGS="${WARNINGS}
  - Toggle(): use OMToggle instead (native renders blue iOS switch)"
fi

# Picker (but not PhotosPicker/DatePicker/OMDropdown)
PICKER_HITS=$(echo "$NEW_CONTENT" | grep -E '\bPicker\(' | grep -v 'PhotosPicker' | grep -v 'DatePicker' | grep -v 'OMDropdown' || true)
if [ -n "$PICKER_HITS" ]; then
  WARNINGS="${WARNINGS}
  - Picker(): use OMDropdown instead (native renders iOS picker wheel)"
fi

# .navigationTitle
if echo "$NEW_CONTENT" | grep -qE '\.navigationTitle\('; then
  WARNINGS="${WARNINGS}
  - .navigationTitle(): use custom header in OMSettingsPage or inline Text + OMIconButton"
fi

# .toolbar {
if echo "$NEW_CONTENT" | grep -qE '\.toolbar\s*\{'; then
  WARNINGS="${WARNINGS}
  - .toolbar { }: use inline HStack with OMIconButton instead"
fi

# NavigationStack {
if echo "$NEW_CONTENT" | grep -qE '\bNavigationStack\s*(\(|\{)'; then
  WARNINGS="${WARNINGS}
  - NavigationStack: use state-driven view switching (see SettingsView.swift SettingsDestination pattern)"
fi

# NavigationLink {
if echo "$NEW_CONTENT" | grep -qE '\bNavigationLink\s*(\(|\{)'; then
  WARNINGS="${WARNINGS}
  - NavigationLink: use OMSettingsRow(showsChevron: true) with action, or Button"
fi

# .sheet(
if echo "$NEW_CONTENT" | grep -qE '\.sheet\('; then
  WARNINGS="${WARNINGS}
  - .sheet(): use OMSheet or ZStack overlay instead (native renders detent/drag handle)"
fi

# .alert(
if echo "$NEW_CONTENT" | grep -qE '\.alert\('; then
  WARNINGS="${WARNINGS}
  - .alert(): use OMConfirmDialog instead (native renders system alert)"
fi

# .confirmationDialog(
if echo "$NEW_CONTENT" | grep -qE '\.confirmationDialog\('; then
  WARNINGS="${WARNINGS}
  - .confirmationDialog(): use OMConfirmDialog instead"
fi

# .contextMenu {
if echo "$NEW_CONTENT" | grep -qE '\.contextMenu\s*\{'; then
  WARNINGS="${WARNINGS}
  - .contextMenu { }: use custom popover overlay instead"
fi

# Menu { } (but not contextMenu)
if echo "$NEW_CONTENT" | grep -qE '\bMenu\s*(\(|\{)' && ! echo "$NEW_CONTENT" | grep -qE 'contextMenu'; then
  WARNINGS="${WARNINGS}
  - Menu { }: use OMDropdown or custom popover instead"
fi

# System font styles
if echo "$NEW_CONTENT" | grep -qE '\.font\(\.(caption|body|title|headline|subheadline|footnote|callout|largeTitle)\)'; then
  WARNINGS="${WARNINGS}
  - .font(.system): use .font(.omXs), .font(.omP), .font(.omH3) etc (system fonts don't match Lexend Deca)"
fi

if [ -n "$WARNINGS" ]; then
  MSG="native-ios-control-guard: $(basename "$FILE") introduces forbidden native iOS controls.
Detected:${WARNINGS}

See .claude/rules/apple-ui.md 'Forbidden Native Controls' for the full replacement table."
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
