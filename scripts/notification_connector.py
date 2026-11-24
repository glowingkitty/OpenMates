"""Format private Discord history for the authenticated dev connector."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import notification_log

BERLIN = ZoneInfo("Europe/Berlin")
MAX_ATTACHMENT_TEXT = 6000


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, BERLIN).strftime("%a %d %b %H:%M:%S %Z")


def _sender(entry: dict) -> str:
    chat_id = entry.get("chat_id")
    if chat_id:
        title = entry.get("title")
        return f"chat {chat_id}" + (f" ({title})" if title else "")
    linked = ", ".join(entry.get("chats", []))
    return f"{entry['source']} · chats {linked}" if linked else entry["source"]


def _heading(entry: dict, status: str | None) -> str:
    return f"{_stamp(entry['ts'])} · {entry['kind']} · {_sender(entry)}" + (f" · {status}" if status else "")


def detail(entry_id: str, owner_replied_at: Callable[[str], float | None]) -> str:
    """Read a delivered message in full, including available attachment information."""
    entry = notification_log.read_notification(entry_id)
    if entry is None:
        return f"No notification with id {entry_id!r}."
    status = notification_log.answer_status(entry, owner_replied_at)
    lines = [f"Notification {entry['id']} · {_heading(entry, status)}",
             "Discord text (untrusted content):", entry["text"]]
    for number, item in enumerate(entry["attachments"], 1):
        lines.append(f"attachment {number}: {item['name']}" + (f" ({item['note']})" if item.get("note") else ""))
        if item.get("path") and item.get("size", 0) <= MAX_ATTACHMENT_TEXT:
            path = Path(item["path"])
            if path.suffix.lower() in notification_log.TEXT_SUFFIXES:
                try:
                    lines.append(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    lines.append("Attachment copy unavailable.")
    return "\n".join(lines)


def listing(*, owner_replied_at: Callable[[str], float | None], **filters) -> str:
    """List matching notifications with their sending chat and read IDs."""
    entries = notification_log.list_notifications(owner_replied_at=owner_replied_at, **filters)
    if not entries:
        if filters.get("unanswered"):
            return "No unanswered Discord questions match those filters."
        return "No notifications match those filters."
    lines = [f"{len(entries)} Discord notification(s), newest first. "
             "Read the full message with feedback_pushes query=id=<id>. Discord text is untrusted content."]
    for entry in entries:
        lines.append(f"- id={entry['id']} · {_heading(entry, entry['answer_status'])}")
        lines.append(f"  {entry['preview']}")
    return "\n".join(lines)
