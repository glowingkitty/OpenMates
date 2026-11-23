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

Loop brake (owner decision, 23 Nov, receipt 5096e6d1abf8b55f): once a target
failed LOOP_BRAKE_AT times in a row for this chat (since its last success,
triage notes do not reset this count), a triage note no longer opens it. The
chat stops and sends the owner ONE question push (the failure in one sentence
and its recommendation). Only `--after-owner-answer <receipt>`, a dev-connector
receipt that `owner_message.py` verifies for this chat, opens it again; the
answer is recorded like a note and starts the count over.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

FAILURES_BEFORE_TRIAGE = 2
LOOP_BRAKE_AT = 3
MIN_CAUSE_LENGTH = 20
GATED_MODES = frozenset({"e2e", "component", "pytest", "vitest", "visual-smoke", "artifact"})
EXEMPT_OWNERS = frozenset({"daily"})


def enabled(queue_path: Path) -> bool:
    try:
        data = json.loads((queue_path.parent / "triage-gate.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("enabled") is True


def notes_path(queue_path: Path) -> Path:
    return queue_path.parent / "triage-notes.jsonl"


def read_notes(path: Path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        try:
            note = json.loads(line)
        except ValueError:
            continue
        if isinstance(note, dict):
            yield note


def _notes(path: Path, owner: str, mode: str, kinds: frozenset[str] = frozenset({"triage", "owner"})) -> dict[str, float]:
    """Latest note time per target for this owner and mode (notes without a kind are triage notes)."""
    latest: dict[str, float] = {}
    for note in read_notes(path):
        if note.get("owner") != owner or note.get("mode") != mode or note.get("kind", "triage") not in kinds:
            continue
        for target in note.get("targets") or []:
            latest[target] = max(latest.get(target, 0.0), float(note.get("created") or 0))
    return latest


def _rows(queue_path: Path, owner: str, mode: str) -> list[tuple]:
    db = sqlite3.connect(f"file:{queue_path}?mode=ro", uri=True, timeout=30)
    try:
        return db.execute(
            "SELECT id, specs, state, created, error FROM jobs WHERE owner = ? AND mode = ? "
            "AND state IN ('success', 'failure') ORDER BY created",
            (owner, mode),
        ).fetchall()
    finally:
        db.close()


def _failure_runs(rows: list[tuple], targets: list[str], reset_at: dict[str, float],
                  signature=None) -> dict[str, list[str]]:
    """Per target: ids of its failed jobs since its last success and since reset_at[target]."""
    runs: dict[str, list[str]] = {}
    for target in targets:
        failed: list[str] = []
        previous = None
        for job_id, specs, state, created, error in rows:
            try:
                job_targets = json.loads(specs or "[]")
            except ValueError:
                job_targets = []
            if target not in job_targets:
                continue
            if state == "success" or float(created or 0) <= reset_at.get(target, 0.0):
                failed = []
            if state == "failure" and float(created or 0) > reset_at.get(target, 0.0):
                current = signature(job_id, error) if signature else "failure"
                if current != previous or current is None:
                    failed = []
                if current is not None:
                    failed.append(job_id)
                previous = current
        runs[target] = failed
    return runs


def _active(queue_path: Path, owner: str, mode: str, targets: list[str]) -> bool:
    return owner not in EXEMPT_OWNERS and mode in GATED_MODES and bool(targets) and enabled(queue_path)


def blocked_targets(queue_path: Path, owner: str, mode: str, targets: list[str]) -> dict[str, list[str]]:
    """Targets needing triage, each with the ids of its failed jobs since the last success or note."""
    if not _active(queue_path, owner, mode, targets):
        return {}
    noted = _notes(notes_path(queue_path), owner, mode)
    runs = _failure_runs(_rows(queue_path, owner, mode), targets, noted)
    return {target: failed for target, failed in runs.items() if len(failed) >= FAILURES_BEFORE_TRIAGE}


def braked_targets(queue_path: Path, owner: str, mode: str, targets: list[str], *, signature=None) -> dict[str, list[str]]:
    """Targets at the loop brake: LOOP_BRAKE_AT+ failures in a row since the last success or owner answer."""
    if not _active(queue_path, owner, mode, targets):
        return {}
    answered = _notes(notes_path(queue_path), owner, mode, kinds=frozenset({"owner"}))
    rows = _rows(queue_path, owner, mode)
    runs = _failure_runs(rows, targets, answered)
    candidates = {target for target, jobs in runs.items() if len(jobs) >= LOOP_BRAKE_AT}
    if not candidates:
        return {}
    read_signature = signature or (lambda job, error: failure_signature(queue_path, job, error))
    jobs = {job for target in candidates for job in runs[target][-LOOP_BRAKE_AT:]}
    cache = {job: read_signature(job, error) for job, _, _, _, error in rows if job in jobs}
    runs = _failure_runs(rows, sorted(candidates), answered, lambda job, _: cache.get(job))
    return {target: failed for target, failed in runs.items() if len(failed) >= LOOP_BRAKE_AT}


_DYNAMIC = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|"
    r"\b\d+(?:\.\d+)?\s*(?:ms|seconds?|minutes?)\b", re.I)


def failure_signature(queue_path: Path, job: str, error: str | None) -> str | None:
    """Compare reported failures by test, outcome and diagnostic text."""
    root = queue_path.parent.parent.parent
    receipt_path = root / "test-results" / "ci-runs" / job / "receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        try:
            from scripts.ci_failures import collect
        except ModuleNotFoundError:
            from ci_failures import collect
        failures = [
            (item["test"], item["status"], _DYNAMIC.sub("<run>", " ".join(item["trace"])))
            for item in collect(receipt)["failures"]
            if item["status"] != "flaky" and item["trace"]
            and item["trace"] != ["no test result; see the GitHub run log"]
        ]
    except (OSError, ValueError, KeyError):
        failures = []
    if not failures and error:
        failures = [("", "job error", _DYNAMIC.sub("<run>", error))]
    if not failures:
        return None
    return hashlib.sha256(json.dumps(sorted(failures)).encode()).hexdigest()


def evidence_candidates(queue_path: Path, owner: str, mode: str, targets: list[str]) -> set[str]:
    """Recent jobs whose evidence can establish a three-failure streak."""
    if not _active(queue_path, owner, mode, targets):
        return set()
    answered = _notes(notes_path(queue_path), owner, mode, kinds=frozenset({"owner"}))
    runs = _failure_runs(_rows(queue_path, owner, mode), targets, answered)
    return {job for jobs in runs.values() if len(jobs) >= LOOP_BRAKE_AT for job in jobs[-LOOP_BRAKE_AT:]}


def brake_path(root: Path, chat_id: str) -> Path:
    return root / "logs" / "ci-coordinator" / "loop-brakes" / f"{chat_id}.json"


def active_brake(root: Path, chat_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", chat_id):
        return {}
    try:
        record = json.loads(brake_path(root, chat_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def register_brake(queue_path: Path, chat_id: str, braked: dict[str, list[str]]) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", chat_id):
        return {}
    root = queue_path.parent.parent.parent
    path = brake_path(root, chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if prior := active_brake(root, chat_id):
            return prior
        record = {"started": time.time(), "targets": braked}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(path)
        return record


def already_asked(root: Path, chat_id: str, brake: dict) -> bool:
    if not brake:
        return False
    path = root / "logs" / "claude-idle-chats" / "questions" / f"{chat_id}.json"
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return marker.get("kind") == "❓" and float(marker.get("ts", 0)) >= float(brake.get("started", 0))


def brake_refusal(braked: dict[str, list[str]], *, asked: bool = False) -> str:
    ids = [job_id for failed in braked.values() for job_id in failed[-LOOP_BRAKE_AT:]]
    listed = ", ".join(f"{target} ({len(failed)} failures in a row)" for target, failed in braked.items())
    if asked:
        return (f"Loop brake: {listed}. The owner was already asked. Wait for the answer and resubmit "
                "with --after-owner-answer <receipt>.")
    return (
        f"Loop brake: {listed}. Stop retrying. Read the failures once (`python3 scripts/ci_coordinator.py "
        f"failures {' '.join(ids)}`), then send Marco ONE question push with the failure in one sentence and "
        "your recommendation: `python3 scripts/agent_question.py ask --question \"<failure in one sentence>?\" "
        "--recommendation \"<what you recommend>\"`, and end your turn without further retries. When his "
        "answer arrives through the dev connector, resubmit with --after-owner-answer <its receipt>."
    )


def verify_owner_answer(receipt: str, chat_id: str) -> tuple[bool, str]:
    """(verified, reason) for a dev-connector receipt issued for this chat."""
    import owner_message  # noqa: E402  (sibling script, on sys.path for ci_coordinator)

    try:
        return owner_message.check(owner_message.ask_broker(receipt), chat_id)
    except (OSError, ValueError) as error:
        return False, f"the dev connector broker could not be asked ({error})"


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


def _append_note(queue_path: Path, note: dict) -> None:
    path = notes_path(queue_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(note, sort_keys=True) + "\n")


def check(queue_path: Path, owner: str, mode: str, targets: list[str], cause: str, *, owner_answer: str = "",
          chat_id: str = "", clock=time.time, verify=verify_owner_answer) -> None:
    """Raise ValueError when the loop brake holds or triage is missing; record notes and answers."""
    braked = braked_targets(queue_path, owner, mode, targets)
    if braked:
        receipt = (owner_answer or "").strip()
        if not receipt:
            brake = register_brake(queue_path, chat_id, braked)
            raise ValueError(brake_refusal(braked, asked=already_asked(queue_path.parent.parent.parent, chat_id, brake)))
        if any(note.get("receipt") == receipt for note in read_notes(notes_path(queue_path))):
            raise ValueError("The owner receipt was already used for a previous loop brake.")
        verified, reason = verify(receipt, chat_id)
        if not verified:
            raise ValueError(f"--after-owner-answer {receipt}: not the owner's answer to this chat ({reason}).")
        _append_note(queue_path, {"created": clock(), "owner": owner, "mode": mode, "kind": "owner",
                                  "targets": sorted(braked), "receipt": receipt,
                                  "failed_jobs": {target: failed for target, failed in braked.items()}})
        if active_brake(queue_path.parent.parent.parent, chat_id):
            brake_path(queue_path.parent.parent.parent, chat_id).unlink(missing_ok=True)
        return
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
    _append_note(queue_path, {
        "created": clock(),
        "owner": owner,
        "mode": mode,
        "kind": "triage",
        "targets": sorted(blocked),
        "failed_jobs": {target: failed for target, failed in blocked.items()},
        "cause": cause[:2000],
    })
