"""Resolve the durable identity of the agent conversation running a command.

Claude Code exports CLAUDE_CODE_SESSION_ID to every shell command and hook
(sub-agents inherit it), so it identifies the owning conversation the same way
the retired Codex workflow used CODEX_THREAD_ID. Codex variables remain as a
fallback so existing session records and scripted callers keep resolving.
"""

from __future__ import annotations

import os

IDENTITY_ENV_VARS = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID")


def agent_thread_id(default: str = "") -> str:
    """Return the current agent conversation ID, or ``default`` when none is set."""
    for name in IDENTITY_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default
