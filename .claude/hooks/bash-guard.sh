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

# --- Allow pnpm dependency installs, but block local builds/tests/dev servers ---
if echo "$COMMAND" | grep -qE '(^|[[:space:];&|])pnpm([[:space:]][^;&|]*)*[[:space:]](add|install|i)([[:space:]]|$)'; then
  exit 0
fi

if echo "$COMMAND" | grep -qE '(^|[[:space:];&|])(npx|pnpm)([[:space:]]|$)'; then
  echo '{"decision":"block","reason":"BLOCKED: pnpm/npx build, dev, run, and test commands are not allowed locally — they crash the server. pnpm add/install is allowed for dependency changes; use sessions.py deploy for builds and python3 scripts/run_tests.py for tests."}' >&2
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

# --- Block Vercel project setting mutations that can enable paid build machines ---
if echo "$COMMAND" | grep -qiE 'api\.vercel\.com/.*/projects|api\.vercel\.com/v[0-9]+/projects|\bvercel\s+project\b'; then
  if echo "$COMMAND" | grep -qiE '(-X|--request)[[:space:]]*(PATCH|PUT|POST|DELETE)|\.(patch|put|post|delete)\s*\(|--data|-d[[:space:]]|buildMachine(Type|Selection)?|elasticConcurrency|resourceConfig'; then
    echo '{"decision":"block","reason":"BLOCKED: Vercel project-setting mutations are forbidden from agent terminal commands because they can switch build machines to paid Turbo/Dynamic. Use the Vercel dashboard manually and keep buildMachineType=standard/buildMachineSelection=fixed."}' >&2
    exit 2
  fi
fi

if echo "$COMMAND" | grep -qiE 'buildMachine(Type|Selection)?|elasticConcurrency|buildMachineElastic|Turbo|Dynamic build'; then
  if echo "$COMMAND" | grep -qiE 'api\.vercel\.com|\bvercel\b|VERCEL_TOKEN'; then
    echo '{"decision":"block","reason":"BLOCKED: Vercel build-machine or elastic-build settings may not be modified from terminal commands. Keep Vercel builds on standard/fixed only."}' >&2
    exit 2
  fi
fi

# Also block running a repo script that contains the same Vercel paid-build mutation surface.
# This catches attempts hidden behind commands like `python3 scripts/foo.py`.
for script_path in $(echo "$COMMAND" | grep -oE '(^|[[:space:];&|])([^[:space:];&|]+\.(py|sh|js|mjs|ts))' | awk '{print $NF}' | sort -u); do
  case "$script_path" in
    /*) candidate="$script_path" ;;
    *) candidate="/home/superdev/projects/OpenMates/$script_path" ;;
  esac
  if [ ! -f "$candidate" ]; then
    continue
  fi
  case "$candidate" in
    /home/superdev/projects/OpenMates/scripts/tests/*) continue ;;
  esac
  if grep -qiE 'api\.vercel\.com/.*/projects|api\.vercel\.com/v[0-9]+/projects|\bvercel\s+project\b' "$candidate" \
    && grep -qiE 'buildMachine(Type|Selection)?|elasticConcurrency|buildMachineElastic|resourceConfig|Dynamic build' "$candidate" \
    && grep -qiE '(-X|--request)[[:space:]]*(PATCH|PUT|POST|DELETE)|\.(patch|put|post|delete)\s*\(|urlopen\([^)]*method=["'"'"'](PATCH|PUT|POST|DELETE)["'"'"']' "$candidate"; then
    echo '{"decision":"block","reason":"BLOCKED: Refusing to run a repo script that can mutate Vercel build-machine/project settings. Keep Vercel buildMachineType=standard and buildMachineSelection=fixed."}' >&2
    exit 2
  fi
done

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
