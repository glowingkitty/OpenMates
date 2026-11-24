#!/usr/bin/env python3
"""Recover stalled dev work chats without interrupting an active turn or owner wait."""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chat_compaction_handoff as handoff
import chat_usage_watch
import claude_chat_waiters as waiters
import claude_idle_chats as lifecycle
import codex_chats
import worktree_wip

OWNER_WAIT = re.compile(r"\b(?:marco|owner)(?:'s)?\b|\b(?:production|prod ssh)\b", re.I)
USER_PAUSE = re.compile(r"owner-requested pause|paused by (?:marco|owner)|owner authoriz|three-failure", re.I)
PROMPT = ("The dev-host watchdog found unfinished work in this chat. Verify the current Task and worktree. "
          "Continue the authorized dev work and preserve any pending owner decisions.")


def cached_tasks(now: float) -> list[dict]:
    data = handoff._load(lifecycle.TASKS_CACHE)
    fetched = lifecycle._iso(data.get("fetched_at"))
    if not 0 <= now - fetched <= 2 * 3600:
        return []
    return (data.get("data") or {}).get("tasks") or []


def protected_chats(directory: Path, registered: dict, live: dict, now: float) -> set[str]:
    protected = set()
    for chat_id, chat in live.items():
        if chat.protected or chat.pushed_question or lifecycle.waiting_on_billing(chat):
            protected.add(chat_id)
    for entry in registered.values():
        if not entry.get("fired_at") and OWNER_WAIT.search(entry["on"]):
            protected.add(entry["chat_id"])
    for chat_id, entry in lifecycle.load_registry(directory).items():
        if entry.get("open_question") or "waits on your answer" in entry.get("reason", ""):
            protected.add(chat_id)
    for path in lifecycle.questions_dir().glob("*.json"):
        marker = handoff._load(path)
        if lifecycle._iso(marker.get("paused_until")) > now:
            protected.add(path.stem)
    return protected


def codex_age(chat_id: str, now: float) -> tuple[float, bool]:
    activity, state = codex_chats.turn_activity(chat_id)
    return now - activity if activity else 0, state == "working"


def problems(directory: Path, now: float, live: dict, codex: dict, status: dict,
             protected: set[str], tasks: list[dict]) -> dict[str, dict]:
    """One actionable current incident per chat. Parked patches and active turns stay intact."""
    handed = handoff._load(directory / "handed_off.json")
    refused = handoff._load(directory / "refused-handovers.json")
    registered = handoff._load(directory / "registered.json")
    waiting = {entry["chat_id"] for entry in registered.values() if not entry.get("deadline_wake")}
    registry = lifecycle.load_registry(directory)
    cases = {}
    for entry in status.get("stalled") or []:
        reason = entry.get("reason", "")
        if "last reply asks" in reason or "waiter timed out" in reason:
            continue
        chat_id = entry["session_id"]
        if "wait is over" in reason:
            cases[chat_id] = {"kind": "waiter", "reason": reason}
            continue
        silent = reason.startswith(("working,", "runs a background"))
        cases[chat_id] = {"kind": "silent" if silent else "stalled", "reason": reason}
    wip = handoff._load(worktree_wip.state_dir() / "status.json")
    sessions = handoff._load(worktree_wip.sessions_file()).get("sessions") or {}
    for entry in wip.get("unfinished") or []:
        chat_id = entry.get("chat_id")
        workspace = (sessions.get(entry.get("session_id")) or {}).get("worktree") or {}
        if not chat_id or entry.get("error") or entry.get("files", 0) <= 0:
            continue
        if workspace.get("status") == "merged":
            continue
        parked = entry.get("parked") or {}
        reason = parked.get("reason", "")
        if USER_PAUSE.search(reason):
            continue
        if chat_id in waiting or (not reason and chat_id in set(live) | set(codex)):
            continue
        cases[chat_id] = {"kind": "parked", "reason": reason or "worktree still has unpublished work"}
    for chat_id, entry in refused.items():
        cases[chat_id] = {"kind": "handoff", **entry}
    for chat_id in codex:
        age, working = codex_age(chat_id, now)
        if working and age >= lifecycle.STALLED_MINUTES * 60 and chat_id not in waiting:
            cases.setdefault(chat_id, {"kind": "silent", "reason": "Codex turn has no recent activity"})
    open_chats = {link.get("id") for task in tasks if task.get("status") not in ("done", "cancelled")
                  if (link := task.get("external_chat")) and link.get("provider") == "claude"}
    for chat_id in open_chats:
        stopped = registry.get(chat_id) or {}
        if stopped.get("state") == "stopped" and chat_id not in waiting:
            cases.setdefault(chat_id, {"kind": "stalled", "reason": "stopped chat still has an open Task"})
    return {chat: case for chat, case in cases.items()
            if chat not in protected and chat not in handed and waiters.UUID_RE.fullmatch(chat)}


def attempt(chat_id: str, incident: dict, live: dict, codex: dict) -> str:
    if incident["kind"] == "waiter":
        return incident["reason"]
    if incident["kind"] == "silent":
        return "Has an active turn or background process. It needs inspection."
    if chat_id in codex:
        _, working = codex_age(chat_id, time.time())
        if working:
            return "Codex still has an active turn."
        return codex_chats.type_into(chat_id, PROMPT)
    if chat := live.get(chat_id):
        if chat.status == "idle" and not chat.children and not chat.agents and lifecycle.wake(chat, PROMPT):
            return "ok"
        return "Existing Claude process could not accept a recovery prompt."
    return handoff.resume_on_codex(chat_id, PROMPT, task_id=incident.get("task") or "")


def cycle(directory: Path, now: float, *, dry_run: bool = False, notify: bool = True) -> dict:
    registered = handoff._load(directory / "registered.json")
    status = handoff._load(directory / "status.json")
    config = lifecycle.load_config()
    live = {chat.session_id: chat for chat in lifecycle.live_chats(Path.home() / ".claude", config, waiters={})}
    codex = codex_chats.live()
    protected = protected_chats(directory, registered, live, now)
    tasks = cached_tasks(now)
    if not dry_run:
        task_status = {key: task["status"] for task in tasks for key in (task.get("task_id"), task.get("short_id"))
                       if key and task.get("status")}
        waiters.settle_external_waits(directory, now, task_status, protected)
    cases = problems(directory, now, live, codex, status, protected, tasks)
    marks_path = directory / "watchdog-incidents.json"
    old = handoff._load(marks_path)
    marks = {}
    attempted = 0
    order = sorted(cases, key=lambda chat_id: (old.get(chat_id, {}).get("attempted_at", 0), chat_id))
    for chat_id in order:
        incident = cases[chat_id]
        kind = incident["kind"]
        mark = dict(old.get(chat_id) or {})
        if mark.get("kind") != kind:
            mark = {"kind": kind}
        marks[chat_id] = mark
        if dry_run:
            continue
        if mark.get("recovered") and (chat_id in live or chat_id in codex):
            incident["outcome"] = "Recovery prompt already delivered"
            continue
        if attempted >= 4:
            incident["outcome"] = "Deferred to next watchdog pass"
            continue
        attempted += 1
        mark["attempted_at"] = now
        try:
            outcome = attempt(chat_id, incident, live, codex)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            outcome = f"Recovery failed ({type(error).__name__})"
        incident["outcome"] = outcome
        mark["recovered"] = outcome == "ok"
        if notify and not mark.get("alerted") and (outcome != "ok" or kind == "handoff"):
            message = "Task handoff failed; recovery is tracked" if kind == "handoff" else outcome
            label = " ".join(message.split()).strip(".")[:145]
            mark["alerted"] = chat_usage_watch.send(f"Chat recovery {chat_id[:8]}: {label}.")
        waiters._write_json(marks_path, {**old, **marks})
    if not dry_run:
        waiters._write_json(marks_path, marks)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()
    directory = lifecycle.state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "watchdog.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        print(json.dumps(cycle(directory, time.time(), dry_run=args.dry_run, notify=not args.no_notify),
                         indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
