#!/usr/bin/env python3
"""Wake Claude chats that stopped while work was still owed.

A chat that ends its turn with "it's running, I'll continue when it finishes" is not woken
by anything; it stays idle until the user types. This script sends one automatic message to
such chats. A chat qualifies only when ALL hold:
  * it is a Remote Control worker whose recorded state is idle,
  * it has been idle between --min-minutes (default 20) and --max-minutes (default 50; the
    upper bound keeps the one-hour prompt cache warm),
  * it has no child process other than tool (MCP) servers,
  * it did not send a scripts/agent_question.py question after its last activity,
  * it was not already nudged for this idle period (``nudges.json``: chat id + last activity),
  * there is evidence of owed work: CI jobs of its sessions.py sessions that are non-terminal
    or reached a terminal state after its last activity, or its last assistant text contains a
    waiting phrase and does not end with a question mark.
The chat that runs the script is never nudged. Delivery reuses claude_usage_guard.deliver.
Decisions are appended to logs/claude-idle-chats/events.jsonl.

Commands:
  list    Show every live chat with the decision.
  nudge   Send the message to the chats that qualify (--dry-run prints instead).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import claude_usage_guard
from agent_peers import transcripts
from claude_idle_chats import TOOL_SERVER_MARKER, Chat, live_chats, log_event
from pending_work_gate import TERMINAL, canonical_root, chat_sessions

DEFAULT_MIN_MINUTES = 20.0
DEFAULT_MAX_MINUTES = 50.0
TAIL_BYTES = 400_000
QUESTION_TAIL = 300
WAITING_PHRASES = ("is running", "is now running", "once it finishes", "once the", "i'll continue",
                   "i'll rerun", "when it's green", "is still running")


def last_assistant_text(path: Path | None) -> str:
    """Text of the newest assistant message in a transcript ('' when none is found)."""
    if path is None:
        return ""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - TAIL_BYTES))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        if '"assistant"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        texts = [block.get("text", "") for block in content or []
                 if isinstance(block, dict) and block.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return ""


def waiting_text(text: str) -> bool:
    lowered = text.lower()
    if not any(phrase in lowered for phrase in WAITING_PHRASES):
        return False
    return "?" not in text.strip()[-QUESTION_TAIL:]


def ci_evidence(root: Path, chat_id: str, last_activity: float) -> tuple[list[str], list[str]]:
    """(ids finished after last_activity, ids still non-terminal) for the chat's sessions."""
    try:
        sessions = chat_sessions(root, chat_id)
        if not sessions:
            return [], []
        db = sqlite3.connect(f"file:{root / 'logs/ci-coordinator/queue.sqlite3'}?mode=ro", uri=True, timeout=0.5)
    except (OSError, ValueError, sqlite3.Error):
        return [], []
    try:
        owners = ",".join("?" for _ in sessions)
        rows = db.execute(f"SELECT id, state, updated FROM jobs WHERE owner IN ({owners})", sessions).fetchall()
    except sqlite3.Error:
        return [], []
    finally:
        db.close()
    finished = [row[0] for row in rows if row[1] in TERMINAL and float(row[2] or 0) > last_activity]
    running = [row[0] for row in rows if row[1] not in TERMINAL]
    return finished, running


def question_time(root: Path, chat_id: str) -> float:
    try:
        recorded = json.loads((root / "logs/claude-idle-chats/questions" / f"{chat_id}.json").read_text("utf-8"))
        return float(recorded.get("ts", 0))
    except (OSError, ValueError, AttributeError):
        return 0.0


def load_nudges(root: Path) -> dict:
    try:
        return json.loads((root / "logs/claude-idle-chats/nudges.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_nudge(root: Path, key: str, now: float) -> None:
    path = root / "logs/claude-idle-chats/nudges.json"
    nudges = load_nudges(root)
    nudges[key] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(nudges, sort_keys=True), encoding="utf-8")


def nudge_key(chat: Chat) -> str:
    return f"{chat.session_id}:{int(chat.last_change)}"


def decide(chat: Chat, now: float, min_s: float, max_s: float, own: str, *, question_ts: float,
           nudged: bool, finished: list[str], running: list[str], last_text: str) -> tuple[bool, str]:
    """Pure rule: should this chat get the wake-up message? Returns (nudge, reason)."""
    if not chat.is_worker:
        return False, "not a Remote Control worker"
    if own and chat.session_id == own:
        return False, "this chat runs the script"
    if chat.status != "idle":
        return False, f"state is {chat.status or 'unknown'}"
    idle = now - chat.last_change
    if idle < min_s:
        return False, f"idle {idle / 60:.0f} min, below {min_s / 60:.0f}"
    if idle > max_s:
        return False, f"idle {idle / 60:.0f} min, above {max_s / 60:.0f} (cache cold)"
    busy = [command for command in chat.children if TOOL_SERVER_MARKER not in command.lower()]
    if busy:
        return False, f"background process running: {busy[0][:60]}"
    if question_ts > chat.last_change:
        return False, "question already sent to the user"
    if nudged:
        return False, "already nudged for this idle period"
    if finished or running:
        return True, f"CI jobs: {len(finished)} finished, {len(running)} running"
    if waiting_text(last_text):
        return True, "last message announces waiting"
    return False, "no owed work found"


def message_text(idle_minutes: int, finished: list[str]) -> str:
    return (f"Automatic check: this chat has been idle for {idle_minutes} minutes and nothing is running "
            f"for it. If work is still owed (finished CI jobs: {', '.join(finished[:8]) or 'none'}), "
            "continue it now. If you are blocked on a decision from the user, send it with "
            "scripts/agent_question.py and stop.")


def run(command: str, dry_run: bool, min_minutes: float, max_minutes: float, root: Path, claude_home: Path,
        now: float | None = None, agents: list[dict] | None = None, sender=claude_usage_guard.deliver) -> int:
    now = time.time() if now is None else now
    own = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    log_dir = root / "logs" / "claude-idle-chats"
    paths = transcripts(root)
    nudges = load_nudges(root)
    failed = 0
    for chat in sorted(live_chats(claude_home), key=lambda item: item.last_change):
        finished, running = ci_evidence(root, chat.session_id, chat.last_change)
        go, reason = decide(
            chat, now, min_minutes * 60, max_minutes * 60, own,
            question_ts=question_time(root, chat.session_id), nudged=nudge_key(chat) in nudges,
            finished=finished, running=running, last_text=last_assistant_text(paths.get(chat.session_id)))
        label = f"{chat.name or chat.session_id[:8]} (pid {chat.pid})"
        if command == "list":
            print(f"{'nudge' if go else 'keep '}  {label}: {reason}")
            continue
        if not go:
            continue
        text = message_text(int((now - chat.last_change) / 60), finished)
        if dry_run:
            print(f"would nudge {label}: {reason}\n  {text}")
            continue
        try:
            rows = agents if agents is not None else claude_usage_guard.list_background_agents()
            row = next((r for r in rows if r.get("sessionId") == chat.session_id), None)
            if row is None:
                raise claude_usage_guard.DeliveryFailed("chat not listed by claude agents")
            target = {"name": row["name"], "sessionId": chat.session_id, "status": row.get("status", ""),
                      "kind": row.get("kind", ""),
                      "permissionMode": claude_usage_guard.chat_permission_mode(paths.get(chat.session_id))}
            mode, _warning = claude_usage_guard.sender_mode([target])
            sender([target], text, root, mode)
            save_nudge(root, nudge_key(chat), now)
            nudges[nudge_key(chat)] = now
            event = "nudged"
        except claude_usage_guard.DeliveryFailed as error:
            failed += 1
            event = "nudge_failed"
            reason = f"{reason}; {error}"
        print(f"{event} {label}: {reason}")
        log_event(log_dir, {"event": event, "reason": reason, "session_id": chat.session_id,
                            "name": chat.name, "pid": chat.pid, "finished_jobs": finished})
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("list", "nudge"))
    parser.add_argument("--min-minutes", type=float, default=float(os.environ.get("NUDGE_MIN_MINUTES", DEFAULT_MIN_MINUTES)))
    parser.add_argument("--max-minutes", type=float, default=float(os.environ.get("NUDGE_MAX_MINUTES", DEFAULT_MAX_MINUTES)))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    args = parser.parse_args(argv)
    return run(args.command, args.dry_run, args.min_minutes, args.max_minutes, canonical_root(), args.claude_home)


if __name__ == "__main__":
    sys.exit(main())
