#!/bin/bash
# Hook: PreToolUse (Edit|Write) — analytics-sdk-forbidden
# ------------------------------------------------------------------
# GDPR enforcement: shared/docs/privacy_policy.yml:89-97 makes an explicit
# NEGATIVE claim — "We do not use Google Analytics, Plausible, PostHog,
# or any third-party analytics platform." Any import of these SDKs makes
# the privacy policy a false statement.
#
# Blocks (warn-only first iteration): posthog, mixpanel, amplitude,
# google-analytics, gtag(, segment.com, plausible, fathom, hotjar,
# fullstory, datadog-rum, heap.io.
#
# Strictness: WARN ONLY (exit 0). Flip to exit 2 once confirmed clean.
# Related: OPE-375, .claude/rules/privacy.md, privacy_policy.yml:89-97

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only inspect source files where an analytics SDK could land
case "$FILE" in
  *.py|*.ts|*.tsx|*.js|*.jsx|*.svelte|*/package.json|*/requirements*.txt|*/pyproject.toml) ;;
  *) exit 0 ;;
esac

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

PATTERN='(posthog|mixpanel|amplitude|google-analytics|googletagmanager|gtag\(|segment\.com|@segment/|plausible\.io|plausible-tracker|usefathom|fathom-client|hotjar|fullstory|@datadog/browser-rum|datadog-rum|heap\.io|heapanalytics)'

MATCHES=$(echo "$NEW_CONTENT" | grep -oiE "$PATTERN" | sort -u)

if [ -n "$MATCHES" ]; then
  FOUND=$(echo "$MATCHES" | tr '\n' ',' | sed 's/,$//')
  MSG="🚨 GDPR/analytics-forbidden: detected banned analytics SDK reference(s): $FOUND. The privacy policy (shared/docs/privacy_policy.yml:89-97) explicitly states NO third-party analytics are used. Adding this makes the policy a false statement. Remove it or update the policy + obtain legal review before deploying. (warn-only, see .claude/rules/privacy.md)"
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
