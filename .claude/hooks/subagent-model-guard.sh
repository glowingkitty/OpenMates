#!/usr/bin/env bash
# subagent-model-guard: sub-agents run on Sonnet (default) or Haiku only.
#
# The Agent tool's `model` parameter overrides both the agent definition and
# CLAUDE_CODE_SUBAGENT_MODEL, so a parent chat could put a whole lane on Opus
# or Fable. One long lane on those models costs more than the parent chat, so
# the override is refused here. A fork is refused too: it always runs on the
# parent's model and carries the parent's full context.
INPUT=$(cat)
MODEL=$(echo "$INPUT" | jq -r '.tool_input.model // empty' | tr '[:upper:]' '[:lower:]')
TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty')

if [ "$TYPE" = "fork" ]; then
  echo "subagent-model-guard: fork sub-agents are not allowed here (a fork runs on the parent's model with the parent's full context). Start a 'lane-worker' with a short brief instead." >&2
  exit 2
fi

case "$MODEL" in
  ""|sonnet|haiku|*sonnet*|*haiku*) exit 0 ;;
esac

echo "subagent-model-guard: model '$MODEL' is not allowed for sub-agents. Omit 'model' (Sonnet is the default; ci-runner uses Haiku). Split a hard lane into smaller Sonnet lanes; only the user can waive this rule." >&2
exit 2
