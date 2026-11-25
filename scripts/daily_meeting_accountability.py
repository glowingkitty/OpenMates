#!/usr/bin/env python3
"""Send the dev-host daily meeting briefing, reminders and evening check-in."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
import fcntl
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
FIRST_EVENING = date(2026, 11, 23)
FIRST_MORNING = date(2026, 11, 24)
BRIEFING_TIME = time(8, 30)
EVENING_TIME = time(22)
REMINDERS = (
    "Marco, it’s 11:00. Hold the OpenMates meeting and submit today’s decisions.",
    "The daily meeting is overdue. Make the decisions and send them in.",
    "Stop and set today’s OpenMates priorities. Submit the meeting decisions when they’re clear.",
    "Take a few minutes for the meeting now. Send today’s decisions before picking up more work.",
    "Today’s meeting is still open. Decide what gets your time and record it.",
    "Close the loop on the OpenMates meeting. The decisions are still due.",
    "Take a short planning break. Hold the meeting and send today’s decisions.",
    "Make the remaining OpenMates calls for today and submit the meeting note.",
)


def decision_note(note: str, day: date) -> bool:
    header, _, body = note.strip().partition("\n")
    return header.strip().upper() == f"DECISIONS {day}" and bool(body.strip())


def audit_path(root: Path) -> Path:
    return root.parent / "openmates-dev-mcp/run/broker-audit.log"


def submitted_decisions(out: Path, audit: Path, day: date) -> str:
    """Read the connector's receipt even if the write-back chat is still queued."""
    saved = out / f"{day}-decisions.md"
    if saved.is_file():
        note = saved.read_text()
        if decision_note(note, day):
            return note
    try:
        handle = audit.open()
    except FileNotFoundError:
        return ""
    latest = ""
    with handle:
        for line in handle:
            if '"submit_decisions"' not in line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("verb") != "submit_decisions" or not entry.get("ok") or not entry.get("session"):
                    continue
                submitted = datetime.fromisoformat(entry["ts"])
                note = entry["args"]["note"]
                if submitted.tzinfo and submitted.astimezone(TZ).date() == day and decision_note(note, day):
                    latest = note
            except (ValueError, KeyError, TypeError, AttributeError):
                # An append may be in progress. Only a complete receipt counts.
                continue
    return latest


def evening_day(local: datetime) -> date:
    """The calendar date on which an overnight check-in started."""
    return local.date() - timedelta(days=int(local.hour < EVENING_TIME.hour))


def slots(local: datetime) -> list[str]:
    """Allow a short dispatch delay and never replay old reminder slots."""
    if local.minute % 30 >= 5:
        return []
    day = local.date()
    slot = time(local.hour, local.minute // 30 * 30)
    due = []
    night = evening_day(local)
    if (night >= FIRST_EVENING and night.weekday() < 5
            and local.hour in (22, 23, 0, 1, 2) and slot.minute == 0
            and (local.hour != 2 or local.minute == 0)):
        due.append("evening")
    if day.weekday() < 5 and day >= FIRST_MORNING:
        if slot == BRIEFING_TIME:
            due.append("briefing")
        if local.hour >= 11:
            due.append("reminder")
    return due


def reminder(local: datetime) -> str:
    index = (local.hour - 11) * 2 + local.minute // 30
    if not index:
        return REMINDERS[0]
    return REMINDERS[1 + (index - 1 + local.date().toordinal()) % (len(REMINDERS) - 1)]


def evening_message(task_id: str) -> str:
    url = f"https://app.dev.openmates.org/#task-id={task_id}"
    return ("Evening check-in: What went well today? What didn’t, and what would you change tomorrow?\n"
            f"[Leave a private Activity comment]({url}) to stop tonight’s reminders. "
            "I’ll bring it into your next morning briefing.")


def evening_stamp(local: datetime) -> str:
    # Keep the existing 22:00 receipt so deploying during that slot cannot resend it.
    return "evening" if local.hour == EVENING_TIME.hour else f"evening-{local.hour:02}00"


def unanswered_evening_task(local: datetime) -> str:
    """Return the Task to link if tonight has no reply."""
    from daily_meeting_reflection import configured_task, read_reply

    night = evening_day(local)
    task_id = configured_task(required=True)
    start = datetime.combine(night, EVENING_TIME, tzinfo=TZ)
    return "" if read_reply(task_id, start, local) else task_id


def dispatch(root: Path, local: datetime) -> int:
    from daily_meeting_briefing import main as briefing, post_discord

    due = slots(local)
    if not due:
        return 0
    day = evening_day(local) if "evening" in due else local.date()
    out = root / "logs/daily-meetings"
    receipts = out / "accountability"
    receipts.mkdir(mode=0o700, parents=True, exist_ok=True)
    failures = []
    # Every delivery in a slot is serialized. A receipt is written only after a
    # confirmed Discord response, so a separately triggered retry can recover.
    with (receipts / f"{day}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for kind in due:
            stamp = kind
            if kind == "evening":
                stamp = evening_stamp(local)
            elif kind == "reminder":
                stamp = f"{local.hour:02}{local.minute // 30 * 30:02}"
            receipt = receipts / f"{day}-{stamp}.json"
            if receipt.exists():
                continue
            try:
                if kind == "briefing":
                    if briefing(["--scheduled"]):
                        failures.append(kind)
                    continue  # The existing builder records its own delivery.
                if kind == "evening":
                    task_id = unanswered_evening_task(local)
                    if not task_id:
                        continue
                    message = evening_message(task_id)
                else:
                    if submitted_decisions(out, audit_path(root), day):
                        continue
                    message = reminder(local)
                result = post_discord(root, message)
                fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as handle:
                    json.dump(result, handle)
                print(f"{day} {stamp}: Discord confirmed")
            except (OSError, ValueError, RuntimeError) as error:
                print(f"{day} {stamp}: {error}")
                failures.append(kind)
    return int(bool(failures))


def main() -> int:
    modes = argparse.ArgumentParser(description=__doc__)
    mutually_exclusive = modes.add_mutually_exclusive_group()
    mutually_exclusive.add_argument("--dry-run", action="store_true", help="show due jobs without sending")
    mutually_exclusive.add_argument("--preview-push", action="store_true",
                                    help="send one labeled evening sample without changing schedule state")
    modes.add_argument("--at", type=datetime.fromisoformat, help="override time for --dry-run only")
    args = modes.parse_args()
    if args.at and (not args.dry_run or args.at.tzinfo is None):
        modes.error("--at requires --dry-run and an explicit UTC offset")
    local = (args.at or datetime.now(TZ)).astimezone(TZ)
    from agent_state import canonical_root

    root = canonical_root(Path(__file__).resolve().parents[1])
    if args.dry_run:
        due = slots(local)
        out = root / "logs/daily-meetings"
        if "evening" in due:
            receipt = out / "accountability" / f"{evening_day(local)}-{evening_stamp(local)}.json"
            try:
                if receipt.exists() or not unanswered_evening_task(local):
                    due.remove("evening")
            except (OSError, RuntimeError) as error:
                print(f"{local.isoformat(timespec='minutes')} — evening check-in pending: {error}")
                return 1
        if "reminder" in due and submitted_decisions(out, audit_path(root), local.date()):
            due.remove("reminder")
        print(f"{local.isoformat(timespec='minutes')} — {', '.join(due) or 'nothing due'}")
        return 0
    if args.preview_push:
        from daily_meeting_briefing import post_discord
        from daily_meeting_reflection import configured_task

        receipt = post_discord(root, "Dry run · " + evening_message(configured_task(required=True)))
        print(f"Discord confirmed preview (message {receipt['message_id']})")
        return 0
    return dispatch(root, local)


if __name__ == "__main__":
    raise SystemExit(main())
