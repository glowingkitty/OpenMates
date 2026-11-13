#!/usr/bin/env python3
"""Stop-hook gate: block ending a turn while this chat's CI jobs have no waiter.

Reads the hook JSON on stdin (``session_id``, ``stop_hook_active``, ``agent_id``).
Finds the sessions.py sessions bound to the chat (``agent_task_id``), selects their
non-terminal jobs from the CI coordinator queue (read-only) and checks whether a
``ci_coordinator.py wait <id>`` process exists. A job nobody waits for would leave the
chat idle forever, so the stop is blocked (exit 2, message on stderr). Every error
fails open (exit 0): a broken gate must never trap a chat.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

TERMINAL = ("success", "failure", "cancelled")  # mirrors scripts/ci_coordinator.py TERMINAL
MAX_LISTED = 8


def canonical_root() -> Path:
    override = os.environ.get("OPENMATES_CANONICAL_ROOT")
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent
    try:
        common = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, timeout=1,
        ).stdout.strip()
        return Path(common).parent
    except (OSError, subprocess.SubprocessError):
        return here.parent


def chat_sessions(root: Path, chat_id: str) -> list[str]:
    data = json.loads((root / ".claude" / "sessions.json").read_text(encoding="utf-8"))
    return [key for key, info in (data.get("sessions") or {}).items()
            if chat_id and (info.get("agent_task_id") or info.get("codex_task_id")) == chat_id]


def pending_jobs(root: Path, session_ids: list[str]) -> list[dict]:
    if not session_ids:
        return []
    db_path = root / "logs" / "ci-coordinator" / "queue.sqlite3"
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.5)
    try:
        db.row_factory = sqlite3.Row
        owners = ",".join("?" for _ in session_ids)
        terminal = ",".join("?" for _ in TERMINAL)
        rows = db.execute(
            f"SELECT id, mode, specs, state FROM jobs WHERE owner IN ({owners}) "
            f"AND state NOT IN ({terminal}) ORDER BY created",
            [*session_ids, *TERMINAL],
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def waiting_commands(proc: Path = Path("/proc")) -> list[str]:
    commands = []
    for entry in proc.glob("[0-9]*/cmdline"):
        try:
            text = entry.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
        except OSError:
            continue
        if "ci_coordinator.py" in text and " wait" in text:
            commands.append(text)
    return commands


def unwaited(jobs: list[dict], commands: list[str]) -> list[dict]:
    return [job for job in jobs if not any(job["id"] in command for command in commands)]


def spec_summary(specs: str) -> str:
    try:
        parsed = json.loads(specs)
    except ValueError:
        parsed = specs
    text = ",".join(str(item) for item in parsed) if isinstance(parsed, list) else str(parsed)
    return text if len(text) <= 60 else text[:57] + "..."


def block_message(jobs: list[dict]) -> str:
    listed = "; ".join(f"{job['id']} ({job['mode']}: {spec_summary(job['specs'])})"
                       for job in jobs[:MAX_LISTED])
    more = f" (+{len(jobs) - MAX_LISTED} more)" if len(jobs) > MAX_LISTED else ""
    return (
        f"{len(jobs)} CI job(s) of this chat are still running with no waiter: {listed}{more}. "
        "Before ending the turn, start `python3 scripts/ci_coordinator.py wait <id>` with "
        "run_in_background (or hand the ids to the ci-runner agent in the background) so you are "
        "re-invoked when they finish. If you are deliberately not waiting, say why in your reply."
    )


def evaluate(payload: dict, root: Path, commands: list[str] | None = None) -> str:
    """Return the block message, or '' when the stop may proceed."""
    if payload.get("stop_hook_active") or payload.get("agent_id"):
        return ""
    jobs = pending_jobs(root, chat_sessions(root, str(payload.get("session_id") or "")))
    if not jobs:
        return ""
    missing = unwaited(jobs, waiting_commands() if commands is None else commands)
    return block_message(missing) if missing else ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        message = evaluate(payload, canonical_root())
    except (OSError, ValueError, KeyError, AttributeError, sqlite3.Error):  # fail open: never trap a chat
        return 0
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
