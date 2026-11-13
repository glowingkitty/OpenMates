#!/usr/bin/env python3
"""
Fable guard for Claude Code chats on the dev server (SessionStart / UserPromptSubmit hook).

Fable (claude-fable-5-2) costs about twice as much as Opus, so it never runs by
default: new chats start on Opus and sub-agents on Sonnet/Haiku. Launchers refuse
implicit Fable (scripts/claude_dispatch.py `check_chat_model`); this hook covers
chats that reach Fable some other way (an app chat with a stale model choice, a
resumed or compacted Fable chat, a manual `claude --model fable`).

  SessionStart       model is Fable and not explicitly requested → mark the
                     session and tell the chat to stop and ask before any work.
  UserPromptSubmit   in a marked session, a prompt that names Fable is the
                     user's explicit request → clear the mark and continue.

Explicit request: the launcher sets OPENMATES_FABLE_REQUESTED=1 (e.g. the voice
connector's start_chat with model Fable), or the user's message names Fable.

Tests: scripts/tests/test_fable_guard.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

DEFAULT_CHAT_MODEL = "claude-opus-5-5"
STATE_DIR = Path(os.getenv("FABLE_GUARD_STATE", Path.home() / ".local/state/openmates/fable-guard"))
SESSION_RE = re.compile(r"^[0-9A-Za-z_-]{1,80}$")
FABLE_WORD_RE = re.compile(r"\bfable\b", re.IGNORECASE)

NOTICE = (
    "FABLE GUARD: this chat runs on {model}. Fable costs about twice as much as Opus and runs on this "
    "server only when the user explicitly asks for it; the default for new chats is " + DEFAULT_CHAT_MODEL + ". "
    "Unless the user's message explicitly asks for Fable, do no work and no tool calls: reply only with one "
    "short message saying this chat is running on Fable, that they can switch with `/model " + DEFAULT_CHAT_MODEL +
    "`, or say \"keep Fable\" to continue on Fable; then stop. If you are no longer running on Fable "
    "(the model was switched), ignore this notice."
)
CONFIRMED = "FABLE GUARD: the user explicitly asked for Fable in this message; the earlier Fable notice no longer applies."


def is_fable(model: str) -> bool:
    return "fable" in (model or "").lower()


def _marker(session_id: str) -> Path | None:
    return STATE_DIR / session_id if SESSION_RE.match(session_id or "") else None


def _context(event: str, text: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def handle(payload: dict, env: dict[str, str]) -> str:
    """Return the hook's stdout (empty when it has nothing to add)."""
    event = payload.get("hook_event_name", "")
    marker = _marker(str(payload.get("session_id", "")))
    if event == "SessionStart":
        model = str(payload.get("model") or env.get("ANTHROPIC_MODEL") or "")
        if payload.get("agent_type") or not is_fable(model) or env.get("OPENMATES_FABLE_REQUESTED") == "1":
            return ""
        if marker:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            marker.write_text(model, encoding="utf-8")
        return _context(event, NOTICE.format(model=model))
    if event == "UserPromptSubmit" and marker and marker.exists():
        if FABLE_WORD_RE.search(str(payload.get("prompt", ""))):
            marker.unlink()
            return _context(event, CONFIRMED)
    return ""


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        print("fable-guard: hook input is not JSON; skipped", file=sys.stderr)
        return 0
    out = handle(payload if isinstance(payload, dict) else {}, dict(os.environ))
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
