#!/usr/bin/env python3
"""Tool-call warnings for sub-agents (PreToolUse hook backend).

Reads the hook JSON from stdin. Main-chat calls (no ``agent_id``) are ignored.
It never blocks (owner, 22 Nov: no hard caps on sub-agents; long lanes such as
the Rust migration need them). From the warning threshold on, every few calls it
reminds the agent to hand back a short summary and let the parent start a fresh
lane. Unusual usage across a chat is reported to the owner by
scripts/chat_usage_watch.py instead. The boundary fails open.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

EXEMPT_TYPES = {"ci-runner"}
STATE_MAX_AGE_SECONDS = 2 * 86400
WARN_EVERY = 10


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _cleanup(directory: Path) -> None:
    cutoff = time.time() - STATE_MAX_AGE_SECONDS
    for path in list(directory.glob("*.json")) + list(directory.glob("*.lock")):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def _load(state: Path) -> int:
    try:
        return int(json.loads(state.read_text())["count"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def _save(state: Path, count: int) -> None:
    tmp = state.with_suffix(".tmp")
    tmp.write_text(json.dumps({"count": count}))
    os.replace(tmp, state)


def run(payload: dict) -> int:
    agent_id = payload.get("agent_id")
    if not agent_id or payload.get("agent_type") in EXEMPT_TYPES:
        return 0
    if payload.get("hook_event_name") == "SubagentStop":
        return 0
    warn = _int_env("OPENMATES_SUBAGENT_WARN_CALLS", 50)
    directory = Path(os.environ.get("OPENMATES_SUBAGENT_BUDGET_DIR", "/tmp/claude-subagent-budget"))
    directory.mkdir(parents=True, exist_ok=True)
    _cleanup(directory)
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{payload.get('session_id', 'x')}__{agent_id}")
    state = directory / f"{key}.json"
    with (directory / f"{key}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        count = _load(state) + 1
        _save(state, count)
    if count >= warn and (count - warn) % WARN_EVERY == 0:
        message = (
            f"Sub-agent note: {count} tool calls so far. If the deliverable is done or the rest is a "
            "separate step, hand back now with a short summary (outcome, files changed, checks run, "
            "pending CI job ids, exact next step; no raw logs) so the parent can start a fresh lane."
        )
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "additionalContext": message}}))
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        return run(payload)
    except Exception:  # noqa: BLE001 - documented fail-open hook boundary
        return 0


if __name__ == "__main__":
    sys.exit(main())
