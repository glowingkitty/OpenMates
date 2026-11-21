#!/bin/bash
# Hook: PreToolUse (Bash)
# Blocks dangerous commands that bypass the session workflow or are destructive.
# Consolidates the old inline pnpm-build blocker + new guards.
#
# IMPORTANT: All patterns match ANYWHERE in the command (no ^ anchor) so they
# catch chained commands like "git add && git commit" or "cd foo && git push".

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
HOOK_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=${OPENMATES_PROJECT_ROOT:-$(cd "$HOOK_DIR/../.." && pwd)}

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
if ! PARSED_GUARD_OUTPUT=$(python3 "$PROJECT_ROOT/scripts/safe_bash_guard.py" "$COMMAND" 2>&1); then
  printf '%s\n' "$PARSED_GUARD_OUTPUT" >&2
  exit 2
fi

# --- Package installs need the 7-day release-age check (cheap regex pre-filter first). ---
if echo "$COMMAND" | grep -qE '(npm|pnpm|yarn|pip3?|pip[0-9.]+|uv|cargo)[[:space:]]+([^;&|]*[[:space:]])?(install|i|add|it|install-test)([[:space:]]|$)'; then
  if ! AGE_GUARD_OUTPUT=$(python3 "$PROJECT_ROOT/scripts/install_age_hook.py" "$COMMAND" 2>&1); then
    printf '%s\n' "$AGE_GUARD_OUTPUT" >&2
    exit 2
  fi
fi

# --- Block Vercel project setting mutations that can enable paid build machines ---
# Credential stores are never read by chats (owner decision 21 Nov, 6d). ssh/git use keys
# themselves; printing or copying a key, token file or credentials file is refused.
CREDENTIAL_PATHS='(~|\$HOME|\$\{HOME\}|/home/[^/[:space:]]+|/root)/(\.ssh/id_[A-Za-z0-9_]+([^.A-Za-z0-9_]|$)|\.aws/credentials|\.config/gh/hosts\.yml|\.claude/\.credentials\.json|\.config/opencode/secrets\.env|\.git-credentials|\.netrc|\.docker/config\.json|\.vault-token)'
CREDENTIAL_READERS='(^|[[:space:];&|(`$])(cat|tac|head|tail|less|more|grep|egrep|fgrep|rg|awk|sed|base64|xxd|od|hexdump|strings|cp|rsync|tar|zip|curl|nc|python3?|node|jq)([[:space:]]|$)'
if echo "$COMMAND" | grep -qE "$CREDENTIAL_PATHS" && echo "$COMMAND" | grep -qE "$CREDENTIAL_READERS"; then
  echo '{"decision":"block","reason":"BLOCKED: reading or copying a credential file (SSH private key, cloud, GitHub, Claude, Docker or Vault token) is not allowed from chats. Tools such as ssh and git read their own keys; ask the operator if a credential is really needed."}' >&2
  exit 2
fi

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
    *) candidate="$PROJECT_ROOT/$script_path" ;;
  esac
  if [ ! -f "$candidate" ]; then
    continue
  fi
  case "$candidate" in
    "$PROJECT_ROOT"/scripts/tests/*) continue ;;
  esac
  if grep -qiE 'api\.vercel\.com/.*/projects|api\.vercel\.com/v[0-9]+/projects|\bvercel\s+project\b' "$candidate" \
    && grep -qiE 'buildMachine(Type|Selection)?|elasticConcurrency|buildMachineElastic|resourceConfig|Dynamic build' "$candidate" \
    && grep -qiE '(-X|--request)[[:space:]]*(PATCH|PUT|POST|DELETE)|\.(patch|put|post|delete)\s*\(|urlopen\([^)]*method=["'"'"'](PATCH|PUT|POST|DELETE)["'"'"']' "$candidate"; then
    echo '{"decision":"block","reason":"BLOCKED: Refusing to run a repo script that can mutate Vercel build-machine/project settings. Keep Vercel buildMachineType=standard and buildMachineSelection=fixed."}' >&2
    exit 2
  fi
done

exit 0
