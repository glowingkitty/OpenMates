#!/bin/bash
# Hook: PreToolUse (Bash)
# Blocks dangerous commands that bypass the session workflow or are destructive.
# Consolidates the old inline pnpm-build blocker + new guards.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[ -z "$COMMAND" ] && exit 0

# --- Block pnpm build (crashes the server) ---
if echo "$COMMAND" | grep -q 'pnpm build'; then
  echo '{"decision":"block","reason":"BLOCKED: pnpm build is not allowed — it crashes the server. Use more targeted commands instead."}' >&2
  exit 2
fi

# --- Block vitest/pnpm test locally (crashes the server — use run_tests.py) ---
if echo "$COMMAND" | grep -qE '(pnpm|npx|yarn)\s+(vitest|test)\b|vitest\s+run'; then
  echo '{"decision":"block","reason":"BLOCKED: vitest/pnpm test must not run locally — it crashes the server. Use: python3 scripts/run_tests.py --suite vitest"}' >&2
  exit 2
fi

# --- Block Playwright locally (must dispatch via run_tests.py to GitHub Actions) ---
if echo "$COMMAND" | grep -qE '(npx|pnpm|yarn)\s+playwright\s+test|playwright\s+test'; then
  echo '{"decision":"block","reason":"BLOCKED: Playwright must not run locally. Use: python3 scripts/run_tests.py --spec <name>.spec.ts or --suite playwright"}' >&2
  exit 2
fi

# --- Block raw git commit (must use sessions.py deploy) ---
if echo "$COMMAND" | grep -qE '^\s*git\s+commit\b'; then
  echo '{"decision":"block","reason":"BLOCKED: Use sessions.py deploy instead of raw git commit. It handles linting, translation validation, and session tracking."}' >&2
  exit 2
fi

# --- Block git stash (forbidden by project rules) ---
if echo "$COMMAND" | grep -qE '^\s*git\s+stash\b'; then
  echo '{"decision":"block","reason":"BLOCKED: git stash is forbidden. Commit your work via sessions.py deploy instead."}' >&2
  exit 2
fi

# --- Block git worktree (all work in main directory) ---
if echo "$COMMAND" | grep -qE '^\s*git\s+worktree\b'; then
  echo '{"decision":"block","reason":"BLOCKED: git worktree is forbidden. All work happens in the main working directory."}' >&2
  exit 2
fi

# --- Block force push to main/master ---
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force.*\b(main|master)\b|git\s+push\s+.*\b(main|master)\b.*--force'; then
  echo '{"decision":"block","reason":"BLOCKED: Force pushing to main/master is not allowed."}' >&2
  exit 2
fi

exit 0
