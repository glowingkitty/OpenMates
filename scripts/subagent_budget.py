#!/usr/bin/env python3
"""Tool-call budget for sub-agents (PreToolUse and SubagentStop hook backend).

Reads the hook JSON from stdin. Main-chat calls (no ``agent_id``) are ignored.
Exit 0 allows (optionally printing additionalContext JSON); exit 2 blocks.
The outer boundary fails open: a budget bug must never stall an agent.
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
EXTRA_LEG_CALLS = 15


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
    warn = _int_env("OPENMATES_SUBAGENT_WARN_CALLS", 50)
    hard = _int_env("OPENMATES_SUBAGENT_MAX_CALLS", 70)
    directory = Path(os.environ.get("OPENMATES_SUBAGENT_BUDGET_DIR", "/tmp/claude-subagent-budget"))
    directory.mkdir(parents=True, exist_ok=True)
    _cleanup(directory)
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{payload.get('session_id', 'x')}__{agent_id}")
    state = directory / f"{key}.json"
    stopping = payload.get("hook_event_name") == "SubagentStop"
    with (directory / f"{key}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        count = _load(state)
        if stopping:
            if count >= hard:
                _save(state, max(0, hard - EXTRA_LEG_CALLS))
            return 0
        if count >= hard:
            blocked = True
        else:
            blocked = False
            count += 1
            _save(state, count)
    if blocked or count >= hard:
        print(
            f"Sub-agent budget reached ({hard} tool calls). Do not call more tools. "
            "Hand back now: outcome, files changed, state of unfinished edits, "
            "pending CI job ids, exact next step.",
            file=sys.stderr,
        )
        return 2
    if count >= warn and (count - warn) % 5 == 0:
        message = (
            f"Sub-agent budget: {count} of {hard} tool calls used. Finish the current step "
            "and hand back with outcome, files changed, checks run, pending CI job ids and "
            "the exact next step. The parent starts a fresh lane for the rest."
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
