"""Keep working chats alive: continue wakes and running background sub-agents (TASK-7707).

On 2026-11-20 the chat lifecycle (scripts/claude_idle_chats.py) closed five chats in the middle
of their work, and they lost the night. Three ended a turn by announcing their next step ("Next:
fix the foreground reconnect") and were stopped as idle 3 minutes later. One had a background
sub-agent mid tool call: background agents run inside the chat's own process, so nothing showed
as a running child. Owner rule 2026-11-21: a chat may only be closed when it reported done (✅
push), asked the owner (❓ push or a closing question) or registered a waiter. A turn that ends any
other way is woken to continue.

This module holds the two pieces the lifecycle needs for that:

  running_agents   background sub-agents of the chat's current process that have not reported
                   back: a `subagents/agent-<id>.meta.json` with requestShape "background" whose
                   `<task-id><id></task-id>` notification is not in the chat's transcript yet,
                   and whose own transcript moved since the process started and within
                   AGENT_STALE_HOURS (an agent that hangs longer no longer holds the chat).
  next_wake        when to type CONTINUE_PROMPT into a chat whose turn ended without done,
                   question or waiter: once per turn end, again after RETRY_MINUTES when the
                   typed line did not take, at most MAX_WAKES times in a row. After that the
                   chat is kept and listed as stalled for the owner, never closed.
"""
from __future__ import annotations

import json
from pathlib import Path

AGENT_STALE_HOURS = 3.0
NOTIFICATION_WINDOW = 16 * 1024 * 1024  # bytes of the chat transcript searched for an agent's notification
MAX_WAKES = 3
RETRY_MINUTES = 10.0
REOPEN_MINUTES = 30.0  # a chat stopped under memory pressure is reopened this long after
CONTINUE_PROMPT = (
    "(Chat lifecycle) Your last turn ended without a ✅ done push, a question to Marco or a registered "
    "waiter, so this chat would sit idle. Continue with your next step now. When everything is finished, "
    "send the done push (python3 scripts/agent_question.py done --summary ...); when you need Marco, ask "
    "(python3 scripts/agent_question.py ask ...); when you wait on something else, register a waiter "
    "(python3 scripts/claude_chat_waiters.py add ...).")
REOPEN_MESSAGE = ("the host was short on memory, so the chat lifecycle stopped this chat in the middle of its "
                  "work; continue where you left off")


def _iso(value) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _last_timestamp(transcript: Path) -> float:
    try:
        with transcript.open("rb") as handle:
            handle.seek(max(0, transcript.stat().st_size - 65536))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return 0.0
    for line in reversed(lines):
        try:
            stamp = json.loads(line).get("timestamp")
        except (ValueError, AttributeError):
            continue
        if stamp:
            return _iso(stamp)
    return 0.0


def _tail_text(transcript: Path) -> str:
    try:
        with transcript.open("rb") as handle:
            handle.seek(max(0, transcript.stat().st_size - NOTIFICATION_WINDOW))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def running_agents(transcript: Path, process_started: float, now: float) -> list[str]:
    """Descriptions of the background sub-agents of this process still at work (see module doc)."""
    folder = transcript.with_suffix("") / "subagents"
    candidates = []
    for meta_path in sorted(folder.glob("agent-*.meta.json")) if folder.is_dir() else []:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("requestShape") != "background":
            continue
        agent_id = meta_path.name.removeprefix("agent-").removesuffix(".meta.json")
        last = _last_timestamp(folder / f"agent-{agent_id}.jsonl")
        if last < process_started or now - last > AGENT_STALE_HOURS * 3600:
            continue  # an agent of an earlier process (it died with it) or one that hangs
        candidates.append((agent_id, str(meta.get("description") or meta.get("agentType") or agent_id)))
    if not candidates:
        return []
    text = _tail_text(transcript)
    return [description for agent_id, description in candidates if f"<task-id>{agent_id}</task-id>" not in text]


def worked_since(transcript: Path, since: float) -> bool:
    """True when the chat ran a tool after `since` (it did real work after a wake)."""
    try:
        with transcript.open("rb") as handle:
            handle.seek(max(0, transcript.stat().st_size - NOTIFICATION_WINDOW))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        stamp = _iso(record.get("timestamp")) if record.get("timestamp") else 0.0
        if stamp and stamp <= since:
            return False
        content = (record.get("message") or {}).get("content") if record.get("type") == "assistant" else None
        if isinstance(content, list) and any(isinstance(c, dict) and c.get("type") == "tool_use" for c in content):
            return True
    return False


def next_wake(marks: dict, chat_id: str, turn_ended: float, now: float, worked: bool = False) -> str:
    """'wake', 'wait' (woken, give it time) or 'stalled' (MAX_WAKES in a row did not help).

    `marks[chat_id]` = {"turn": turn end woken for, "at": last wake, "count": wakes in a row}.
    `worked`: the chat ran tools after the last wake, so the wake helped and the count starts
    over. A chat that only answers (no tool) and again ends without done, question or waiter
    counts on and is no longer woken after MAX_WAKES."""
    mark = marks.get(chat_id) or {}
    if worked and mark.get("turn") != turn_ended:
        mark = marks[chat_id] = {**mark, "count": 0}
    if mark.get("count", 0) >= MAX_WAKES:
        return "stalled"
    if mark.get("turn") == turn_ended and now - float(mark.get("at", 0)) < RETRY_MINUTES * 60:
        return "wait"
    return "wake"


def record_wake(marks: dict, chat_id: str, turn_ended: float, now: float) -> None:
    mark = marks.get(chat_id) or {}
    marks[chat_id] = {"turn": turn_ended, "at": now, "count": int(mark.get("count", 0)) + 1}
