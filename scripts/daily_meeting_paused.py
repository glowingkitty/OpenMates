#!/usr/bin/env python3
"""Paused chats, importance ranking and the "no decision for 7 days" check of the daily meeting.

Pause convention (documented in docs/contributing/guides/daily-meeting.md): a chat that stops
before its work is finished (usage limit, waiting for a date, parked in the meeting) writes into
its OpenMates Task, in one `tasks edit` call, the label `paused` and a description block

    PAUSED <since YYYY-MM-DD> until <resume YYYY-MM-DD> [HH:MM] — <reason>
    Done: ...
    Not done: ...
    Next step: ...
    Open decisions: ...

The block is the saved state: the resuming chat needs nothing else. Removing the label resumes
the Task. Used by scripts/daily_meeting_waiting.py and scripts/daily_meeting_briefing.py.
"""

from __future__ import annotations

from datetime import date, datetime
import re

STALE_DAYS = 7
PAUSE_FIELDS = ("Done", "Not done", "Next step", "Open decisions")
_HEAD = re.compile(r"^PAUSED\s+(\d{4}-\d{2}-\d{2})\s+until\s+(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?\s*(?:[—–-]+\s*(.*))?$",
                   re.M)
_FIELD = re.compile(r"^(Done|Not done|Next step|Open decisions):[ \t]*", re.M)

# Current priorities, most important first (FOCUS.md "Current priorities"); keep in sync with it.
PRIORITY_TOPICS = (
    ("marketing", re.compile(r"\b(marketing|seo|landing|newsletter|launch|social|campaign|blog|growth)\b", re.I)),
    ("agentic coding", re.compile(r"\b(agentic|agent(s)?\b|claude code|sub-?agent|coding agent|dev server|worktree|ci\b)", re.I)),
    ("Projects", re.compile(r"\bprojects?\b", re.I)),
    ("safety", re.compile(r"\b(safety|moderation|wellbeing|abuse|appeal|suspension)\b", re.I)),
)
TASK_PRIORITY = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


def parse_pause(description: str | None) -> dict:
    """The saved pause state of a Task description; {} when it has no PAUSED block."""
    text = description or ""
    head = _HEAD.search(text)
    if not head:
        return {}
    since, resume, at, reason = head.groups()
    state = {"since": since, "resume": resume, "resume_at": at or "", "reason": (reason or "").strip()}
    body = text[head.end():]
    marks = list(_FIELD.finditer(body))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        state[mark.group(1)] = re.sub(r"\s+", " ", body[mark.end():end]).strip()
    return state


def _days(since: str, today: date) -> int:
    return (today - date.fromisoformat(since)).days


def paused_chats(tasks: list[dict] | None, now: datetime) -> list[dict]:
    """Every not-done Task labelled `paused`, soonest resume date first, with its saved state."""
    today, found = now.date(), []
    for task in tasks or []:
        if "paused" not in (task.get("labels") or []) or task.get("status") == "done":
            continue
        state = task.get("pause") or {}
        missing = [name for name in PAUSE_FIELDS if not state.get(name)]
        if not state:
            missing = ["PAUSED block"]
        row = {"task": task.get("id", ""), "title": task.get("title", ""), "chat": task.get("chat", ""),
               "since": state.get("since", ""), "resume": state.get("resume", ""),
               "resume_at": state.get("resume_at", ""), "reason": state.get("reason", ""),
               "missing": missing, **{name: state.get(name, "") for name in PAUSE_FIELDS}}
        resume_passed = bool(row["resume"]) and date.fromisoformat(row["resume"]) <= today
        age = _days(row["since"], today) if row["since"] else None
        row["resume_due"] = resume_passed
        if resume_passed:
            row["flag"] = f"resume date {row['resume']} has passed with no decision: resume, reschedule or archive"
        elif not row["resume"]:
            row["flag"] = "no resume date: set one or archive"
        elif age is not None and age > STALE_DAYS and missing:
            row["flag"] = f"paused {age} days and its saved state is incomplete ({', '.join(missing)})"
        found.append(row)
    found.sort(key=lambda r: (r["resume"] or "9999", r["title"]))
    return found


def importance(chat: dict, task: dict | None = None) -> tuple[int, int]:
    """(current-priority rank, Task priority rank); lower is more important."""
    text = " ".join(str(v) for v in (chat.get("title"), chat.get("last_prompt"), chat.get("last_reply"),
                                      (task or {}).get("title"), " ".join((task or {}).get("labels") or [])))
    topic = next((i for i, (_, rx) in enumerate(PRIORITY_TOPICS) if rx.search(text)), len(PRIORITY_TOPICS))
    return topic, TASK_PRIORITY.get((task or {}).get("priority"), 4)


def topic_name(rank: int) -> str:
    return PRIORITY_TOPICS[rank][0] if rank < len(PRIORITY_TOPICS) else ""


def question_of(reply: str) -> str:
    """Fallback for "what it needs": the last question in the reply, else its last sentence."""
    text = re.sub(r"[`*#>]+", "", re.sub(r"\s+", " ", reply or "")).strip()
    sentences = re.split(r"(?<=[.?!])\s+", text)
    asked = [s for s in sentences if s.endswith("?")]
    return (asked or sentences or [""])[-1][:200]


def stale_flags(waiting: list[dict], paused: list[dict]) -> list[str]:
    """One line per waiting or paused chat that has gone more than STALE_DAYS without a decision."""
    flags = [f"{chat['title']} has waited {chat['age_days']} days with no decision (answer, park, reschedule or archive)"
             for chat in waiting if chat.get("age_days", 0) > STALE_DAYS]
    flags += [f"{row['title']}: {row['flag']}" for row in paused if row.get("flag")]
    return flags
