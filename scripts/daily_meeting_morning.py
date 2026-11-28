"""Build the weekday accountability section from the existing meeting evidence."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import re

from daily_meeting_accountability import TZ, audit_path, submitted_decisions
from daily_meeting_context import clean
from daily_meeting_reflection import read_reflection


def _task_day(task: dict) -> str:
    stamp = task.get("updated_at")
    return datetime.fromtimestamp(stamp, TZ).date().isoformat() if stamp else ""


def collect(root: Path, out: Path, evidence: dict, now: datetime) -> dict:
    today = now.astimezone(TZ).date()
    yesterday = today - timedelta(days=1)
    day = yesterday.isoformat()
    commits = evidence.get("git", {}).get("commits_on_dev", [])
    chats = evidence.get("claude_chats", [])
    tasks = evidence.get("tasks", {})
    focus = evidence.get("focus_file", "")
    standing = re.search(r"(?ms)^## Current priorities\s*$\n(.*?)(?=^## |\Z)", focus)
    priorities = re.findall(r"(?m)^-\s+([^:\n]+):", standing[1]) if standing else []
    note = submitted_decisions(out, audit_path(root), yesterday)
    prior_focus = re.search(r"(?im)^Focus:[ \t]*(.+)$", note)
    completed = [t for t in tasks.get("done_since_last_meeting", []) if _task_day(t) == day]
    focus_tasks = re.search(r"(?im)^Focus tasks:[ \t]*\n((?:\d+\..*\n?)+)", note)
    commitments = re.findall(r"(?m)^\d+\.\s+(.+)$", focus_tasks[1]) if focus_tasks else []
    return {
        "day": day,
        "weekday": yesterday.weekday(),
        "meeting_held": bool(note),
        "chats": [c.get("title") or (c.get("user_prompts") or [""])[0]
                  for c in reversed(chats) if day in c.get("active_days", [])][:4],
        "commits": [c["subject"] for c in commits if c.get("day") == day][:4],
        "done": [t["title"] for t in completed][:4],
        "commitments": commitments[:3],
        "unnamed_done": [t["title"] for t in completed if t["title"].casefold() not in note.casefold()][:3],
        "prior_focus": prior_focus[1].strip() if prior_focus else "",
        "priorities": priorities[:3],
        "reflection": read_reflection(now, evidence.setdefault("gaps", [])),
    }


def _line(text: str, limit: int = 170) -> str:
    return clean(" ".join(text.split()).replace("`", "'"), limit)


def render(data: dict) -> list[str]:
    if not data:
        return []
    out = ["", "## Morning check-in", "", f"**Yesterday’s progress ({data['day']})**"]
    for label, key in (("Chats", "chats"), ("Dev commits", "commits"), ("Tasks marked done", "done")):
        items = [item for item in data[key] if item]
        out.append(f"- {label}: " + (", ".join(_line(item, 105) for item in items) or "none recorded"))
    out += ["", "**What yesterday’s meeting missed**"]
    if not data["meeting_held"]:
        out.append("No decisions were submitted yesterday."
                   if data["weekday"] < 5 else "Yesterday was outside the weekday meeting schedule.")
    elif data["commitments"]:
        out.append("Check these commitments against the progress above. Carry forward what is still open.")
        out += [f"- {_line(item)}" for item in data["commitments"]]
    else:
        out.append("The decisions note contains no numbered focus tasks to check against the progress.")
    if data["meeting_held"] and data["unnamed_done"]:
        out.append("Finished Tasks absent by title from the decisions: "
                   + ", ".join(_line(title, 105) for title in data["unnamed_done"]) + ".")
    out += ["", "**Today’s priorities**"]
    if data["prior_focus"]:
        out.append(f"- Review yesterday’s focus: {_line(data['prior_focus'])}")
    out += [f"- {_line(priority)}" for priority in data["priorities"]]
    if not data["priorities"]:
        out.append("- Choose one OpenMates outcome you can finish or verify today.")
    reply = data["reflection"]
    if reply:
        out += ["", f"**Evening reflection from {reply['day']}**"]
        if reply["text"]:
            out += ["", "```", reply["text"].replace("```", "'''"), "```"]
        else:
            out.append("The private reply was unavailable." if reply["unavailable"] else "No reply was recorded.")
    out += ["", "**Mood check:** How are you feeling this morning, in one word?"]
    priority = _line(data["priorities"][0], 70) if data["priorities"] else "your current milestone"
    if data["weekday"] < 5 and not data["meeting_held"]:
        coach = f"Open the day by making one decision about {priority}. Give it a finish line the agents can work toward."
    elif data["commitments"]:
        coach = f"Pick one carryover that advances {priority}. Make it the first thing you can verify in OpenMates today."
    else:
        coach = f"Give {priority} your first OpenMates work block. Pick an outcome you can verify before checking the agent queue."
    out += ["", f"**Founder’s nudge:** {coach}", ""]
    return out
