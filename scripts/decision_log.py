#!/usr/bin/env python3
"""Persistent log of everything the founder dropped (idea, chat, Task, reminder, issue), with re-check.

Nothing dropped is ever deleted: the thing is archived or closed and one entry is appended here with
what it was, the date, why and by whom. When a new idea, Task or chat request resembles an earlier entry,
`match` returns it so the meeting can say "We dropped this on <date> because <reason>. Still want it?".
The log is private (`logs/decision-log/dropped.jsonl` of the canonical checkout, git-ignored) and shared by
the daily meeting (`scripts/daily_meeting_apply.py` writes the `Dropped:` lines of a decisions note,
`scripts/daily_meeting_briefing.py` re-checks new items) and, later, the dev connector's start_chat path.

  python3 scripts/decision_log.py add --kind chat --what "..." --why "..." [--by "..."] [--ref ID]
  python3 scripts/decision_log.py check "text of the new idea or request"
  python3 scripts/decision_log.py list
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import subprocess
import sys

KINDS = ("idea", "chat", "task", "reminder", "issue")
MIN_SHARED, MIN_SCORE = 2, 0.6
STOP = {"with", "from", "that", "this", "when", "after", "before", "into", "should", "would", "about", "have",
        "make", "need", "want", "chat", "task", "idea", "page", "user", "users", "feature"}


def log_path() -> Path:
    """The canonical checkout's private log (worktrees share it); DECISION_LOG_DIR overrides it for tests."""
    override = os.environ.get("DECISION_LOG_DIR")
    if override:
        return Path(override) / "dropped.jsonl"
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=Path(__file__).parent,
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent / "logs" / "decision-log" / "dropped.jsonl"


def entries(path: Path | None = None) -> list[dict]:
    path = path or log_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def add(kind: str, what: str, why: str, by: str, ref: str = "", day: str = "", path: Path | None = None) -> dict:
    """Append one entry (what, date, why, by whom); returns it. Never rewrites or removes earlier entries."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not what.strip() or not why.strip() or not by.strip():
        raise ValueError("what, why and by are required: a drop without a reason is not logged")
    entry = {"kind": kind, "what": what.strip(), "date": day or date.today().isoformat(), "why": why.strip(),
             "by": by.strip(), "ref": ref.strip()}
    path = path or log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower())} - STOP


def match(text: str, logged: list[dict] | None = None) -> list[dict]:
    """Earlier drops whose words overlap the text (at least 2 shared words and 60% of the shorter side)."""
    wanted, found = _words(text), []
    for entry in logged if logged is not None else entries():
        words = _words(entry["what"])
        shared = len(wanted & words)
        if shared >= MIN_SHARED and shared / max(min(len(wanted), len(words)), 1) >= MIN_SCORE:
            found.append(entry)
    return found


def question(entry: dict) -> str:
    return f"We dropped this on {entry['date']} because {entry['why']}. Still want it?"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    adder = sub.add_parser("add")
    adder.add_argument("--kind", required=True, choices=KINDS)
    adder.add_argument("--what", required=True)
    adder.add_argument("--why", required=True)
    adder.add_argument("--by", default="Marco (daily meeting)")
    adder.add_argument("--ref", default="")
    sub.add_parser("list")
    checker = sub.add_parser("check")
    checker.add_argument("text")
    args = parser.parse_args(argv)
    if args.command == "add":
        print(json.dumps(add(args.kind, args.what, args.why, args.by, args.ref), ensure_ascii=False))
    elif args.command == "list":
        for entry in entries():
            print(f"{entry['date']} [{entry['kind']}] {entry['what']} — {entry['why']} ({entry['by']})")
    else:
        hits = match(args.text)
        print("\n".join(f"{question(h)}  [{h['kind']}: {h['what']}]" for h in hits) or "no earlier drop matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
