#!/usr/bin/env bash
# lint-design-tokens.sh
#
# Non-blocking lint: warns when CSS/Svelte files use hardcoded colors,
# font sizes, or spacing instead of design token custom properties.
# Called by Claude Code PostToolUse hook — receives JSON on stdin.
#
# Exit 2 = feed warning back to Claude so it can self-correct.
# Exit 0 = no issues found.

set -euo pipefail

# Read hook input from stdin
input=$(cat)
file=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null || echo "")

# Only check frontend CSS/Svelte files
case "$file" in
  */frontend/packages/ui/src/styles/*.css | \
  */frontend/packages/ui/src/components/*.svelte | \
  */frontend/packages/ui/src/components/**/*.svelte | \
  */frontend/apps/web_app/src/**/*.svelte | \
  */frontend/apps/web_app/src/**/*.css)
    ;;
  *)
    exit 0
    ;;
esac

# Skip generated token files
case "$file" in
  */tokens/generated/*) exit 0 ;;
esac

[ -f "$file" ] || exit 0

warnings=""

# 1. Hardcoded hex colors in property values
#    Allowed: custom property definitions (--foo: #hex), var(--) refs, comments
hex_hits=$(grep -n '#[0-9a-fA-F]\{3,8\}' "$file" 2>/dev/null \
  | grep -v '^\s*/[/*]' \
  | grep -v '\-\-[a-z].*:.*#' \
  | grep -v 'var(--' \
  | grep -v '<!--' \
  || true)
if [ -n "$hex_hits" ]; then
  warnings+="
HARDCODED HEX COLOR — use var(--color-*) token instead:
$hex_hits
"
fi

# 2. Hardcoded rgb/rgba colors
#    Allowed: inside drop-shadow/box-shadow (rgba for opacity is standard),
#    custom property definitions, comments
rgb_hits=$(grep -n 'rgba\{0,1\}\s*(' "$file" 2>/dev/null \
  | grep -v '^\s*/[/*]' \
  | grep -v '\-\-[a-z].*:' \
  | grep -v '<!--' \
  | grep -v 'drop-shadow' \
  | grep -v 'box-shadow' \
  | grep -v 'shadow' \
  || true)
if [ -n "$rgb_hits" ]; then
  warnings+="
HARDCODED RGB/RGBA — use var(--color-*) token instead:
$rgb_hits
"
fi

# 3. Hardcoded font-size (not using token variable)
font_hits=$(grep -n 'font-size\s*:' "$file" 2>/dev/null \
  | grep -v 'var(--' \
  | grep -v '^\s*/[/*]' \
  | grep -v '\-\-.*font-size' \
  | grep -v '<!--' \
  || true)
if [ -n "$font_hits" ]; then
  warnings+="
HARDCODED FONT-SIZE — use var(--font-size-*) or var(--chat-message-font-size) token:
$font_hits
"
fi

# 4. Hardcoded border-radius (not using token variable)
#    Allowed: 13px (speech bubble, matches web spec intentionally), 50% (circles)
radius_hits=$(grep -n 'border-radius\s*:' "$file" 2>/dev/null \
  | grep -v 'var(--' \
  | grep -v '^\s*/[/*]' \
  | grep -v '\-\-.*radius' \
  | grep -v '<!--' \
  | grep -v '13px' \
  | grep -v '50%' \
  || true)
if [ -n "$radius_hits" ]; then
  warnings+="
HARDCODED BORDER-RADIUS — use var(--border-radius-*) token:
$radius_hits
"
fi

if [ -n "$warnings" ]; then
  cat >&2 <<EOF
Design Token Lint — $(basename "$file")
$warnings
Tokens defined in: frontend/packages/ui/src/tokens/generated/theme.generated.css
Use var(--color-*), var(--font-size-*), var(--border-radius-*), var(--spacing-*).
Do NOT hardcode hex colors, px font sizes, or px border radii — use existing tokens.
EOF
  exit 2
fi

exit 0
