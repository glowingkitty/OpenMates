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

# --- Allow orchestrated session worktree commands, not raw git worktree ---
if echo "$COMMAND" | grep -qE 'sessions\.py\s+worktree\s+(ensure|cleanup)'; then
  exit 0
fi

# --- Allow git operations in the marketing repo (no code, just yml/md content) ---
if echo "$COMMAND" | grep -qE 'openmates-marketing'; then
  exit 0
fi

# --- Block parsed unsafe command invocations without matching quoted data. ---
if ! PARSED_GUARD_OUTPUT=$(python3 "/home/superdev/projects/OpenMates/scripts/safe_bash_guard.py" "$COMMAND" 2>&1); then
  printf '%s\n' "$PARSED_GUARD_OUTPUT" >&2
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

exit 0
