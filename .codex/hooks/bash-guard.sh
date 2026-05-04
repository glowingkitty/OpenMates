#!/bin/bash
# Hook: PreToolUse (Bash)
# Blocks dangerous commands that bypass the session workflow or are destructive.
# Consolidates the old inline pnpm-build blocker + new guards.
#
# IMPORTANT: All patterns match ANYWHERE in the command (no ^ anchor) so they
# catch chained commands like "git add && git commit" or "cd foo && git push".

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[ -z "$COMMAND" ] && exit 0

# --- Allow sessions.py deploy (the approved commit/push workflow) ---
if echo "$COMMAND" | grep -qE 'sessions\.py\s+deploy'; then
  exit 0
fi

# --- Allow git operations in the marketing repo (no code, just yml/md content) ---
if echo "$COMMAND" | grep -qE 'openmates-marketing'; then
  exit 0
fi

# --- Block pnpm / npx commands (crashes the server / exhausts memory) ---
if echo "$COMMAND" | grep -qE '\b(pnpm|npx)\b'; then
  echo '{"decision":"block","reason":"BLOCKED: pnpm/npx commands are not allowed — they crash the server. Use sessions.py deploy for builds, and python3 scripts/run_tests.py for tests."}' >&2
  exit 2
fi

# --- Block raw git commit (must use sessions.py deploy) ---
if echo "$COMMAND" | grep -qE '\bgit\s+commit\b'; then
  echo '{"decision":"block","reason":"BLOCKED: Use sessions.py deploy instead of raw git commit. It handles linting, translation validation, and session tracking."}' >&2
  exit 2
fi

# --- Block raw git push (must use sessions.py deploy) ---
if echo "$COMMAND" | grep -qE '\bgit\s+push\b'; then
  echo '{"decision":"block","reason":"BLOCKED: Use sessions.py deploy instead of raw git push. It handles session tracking and deploy coordination."}' >&2
  exit 2
fi

# --- Block git add -A / git add . (stages everything including secrets and unrelated files) ---
if echo "$COMMAND" | grep -qE '\bgit\s+add\s+(-A|--all|\.)'; then
  echo '{"decision":"block","reason":"BLOCKED: git add -A / git add . stages everything (secrets, unrelated files). Add specific files by name instead."}' >&2
  exit 2
fi

# --- Block git stash (forbidden by project rules) ---
if echo "$COMMAND" | grep -qE '\bgit\s+stash\b'; then
  echo '{"decision":"block","reason":"BLOCKED: git stash is forbidden. Commit your work via sessions.py deploy instead."}' >&2
  exit 2
fi

# --- Block git worktree (all work in main directory) ---
if echo "$COMMAND" | grep -qE '\bgit\s+worktree\b'; then
  echo '{"decision":"block","reason":"BLOCKED: git worktree is forbidden. All work happens in the main working directory."}' >&2
  exit 2
fi

# --- Block force push to main/master ---
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force.*\b(main|master)\b|git\s+push\s+.*\b(main|master)\b.*--force'; then
  echo '{"decision":"block","reason":"BLOCKED: Force pushing to main/master is not allowed."}' >&2
  exit 2
fi

exit 0
