#!/bin/bash
# Hook: PreToolUse (Edit|Write) — cookie-consent-gate
# ------------------------------------------------------------------
# ePrivacy Directive enforcement: warn if new Set-Cookie / set_cookie()
# calls are added OUTSIDE the approved cookie-setting routes.
#
# Approved locations (all cookies here are consent_exempt per
# docs/architecture/compliance/cookies.yml):
#   - backend/core/api/app/routes/auth_routes/**
#   - any path containing "payment"
#   - any path containing "stripe" or "polar"
#
# A new cookie outside these routes likely needs a consent banner.
#
# Strictness: WARN ONLY.
# Related: docs/architecture/compliance/cookies.yml, .claude/rules/privacy.md

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

case "$FILE" in
  *.py|*.ts|*.tsx|*.js|*.svelte) ;;
  *) exit 0 ;;
esac

# Is the file already in an approved cookie-setting location?
case "$FILE" in
  */auth_routes/*) exit 0 ;;
  *payment*) exit 0 ;;
  *stripe*) exit 0 ;;
  *polar*) exit 0 ;;
esac

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

# Match: set_cookie(, .set_cookie(, Set-Cookie: header, document.cookie =, response.cookies[
PATTERN='(\.set_cookie\(|set_cookie\(|["'"'"']Set-Cookie["'"'"']|document\.cookie\s*=|response\.cookies\[|\.cookies\.set\()'

HITS=$(echo "$NEW_CONTENT" | grep -nE "$PATTERN" || true)

if [ -n "$HITS" ]; then
  COUNT=$(echo "$HITS" | wc -l)
  SAMPLE=$(echo "$HITS" | head -3)
  MSG="⚠️  cookie-consent-gate: $COUNT new cookie-setting call(s) in $(basename "$FILE") — this file is NOT under an approved cookie route (auth_routes/, payment*, stripe*, polar*).

Sample:
$SAMPLE

All 5 currently approved cookies are listed in docs/architecture/compliance/cookies.yml with consent_exempt: true. A 6th cookie likely needs a consent banner per ePrivacy Directive. Either move the cookie to an auth/payment route, or update cookies.yml + add consent UI before deploying. (warn-only, see .claude/rules/privacy.md)"
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
