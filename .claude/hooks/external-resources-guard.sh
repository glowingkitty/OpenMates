#!/bin/bash
# Hook: PreToolUse (Edit|Write) — external-resources-guard
# ------------------------------------------------------------------
# Privacy promise enforcement: shared/docs/privacy_promises.yml →
# no-external-resources.
#
# The OpenMates web app never loads external images, favicons, fonts, or
# scripts directly — every external asset routes through our
# preview.openmates.org proxy so the originating website never sees the
# user's IP address. The only third-party scripts the web app loads are
# the payment SDKs (Stripe, Polar) on the explicit payment flow.
#
# Scope: files under frontend/packages/ui/src/**, frontend/apps/web_app/src/**.
# Skipped: test files (*.test.ts, *.spec.ts), mock data, the payment
# component itself (Payment.svelte), and the legal/config plumbing that
# *defines* allowed origins.
#
# Detects (warn-only):
#   - <img src="https://..."> outside proxyImage/proxyFavicon
#   - fetch("https://..."), new URL("https://...") where the host is not
#     openmates.org, localhost, or an allowlisted payment origin
#   - <script src="https://..."> or dynamic import("https://...")
#   - <link href="https://..."> for external fonts/CSS
#   - Bare URL literals ending in .png/.jpg/.jpeg/.webp/.gif/.svg/.ico
#     pointing to a non-openmates host
#
# Allowlist (documented in the privacy promise):
#   openmates.org, preview.openmates.org, api.dev.openmates.org,
#   js.stripe.com, checkout.stripe.com, *.polar.sh
#
# Strictness: WARN ONLY (exit 0).
# Related: frontend/packages/ui/src/utils/imageProxy.ts, .claude/rules/privacy.md

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only inspect web-app + shared UI source files.
case "$FILE" in
  */frontend/packages/ui/src/*|*/frontend/apps/web_app/src/*) ;;
  *) exit 0 ;;
esac

# Skip files where external references are expected:
case "$FILE" in
  *.test.ts|*.spec.ts|*__tests__*|*__fixtures__*|*/mock*|*/test-*) exit 0 ;;
  *Payment.svelte|*/payment/*|*PaymentProvider*|*/legal/*) exit 0 ;;
  */config/links.ts|*/config/api.ts|*/i18n/*) exit 0 ;;
  *ExternalLink*|*imageProxy*|*favicon*) exit 0 ;;
esac

# File type check — only scan files that can embed URLs.
case "$FILE" in
  *.ts|*.tsx|*.js|*.jsx|*.svelte|*.html|*.css) ;;
  *) exit 0 ;;
esac

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

# Allowlisted host suffixes — matches must end with one of these.
ALLOW_RE='(openmates\.org|openmates\.dev|localhost|127\.0\.0\.1|js\.stripe\.com|checkout\.stripe\.com|\.stripe\.com|\.polar\.sh|polar\.sh)'

# Extract every https:// URL that appears in the added content.
URLS=$(echo "$NEW_CONTENT" | grep -oE 'https?://[A-Za-z0-9._-]+' | sort -u || true)

[ -z "$URLS" ] && exit 0

# Filter: drop allowlisted hosts.
OFFENDERS=$(echo "$URLS" | grep -viE "$ALLOW_RE" || true)

[ -z "$OFFENDERS" ] && exit 0

# Classify: is the offending URL being used for a resource load
# (img/script/link/fetch/import) or is it just text (comment, docstring,
# config label)? We warn more strongly on resource loads.
RESOURCE_RE='(src=|href=|<script|<link|<img|fetch\(|XMLHttpRequest|axios|import\(|new[[:space:]]+URL|background-image|@import)'

# Check whether any line contains BOTH a non-allowlisted URL AND a
# resource-loading verb.
RESOURCE_HITS=$(echo "$NEW_CONTENT" | grep -nE "$RESOURCE_RE" | grep -iE 'https?://' | grep -viE "$ALLOW_RE" || true)

if [ -n "$RESOURCE_HITS" ]; then
  MSG="🌐 external-resources-guard: direct external resource load detected.

Privacy promise: shared/docs/privacy_promises.yml → no-external-resources
  'The web app never loads external images or scripts.'
  Every external asset must route through preview.openmates.org so the
  originating website never sees the user's IP.

Resource-loading line(s):
$(echo "$RESOURCE_HITS" | head -5)

Fix: for images/favicons, use proxyImage() / proxyFavicon() from
frontend/packages/ui/src/utils/imageProxy.ts. For scripts, route through
our own origin or add the domain to the payment allowlist above only
after updating the privacy promise. (warn-only)"
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
  exit 0
fi

# Otherwise: URL appears in text but not obviously as a resource load.
# Still worth a lightweight nudge.
FIRST=$(echo "$OFFENDERS" | head -3 | tr '\n' ',' | sed 's/,$//')
MSG="🌐 external-resources-guard: external URL reference(s) detected: $FIRST.

Privacy promise: no-external-resources. If any of these will be loaded
as an image, script, iframe, font, or fetch target, route them through
proxyImage() / proxyFavicon() (frontend/packages/ui/src/utils/imageProxy.ts)
so the user's IP is never sent to the third-party host. If they're just
strings (labels, comments, allowlisted payment origins), you can ignore
this reminder. (warn-only, see .claude/rules/privacy.md)"
echo "$MSG" >&2
jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
exit 0
