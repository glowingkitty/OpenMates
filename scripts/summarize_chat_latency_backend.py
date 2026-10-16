#!/usr/bin/env python3
"""Summarize real dev worker phase logs for owned disposable chat IDs.

Reads a private `openmates chats list --json` snapshot for account scoping.
Matches only those chat IDs in retained app-ai-worker logs.
Emits structural phase durations, never identifiers, prompts or answers.
Scopes each named cohort to an explicit UTC chat-creation window.
The worker does not log a reliable first visible answer timestamp here.
This is diagnostic evidence, not a population percentile or trace join.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import subprocess

CHAT = re.compile(r"ChatID: ([0-9a-f-]{36})")
PRE_START = "Starting preprocessing."
PRE_DONE = "Preprocessing finished."
MAIN_START = "MainProcessor: Starting main processing."
MAIN_DONE = "MainProcessor: Main processing stream finished."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("chats_json", type=Path)
    parser.add_argument("--since", required=True)
    parser.add_argument(
        "--window", action="append", required=True, help="NAME,START_ISO,END_ISO"
    )
    parser.add_argument("--container", default="app-ai-worker")
    args = parser.parse_args()
    windows = []
    for item in args.window:
        name, start, end = item.split(",", 2)
        windows.append(
            (
                name,
                datetime.fromisoformat(start).timestamp(),
                datetime.fromisoformat(end).timestamp(),
            )
        )
    chats = json.loads(args.chats_json.read_text())["chats"]
    owned = {c["id"]: c for c in chats if c.get("id")}
    raw = subprocess.run(
        ["docker", "logs", args.container, "--since", args.since],
        capture_output=True,
        text=True,
        check=True,
    )
    records = {id: {} for id in owned}
    for line in (raw.stdout + "\n" + raw.stderr).splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message", "")
        match = CHAT.search(message)
        if not match or match.group(1) not in owned:
            continue
        stamp = event.get("timestamp")
        if not stamp:
            continue
        when = (
            datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S,%f")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        phases = records[match.group(1)]
        if PRE_START in message:
            phases.setdefault("pre_start", when)
        if PRE_DONE in message:
            phases.setdefault("pre_done", when)
        if MAIN_START in message:
            phases.setdefault("main_start", when)
        if MAIN_DONE in message:
            phases.setdefault("main_done", when)
    groups = {}
    for chat_id, phases in records.items():
        chat = owned[chat_id]
        created = chat.get("createdAt") or 0
        cohort = next(
            (name for name, start, end in windows if start <= created < end), None
        )
        if cohort is None:
            continue
        if not all(
            k in phases for k in ("pre_start", "pre_done", "main_start", "main_done")
        ):
            continue
        row = {
            "preprocess_ms": round((phases["pre_done"] - phases["pre_start"]) * 1000),
            "preprocess_to_main_ms": round(
                (phases["main_start"] - phases["pre_start"]) * 1000
            ),
            "main_stream_ms": round(
                (phases["main_done"] - phases["main_start"]) * 1000
            ),
        }
        groups.setdefault(cohort, []).append(row)
    result = {
        "scope": "dev_app_ai_worker_owned_disposable_chats",
        "first_token_timing": "unavailable_in_worker_log",
        "cohorts": {},
    }
    for cohort, rows in groups.items():
        result["cohorts"][cohort] = {
            "n": len(rows),
            "medians_ms": {
                k: round(statistics.median(r[k] for r in rows)) for k in rows[0]
            },
            "ranges_ms": {
                k: [min(r[k] for r in rows), max(r[k] for r in rows)] for k in rows[0]
            },
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
