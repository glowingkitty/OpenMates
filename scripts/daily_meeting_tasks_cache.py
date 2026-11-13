#!/usr/bin/env python3
"""Private, timestamped copy of the OpenMates Tasks for the daily meeting.

`openmates tasks list --json` is the source. A cron job refreshes the copy hourly, the
briefing refreshes it right before building, and when the live read fails the older copy
is used together with its age so the meeting can say that Tasks may be out of date.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

CACHE = Path.home() / ".local/state/openmates/tasks-cache.json"
EXTRA_PATH = [str(Path.home() / ".npm-global/bin"), "/usr/local/bin", "/usr/bin", "/bin"]
STALE_AFTER_HOURS = 3.0


class TasksError(RuntimeError):
    pass


def find_cli() -> str:
    """Cron runs with a minimal PATH, so the npm-global install dir is searched explicitly."""
    path = os.pathsep.join([os.environ.get("PATH", ""), *EXTRA_PATH])
    found = shutil.which("openmates", path=path)
    if not found:
        raise TasksError("openmates CLI not found on PATH or in ~/.npm-global/bin")
    return found


def fetch() -> dict:
    try:
        run = subprocess.run([find_cli(), "tasks", "list", "--json"], capture_output=True, text=True,
                             timeout=180, check=True)
        data = json.loads(run.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise TasksError(f"{type(error).__name__}: {str(error)[-200:]}") from error
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise TasksError("unexpected tasks list output")
    return data


def sync(cache: Path = CACHE) -> dict:
    data = fetch()
    cache.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": data}
    temp = cache.with_suffix(".tmp")
    temp.write_text(json.dumps(payload))
    temp.chmod(0o600)
    temp.replace(cache)
    return {"fetched_at": payload["fetched_at"], "tasks": len(data["tasks"])}


def age_hours(fetched_at: str, now: datetime | None = None) -> float:
    return ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(fetched_at)).total_seconds() / 3600


def load(cache: Path = CACHE) -> tuple[dict | None, dict]:
    """(tasks data or None, status). Status: source live|cache|none, fetched_at, age_hours,
    fresh, error. Tries a live read first and refreshes the copy; falls back to the copy."""
    error = ""
    try:
        sync(cache)
    except (TasksError, OSError) as failure:
        error = str(failure)
    if cache.exists():
        stored = json.loads(cache.read_text())
        hours = round(age_hours(stored["fetched_at"]), 1)
        live = not error
        return stored["data"], {"source": "live" if live else "cache", "fetched_at": stored["fetched_at"],
                                "age_hours": hours, "fresh": live or hours < STALE_AFTER_HOURS, "error": error}
    return None, {"source": "none", "fetched_at": "", "age_hours": None, "fresh": False, "error": error}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the private OpenMates Tasks copy (cron: hourly).")
    parser.add_argument("command", choices=["sync"])
    parser.parse_args()
    try:
        print(json.dumps(sync()))
    except (TasksError, OSError) as error:
        print(f"tasks sync failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
