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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_question
import chat_compaction_handoff as handoff
import chat_usage_watch
import claude_chat_waiters as waiters
import claude_idle_chats as lifecycle
import codex_chats
import worktree_wip

OWNER_WAIT = re.compile(
    r"\b(?:marco|owner)(?:'s)?(?:\s+\w+){0,3}\s+(?:go|answer|approv\w*|decision|permission|confirm\w*|authoriz\w*)\b"
    r"|\b(?:ask|waiting (?:for|on))\s+(?:marco|(?:the )?owner)\b"
    r"|\b(?:authenticator|totp|ssh access window)\b", re.I)
RELEASE = re.compile(r"\brelease pr\b|\b(?:prod|production)\b.{0,30}\b(?:deploy\w*|rollout|release)\b"
                     r"|\b(?:deploy\w*|rollout|release)\b.{0,30}\b(?:prod|production)\b", re.I)
WAKE_GRACE = 120
ORDINARY_WAKE_GRACE = 300
MAX_WAKE_ATTEMPTS = 2
RELEASE_STALL = 10 * 60
USER_PAUSE = re.compile(r"owner(?:-requested)? pause|paused by (?:marco|owner)|owner authoriz|three-failure", re.I)
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
    pending = {}
    for entry in registered.values():
        if not entry.get("fired_at") and entry.get("kind") != "timer":
            pending.setdefault(entry["chat_id"], []).append(entry["on"])
    protected.update(chat for chat, reasons in pending.items() if all(OWNER_WAIT.search(reason) for reason in reasons))
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


def transcript_step(rows: list[dict]) -> tuple[float, float, str]:
    """Return latest work, latest real user input, and a safe label for the current tool."""
    step = prompt = 0.0
    command = ""
    for row in rows:
        at = lifecycle._iso(row.get("timestamp"))
        kind, payload = row.get("type"), row.get("payload") or {}
        if kind == "response_item":
            event = payload.get("type")
            if event == "message" and payload.get("role") == "user":
                continue
            if event in {"message", "function_call", "custom_tool_call", "local_shell_call",
                         "function_call_output", "custom_tool_call_output"}:
                step = max(step, at)
                if event.endswith("_call"):
                    command = str(payload.get("arguments") or payload.get("action") or payload.get("input") or "")
        elif kind == "event_msg" and payload.get("type") == "user_message":
            prompt = max(prompt, at)
        elif kind == "assistant":
            step = max(step, at)
            content = (row.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    command = str(block.get("input") or "")
        elif kind == "user":
            if row.get("isMeta") or row.get("toolUseResult") is not None:
                step = max(step, at)
            else:
                prompt = max(prompt, at)
    label = "the current turn"
    if re.search(r"\binstall(?:er|ing)?\b|[_-]install\b", command, re.I):
        label = "an installer"
    elif re.search(r"\bwait-deploy\b|\bdeployment\b", command, re.I):
        label = "a deployment command"
    elif command:
        label = "a running command"
    return step, prompt, label


def active_stalls(now: float, live: dict, codex: dict, status: dict, registry: dict,
                  protected: set[str], tasks: list[dict]) -> dict:
    waiting = {entry["session_id"]: entry for entry in status.get("waiting") or []
               if entry.get("ready") or set(entry.get("kinds") or []) != {"timer"}}
    task_titles = {(task.get("external_chat") or {}).get("id"): task.get("title") or "" for task in tasks}
    cases = {}
    for chat_id in (set(live) | set(codex) | set(waiting)) - protected:
        wait = waiting.get(chat_id) or {}
        reasons = [str(line) for line in wait.get("waits_on") or []]
        external = [line for line in reasons if not OWNER_WAIT.search(line)]
        if reasons and not external:
            continue
        if external and not wait.get("ready") and all(line.startswith("ci:") for line in external):
            continue  # The CI coordinator owns a live job and retains its final result.
        chat = live.get(chat_id)
        codex_record = (codex_chats.load(chat_id) or {}) if chat_id in codex else {}
        native = codex_chats.rollout_path(codex_record.get("thread_id") or "") if chat_id in codex else None
        transcript = native or (Path(chat.transcript) if chat and chat.transcript else None)
        step, prompt, label = transcript_step(lifecycle._tail_records(transcript) if transcript else [])
        details = registry.get(chat_id) or {}
        if chat_id in codex:
            activity, turn = codex_chats.turn_activity(chat_id)
            marker = lifecycle.pushed(chat_id, prompt)
            if marker.get("kind") == "❓" and not external:
                continue
            working = turn == "working"
        elif chat:
            activity = chat.last_activity
            working = chat.status in {"busy", "working", "waiting"} or bool(chat.waiting_for) or any(
                lifecycle.TOOL_SERVER_MARKER not in command.lower() for command in chat.children)
        else:
            activity, working = lifecycle._iso(details.get("last_activity")), False
        if not working and not wait:
            continue
        title = (chat.title if chat else "") or codex_record.get("title") or wait.get("title") or (
            details.get("title") or task_titles.get(chat_id) or (chat.name if chat else "Untitled work chat"))
        release = bool(RELEASE.search(f"{title} {task_titles.get(chat_id, '')}"))
        if external:
            label = re.sub(r"^(?:background|ci|disk|timer|handoff):\s*", "", external[0].split(" (", 1)[0])
        elif chat and chat.waiting_for and not OWNER_WAIT.search(chat.waiting_for):
            label = chat.waiting_for
        since = max(step, prompt, lifecycle._iso(wait.get("since"))) or activity
        if since and now - since >= (RELEASE_STALL if release else lifecycle.STALLED_MINUTES * 60):
            cases[chat_id] = {"kind": "active_stall", "title": title, "reason": label,
                              "since": since, "release": release}
    return cases


def delivery_topic(entry: dict) -> str:
    """Classify the message without exposing its text in an alert."""
    text = str(entry.get("text") or entry.get("body") or "").casefold()
    if re.search(r"\bremote[- ]access\b", text) and re.search(r"\b(?:live editing|collaboration)\b", text):
        return "remote-access live editing"
    if re.search(r"\b(?:production rollout|production release|deploy to prod)\b", text):
        return "a production rollout"
    if re.search(r"\b(?:verify|verification|tests?|proof)\b", text):
        return "verification"
    return "a work follow-up"


def delivery_stalls(directory: Path, now: float) -> dict[str, dict]:
    """One aged unseen delivery per chat, with a safe topic label."""
    cases: dict[str, dict] = {}
    for key, entry in handoff._load(directory / "connector-deliveries.json").items():
        if entry.get("state") not in ("pending", "undelivered"):
            continue
        chat_id = entry.get("chat") or key.partition(":")[0]
        sent = entry.get("sent_at") or entry.get("typed_at")
        if not isinstance(sent, (int, float)) or not 600 <= now - sent <= 24 * 3600:
            continue
        if chat_id not in cases or sent < cases[chat_id]["since"]:
            cases[chat_id] = {"kind": "unseen_delivery", "title": entry.get("title"),
                              "reason": "a message unseen for ten minutes", "since": sent,
                              "topic": delivery_topic(entry)}
    return cases


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
        if not reason.startswith(("working,", "runs a background")):
            cases[chat_id] = {"kind": "stalled", "reason": reason, "title": entry.get("title")}
    wip = handoff._load(worktree_wip.state_dir() / "status.json")
    sessions = handoff._load(worktree_wip.sessions_file()).get("sessions") or {}
    wip_owners = set()
    for entry in wip.get("unfinished") or []:
        chat_id = entry.get("chat_id")
        workspace = (sessions.get(entry.get("session_id")) or {}).get("worktree") or {}
        if not chat_id or entry.get("error") or entry.get("files", 0) <= 0:
            continue
        if workspace.get("status") == "merged":
            continue
        wip_owners.add(chat_id)
        if chat_id not in live and chat_id not in codex:
            continue  # The half-hour worktree recovery owns stopped WIP.
        parked = entry.get("parked") or {}
        reason = parked.get("reason", "")
        if USER_PAUSE.search(reason):
            continue
        if chat_id in waiting or (not reason and chat_id in set(live) | set(codex)):
            continue
        cases[chat_id] = {"kind": "parked", "reason": reason or "worktree still has unpublished work"}
    for chat_id, entry in refused.items():
        cases[chat_id] = {"kind": "handoff", **entry}
    open_chats = {link.get("id") for task in tasks if task.get("status") not in ("done", "cancelled")
                  if (link := task.get("external_chat")) and link.get("provider") == "claude"}
    for chat_id in open_chats:
        stopped = registry.get(chat_id) or {}
        if stopped.get("state") == "stopped" and chat_id not in waiting and chat_id not in wip_owners:
            cases.setdefault(chat_id, {"kind": "stalled", "reason": "stopped chat still has an open Task"})
    cases.update(active_stalls(now, live, codex, status, registry, protected, tasks))
    for chat_id, delivery in delivery_stalls(directory, now).items():
        previous = cases.get(chat_id, {})
        cases[chat_id] = {**previous, **delivery}
    return {chat: case for chat, case in cases.items()
            if chat not in protected and chat not in handed and waiters.UUID_RE.fullmatch(chat)
            and not (chat not in live and chat not in codex and
                     (registry.get(chat) or {}).get("reason") == "reported done")}



def attempt(chat_id: str, incident: dict, live: dict, codex: dict) -> str:
    prompt = PROMPT
    if incident.get("fresh_context"):
        reason = friendly_reason(incident)
        prompt += f" A prior wake did not move this work forward. The latest check found {reason}."
        prompt += " Check the current Task, wait, and recorded result before retrying any operation."
    if chat_id in codex:
        return codex_chats.type_into(chat_id, prompt, preserve_input=True)
    if chat := live.get(chat_id):
        if not OWNER_WAIT.search(chat.waiting_for or "") and lifecycle.wake(chat, prompt, preserve_input=True):
            return "ok"
        return "The active chat could not accept a safe wake"
    if codex_chats.is_codex_chat(chat_id) and not incident.get("fresh_context"):
        import claude_dispatch

        return claude_dispatch.resume_codex_chat(chat_id, prompt, title=incident.get("title") or "")
    return handoff.resume_on_codex(chat_id, prompt, task_id=incident.get("task") or "")


def friendly_reason(incident: dict) -> str:
    reason = incident.get("reason") or ""
    if incident["kind"] == "unseen_delivery":
        return f"a message about {incident['topic']} that the chat had not read after ten minutes"
    if incident["kind"] == "handoff":
        return "a transfer of unfinished work"
    if incident["kind"] == "waiter":
        return "work that was ready to continue"
    if incident["kind"] == "parked":
        return "unfinished work"
    if reason in {"an installer", "a deployment command", "a running command", "the current turn"}:
        return reason
    if "installer" in reason.casefold():
        return "an installer"
    if "ci " in reason.casefold() or "check" in reason.casefold():
        return "an automated check"
    return "a work step that did not advance"


def display_title(title: str) -> str:
    title = agent_question.scrub(title)
    title = re.sub(r"(?i)\b[0-9a-f]{8}(?:-[0-9a-f-]{4,28})?\b|\bTASK-\d+\b", "", title)
    return " ".join(title.split()).strip(" ·-")[:62] or "A work chat"


def alert_text(incident: dict, mark: dict) -> str:
    title = display_title(incident.get("title") or "")
    reason = friendly_reason(incident)
    result = "got no new step" if mark.get("outcome") == "ok" else "could not reach it safely"
    action = ("Check with the release team before continuing the rollout."
              if incident.get("release") else "Open the chat to continue the work when you can.")
    affected = "The rollout may be delayed." if incident.get("release") else "The chat's work is waiting."
    first = f"{title} is still stalled after two recovery attempts."
    if incident["kind"] == "unseen_delivery":
        first = f"{title} still has an unread message about {incident['topic']}."
    return (first + "\n"
            f"Last step or wait: {reason}. We tried waking it again with fresh context and {result}. "
            f"{affected} {action}")


def daily_list(directory: Path, now: float, cases: dict, protected: set[str], status: dict) -> None:
    """Keep a short daily list on the dev host, independent of Discord pushes."""
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    rows = [f"{display_title(case.get('title') or '')} — {friendly_reason(case)}" for case in cases.values()]
    rows.extend(f"{display_title(entry.get('title') or '')} — needs Marco's answer"
                for entry in status.get("waiting", []) if entry.get("session_id") in protected)
    waiters._write_json(directory / "watchdog-daily-list.json", {"date": day, "items": rows[:12]})


def cycle(directory: Path, now: float, *, dry_run: bool = False, notify: bool = True) -> dict:
    registered = handoff._load(directory / "registered.json")
    status = handoff._load(directory / "status.json")
    config = lifecycle.load_config()
    live = {chat.session_id: chat for chat in lifecycle.live_chats(Path.home() / ".claude", config, waiters={})}
    codex = codex_chats.live()
    protected = protected_chats(directory, registered, live, now)
    tasks = cached_tasks(now)
    if not dry_run:
        task_status = {task["task_id"]: task["status"] for task in tasks if task.get("task_id") and task.get("status")}
        short_ids: dict[str, list[str]] = {}
        for task in tasks:
            if task.get("short_id") and task.get("status"):
                short_ids.setdefault(task["short_id"], []).append(task["status"])
        task_status.update({key: states[0] for key, states in short_ids.items() if len(states) == 1})
        waiters.settle_external_waits(directory, now, task_status, protected)
    cases = problems(directory, now, live, codex, status, protected, tasks)
    if dry_run:
        return cases
    registry = lifecycle.load_registry(directory)
    task_titles = {}
    for task in tasks:
        link = task.get("external_chat") or {}
        if link.get("id"):
            task_titles.setdefault(link["id"], []).append(task)
    marks_path = directory / "watchdog-incidents.json"
    old = handoff._load(marks_path)
    marks = dict(old)
    order = sorted(cases, key=lambda cid: (not cases[cid].get("release"), old.get(cid, {}).get("attempted_at", 0), cid))
    attempted = 0
    for chat_id in order:
        incident = cases[chat_id]
        linked = task_titles.get(chat_id, [])
        if len(linked) == 1:
            incident.setdefault("task", linked[0].get("task_id"))
        if not incident.get("title"):
            native = (codex_chats.load(chat_id) or {}).get("title")
            chat = live.get(chat_id)
            incident["title"] = (native or (chat.title if chat else "") or (registry.get(chat_id) or {}).get("title")
                                 or (linked[0].get("title") if len(linked) == 1 else "") or "A work chat")
        mark = dict(old.get(chat_id) or {})
        if not mark or "attempts" not in mark:
            mark = {"kind": incident["kind"], "since": incident.get("since")}
        if (incident["kind"] == mark.get("kind") == "active_stall"
                and mark.get("since") != incident.get("since")):
            mark = {"kind": incident["kind"], "since": incident.get("since")}
        marks[chat_id] = mark
        grace = WAKE_GRACE if incident.get("release") else ORDINARY_WAKE_GRACE
        last = mark.get("attempted_at")
        if last is not None and now - last < grace:
            incident["outcome"] = "Waiting for a new step"
            continue
        count = mark.get("attempts", 0)
        if count >= MAX_WAKE_ATTEMPTS:
            incident["outcome"] = "Still stalled after two attempts"
            if notify and not mark.get("alerted"):
                mark["alerted"] = chat_usage_watch.send(alert_text(incident, mark), chats=[chat_id])
                waiters._write_json(marks_path, marks)
            continue
        if attempted >= 4:
            incident["outcome"] = "Recovery scheduled for the next check"
            continue
        attempted += 1
        incident["fresh_context"] = bool(count)
        mark.update(attempts=count + 1, attempted_at=now)
        waiters._write_json(marks_path, marks)
        try:
            outcome = attempt(chat_id, incident, live, codex)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            outcome = f"Recovery failed ({type(error).__name__})"
        incident["outcome"] = mark["outcome"] = outcome
        waiters._write_json(marks_path, marks)
    waiters._write_json(marks_path, {chat: marks[chat] for chat in cases})
    daily_list(directory, now, cases, protected, status)
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
        with (directory / "waiter-delivery.lock").open("a") as wake_lock:
            try:
                fcntl.flock(wake_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            report = cycle(directory, time.time(), dry_run=args.dry_run, notify=not args.no_notify)
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
