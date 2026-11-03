#!/usr/bin/env python3
"""Read and arrange the user's Apple Reminders from the dev server for the daily meeting.

Transport: `apple_remote.py reminders-op` (Tailscale SSH) runs the fixed EventKit
helper `_apple_reminders_remote.py` on the Mac. Reads cover the OpenMates and
Personal Tasks lists; writes are limited to those lists and never delete
(finishing a reminder = complete). Apply changes only after the user approved them.

  overview                      bucketed snapshot for the meeting (JSON)
  create --list L --title T [--due D] [--notes N]
  complete|set-due|update|move  single changes by reminder id
  batch --file changes.json     [{"action": "set-due", "id": ..., "due": ...}, ...]

Dates: YYYY-MM-DD (all-day) or an ISO timestamp with offset.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent
LISTS = ("OpenMates", "Personal Tasks")
TZ = ZoneInfo("Europe/Berlin")


class RemindersError(RuntimeError):
    """The Mac could not be reached or rejected the request."""


def remote(request: dict, timeout: int = 180) -> object:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(request, handle)
        path = handle.name
    try:
        run = subprocess.run([sys.executable, str(SCRIPTS / "apple_remote.py"), "reminders-op",
                              "--request", path], capture_output=True, text=True, timeout=timeout)
    finally:
        Path(path).unlink()
    lines = [line for line in run.stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise RemindersError(f"Mac unreachable or no answer (exit {run.returncode}): "
                             f"{(run.stderr or run.stdout).strip()[-400:]}")
    reply = json.loads(lines[-1])
    if not reply.get("ok"):
        raise RemindersError(f"{reply.get('error')}: {reply.get('detail', '')}".strip(": "))
    return reply["result"]


def due_date(item: dict) -> date | None:
    due = item.get("due")
    if not due:
        return None
    if len(due) == 10:
        return date.fromisoformat(due)
    return datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(TZ).date()


def _brief(item: dict) -> dict:
    row = {"id": item["id"], "title": item["title"], "list": item["list"], "due": item.get("due")}
    if item.get("notes"):
        row["notes"] = item["notes"][:200]
    if item.get("priority"):
        row["priority"] = item["priority"]
    return row


def overview(items: list[dict], today: date, ahead_days: int = 7, recent_days: int = 7,
             sample: int = 15) -> dict:
    """Buckets for the meeting; old backlog is summarized, not listed in full."""
    buckets: dict[str, list[dict]] = {"overdue_recent": [], "due_next_days": [], "undated": [],
                                      "overdue_old": [], "later": []}
    for item in items:
        due = due_date(item)
        if due is None:
            key = "undated"
        elif due < today - timedelta(days=recent_days):
            key = "overdue_old"
        elif due < today:
            key = "overdue_recent"
        elif due <= today + timedelta(days=ahead_days):
            key = "due_next_days"
        else:
            key = "later"
        buckets[key].append(item)
    for key in buckets:
        buckets[key].sort(key=lambda item: (due_date(item) or date.max, item["title"]))
    old = buckets["overdue_old"]
    return {
        "today": today.isoformat(),
        "open_total": len(items),
        "counts": {key: dict(Counter(item["list"] for item in rows)) for key, rows in buckets.items()},
        "overdue_recent": [_brief(i) for i in buckets["overdue_recent"]],
        "due_next_days": [_brief(i) for i in buckets["due_next_days"]],
        "undated": [_brief(i) for i in buckets["undated"]],
        "later_sample": [_brief(i) for i in buckets["later"][:sample]],
        "overdue_old_by_month": dict(sorted(Counter(due_date(i).strftime("%Y-%m") for i in old).items())),
        "overdue_old_newest_sample": [_brief(i) for i in old[-sample:]],
        "note": "overdue_old is a long backlog: propose bulk triage (complete, push out, or keep a few), "
                "never a one-by-one review. `items` for any bucket: mac_reminders.py list --bucket <name>.",
    }


def fetch(lists: tuple[str, ...] = LISTS) -> list[dict]:
    result = remote({"action": "list", "lists": list(lists)})
    if not isinstance(result, list):
        raise RemindersError("unexpected list result")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    view = sub.add_parser("overview")
    view.add_argument("--ahead-days", type=int, default=7)
    view.add_argument("--recent-days", type=int, default=7)
    listing = sub.add_parser("list", help="every open reminder, optionally one overview bucket")
    listing.add_argument("--bucket", choices=("overdue_recent", "due_next_days", "undated",
                                               "overdue_old", "later"))
    create = sub.add_parser("create")
    create.add_argument("--list", required=True, choices=LISTS)
    create.add_argument("--title", required=True)
    create.add_argument("--due")
    create.add_argument("--notes")
    for name in ("complete", "set-due", "update", "move"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--id", required=True)
        if name == "set-due":
            cmd.add_argument("--due", default="", help="empty clears the due date")
        if name == "update":
            cmd.add_argument("--title")
            cmd.add_argument("--notes")
        if name == "move":
            cmd.add_argument("--list", required=True, choices=LISTS)
    batch = sub.add_parser("batch")
    batch.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)

    today = datetime.now(timezone.utc).astimezone(TZ).date()
    if args.command == "overview":
        result: object = overview(fetch(), today, args.ahead_days, args.recent_days)
    elif args.command == "list":
        items = fetch()
        if args.bucket:
            full = overview(items, today, sample=10**6)
            wanted = {"later": "later_sample", "overdue_old": "overdue_old_newest_sample"}.get(
                args.bucket, args.bucket)
            result = full[wanted]
        else:
            result = [_brief(i) for i in items]
    elif args.command == "batch":
        ops = json.loads(args.file.read_text())
        if not isinstance(ops, list):
            raise SystemExit("batch file must hold a JSON list of changes")
        result = remote({"action": "batch", "ops": ops})
    else:
        request = {key.replace("_", "-") if key == "command" else key: value
                   for key, value in vars(args).items() if value is not None}
        request["action"] = request.pop("command")
        result = remote(request)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
