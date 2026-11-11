#!/usr/bin/env python3
"""Close Claude Code chat processes that have been idle for a long time.

The Remote Control server (``claude remote-control``) keeps one worker process
per chat, plus that chat's tool servers, until the chat is archived. It has no
idle timeout, so finished chats pile up and hold several GB on the dev server.

A chat is closed only when every rule holds:
  * its process is a Remote Control worker (never the server, never a chat
    started by hand in a terminal),
  * its recorded state is ``idle``,
  * its state and its transcript (sub-agent transcripts included) have not
    changed for longer than the limit (default 24 hours),
  * it has no child process other than its tool (MCP) servers, so no background
    command is still running,
  * it is not the chat that runs this script.

Closing sends SIGTERM and never SIGKILL. The transcript stays on disk; the chat
shows as disconnected in claude.ai and does not wake up by itself when it
receives a message.

Commands:
  list   Show every live chat with its idle time and the decision.
  reap   Close the chats that qualify (--dry-run prints instead).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MAX_IDLE_HOURS = 24.0
TERM_WAIT_SECONDS = 20.0
WORKER_MARKERS = ("--sdk-url", "/code/sessions/")
TOOL_SERVER_MARKER = "mcp"


@dataclass
class Chat:
    """One live chat process as recorded in ``~/.claude/sessions/<pid>.json``."""

    pid: int
    session_id: str
    name: str
    status: str
    is_worker: bool
    last_change: float
    children: list[str] = field(default_factory=list)


@dataclass
class Decision:
    close: bool
    reason: str


def decide(chat: Chat, now: float, max_idle_seconds: float, own_session_id: str) -> Decision:
    """Pure rule: may this chat's process be closed?"""
    if not chat.is_worker:
        return Decision(False, "not a Remote Control worker")
    if own_session_id and chat.session_id == own_session_id:
        return Decision(False, "this chat runs the script")
    if chat.status != "idle":
        return Decision(False, f"state is {chat.status or 'unknown'}")
    idle = now - chat.last_change
    if idle <= max_idle_seconds:
        return Decision(False, f"idle {idle / 3600:.1f}h, limit {max_idle_seconds / 3600:.0f}h")
    busy = [command for command in chat.children if TOOL_SERVER_MARKER not in command.lower()]
    if busy:
        return Decision(False, f"background process running: {busy[0][:60]}")
    return Decision(True, f"idle {idle / 3600:.1f}h")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _proc_start(pid: int) -> str:
    stat = _read(Path(f"/proc/{pid}/stat"))
    if ")" not in stat:
        return ""
    fields = stat.rsplit(")", 1)[1].split()
    return fields[19] if len(fields) > 19 else ""


def _cmdline(pid: int | str) -> str:
    return _read(Path(f"/proc/{pid}/cmdline")).replace("\0", " ").strip()


def _children(pid: int) -> list[str]:
    commands = []
    for child in _read(Path(f"/proc/{pid}/task/{pid}/children")).split():
        command = _cmdline(child)
        if command:
            commands.append(command)
    return commands


def _transcript_change(claude_home: Path, session_id: str) -> float:
    """Newest change time of the chat's transcript and its sub-agent transcripts."""
    newest = 0.0
    for transcript in (claude_home / "projects").glob(f"*/{session_id}.jsonl"):
        newest = max(newest, transcript.stat().st_mtime)
        for extra in transcript.with_suffix("").rglob("*"):
            if extra.is_file():
                newest = max(newest, extra.stat().st_mtime)
    return newest


def live_chats(claude_home: Path) -> list[Chat]:
    chats = []
    for record_path in sorted((claude_home / "sessions").glob("*.json")):
        try:
            record = json.loads(_read(record_path))
        except json.JSONDecodeError:
            continue
        pid = record.get("pid")
        if not isinstance(pid, int) or not Path(f"/proc/{pid}").exists():
            continue
        # A recycled pid belongs to another program: the start time must match.
        if str(record.get("procStart", "")) != _proc_start(pid):
            continue
        session_id = str(record.get("sessionId", ""))
        command = _cmdline(pid)
        state_change = float(record.get("statusUpdatedAt") or record.get("startedAt") or 0) / 1000
        chats.append(Chat(
            pid=pid,
            session_id=session_id,
            name=str(record.get("name", "")),
            status=str(record.get("status", "")),
            is_worker=all(marker in command for marker in WORKER_MARKERS),
            last_change=max(state_change, _transcript_change(claude_home, session_id)),
            children=_children(pid),
        ))
    return chats


def close(chat: Chat) -> bool:
    """Ask the worker to exit; True when it is gone within the wait."""
    expected_start = _proc_start(chat.pid)
    try:
        os.kill(chat.pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + TERM_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _proc_start(chat.pid) != expected_start:
            return True
        time.sleep(0.5)
    return False


def log_event(log_dir: Path, event: dict) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    event = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **event}
    with (log_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("list", "reap"))
    parser.add_argument("--max-idle-hours", type=float, default=DEFAULT_MAX_IDLE_HOURS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    parser.add_argument("--log-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "logs" / "claude-idle-chats")
    args = parser.parse_args(argv)

    now = time.time()
    own = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    failed = 0
    for chat in sorted(live_chats(args.claude_home), key=lambda item: item.last_change):
        decision = decide(chat, now, args.max_idle_hours * 3600, own)
        label = f"{chat.name or chat.session_id[:8]} (pid {chat.pid})"
        if args.command == "list" or not decision.close:
            if args.command == "list":
                print(f"{'close' if decision.close else 'keep '}  {label}: {decision.reason}")
            continue
        if args.dry_run:
            print(f"would close {label}: {decision.reason}")
            continue
        closed = close(chat)
        failed += 0 if closed else 1
        print(f"{'closed' if closed else 'STILL RUNNING'} {label}: {decision.reason}")
        log_event(args.log_dir, {"event": "closed" if closed else "close_failed",
                                 "reason": decision.reason, **asdict(chat)})
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
