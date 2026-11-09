#!/usr/bin/env python3
"""Goals, milestones and agreed meeting adjustments for the daily meeting briefing.

`GOALS.md` (private, gitignored, canonical checkout only) holds mission, goals and milestones.
OpenMates Tasks that serve a milestone carry the label `milestone:<name>`; this module turns
those labels into progress evidence and drift warnings. The Monday meeting has a goals block;
other days only check which milestone the day's top task serves.
Meeting adjustments agreed in the closing "improve the meeting" block live in the private
`logs/daily-meetings/meeting-settings.md`, with a dated log in `meeting-changelog.md`.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import re

REVIEW_LINE = re.compile(r"^\s*Last weekly review:\s*(\d{4}-\d{2}-\d{2})", re.M)
LABEL_PREFIX = "milestone:"
OPEN_STATUSES = ("todo", "in_progress", "blocked", "backlog")
OVERDUE_DAYS = 8
MAX_TEXT = 9000


def read_private(path: Path, limit: int = MAX_TEXT) -> str:
    return path.read_text()[:limit] if path.exists() else ""


def last_review(text: str) -> date | None:
    found = REVIEW_LINE.search(text)
    return date.fromisoformat(found.group(1)) if found else None


def milestone_labels(task: dict) -> list[str]:
    return [label[len(LABEL_PREFIX):] for label in task.get("labels") or [] if label.startswith(LABEL_PREFIX)]


def week_old_snapshot(out: Path, today: date) -> list[dict] | None:
    """The newest saved Task snapshot that is at least 6 days old, for week-on-week movement."""
    limit = (today - timedelta(days=6)).isoformat()
    older = sorted(p for p in out.glob("????-??-??-tasks.json") if p.name[:10] <= limit)
    return json.loads(older[-1].read_text()) if older else None


def milestone_progress(tasks: list[dict] | None, old: list[dict] | None) -> dict:
    """Per-milestone Task counts, movement since the old snapshot, and high-priority Tasks on no milestone."""
    if tasks is None:
        return {}
    before = {t["id"]: t["status"] for t in old or []}
    names: dict[str, dict] = {}
    for task in tasks:
        for name in milestone_labels(task):
            row = names.setdefault(name, {"statuses": Counter(), "moved_this_week": 0, "open_high": 0})
            row["statuses"][task["status"]] += 1
            if old is not None and before.get(task["id"]) != task["status"]:
                row["moved_this_week"] += 1
            if task["status"] in OPEN_STATUSES and task.get("priority") in ("high", "urgent"):
                row["open_high"] += 1
    unlabeled = [t["title"] for t in tasks if t["status"] in ("todo", "in_progress", "blocked")
                 and t.get("priority") in ("high", "urgent") and not milestone_labels(t)]
    return {"milestones": {n: {**r, "statuses": dict(r["statuses"])} for n, r in sorted(names.items())},
            "high_open_without_milestone": {"count": len(unlabeled), "examples": unlabeled[:6]},
            "baseline": "snapshot about a week ago" if old is not None else "none (no week-old snapshot yet)"}


def drift_warnings(progress: dict, goals_text: str, today: date) -> list[str]:
    warnings = []
    if not goals_text:
        warnings.append("GOALS.md does not exist yet: the first goals block is a workshop (draft the mission, "
                        "at most 3 goals and the next milestone together).")
    reviewed = last_review(goals_text)
    if goals_text and reviewed is None:
        warnings.append("GOALS.md has no 'Last weekly review: YYYY-MM-DD' line: add it after the next review.")
    elif reviewed and (today - reviewed).days > OVERDUE_DAYS:
        warnings.append(f"The weekly goals review is overdue: last one {reviewed.isoformat()}.")
    for name, row in (progress.get("milestones") or {}).items():
        if progress.get("baseline", "").startswith("snapshot") and not row["moved_this_week"] and row["open_high"]:
            warnings.append(f"Milestone '{name}': {row['open_high']} high-priority Tasks open and none moved this week.")
    missing = (progress.get("high_open_without_milestone") or {}).get("count", 0)
    if progress and missing:
        warnings.append(f"{missing} open high-priority Tasks serve no milestone: label them `milestone:<name>` "
                        "or question why they are high priority.")
    return warnings


def collect(root: Path, out: Path, tasks: list[dict] | None, today: date) -> dict:
    text = read_private(root / "GOALS.md")
    reviewed = last_review(text)
    progress = milestone_progress(tasks, week_old_snapshot(out, today))
    settings = read_private(out / "meeting-settings.md", 3000)
    log_lines = read_private(out / "meeting-changelog.md", 4000).strip().splitlines()[-8:]
    return {
        "goals_file": text, "exists": bool(text), "last_review": reviewed.isoformat() if reviewed else "",
        "is_monday": today.weekday() == 0, "progress": progress,
        "warnings": drift_warnings(progress, text, today),
        "meeting_settings": settings.strip(), "meeting_changelog": log_lines,
    }
