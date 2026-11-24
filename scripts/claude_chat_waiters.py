#!/usr/bin/env python3
"""What a Claude Code chat on the dev host waits on, and reopening it when the wait ends.

On 2026-11-15 chat d2a774d9 parked its CI step because the disk was at 91%; the disk
coordinator held the step (a threaded request in its ledger) and the chat told the
owner "the coordinator notifies me". Nothing delivered that notice to a Claude chat
(only the Codex adapter did), and the chat lifecycle saw an idle chat and stopped it
after an hour. It sat closed for two more hours after the disk was cleaned (TASK-662).

A *waiter* is one thing a chat waits on:

  disk        a disk-coordinator request of the chat (ledger column `thread`) that is
              waiting or granted. The coordinator marks a parked request (its owner
              process exited) ready with PARKED_READY_REASON once capacity admits it.
              A waiting request older than a later request of the same chat that went
              through does not count: the chat moved on (most of 190 waiting rows on
              2026-11-15 were such leftovers of CI result downloads).
  ci          a CI job of the chat's sessions.py session that is queued or active.
              It fires when the job reaches a final state.
  handoff     registered by the chat (`add`): it waits for another chat, the owner or
  background  any other outside event. It fires when someone runs `fire`.
  timer       registered by the chat (`add --kind timer --at <ISO time with zone> --message ...`):
              it fires by itself once that time is reached. `--at usage-reset` takes the
              weekly Claude usage reset from claude_usage_guard (+5 minutes) and turns on
              the usage check; `--usage-check` does it for an explicit time. With the check,
              a due timer whose weekly usage is still >= USAGE_AVAILABLE_BELOW is moved one
              hour later instead of waking the chat (no usage spent); if usage cannot be
              read, it fires and the wake line says so. A timer never keeps a chat from idle
              stop and is never stalled: the stopped chat is reopened when it fires.

Rules (applied by scripts/claude_idle_chats.py every cycle):
  * A chat with a waiter that has not timed out is never stopped as idle, done or by
    the cap (a hard rule, like a running background command).
  * When a waiter fires, the chat is woken through one path for every kind: an idle
    zellij-pane chat gets one line typed into its pane; a chat that is not running
    (stopped by the lifecycle, killed with its zellij server, closed while waiting) is
    reopened with `claude --resume` and the same line as its next message
    (claude_dispatch.resume_chat). A busy chat is woken on a later cycle. Each fired
    set is delivered once (`waiter_wakes.json`); a failed reopen is retried.
  * A CI job that finished while its live chat was already active again (its own
    background waiter delivered the result) does not wake it a second time.
  * A waiter past its timeout is `stalled`: it no longer keeps the chat from idle
    stop, it is listed in status.json (`stalled`, `waiting`), and it still reopens
    the chat if it fires later. Timeouts: TIMEOUT_MINUTES, or `--timeout-minutes`.
  * Explicit recovery waiters can wake an archived source or its verified successor.
    The watchdog wakes timed-out manual waits with a deadline notice and fires
    Task dependencies from confirmed Task status.
  * TASK-9844 (2026-11-18): chats that stopped because weekly usage ran out are woken by
    a `timer --at usage-reset` waiter instead of the owner remembering to restart them.
  * TASK-4594 (2026-11-19): a queued chat START is a timer too (add_start): the dev connector
    queues start_chat when weekly usage is low, for an explicit time or until marketing time
    ends. It has no chat yet (`chat_id` ""), carries the saved request in `start`, always has
    the usage check, and wakes no chat: settle_timers fires it like any timer and the
    connector starts the fired ones (due_starts / take_start). Writes to registered.json hold
    a file lock, since the connector and the lifecycle both write it.

State, in logs/claude-chat-lifecycle/: registered.json (handoff/background/timer waiters),
waiters.json (the waiters seen last cycle, to notice CI jobs that ended),
waiter_wakes.json (delivered wakes); events in events.jsonl.

Commands:
  list                                   every chat's current waiters
  add  --chat <id> --kind handoff|background --on "<what>" [--key K] [--timeout-minutes N]
  add  --chat <id> --kind timer --at "<ISO time with zone>"|usage-reset [--usage-check] --message "<what to do>"
  fire --chat <id> --key K [--message "<text for the chat>"]   (the waited-for side)
  clear --chat <id> --key K              drop a registered waiter without waking
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disk_coordinator_state  # noqa: E402  (path set above; the units run python3 -I -S)

# A CI run takes 12-15 min (Nov 2026): a CI waiter times out at about twice that, and the
# chat is then woken once with the job's real state (ci_overdue) instead of staying silent.
TIMEOUT_MINUTES = {"disk": 360.0, "ci": 30.0, "handoff": 240.0, "background": 240.0, "timer": 0.0}
REGISTERED_KINDS = ("handoff", "background", "timer")
USAGE_AVAILABLE_BELOW = 95.0  # weekly used percent; a usage-checked timer waits while usage is at or above it
USAGE_RETRY_SECONDS = 3600.0
USAGE_RESET_MARGIN_SECONDS = 300.0
CI_WAITING_STATES = ("queued", "dispatching", "submitted", "running", "attention")
CI_FINAL_STATES = ("success", "failure", "cancelled")
WAKE_PREFIX = "[chat lifecycle] "
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass
class Waiter:
    """One thing a chat waits on."""

    chat_id: str
    kind: str  # disk | ci | handoff | background | timer
    key: str  # unique per chat: disk:<request>, ci:<job>, reg:<key>
    detail: str  # what, in words
    since: float
    timeout_at: float
    ready: bool = False  # the wait is over: wake the chat
    ready_text: str = ""  # what the wake line says about it
    ready_at: float = 0.0

    def stalled(self, now: float) -> bool:
        return self.kind != "timer" and not self.ready and now > self.timeout_at

    def late(self, now: float) -> bool:
        """Stalled background work (a timed-out handoff waits on a person: shown as timed out, not stalled)."""
        return self.stalled(now) and self.kind != "handoff"

    def blocks_stop(self, now: float) -> bool:
        """Keeps the chat running: not timed out, or over and about to be woken (a timer only when due)."""
        return self.ready or (self.kind != "timer" and not self.stalled(now))

    def label(self, now: float) -> str:
        state = ("ready" if self.ready else f"timed out {_clock(self.timeout_at)} UTC, nobody fired it"
                 if self.kind == "handoff" and self.stalled(now) else "STALLED" if self.stalled(now) else "waiting")
        until = (f", fires {_utc(self.timeout_at)}" if self.kind == "timer"
                 else f", times out {_clock(self.timeout_at)} UTC")
        return (f"{self.kind}: {self.detail} ({state}, since {_clock(self.since)} UTC"
                + ("" if self.ready else until) + ")")


@dataclass
class Sources:
    """Where waiters come from; tests pass their own paths."""

    root: Path
    state: Path
    ledger: Path | None = None
    sessions: dict[str, list[str]] = field(default_factory=dict)  # chat id -> sessions.py ids
    usage: Callable[[], tuple[float, datetime]] | None = None  # weekly (used %, reset); default: claude_usage_guard


def _utc(ts: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clock(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%m-%d %H:%M")


def _short_operation(operation: str) -> str:
    name, _, rest = operation.partition(":")
    return f"{name}:{rest[:8]}" if len(rest) > 16 else operation


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


@contextlib.contextmanager
def _locked(state: Path):
    """Serialise read-modify-write of registered.json (the lifecycle, chats and the connector write it)."""
    state.mkdir(parents=True, exist_ok=True)
    with (state / ".registered.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def default_ledger() -> Path:
    return disk_coordinator_state.default_state() / "ledger.sqlite3"


# ---------------------------------------------------------------------------
# Reading the waiters.
# ---------------------------------------------------------------------------


def disk_waiters(ledger: Path, now: float) -> list[Waiter]:
    """Threaded disk requests still waiting or granted (read-only)."""
    if not ledger.exists():
        return []
    try:
        with sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=5) as conn:
            rows = conn.execute(
                "SELECT id, thread, operation, state, reason, created_at, updated_at FROM requests "
                "WHERE thread != '' AND state IN ('waiting', 'granted')").fetchall()
            progressed = dict(conn.execute(
                "SELECT thread, MAX(created_at) FROM requests WHERE thread != '' "
                "AND state IN ('granted', 'claimed', 'complete') GROUP BY thread").fetchall())
    except sqlite3.Error as error:
        raise RuntimeError(f"disk ledger unreadable: {error}") from error
    found = []
    for request_id, thread, operation, state, reason, created, updated in rows:
        if now - created > disk_coordinator_state.PARKED_WAIT_EXPIRY:
            continue  # the coordinator cancels these
        if state == "waiting" and progressed.get(thread, 0) > created:
            continue  # a later disk request of the chat went through: it moved on past this wait
        ready = state == "granted" or reason == disk_coordinator_state.PARKED_READY_REASON
        what = f"disk space for {_short_operation(operation)}"
        found.append(Waiter(
            chat_id=thread, kind="disk", key=f"disk:{request_id}", detail=what, since=created,
            timeout_at=created + TIMEOUT_MINUTES["disk"] * 60, ready=ready, ready_at=updated if ready else 0.0,
            ready_text=(f"the disk coordinator now has space for your waiting step {operation} "
                        f"(request {request_id[:8]}, waiting since {_clock(created)} UTC): rerun that step now "
                        "with the same command; it claims the reserved space") if ready else ""))
    return found


def _ci_queue(root: Path) -> Path:
    return root / "logs" / "ci-coordinator" / "queue.sqlite3"


def ci_waiters(root: Path, sessions: dict[str, list[str]], now: float) -> list[Waiter]:
    """Queued or active CI jobs of each chat's sessions.py sessions."""
    path = _ci_queue(root)
    owners = {session: chat for chat, ids in sessions.items() for session in ids}
    if not path.exists() or not owners:
        return []
    marks = ",".join("?" * len(CI_WAITING_STATES))
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
            rows = conn.execute(f"SELECT id, owner, mode, state, created FROM jobs WHERE state IN ({marks})",
                                CI_WAITING_STATES).fetchall()
    except sqlite3.Error as error:
        raise RuntimeError(f"CI queue unreadable: {error}") from error
    return [Waiter(chat_id=owners[str(owner)], kind="ci", key=f"ci:{job_id}",
                   detail=f"CI {mode} job {str(job_id)[:8]} ({state})", since=float(created or now),
                   timeout_at=float(created or now) + TIMEOUT_MINUTES["ci"] * 60)
            for job_id, owner, mode, state, created in rows if str(owner) in owners]


def ci_final_states(root: Path, job_ids: list[str]) -> dict[str, tuple[str, float]]:
    """job id -> (final state, updated) for jobs that ended."""
    path = _ci_queue(root)
    if not job_ids or not path.exists():
        return {}
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
        rows = conn.execute(f"SELECT id, state, updated FROM jobs WHERE id IN ({','.join('?' * len(job_ids))})",
                            job_ids).fetchall()
    return {job_id: (state, float(updated or 0)) for job_id, state, updated in rows if state in CI_FINAL_STATES}


def weekly_usage() -> tuple[float, datetime]:
    import claude_usage_guard  # noqa: E402  (sibling script; network read only when a usage timer is due)

    return claude_usage_guard.fetch_weekly_usage()


def _scheduled_start_uses_codex(entry: dict, now: float) -> bool:
    request = entry.get("start") or {}
    if request.get("verb") != "start_chat":
        return False
    import claude_weekly_model

    model = (request.get("args") or {}).get("model") or "claude"
    return claude_weekly_model.queued_route(model, datetime.fromtimestamp(now, timezone.utc))[0] == "codex"


def settle_timers(state: Path, now: float, usage: Callable[[], tuple[float, datetime]] | None = None,
                  log=lambda event: None) -> None:
    """Fire due timers; a due usage-checked timer whose weekly usage is still used up moves one hour later."""
    with _locked(state):
        path = state / "registered.json"
        data = _read_json(path)
        changed = False
        read: list = []  # one usage read per cycle, however many timers are due (the endpoint rate-limits)
        for key, entry in data.items():
            if entry["kind"] != "timer" or entry.get("fired_at") or now < entry["timeout_at"]:
                continue
            if entry.get("usage_check") and not _scheduled_start_uses_codex(entry, now):
                import claude_usage_guard  # noqa: E402  (sibling script)

                try:
                    if not read:
                        try:
                            read.append((usage or weekly_usage)())
                        except claude_usage_guard.UsageUnavailable as error:
                            read.append(error)
                    if isinstance(read[0], Exception):
                        raise read[0]
                    used, resets = read[0]
                except claude_usage_guard.UsageUnavailable as error:
                    entry["usage_note"] = f"weekly usage could not be read ({error}); check /usage before working"
                else:
                    if used >= USAGE_AVAILABLE_BELOW:
                        entry["timeout_at"] = now + USAGE_RETRY_SECONDS
                        entry["postponed"] = int(entry.get("postponed", 0)) + 1
                        log({"event": "timer_postponed", "session_id": entry["chat_id"], "key": key,
                             "used_percent": used, "resets_at": resets.isoformat(), "next": _utc(entry["timeout_at"])})
                        changed = True
                        continue
                    entry["usage_note"] = f"weekly usage is {used:.0f}% (resets {resets.isoformat()})"
            entry["fired_at"] = now
            log({"event": "timer_fired", "session_id": entry["chat_id"], "key": key})
            changed = True
        if changed:
            _write_json(path, data)


def registered_waiters(state: Path) -> list[Waiter]:
    found = []
    for key, entry in _read_json(state / "registered.json").items():
        if "start" in entry:
            continue  # a queued chat start wakes no chat; the dev connector starts it (due_starts)
        fired = bool(entry.get("fired_at"))
        if entry["kind"] == "timer":
            found.append(Waiter(
                chat_id=entry["chat_id"], kind="timer", key=f"reg:{key}", detail=entry["on"], since=entry["since"],
                timeout_at=entry["timeout_at"], ready=fired, ready_at=entry.get("fired_at", 0.0),
                ready_text=(f"your timer for {_utc(entry['at'])} is due"
                            + (f", {entry['usage_note']}" if entry.get("usage_note") else "")
                            + f": {entry['on']}") if fired else ""))
            continue
        found.append(Waiter(
            chat_id=entry["chat_id"], kind=entry["kind"], key=f"reg:{key}", detail=entry["on"],
            since=entry["since"], timeout_at=entry["timeout_at"], ready=fired, ready_at=entry.get("fired_at", 0.0),
            ready_text=((f"wait deadline passed without confirmation ({entry['on']}). Check the actual "
                         "state and continue any unblocked work" if entry.get("deadline_wake")
                         else f"what you waited on is here ({entry['on']})")
                        + (f": {entry['message']}" if entry.get("message") else "")) if fired else ""))
    return found


def collect(sources: Sources, now: float) -> dict[str, list[Waiter]]:
    """chat id -> its waiters now, with CI jobs that ended since last cycle as ready waiters."""
    settle_timers(sources.state, now, sources.usage)
    current = (disk_waiters(sources.ledger or default_ledger(), now)
               + ci_waiters(sources.root, sources.sessions, now) + registered_waiters(sources.state))
    seen = {waiter.key for waiter in current}
    previous = _read_json(sources.state / "waiters.json")
    gone_ci = {entry["key"][3:]: entry for entries in previous.values() for entry in entries
               if entry["kind"] == "ci" and not entry.get("ready") and entry["key"] not in seen}
    for job_id, (state, updated) in ci_final_states(sources.root, list(gone_ci)).items():
        entry = gone_ci[job_id]
        current.append(Waiter(**{**entry, "ready": True, "ready_at": updated or now,
                                 "detail": entry["detail"].rsplit(" (", 1)[0] + f" ({state})",
                                 "ready_text": f"{entry['detail'].rsplit(' (', 1)[0]} finished: {state} "
                                               f"(`python3 scripts/ci_coordinator.py result {job_id}`)"}))
    current += ci_overdue(current, now)
    # A ready CI waiter stays until it is delivered (kept in waiters.json by remember()).
    for entries in previous.values():
        for entry in entries:
            if entry["kind"] == "ci" and entry.get("ready") and entry["key"] not in {w.key for w in current}:
                current.append(Waiter(**entry))
    by_chat: dict[str, list[Waiter]] = {}
    for waiter in current:
        by_chat.setdefault(waiter.chat_id, []).append(waiter)
    return by_chat


def ci_overdue(current: list[Waiter], now: float) -> list[Waiter]:
    """One ready `ci-overdue:<job>` waiter per CI job still queued or running past its timeout.

    TASK-1338 (2026-11-23): chats waiting on CI went silent for 40-95 minutes. The job's own
    `ci:<job>` waiter stays and still wakes the chat with the final result; this one wakes it
    once when the run is overdue, with the state the CI queue reports now. Its distinct key
    makes waiter_wakes.json deliver it only once per job.
    """
    overdue = []
    for waiter in current:
        if waiter.kind != "ci" or waiter.ready or not waiter.key.startswith("ci:") or now <= waiter.timeout_at:
            continue
        job_id, minutes = waiter.key[3:], int((now - waiter.since) // 60)
        overdue.append(Waiter(
            chat_id=waiter.chat_id, kind="ci", key=f"ci-overdue:{job_id}", detail=waiter.detail + " overdue",
            since=waiter.since, timeout_at=waiter.timeout_at, ready=True, ready_at=waiter.timeout_at,
            ready_text=(f"{waiter.detail} has not finished after {minutes} min (a run takes 12-15 min; "
                        f"`python3 scripts/ci_coordinator.py status {job_id}`): check it and rerun, keep "
                        "waiting with a fresh waiter, or report the blocker")))
    return overdue


def remember(state: Path, waiters: dict[str, list[Waiter]], delivered: set[str]) -> None:
    """Keep this cycle's waiters for the next one; delivered ready CI waiters are dropped."""
    _write_json(state / "waiters.json", {
        chat: [asdict(w) for w in items if not (w.kind == "ci" and w.ready and w.key in delivered)
               and not w.key.startswith("ci-overdue:")]  # recomputed from the live job every cycle
        for chat, items in waiters.items()})


# ---------------------------------------------------------------------------
# Registered waiters (handoff, background).
# ---------------------------------------------------------------------------


def add(state: Path, chat_id: str, kind: str, on: str, key: str = "", timeout_minutes: float | None = None,
        now: float | None = None, at: float | None = None, usage_check: bool = False,
        task_id: str = "") -> str:
    """Register a waiter; a timer needs `at` (epoch seconds) and `on` is then the wake message."""
    if kind not in REGISTERED_KINDS:
        raise ValueError(f"kind must be one of {REGISTERED_KINDS}")
    if not UUID_RE.match(chat_id) or not on.strip():
        raise ValueError("add needs a chat id (uuid) and --on (a timer: --message)")
    if (kind == "timer") != (at is not None):
        raise ValueError("--at is required for a timer and only for a timer")
    if task_id and (kind == "timer" or not UUID_RE.fullmatch(task_id)):
        raise ValueError("--task requires a full Task UUID and a handoff or background wait")
    now = time.time() if now is None else now
    key = key or uuid.uuid4().hex[:10]
    with _locked(state):
        path = state / "registered.json"
        data = _read_json(path)
        minutes = TIMEOUT_MINUTES[kind] if timeout_minutes is None else timeout_minutes
        data[key] = {"chat_id": chat_id, "kind": kind, "on": " ".join(on.split())[:1000 if at else 300], "since": now,
                     "timeout_at": at if at is not None else now + minutes * 60}
        if at is not None:
            data[key] |= {"at": at, "usage_check": usage_check}
        if task_id:
            data[key]["task_id"] = task_id
        _write_json(path, data)
        return key


def fire(state: Path, chat_id: str, key: str, message: str = "", now: float | None = None) -> None:
    with _locked(state):
        path = state / "registered.json"
        data = _read_json(path)
        entry = data.get(key)
        if not entry or entry["chat_id"] != chat_id:
            raise KeyError(f"no registered waiter {key!r} for chat {chat_id}")
        entry["fired_at"] = time.time() if now is None else now
        entry.pop("deadline_wake", None)
        entry["message"] = " ".join(message.split())[:1000]
        _write_json(path, data)


def settle_external_waits(state: Path, now: float, task_status: dict[str, str],
                          protected: set[str]) -> None:
    """Keep a ready registration until it is delivered, including a deadline wake."""
    with _locked(state):
        path = state / "registered.json"
        data = _read_json(path)
        changed = False
        for entry in data.values():
            if entry["kind"] == "timer" or entry.get("fired_at") or entry["chat_id"] in protected:
                continue
            task_id = entry.get("task_id")
            if not task_id:
                # Existing waiters sometimes explicitly name completion as the event.
                match = re.match(r"^(TASK-\d+) (?:lands on dev|is done)\b", entry["on"], re.I)
                task_id = match[1].upper() if match else None
            if task_status.get(task_id) == "done":
                entry["message"] = "The dependency Task is marked done."
            elif now >= entry["timeout_at"]:
                entry["deadline_wake"] = True
            else:
                continue
            entry["fired_at"] = now
            changed = True
        if changed:
            _write_json(path, data)


def clear(state: Path, chat_id: str, key: str) -> bool:
    with _locked(state):
        path = state / "registered.json"
        data = _read_json(path)
        if data.get(key, {}).get("chat_id") != chat_id:
            return False
        del data[key]
        _write_json(path, data)
        return True


def _drop_delivered_registrations(state: Path, delivered: set[str]) -> None:
    with _locked(state):
        path = state / "registered.json"
        data = _read_json(path)
        keep = {key: entry for key, entry in data.items() if f"reg:{key}" not in delivered}
        if keep != data:
            _write_json(path, keep)


def add_start(state: Path, request: dict, at: float, reasons: list[str], now: float | None = None,
              key: str = "") -> str:
    """Queue a chat start (the dev connector's start_chat) as a usage-checked timer; returns its key."""
    now = time.time() if now is None else now
    key = key or uuid.uuid4().hex[:8]
    title = " ".join(str(request.get("args", {}).get("title") or request.get("args", {}).get("chat", "")).split())
    with _locked(state):
        path = state / "registered.json"
        data = _read_json(path)
        data[key] = {"chat_id": "", "kind": "timer", "on": f"start {title}"[:300], "since": now, "timeout_at": at,
                     "at": at, "usage_check": True, "start": request, "reasons": reasons, "attempts": 0}
        _write_json(path, data)
    return key


def starts(state: Path) -> dict[str, dict]:
    """Every queued chat start (key -> entry), fired or not."""
    return {key: entry for key, entry in _read_json(state / "registered.json").items() if "start" in entry}


def take_start(state: Path, key: str) -> dict | None:
    """Remove a queued start and return it (run now, cancel, or before starting it): never starts twice."""
    with _locked(state):
        path = state / "registered.json"
        data = _read_json(path)
        entry = data.get(key)
        if not entry or "start" not in entry:
            return None
        del data[key]
        _write_json(path, data)
    return entry


def put_start(state: Path, key: str, entry: dict) -> None:
    """Store a start back (a failed start to retry, or one kept as failed)."""
    with _locked(state):
        path = state / "registered.json"
        data = _read_json(path)
        data[key] = entry
        _write_json(path, data)


def due_starts(state: Path, now: float, usage: Callable[[], tuple[float, datetime]] | None = None,
               log=lambda event: None) -> dict[str, dict]:
    """Fire due timers (the usage check postpones a start while usage is used up) and take the fired starts."""
    settle_timers(state, now, usage, log)
    fired = {key for key, entry in starts(state).items() if entry.get("fired_at") and not entry.get("failed")}
    return {key: entry for key in fired if (entry := take_start(state, key))}


# ---------------------------------------------------------------------------
# Waking.
# ---------------------------------------------------------------------------


def wake_text(ready: list[Waiter]) -> str:
    shown = "; ".join(waiter.ready_text for waiter in ready[:3])
    more = f"; and {len(ready) - 3} more (`python3 scripts/claude_chat_waiters.py list`)" if len(ready) > 3 else ""
    return (WAKE_PREFIX + "A wait of this chat is over, so it was woken: " + shown + more
            + ". Continue the parked work now (if it is already done, say so in one line).")


# resume() outcomes that no later retry can fix (scripts/claude_dispatch.py resume_chat).
PERMANENT_WAKE_FAILURES = ("no transcript on this host", "its folder is gone")


def deliver(waiters: dict[str, list[Waiter]], live: dict, registry: dict[str, dict], state: Path, now: float, *,
            type_into, resume, room: int, log, asks=lambda chat: False,
            priority: dict[str, int] | None = None,
            resume_archived=lambda chat_id, ready: False, live_resume: set[str] | None = None) -> tuple[set[str], list[dict]]:
    """Serialize wakes from systemd, manual reap and admission."""
    state.mkdir(parents=True, exist_ok=True)
    with (state / "waiter-delivery.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return set(), []
        return _deliver(waiters, live, registry, state, now, type_into=type_into, resume=resume, room=room,
                        log=log, asks=asks, priority=priority, resume_archived=resume_archived, live_resume=live_resume)


def _deliver(waiters: dict[str, list[Waiter]], live: dict, registry: dict[str, dict], state: Path, now: float, *,
             type_into, resume, room: int, log, asks, priority, resume_archived,
             live_resume) -> tuple[set[str], list[dict]]:
    """Wake every chat with ready waiters once. `live` maps chat id -> lifecycle Chat.

    type_into(chat, text) -> bool types into a live pane chat; resume(chat_id, text) -> 'ok'
    or why not reopens a chat that is not running (at most `room` of them). A live chat
    whose last reply asks the owner something (`asks`) is not typed into: the owner's
    answer comes first and the chat retries then. Chats go in order: a finished job's
    result before a timer, then the rank of the chat's Task (`priority`: chat id -> 0
    urgent .. 3 low), then the longest wait. Returns the delivered waiter keys and the
    wake failures to list as stalled.
    """
    marks = _read_json(state / "waiter_wakes.json")
    delivered: set[str] = set()
    failures: list[dict] = []
    ranks = priority or {}

    def receipt(waiter: Waiter) -> str:
        return f"{waiter.key} {waiter.since:.6f}"

    def order(pair: tuple[str, list[Waiter]]) -> tuple:
        chat_id, items = pair
        ready = [w for w in items if w.ready] or items
        return (all(w.kind == "timer" for w in ready), ranks.get(chat_id, 4),
                min(w.ready_at or w.since for w in ready), chat_id)

    for chat_id, items in sorted(waiters.items(), key=order):
        delivered |= {w.key for w in items if w.ready and receipt(w) in marks}
        ready = [w for w in items if w.ready and w.key not in delivered]
        chat = live.get(chat_id)
        if chat is not None:
            # Its own background waiter already brought the CI result if the chat was active after it.
            ready = [w for w in ready if not (w.kind == "ci" and chat.last_activity > w.ready_at)]
            delivered |= {w.key for w in items if w.ready and w not in ready}
        if not ready:
            continue
        mark = f"{chat_id} {'+'.join(sorted(w.key for w in ready))}"
        if mark in marks:
            delivered |= {w.key for w in ready}
            continue
        text = wake_text(ready)
        if chat is not None:
            if chat.status != "idle" or chat.waiting_for or chat.kind != "pane" or asks(chat):
                if chat.kind != "pane" or asks(chat):
                    failures.append({"session_id": chat_id, "title": chat.title or chat.name,
                                     "reason": "wait is over but " + (
                                         "its last reply asks you something; your answer wakes it"
                                         if asks(chat) else "this Remote Control chat cannot be typed into: send "
                                         "it a message (connector send_message)"),
                                     "waits_on": [w.label(now) for w in ready]})
                continue  # busy or asking: a later cycle wakes it
            outcome = "ok" if type_into(chat, text) else "typing into its pane failed"
        elif (registry.get(chat_id) or {}).get("state") == "archived" and not resume_archived(chat_id, ready):
            delivered |= {w.key for w in ready}
            continue
        elif chat_id in (live_resume or ()):
            outcome = resume(chat_id, text)
        elif room <= 0:
            continue  # no free chat slot: next cycle
        else:
            outcome = resume(chat_id, text)
            room -= 1 if outcome == "ok" else 0
        log({"event": "waiter_woken" if outcome == "ok" else "waiter_wake_failed", "session_id": chat_id,
             "how": "typed" if chat is not None else "resumed", "outcome": outcome,
             "waiters": [w.key for w in ready]})
        if outcome == "ok":
            marks.update({receipt(w): _utc(now) for w in ready})
            delivered |= {w.key for w in ready}
        elif outcome.startswith(PERMANENT_WAKE_FAILURES):
            # Retrying cannot help (the chat lives on another host or its folder is gone):
            # drop these waiters after one report instead of failing every minute.
            marks.update({receipt(w): _utc(now) for w in ready})
            delivered |= {w.key for w in ready}
            log({"event": "waiter_dropped", "session_id": chat_id, "outcome": outcome,
                 "waiters": [w.key for w in ready]})
            failures.append({"session_id": chat_id, "title": (registry.get(chat_id) or {}).get("title", ""),
                             "reason": f"wait is over but the chat cannot be woken ({outcome}); waiting stopped",
                             "waits_on": [w.label(now) for w in ready]})
        else:
            failures.append({"session_id": chat_id, "title": (registry.get(chat_id) or {}).get("title", ""),
                             "reason": f"wait is over but waking it failed ({outcome})",
                             "waits_on": [w.label(now) for w in ready]})
    _write_json(state / "waiter_wakes.json", dict(sorted(marks.items(), key=lambda row: row[1])[-500:]))
    _drop_delivered_registrations(state, delivered)
    return delivered, failures


def status_entries(waiters: dict[str, list[Waiter]], live: dict, registry: dict[str, dict], now: float, *,
                   live_codex: set[str] | None = None) -> list[dict]:
    """status.json `waiting`: every chat that waits, running or not, with what on."""
    entries = []
    for chat_id, items in sorted(waiters.items()):
        chat = live.get(chat_id)
        stopped = registry.get(chat_id) or {}
        running = chat is not None or chat_id in (live_codex or ())
        if not running and stopped.get("state") == "archived" and not any(w.ready for w in items):
            continue
        entries.append({
            "session_id": chat_id, "title": (chat.title or chat.name) if chat else stopped.get("title", ""),
            "running": running, "waits_on": [w.label(now) for w in items],
            "kinds": sorted({w.kind for w in items}), "since": _utc(min(w.since for w in items)),
            "stalled": any(w.late(now) for w in items), "ready": any(w.ready for w in items),
            "timed_out": any(w.stalled(now) and not w.late(now) for w in items)})
    return entries


def stalled_entries(waiters: dict[str, list[Waiter]], live: dict, registry: dict[str, dict], now: float) -> list[dict]:
    """Waiters past their timeout, for status.json `stalled`."""
    entries = []
    for chat_id, items in sorted(waiters.items()):
        late = [w for w in items if w.late(now)]
        if not late:
            continue
        chat = live.get(chat_id)
        entries.append({
            "session_id": chat_id, "title": (chat.title or chat.name) if chat else (registry.get(chat_id) or {}).get(
                "title", ""), "kind": chat.kind if chat else (registry.get(chat_id) or {}).get("kind", ""),
            "last_activity": _utc(chat.last_activity) if chat else (registry.get(chat_id) or {}).get(
                "last_activity", ""),
            "reason": "waiter timed out: " + "; ".join(w.label(now) for w in late)
                      + (" (the chat may be stopped as idle now; it is reopened if the wait still ends)"),
            "stalled_waiters": [w.key for w in late], "stopped": chat is None})
    return entries


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def parse_at(value: str, usage_check: bool) -> tuple[float, bool]:
    """`--at` as epoch seconds: an ISO time with zone, or `usage-reset` (weekly reset + margin, usage-checked)."""
    if value == "usage-reset":
        return weekly_usage()[1].timestamp() + USAGE_RESET_MARGIN_SECONDS, True
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--at needs a time zone, e.g. 2026-11-20T10:05:00+00:00")
    return parsed.timestamp(), usage_check


def _state_dir() -> Path:
    import claude_idle_chats  # noqa: E402  (imports this module; only for the CLI)

    return claude_idle_chats.state_dir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("list", "add", "fire", "clear"))
    parser.add_argument("--chat", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    parser.add_argument("--kind", default="handoff", choices=REGISTERED_KINDS)
    parser.add_argument("--on", default="")
    parser.add_argument("--key", default="")
    parser.add_argument("--message", default="")
    parser.add_argument("--timeout-minutes", type=float)
    parser.add_argument("--at", default="", help="timer: ISO time with zone, or usage-reset")
    parser.add_argument("--usage-check", action="store_true", help="timer: wait while weekly usage is used up")
    parser.add_argument("--task", default="", help="automatically wake when this dependency Task UUID is done")
    args = parser.parse_args(argv)
    state = _state_dir()
    if args.command == "add":
        at, usage_check = parse_at(args.at, args.usage_check) if args.at else (None, False)
        on = args.message if args.kind == "timer" else args.on
        key = add(state, args.chat, args.kind, on, args.key, args.timeout_minutes, at=at, usage_check=usage_check, task_id=args.task)
        if at is not None:
            print(json.dumps({"key": key, "chat": args.chat, "fires": _utc(at), "usage_check": usage_check}))
            return 0
        print(json.dumps({"key": key, "chat": args.chat, "fire": f"python3 scripts/claude_chat_waiters.py fire "
                                                                  f"--chat {args.chat} --key {key} --message '...'"}))
        return 0
    if args.command == "fire":
        fire(state, args.chat, args.key, args.message)
        print(f"fired {args.key}: the chat lifecycle wakes or reopens chat {args.chat[:8]} within 5 minutes")
        return 0
    if args.command == "clear":
        return 0 if clear(state, args.chat, args.key) else 1
    import claude_chat_pending  # noqa: E402  (sibling script)
    import claude_idle_chats  # noqa: E402

    root = claude_idle_chats.canonical_root()
    now = time.time()
    found = collect(Sources(root=root, state=state, sessions=claude_chat_pending.session_ids_by_chat(root)), now)
    for chat_id, items in sorted(found.items()):
        print(chat_id, "; ".join(w.label(now) for w in items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
