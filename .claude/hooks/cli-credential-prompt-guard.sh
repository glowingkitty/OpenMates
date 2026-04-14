#!/bin/bash
# Hook: PreToolUse (Edit|Write) — cli-credential-prompt-guard
# ------------------------------------------------------------------
# Privacy promise enforcement: shared/docs/privacy_promises.yml →
# cli-no-credential-prompts. The OpenMates CLI authenticates exclusively
# through the browser-based pair-auth handshake. Any interactive prompt
# for an email address, password, 2FA/TOTP/OTP code, or recovery code
# violates the promise.
#
# Scope: only files under frontend/packages/openmates-cli/src/**/*.ts.
#
# Blocks (warn-only first iteration):
#   - Prompt strings mentioning password / passphrase / email / username /
#     2fa / totp / otp / verification code / recovery code
#   - Imports of credential-prompting libraries: inquirer, prompts,
#     enquirer, prompt-sync, @inquirer/prompts, read, read-input
#
# Exception: the 6-char pairing PIN is the ONLY legitimate interactive
# prompt the CLI makes. Lines referencing "pair", "pairing", or "pin" pass.
#
# Strictness: WARN ONLY (exit 0).
# Related: docs/architecture/apps/cli-package.md, .claude/rules/privacy.md

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# Only inspect CLI source files.
case "$FILE" in
  */frontend/packages/openmates-cli/src/*.ts) ;;
  */frontend/packages/openmates-cli/src/**/*.ts) ;;
  *) exit 0 ;;
esac

if [ "$TOOL" = "Write" ]; then
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')
fi

[ -z "$NEW_CONTENT" ] && exit 0

# Patterns that suggest a credential prompt is being added.
CRED_RE='(password|passphrase|\bemail\b|username|\b2fa\b|\btotp\b|\botp\b|verification[[:space:]]?code|recovery[[:space:]]?code|backup[[:space:]]?code|authenticator)'
PROMPT_CTX_RE='(prompt|readline|question|createInterface|inquirer|prompts\(|enquirer|prompt-sync|readlineSync)'

# Pairing PIN is allowed — any line that references pair/pairing/pin near a
# prompt is fine.
PAIR_OK_RE='(pair|pairing|\bpin\b)'

# Find lines that (a) look like a prompt call AND (b) mention a credential
# keyword AND (c) do NOT also mention the pairing PIN.
HITS=$(echo "$NEW_CONTENT" | grep -nE "$PROMPT_CTX_RE" | grep -iE "$CRED_RE" | grep -viE "$PAIR_OK_RE" || true)

# Also flag new imports of credential-prompting libraries (always a smell in
# the CLI package, regardless of context).
IMPORT_RE="^[[:space:]]*import[[:space:]].*(from[[:space:]]+['\"](inquirer|prompts|enquirer|prompt-sync|@inquirer/prompts|read|read-input)['\"])"
IMPORT_HITS=$(echo "$NEW_CONTENT" | grep -nE "$IMPORT_RE" || true)

if [ -n "$HITS" ] || [ -n "$IMPORT_HITS" ]; then
  MSG="🛡  cli-credential-prompt-guard: possible login-credential prompt being added to the OpenMates CLI.

Privacy promise: shared/docs/privacy_promises.yml → cli-no-credential-prompts
  'The command-line tool never asks for your password.'
  Authentication uses the browser-based pair-auth handshake. The ONLY
  legitimate interactive prompt is the 6-char binding PIN."

  if [ -n "$HITS" ]; then
    MSG="$MSG

Suspect prompt line(s):
$(echo "$HITS" | head -5)"
  fi

  if [ -n "$IMPORT_HITS" ]; then
    MSG="$MSG

Suspect import(s):
$(echo "$IMPORT_HITS" | head -5)"
  fi

  MSG="$MSG

If this is actually pair-auth PIN handling, reference 'pair' or 'pin'
near the prompt so the guard allows it. Otherwise, remove the prompt.
(warn-only; to add a new interactive flow, amend the privacy promise first.)"

  echo "$MSG" >&2
  jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$msg}}'
fi

exit 0
