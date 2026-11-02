#!/bin/bash
# Hook: SessionStart / UserPromptSubmit
# Injects other running Claude chats in this repository (task, workspace,
# recent files) so parallel chats avoid overlapping work. Successor of the
# retired Codex chat presence. Re-emits on prompts only when peers change.
exec python3 "$(dirname "$0")/../../scripts/agent_peers.py" hook
