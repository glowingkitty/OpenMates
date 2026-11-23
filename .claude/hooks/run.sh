#!/bin/bash
# Run one repository hook script from the main checkout, never from the chat's cwd.
#
# Usage (from .claude/settings.json): "$CLAUDE_PROJECT_DIR"/.claude/hooks/run.sh <repo-relative path> [args...]
#
# Hooks used to call `$(git rev-parse --show-toplevel)/<path>`, which resolves to whatever
# worktree the chat's shell has cd'ed into. On 2026-11-23 scripts/chat_mailbox.py landed on
# dev at 13:00; every chat whose shell sat in a worktree based before that got
# "python3: can't open file .../agent-xxxx/scripts/chat_mailbox.py" (exit 2) from its
# UserPromptSubmit hook, so every prompt, task notification and lifecycle wake-up was
# blocked and stayed in the input box for over an hour.
#
# The script is resolved in the main checkout (the parent of the shared git common dir),
# which always holds current dev. A missing script is logged and skipped (exit 0): a
# hook that cannot run must never block the chat. The target's own exit code passes through.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
root="$here"
common="$(git -C "$here" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
if [ -n "$common" ] && [ -d "$(dirname "$common")/.claude/hooks" ]; then
  root="$(dirname "$common")"
fi
target="${1:-}"
[ $# -gt 0 ] && shift
path="$root/$target"
if [ -z "$target" ] || [ ! -f "$path" ]; then
  echo "hook skipped: ${path} is missing (see .claude/hooks/run.sh)" >&2
  log_dir="$root/logs/claude-chat-lifecycle"
  if [ -d "$log_dir" ]; then
    printf '{"event": "hook_script_missing", "path": "%s", "ts": "%s"}\n' \
      "$path" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_dir/events.jsonl" 2>/dev/null
  fi
  exit 0
fi
case "$path" in
  *.py) exec python3 "$path" "$@" ;;
  *) exec bash "$path" "$@" ;;
esac
