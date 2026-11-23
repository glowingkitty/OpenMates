#!/usr/bin/env python3
"""Triage gate: diagnose before running a spec that already failed twice in a row.

Purpose: a chat that resubmits the same failing spec again and again spends CI
time and tokens without learning anything (owner decision, 22 Nov: after two
failures of the same spec, the cause is diagnosed before the next submit).
`ci_coordinator.py submit` calls `check()` for every e2e/component/pytest/
vitest target; when one target's last two finished jobs of this owner and mode
both failed (no success and no triage note since), the submit is refused
unless it carries `--after-triage "<cause>"`. The note is appended to
`logs/ci-coordinator/triage-notes.jsonl` and opens the gate for one more pair
of attempts. Code changes between attempts do not reset the count: "same code"
means the same spec and chat, since retries normally carry small tweaks.
The daily batch is exempt. Switch: `logs/ci-coordinator/triage-gate.json`
`{"enabled": true}` (missing or unreadable = off).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

FAILURES_BEFORE_TRIAGE = 2
MIN_CAUSE_LENGTH = 20
GATED_MODES = frozenset({"e2e", "component", "pytest", "vitest", "visual-smoke"})
EXEMPT_OWNERS = frozenset({"daily"})


def enabled(queue_path: Path) -> bool:
    try:
        data = json.loads((queue_path.parent / "triage-gate.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("enabled") is True


def notes_path(queue_path: Path) -> Path:
    return queue_path.parent / "triage-notes.jsonl"


def _notes(path: Path, owner: str, mode: str) -> dict[str, float]:
    """Latest triage-note time per target for this owner and mode."""
    latest: dict[str, float] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return latest
    for line in lines:
        try:
            note = json.loads(line)
        except ValueError:
            continue
        if note.get("owner") != owner or note.get("mode") != mode:
            continue
        for target in note.get("targets") or []:
            latest[target] = max(latest.get(target, 0.0), float(note.get("created") or 0))
    return latest


def blocked_targets(queue_path: Path, owner: str, mode: str, targets: list[str]) -> dict[str, list[str]]:
    """Targets needing triage, each with the ids of its failed jobs since the last success or note."""
    if owner in EXEMPT_OWNERS or mode not in GATED_MODES or not targets or not enabled(queue_path):
        return {}
    db = sqlite3.connect(f"file:{queue_path}?mode=ro", uri=True, timeout=30)
    try:
        rows = db.execute(
            "SELECT id, specs, state, created FROM jobs WHERE owner = ? AND mode = ? "
            "AND state IN ('success', 'failure') ORDER BY created",
            (owner, mode),
        ).fetchall()
    finally:
        db.close()
    noted = _notes(notes_path(queue_path), owner, mode)
    blocked: dict[str, list[str]] = {}
    for target in targets:
        failed: list[str] = []
        for job_id, specs, state, created in rows:
            try:
                job_targets = json.loads(specs or "[]")
            except ValueError:
                job_targets = []
            if target not in job_targets:
                continue
            if state == "success" or float(created or 0) <= noted.get(target, 0.0):
                failed = []
            if state == "failure" and float(created or 0) > noted.get(target, 0.0):
                failed.append(job_id)
        if len(failed) >= FAILURES_BEFORE_TRIAGE:
            blocked[target] = failed
    return blocked


def refusal(blocked: dict[str, list[str]]) -> str:
    ids = [job_id for failed in blocked.values() for job_id in failed[-FAILURES_BEFORE_TRIAGE:]]
    listed = ", ".join(f"{target} ({len(failed)} failures in a row)" for target, failed in blocked.items())
    return (
        f"Triage first: {listed} failed {FAILURES_BEFORE_TRIAGE}+ times in a row for this chat. "
        "Find the cause before another run: `python3 scripts/ci_coordinator.py failures "
        + " ".join(ids)
        + "` (trace lines, screenshots, videos), the test-failure-triager or e2e-test-investigator "
        "agent, and the debugging bounds in .claude/rules/testing.md. Then resubmit with "
        '--after-triage "<the cause you found and what this run changes>".'
    )


def check(queue_path: Path, owner: str, mode: str, targets: list[str], cause: str, *, clock=time.time) -> None:
    """Raise ValueError when triage is required and missing; record the note when given."""
    blocked = blocked_targets(queue_path, owner, mode, targets)
    if not blocked:
        return
    cause = (cause or "").strip()
    if not cause:
        raise ValueError(refusal(blocked))
    if len(cause) < MIN_CAUSE_LENGTH:
        raise ValueError(
            f"--after-triage needs the diagnosed cause in a sentence (at least {MIN_CAUSE_LENGTH} characters)."
        )
    path = notes_path(queue_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    note = {
        "created": clock(),
        "owner": owner,
        "mode": mode,
        "targets": sorted(blocked),
        "failed_jobs": {target: failed for target, failed in blocked.items()},
        "cause": cause[:2000],
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(note, sort_keys=True) + "\n")
