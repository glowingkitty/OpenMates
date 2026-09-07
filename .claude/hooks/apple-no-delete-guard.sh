#!/bin/bash
# Canonical Mac deletion-stop hook: every tool checks the same durable latch.
# A stop is a terminal response, not a retry hint or permission prompt.
# The Python helper never accepts a transcript, approval flag or timeout as a
# human confirmation. Shared Codex/OpenCode adapters must preserve this result.
set -u
HOOK_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd) || exit 2
RESULT=$(python3 "$HOOK_ROOT/scripts/apple_no_delete_guard.py" hook)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
  exit 0
fi
if [ "$STATUS" -eq 77 ]; then
  printf '%s\n' "$RESULT"
  # Claude consumes continue=false on success; the bridge calls Python directly
  # to preserve the terminal status for OpenCode's explicit abort adapter.
  exit 0
fi
printf '%s\n' 'MAC_NO_DELETE_STOP: Safety hook failed. Stop this task; do not retry through another tool.' >&2
exit 2
