"""Background work a Claude Code chat is still owed, read from its transcript and the CI queue.

Used by scripts/claude_idle_chats.py so a chat that waits on a background job is never
treated as idle, and so a finished job always reaches its chat.

How a result gets lost: when a background command or agent finishes, Claude Code queues
a `<task-notification>` and submits it as the chat's next prompt. On 2026-11-14 the
UserPromptSubmit host-load hook refused three such notifications of chat d2a774d9
(13:20-13:31 UTC, `promptKept: false`, so nothing stayed in the input box). The chat
then sat idle for seven hours with its CI results unread. A refused notification is
"undelivered" until a later prompt carries the same task id; only refusals after the
chat's last reply count (a later reply means the chat moved on).

A chat whose sessions.py session has a CI job in state `running`
(logs/ci-coordinator/queue.sqlite3, column `owner`) is waiting on CI.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

REFUSED_PREFIX = "UserPromptSubmit operation blocked by hook"
NOTIFICATION_RE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
TAG_RE = {name: re.compile(rf"<{name}>(.*?)</{name}>", re.S) for name in ("task-id", "output-file", "status", "summary")}


@dataclass
class Pending:
    """What a transcript says about the chat's background work."""

    undelivered: list[dict] = field(default_factory=list)  # refused notifications, oldest first
    refusal_kept: bool | None = None  # promptKept of the newest refusal (None: no refusal or unknown)
    refusal_at: str = ""  # timestamp of the newest refusal

    @property
    def task_ids(self) -> list[str]:
        return [item["task_id"] for item in self.undelivered]


def _content_text(record: dict) -> str:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else record.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content if isinstance(block, dict)
                         and block.get("type") == "text")
    return ""


def notifications(text: str) -> list[dict]:
    """Each `<task-notification>` in the text as {task_id, output, status, summary}."""
    found = []
    for body in NOTIFICATION_RE.findall(text or ""):
        values = {name: (match.group(1).strip() if (match := regex.search(body)) else "")
                  for name, regex in TAG_RE.items()}
        if values["task-id"]:
            found.append({"task_id": values["task-id"], "output": values["output-file"],
                          "status": values["status"], "summary": " ".join(values["summary"].split())[:160]})
    return found


def scan(records: list[dict]) -> Pending:
    """Refused, never re-delivered notifications after the chat's last reply."""
    refused: dict[str, dict] = {}
    pending = Pending()
    for record in records:
        kind = record.get("type")
        text = _content_text(record)
        if kind == "assistant" and text.strip() and not record.get("isSidechain"):
            refused.clear()  # the chat replied after them: it moved on
        elif kind == "system" and text.startswith(REFUSED_PREFIX):
            ending = (record.get("promptSubmitEnding") or {})
            pending.refusal_kept = ending.get("promptKept") if isinstance(ending.get("promptKept"), bool) else None
            pending.refusal_at = str(record.get("timestamp") or "")
            for item in notifications(text.partition("Original prompt:")[2]):
                refused[item["task_id"]] = {**item, "refused_at": pending.refusal_at}
        elif kind == "user" and not record.get("isMeta"):
            for item in notifications(text):
                refused.pop(item["task_id"], None)  # delivered after all
    pending.undelivered = list(refused.values())
    return pending


def wake_prompt(items: list[dict]) -> str:
    """One line typed into the chat so it reads the results it never got."""
    parts = [f"task {item['task_id']} {item['status'] or 'finished'}"
             + (f" ({item['summary']})" if item["summary"] else "")
             + (f", output {item['output']}" if item["output"] else "") for item in items]
    return ("[chat lifecycle] Background work of this chat finished while the dev host refused its "
            "notifications, so you never saw the results: " + "; ".join(parts)
            + ". Read those output files now and continue your work.")


def session_ids_by_chat(root: Path) -> dict[str, list[str]]:
    """Chat id -> its sessions.py session ids (from .claude/sessions.json)."""
    try:
        data = json.loads((root / ".claude" / "sessions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    mapping: dict[str, list[str]] = {}
    for key, info in (data.get("sessions") or {}).items():
        if isinstance(info, dict) and info.get("agent_task_id"):
            mapping.setdefault(str(info["agent_task_id"]), []).append(str(key))
    return mapping


def running_ci_jobs(root: Path) -> dict[str, list[str]]:
    """sessions.py session id -> ids of its CI jobs that still run (read-only)."""
    path = root / "logs" / "ci-coordinator" / "queue.sqlite3"
    if not path.exists():
        return {}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
            rows = conn.execute("SELECT owner, id, mode FROM jobs WHERE state = 'running'").fetchall()
    except sqlite3.Error as error:
        raise RuntimeError(f"CI queue unreadable: {error}") from error
    jobs: dict[str, list[str]] = {}
    for owner, job_id, mode in rows:
        jobs.setdefault(str(owner), []).append(f"{mode} {str(job_id)[:8]}")
    return jobs


def ci_jobs_for(chat_id: str, sessions: dict[str, list[str]], jobs: dict[str, list[str]]) -> list[str]:
    return [job for session in sessions.get(chat_id, []) for job in jobs.get(session, [])]
