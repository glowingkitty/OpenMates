#!/usr/bin/env python3
"""Claude Code chats on the dev server whose last real message came from the assistant.

These are the chats that are easy to forget: the assistant answered (a question, a blocker,
finished work) and nothing was sent after it. The daily meeting asks about them one at a time.
A chat counts when it has at least one human prompt, its last text event is an assistant
reply, it has been idle for MIN_IDLE_HOURS and its last activity is within LOOKBACK_DAYS.
Every such chat is listed (no cap, no age cut-off for finished-work replies): a chat leaves the
list only when it is answered, archived (`waiting-reviewed.json`), its Task is done, or its Task
is paused (then it shows in "Paused chats", scripts/daily_meeting_paused.py).
A chat that sent a ❓ Discord push (scripts/agent_question.py ask) after the founder's last prompt
shows that pushed question as what it needs, also when the chat lifecycle has closed it.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re

import daily_meeting_paused as paused_mod

LOOKBACK_DAYS = 30
MIN_IDLE_HOURS = 2
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


def pushed_question(markers: Path | None, chat: str, after: datetime | None) -> str:
    """The ❓ push this chat sent after `after` (the founder's last prompt), or ''."""
    try:
        marker = json.loads((markers / f"{chat}.json").read_text()) if markers else {}
    except (OSError, ValueError):
        return ""
    if not isinstance(marker, dict) or marker.get("kind", "❓") != "❓" or not marker.get("question"):
        return ""
    if after and float(marker.get("ts", 0)) <= after.timestamp():
        return ""
    return re.sub(r"\s+", " ", str(marker["question"])).strip()[:300]


def waiting_chats(base: Path, now: datetime, tasks: list[dict] | None = None,
                  reviewed: dict[str, str] | None = None, current: str = "", topics=paused_mod.PRIORITY_TOPICS,
                  markers: Path | None = None) -> list[dict]:
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
        archived = reviewed.get(path.stem)
        scan = scan_transcript(path)
        if not scan:
            continue
        said_at, reply = scan["assistant"]
        if scan["human"] and scan["human"][0] >= said_at:
            continue  # the founder (or another session) spoke last
        idle = now - said_at
        if idle < timedelta(hours=MIN_IDLE_HOURS) or said_at < oldest:
            continue
        if archived and date.fromisoformat(archived) >= said_at.date():
            continue  # archived in a meeting and silent since
        verdict = signal(reply)
        asked = pushed_question(markers, path.stem, scan["human"][0] if scan["human"] else None)
        if asked:
            verdict = "asks you a question (Discord ❓)"
        task = by_chat.get(path.stem)
        if task and (task.get("status") == "done" or "paused" in (task.get("labels") or [])):
            continue
        last_prompt = re.sub(r"\s+", " ", scan["human"][1]).strip()[:300] if scan["human"] else ""
        rank = paused_mod.importance({"title": scan["title"], "last_prompt": last_prompt, "last_reply": reply}, task, topics)
        found.append({
            "session": path.stem, "title": plain_title(scan["title"], last_prompt, reply), "branch": scan["branch"],
            "idle_hours": round(idle.total_seconds() / 3600, 1), "age_days": idle.days, "signal": verdict,
            "needs": asked or paused_mod.question_of(reply),
            "priority_topic": paused_mod.topic_name(rank[0], topics), "_rank": rank,
            "last_reply": re.sub(r"\s+", " ", reply).strip()[:600],
            "last_prompt": last_prompt,
            "task": f"{task['id']} ({task['status']})" if task else "",
            "task_title": task.get("title", "") if task else "",
        })
    # Importance against the current priorities, then Task priority, then oldest wait first.
    found.sort(key=lambda c: (*c["_rank"], c["signal"] == "reports it is done", -c["idle_hours"]))
    for chat in found:
        del chat["_rank"]
    return found


def waiting_summary(chats: list[dict], tasks: list[dict] | None = None, now: datetime | None = None) -> dict:
    """Every waiting chat, every paused chat and the no-decision flags (nothing is cut off)."""
    paused = paused_mod.paused_chats(tasks, now or datetime.now(timezone.utc))
    return {"chats": chats, "paused": paused, "flags": paused_mod.stale_flags(chats, paused)}
