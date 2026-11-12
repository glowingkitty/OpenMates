#!/usr/bin/env python3
"""Block sub-agents from creating sessions or worktrees (PreToolUse Bash hook).

Exit 2 when a sub-agent (payload has ``agent_id``) runs ``sessions.py start`` or
``lane_start.py`` as a command. Quoted arguments of other commands do not match.
Fails open on any error.
"""

from __future__ import annotations

import json
import re
import shlex
import sys

MESSAGE = (
    "Sub-agents use the parent's session and worktree. Pass --session <id> given by "
    "the parent; do not create a session or worktree."
)
_PUNCT = ";&|(){}"
_WRAPPERS = {"python", "python3", "env", "sudo", "nohup", "time", "exec", "command", "rtk"}


def _segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCT)
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    for token in lexer:
        if set(token) <= set(_PUNCT):
            segments.append([])
        else:
            segments[-1].append(token)
    return [s for s in segments if s]


def is_session_start(command: str) -> bool:
    for words in _segments(command):
        index = 0
        while index < len(words) and (
            words[index] in _WRAPPERS
            or re.match(r"^\w+=", words[index])
            or words[index].startswith("-")
        ):
            index += 1
        if index >= len(words):
            continue
        script = words[index].rsplit("/", 1)[-1]
        if script == "lane_start.py":
            return True
        if script == "sessions.py":
            rest = [w for w in words[index + 1:] if not w.startswith("-")]
            if rest and rest[0] == "start":
                return True
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not payload.get("agent_id"):
            return 0
        command = (payload.get("tool_input") or {}).get("command") or ""
        if is_session_start(command):
            print(MESSAGE, file=sys.stderr)
            return 2
    except Exception:  # noqa: BLE001 - documented fail-open hook boundary
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
