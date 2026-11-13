#!/usr/bin/env python3
"""Claude Code chats on the dev server whose last real message came from the assistant.

These are the chats that are easy to forget: the assistant answered (a question, a blocker,
finished work) and nothing was sent after it. The daily meeting asks about them one at a time.
A chat counts when it has at least one human prompt, its last text event is an assistant
reply, it has been idle for MIN_IDLE_HOURS and its last activity is within LOOKBACK_DAYS.
Chats dismissed in a meeting (`waiting-reviewed.json`) are skipped for REVIEW_PAUSE_DAYS.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re

LOOKBACK_DAYS = 5
MIN_IDLE_HOURS = 2
REVIEW_PAUSE_DAYS = 14
MAX_LISTED = 12
DONE_RELEVANT_HOURS = 36  # finished-work replies older than this are not a forgotten chat
BLOCKED = re.compile(r"\b(blocked|cannot|can't|unable|failed|failing|need your|waiting for|your call|decide)\b", re.I)


def _texts(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def plain_title(title: str, prompt: str, reply: str) -> str:
    """A title the founder can recognise: the chat title, else the last prompt or reply in words.

    Claude Code stores no title for many chats, and some titles are slugs or ids; the briefing
    must never show a bare id or "untitled" (plain-language rule of the daily meeting).
    """
    title = (title or "").strip()
    slug = bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)+", title)) or bool(re.fullmatch(r"[0-9a-f-]{8,}", title))
    if title and title.lower() != "untitled" and not slug:
        return title[:120]
    for source in (prompt, reply):
        text = re.sub(r"[`*#>]+", "", re.sub(r"\s+", " ", source or "")).strip()
        if len(text) > 12:
            return (text[:80].rsplit(" ", 1)[0] if len(text) > 80 else text) + ("…" if len(text) > 80 else "")
    return "chat without a title" if slug or title.lower() == "untitled" or not title else title[:120]


def signal(reply: str) -> str:
    tail = reply[-500:]
    if "?" in tail:
        return "asks you a question"
    if BLOCKED.search(tail):
        return "blocked or needs a decision"
    return "reports it is done"


def scan_transcript(path: Path) -> dict | None:
    """Last human prompt, last assistant text and title of one transcript (None if unusable)."""
    human = assistant = None  # (timestamp, text)
    title, branch, prompts = "", "", 0
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        kind = row.get("type")
        if kind in ("summary", "ai-title", "custom-title"):
            title = row.get("summary") or row.get("title") or row.get("aiTitle") or title
        if row.get("isSidechain") or kind not in ("user", "assistant"):
            continue
        stamp = _ts(row.get("timestamp"))
        text = _texts((row.get("message") or {}).get("content")).strip()
        if stamp is None or not text:
            continue
        branch = row.get("gitBranch") or branch
        origin = row.get("turnOrigin", (row.get("origin") or {}).get("kind"))
        if kind == "user" and origin in ("human", "peer") and not text.lstrip().startswith("<"):
            human = (stamp, text)
            prompts += origin == "human"
        elif kind == "assistant":
            assistant = (stamp, text)
    if not prompts or assistant is None:
        return None
    return {"human": human, "assistant": assistant, "title": title, "branch": branch}


def waiting_chats(base: Path, now: datetime, tasks: list[dict] | None = None,
                  reviewed: dict[str, str] | None = None, current: str = "") -> list[dict]:
    """Chats waiting on the founder, longest-waiting first, with their Task if one is linked."""
    reviewed, found = reviewed or {}, []
    by_chat = {t["chat"].split(":", 1)[1]: t for t in tasks or [] if str(t.get("chat", "")).startswith("claude:")}
    oldest = now - timedelta(days=LOOKBACK_DAYS)
    for path in base.glob("*/*.jsonl"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < oldest or path.stem == current:
                continue
        except OSError:
            continue
        paused = reviewed.get(path.stem)
        if paused and date.fromisoformat(paused) > (now - timedelta(days=REVIEW_PAUSE_DAYS)).date():
            continue
        scan = scan_transcript(path)
        if not scan:
            continue
        said_at, reply = scan["assistant"]
        if scan["human"] and scan["human"][0] >= said_at:
            continue  # the founder (or another session) spoke last
        idle = now - said_at
        if idle < timedelta(hours=MIN_IDLE_HOURS) or said_at < oldest:
            continue
        verdict = signal(reply)
        if verdict == "reports it is done" and idle > timedelta(hours=DONE_RELEVANT_HOURS):
            continue
        task = by_chat.get(path.stem)
        if task and task.get("status") == "done":
            continue
        last_prompt = re.sub(r"\s+", " ", scan["human"][1]).strip()[:300] if scan["human"] else ""
        found.append({
            "session": path.stem, "title": plain_title(scan["title"], last_prompt, reply), "branch": scan["branch"],
            "idle_hours": round(idle.total_seconds() / 3600, 1), "signal": verdict,
            "last_reply": re.sub(r"\s+", " ", reply).strip()[:600],
            "last_prompt": last_prompt,
            "task": f"{task['id']} ({task['status']})" if task else "",
            "task_title": task.get("title", "") if task else "",
        })
    # Questions and blockers first, then finished work; newest first within each group.
    found.sort(key=lambda c: (c["signal"] == "reports it is done", c["idle_hours"]))
    return found


def waiting_summary(chats: list[dict]) -> dict:
    return {"chats": chats[:MAX_LISTED], "omitted": max(len(chats) - MAX_LISTED, 0)}
