#!/bin/bash
# Hook: PreToolUse (Edit|Write) — pii-logger-guard
# ------------------------------------------------------------------
# GDPR minimization: warn when new logging code references bare sensitive
# variable names without a redaction/mask/hash wrapper. Catches accidental
# PII in OpenObserve logs (which are queryable by --query-json and retained
# for 14-30 days per privacy_policy.yml data_retention).
#
# Detects additions of:
#   print(...), logger.(info|debug|warning|error)(...),
#   console.(log|debug|warn|error|info)(...)
# containing one of:
#   email, password, passwd, token, api_key, api_secret, phone, address,
#   tfa_secret, session_id, refresh_token, credit_card, ssn
# UNLESS the same line also contains:
#   redact, mask, hash, sha, SensitiveDataFilter, ****, ..., [REDACTED]
#
# Strictness: WARN ONLY.
# Related: .claude/rules/privacy.md, .claude/rules/backend.md (logging rule)

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

case "$FILE" in
  *.py|*.ts|*.tsx|*.js|*.jsx|*.svelte) ;;
  *) exit 0 ;;
esac

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

PII='(email|password|passwd|\btoken\b|api_key|api_secret|\bphone\b|\baddress\b|tfa_secret|session_id|refresh_token|credit_card|\bssn\b)'
LOGGING='(print\(|logger\.(info|debug|warning|warn|error|exception)\(|console\.(log|debug|warn|error|info)\()'
SAFE='(redact|mask|\bhash|\bsha[0-9]|SensitiveDataFilter|\*\*\*|\[REDACTED\]|\.\.\.|truncat)'

# Only consider lines that contain BOTH a logging call AND a PII token,
# and DO NOT contain a safe-wrapper token.
HITS=$(echo "$NEW_CONTENT" | grep -nE "$LOGGING" | grep -iE "$PII" | grep -vEi "$SAFE" || true)

if [ -n "$HITS" ]; then
  COUNT=$(echo "$HITS" | wc -l)
  SAMPLE=$(echo "$HITS" | head -3)
  MSG="⚠️  pii-logger-guard: $COUNT potential PII logging site(s) in $(basename "$FILE"). Sensitive identifiers (email/password/token/phone/address/session_id/…) must be redacted, masked, or hashed before entering logs.

Sample:
$SAMPLE

Fix: use SensitiveDataFilter, hash_identifier(), or mask_email() before logging. (warn-only, see .claude/rules/privacy.md and backend.md)"
  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
