"""Read Marco's evening reply from the private OpenMates Task activity."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import subprocess
from uuid import UUID

from daily_meeting_accountability import EVENING_TIME, FIRST_EVENING, TZ
from daily_meeting_tasks_cache import TasksError, find_cli

CONFIG = Path.home() / ".config/openmates/daily-meeting-task-id"


def configured_task(*, required: bool = False) -> str:
    try:
        return str(UUID(CONFIG.read_text().strip()))
    except FileNotFoundError:
        if not required:
            return ""
        raise RuntimeError("The private evening check-in Task is not configured") from None
    except ValueError:
        raise RuntimeError("The private evening check-in Task ID is invalid") from None


def previous_evening(today: date) -> datetime:
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, EVENING_TIME, tzinfo=TZ)


def latest_reply(entries: list[dict], start: datetime, now: datetime) -> str:
    """Choose the latest human comment, ignoring events and deleted comments."""
    candidates = [
        entry for entry in entries
        if entry.get("kind") == "comment" and entry.get("actor_type") == "user"
        and not entry.get("deleted_at") and isinstance(entry.get("message"), str)
        and entry["message"].strip() and isinstance(entry.get("created_at"), int)
        and start.timestamp() <= entry["created_at"] <= now.timestamp()
    ]
    latest = max(candidates, key=lambda entry: (entry["created_at"], entry.get("entry_id", "")), default={})
    return latest.get("message", "").strip()[:4000]


def read_reflection(now: datetime, gaps: list[str]) -> dict:
    start = previous_evening(now.astimezone(TZ).date())
    if start.date() < FIRST_EVENING:
        return {}
    result = {"day": start.date().isoformat(), "text": "", "unavailable": False}
    try:
        if not (task_id := configured_task()):
            return {}
        run = subprocess.run([find_cli(), "tasks", "activity", "list", task_id,
                              "--max-entries", "50", "--newest-first", "--json"],
                             capture_output=True, text=True, timeout=30, check=True)
        entries = json.loads(run.stdout)["entries"]
        result["text"] = latest_reply(entries, start, now)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, TasksError, RuntimeError):
        gaps.append("Private evening check-in reply could not be read.")
        result["unavailable"] = True
    return result
