#!/usr/bin/env bash
# lint-swift-design-tokens.sh
#
# Non-blocking lint: warns when Swift UI files use hardcoded colors, font sizes,
# spacing, or native controls instead of the generated design token system.
# Called by Claude Code PostToolUse hook — receives JSON on stdin.
#
# Token files:
#   ColorTokens.generated.swift    → Color.grey0, Color.buttonPrimary, etc.
#   SpacingTokens.generated.swift  → .spacing4, .radius8, etc.
#   TypographyTokens.generated.swift → .omH1, .omP, .omSmall, etc.
#   GradientTokens.generated.swift → LinearGradient.omGradient, etc.
#
# Exit 2 = feed warning back to Claude so it can self-correct.
# Exit 0 = no issues found.

set -euo pipefail

# Read hook input from stdin
input=$(cat)
file=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null || echo "")

# Only check Swift UI files under apple/OpenMates/Sources
case "$file" in
  */apple/OpenMates/Sources/*.swift)
    ;;
  *)
    exit 0
    ;;
esac

# Skip generated token files, Core (business logic), and non-UI files
case "$file" in
  *.generated.swift) exit 0 ;;
  */Core/Crypto/*|*/Core/Services/*|*/Core/Networking/*) exit 0 ;;
  # DataExtensions.swift defines Color(hex:) initializer and hand-maintained gradient
  # extensions — Color(hex:) is the implementation, not a hardcoded UI value.
  */Shared/Extensions/DataExtensions.swift) exit 0 ;;
esac

[ -f "$file" ] || exit 0

warnings=""

# ── 1. Hardcoded colors ──────────────────────────────────────────────
# Color(red:green:blue:), Color(.sRGB), UIColor(red:), Color(hex: 0x...)
# Allowed: Color.black.opacity() for shadows/overlays, Color.white on gradients,
#          Color.clear, Color.primary (SwiftUI semantic)
hex_hits=$(grep -n 'Color(hex:' "$file" 2>/dev/null \
  | grep -v '^\s*//' \
  | grep -v '\.generated\.' \
  || true)

srgb_hits=$(grep -n 'Color(.sRGB\|Color(red:\|UIColor(red:\|Color(\.sRGB' "$file" 2>/dev/null \
  | grep -v '^\s*//' \
  || true)

# Color("name") — using asset catalog directly instead of Color.tokenName
asset_hits=$(grep -n 'Color("' "$file" 2>/dev/null \
  | grep -v '^\s*//' \
  || true)

color_issues=""
[ -n "$hex_hits" ] && color_issues+="$hex_hits"$'\n'
[ -n "$srgb_hits" ] && color_issues+="$srgb_hits"$'\n'
[ -n "$asset_hits" ] && color_issues+="$asset_hits"$'\n'

if [ -n "$color_issues" ]; then
  warnings+="
HARDCODED COLOR — use Color.grey0, Color.buttonPrimary, etc. from ColorTokens.generated.swift:
$color_issues"
fi

# ── 2. Hardcoded font sizes ──────────────────────────────────────────
# Font.system(size:), .font(.system(size:)), Font.custom("...", size: N)
# Allowed: Font.custom in TypographyTokens.generated.swift itself (already skipped)
font_hits=$(grep -n 'Font\.system(size:\|\.font(\.system\|Font\.custom(' "$file" 2>/dev/null \
  | grep -v '^\s*//' \
  || true)

if [ -n "$font_hits" ]; then
  warnings+="
HARDCODED FONT — use .omH1, .omP, .omSmall, etc. from TypographyTokens.generated.swift:
$font_hits"
fi

# ── 3. System font styles ────────────────────────────────────────────
# .font(.caption), .font(.body), .font(.title), .font(.headline), etc.
# These use SF Pro instead of Lexend Deca
sysfont_hits=$(grep -n '\.font(\.caption\|\.font(\.body\|\.font(\.title\|\.font(\.headline\|\.font(\.subheadline\|\.font(\.footnote\|\.font(\.callout\|\.font(\.largeTitle' "$file" 2>/dev/null \
  | grep -v '^\s*//' \
  || true)

if [ -n "$sysfont_hits" ]; then
  warnings+="
SYSTEM FONT STYLE — use .font(.omP), .font(.omSmall), etc. instead of system text styles:
$sysfont_hits"
fi

# ── 4. Hardcoded spacing/padding values ──────────────────────────────
# Direct numeric literals in padding/spacing where tokens should be used
# Match: padding(16), padding(.horizontal, 12), spacing: 8, etc.
# Allowed: 0, 1, 2 (too small for tokens), and 13 (speech bubble radius)
spacing_hits=$(grep -n '\.padding([0-9]\|\.padding(\.[a-z]*, [0-9]\|spacing: [0-9]' "$file" 2>/dev/null \
  | grep -v '^\s*//' \
  | grep -v '[, (]0)' \
  | grep -v '[, (]1)' \
  | grep -v '[, (]2)' \
  | grep -v '\.spacing' \
  || true)

if [ -n "$spacing_hits" ]; then
  warnings+="
HARDCODED SPACING — use .spacing4, .spacing8, etc. from SpacingTokens.generated.swift:
$spacing_hits"
fi

# ── 5. Hardcoded corner radius ───────────────────────────────────────
# cornerRadius: N where N is a numeric literal instead of .radius token
# Allowed: cornerRadius: 13 (speech bubble), cornerRadius: 0,
#          cornerRadius: 24 (OMDropdown 1.5rem — no matching radius token exists between radius7=16 and radius8=20)
radius_hits=$(grep -n 'cornerRadius: [0-9]' "$file" 2>/dev/null \
  | grep -v '^\s*//' \
  | grep -v 'cornerRadius: 13\b\|cornerRadius: 0\b\|cornerRadius: 24\b' \
  | grep -v '\.radius' \
  || true)

if [ -n "$radius_hits" ]; then
  warnings+="
HARDCODED CORNER RADIUS — use .radius3, .radius8, .radiusFull, etc. from SpacingTokens.generated.swift:
$radius_hits"
fi

# ── 6. Forbidden native controls ─────────────────────────────────────
# These inject iOS chrome that conflicts with the custom design system
native_hits=""

# Form { } — renders iOS grouped background
form_hits=$(grep -n '^\s*Form\s*{' "$file" 2>/dev/null | grep -v '^\s*//' || true)
[ -n "$form_hits" ] && native_hits+="  Form { } — use ScrollView + VStack + OMSettingsSection"$'\n'"$form_hits"$'\n'

# Toggle(_, isOn:) — renders blue iOS switch
toggle_hits=$(grep -n 'Toggle(' "$file" 2>/dev/null | grep -v '^\s*//' | grep -v 'OMToggle' || true)
[ -n "$toggle_hits" ] && native_hits+="  Toggle — use OMToggle"$'\n'"$toggle_hits"$'\n'

# .navigationTitle — renders native nav bar
navtitle_hits=$(grep -n '\.navigationTitle(' "$file" 2>/dev/null | grep -v '^\s*//' || true)
[ -n "$navtitle_hits" ] && native_hits+="  .navigationTitle — use custom header"$'\n'"$navtitle_hits"$'\n'

# .toolbar { ToolbarItem } — renders system nav bar items
toolbar_hits=$(grep -n '\.toolbar\s*{' "$file" 2>/dev/null | grep -v '^\s*//' || true)
[ -n "$toolbar_hits" ] && native_hits+="  .toolbar — use inline HStack with OMIconButton"$'\n'"$toolbar_hits"$'\n'

if [ -n "$native_hits" ]; then
  warnings+="
FORBIDDEN NATIVE CONTROL — see apple-ui.md Forbidden Native Controls table:
$native_hits"
fi

if [ -n "$warnings" ]; then
  cat >&2 <<EOF
Swift Design Token Lint — $(basename "$file")
$warnings
Token files: frontend/packages/ui/src/tokens/generated/swift/
  ColorTokens.generated.swift    → Color.grey0, .buttonPrimary, .fontPrimary, etc.
  SpacingTokens.generated.swift  → .spacing4, .radius8, .radiusFull, etc.
  TypographyTokens.generated.swift → .omH1, .omP, .omSmall, .omXs, etc.
  GradientTokens.generated.swift → LinearGradient extensions
Do NOT hardcode colors, font sizes, spacing, or corner radii — use existing tokens.
EOF
  exit 2
fi

exit 0
