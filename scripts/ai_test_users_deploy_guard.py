"""Keep AI test-user production runs out of production updates (owner, 23 Nov 2026).

On 23 Nov a manual prod run (12:05-12:13 UTC) fell into the minutes after the release went live: the new
API's chat-recovery cutover closed every WebSocket with client_update_required every 15 s, so 11 issues
("Please update OpenMates", voice calls that never connect) described the update, not the product.

A production run must not start while an update is pending, running or settling, and a run that still
overlapped one is marked so its PRODUCTION issues are read as deploy-time and start no debug chat.

Signals (all read from the dev host, nothing on production changes):
  marker     ~/.openmates/prod-update-in-progress, written by the update-prod-server workflow
             (`begin` before `openmates server update`, `end` after verification); honoured for 4 hours.
  pending    origin/main has a commit newer than production's last API start, within 12 hours: a release
             was merged and production has not restarted on it yet.
  settling   production's API started less than 45 minutes ago. Its chat-recovery auto cutover logs at every
             start (chat_recovery_auto_cutover); it retries for up to 30 minutes after a start.

    python3 scripts/ai_test_users_deploy_guard.py status
    python3 scripts/ai_test_users_deploy_guard.py begin --reason "release PR 537"
    python3 scripts/ai_test_users_deploy_guard.py end

Tests: scripts/tests/test_ai_test_users_deploy_guard.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = Path.home() / ".openmates" / "prod-update-in-progress"
MARKER_MAX_AGE = timedelta(hours=4)
SETTLE = timedelta(minutes=45)
PENDING_MAX_AGE = timedelta(hours=12)
WAIT_POLL_SECONDS = 300
WAIT_MAX = timedelta(minutes=90)
START_LOGGER = "chat_recovery_auto_cutover"
LOG_TIMEOUT_SECONDS = 90


class GuardUnavailable(RuntimeError):
    """The production update state could not be read; a prod run must not start blind."""


@dataclass
class State:
    """What the guard knows at one moment."""

    now: datetime
    marker: dict | None  # marker file content when present and fresh
    main_commit_at: datetime | None  # newest commit on origin/main
    api_start_logs: list[datetime]  # times of production auto-cutover log lines (each API start logs them)


def blocker(state: State) -> str | None:
    """Why a production run must not run now, or None."""
    if state.marker:
        since = state.marker.get("started_at", "?")
        return f"production update in progress (marker since {since}: {state.marker.get('reason', 'no reason')})"
    last_start = max(state.api_start_logs) if state.api_start_logs else None
    if last_start and state.now - last_start < SETTLE:
        minutes = int((state.now - last_start).total_seconds() // 60)
        return f"production API (re)started {minutes} min ago; waiting {int(SETTLE.total_seconds() // 60)} min to settle"
    main_at = state.main_commit_at
    if main_at and state.now - main_at < PENDING_MAX_AGE and (last_start is None or main_at > last_start):
        return f"release merged to main at {main_at:%H:%M} UTC is not live on production yet"
    return None


def overlap(started: datetime, ended: datetime, state: State) -> str | None:
    """Why a finished run overlapped a production update, or None."""
    if state.marker:
        return f"production update marker present at the end of the run ({state.marker.get('reason', 'no reason')})"
    window_start = started - SETTLE  # a start shortly before the run still settles during it
    hits = [t for t in state.api_start_logs if window_start <= t <= ended]
    if hits:
        return f"production API (re)started or cut over at {min(hits):%H:%M} UTC, during or just before this run"
    return None


def read_marker(path: Path, now: datetime) -> dict | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    started = datetime.fromisoformat(data["started_at"])
    if now - started > MARKER_MAX_AGE:
        return None
    return data


def main_commit_at() -> datetime | None:
    subprocess.run(["git", "-C", str(ROOT), "fetch", "-q", "origin", "main"], capture_output=True, timeout=120,
                   check=False)
    shown = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%ct", "origin/main"], capture_output=True,
                           text=True, timeout=30, check=False)
    if shown.returncode or not shown.stdout.strip():
        raise GuardUnavailable(f"origin/main could not be read: {shown.stderr.strip()[:200]}")
    return datetime.fromtimestamp(int(shown.stdout.strip()), UTC)


def api_start_logs(since_minutes: int = 10080) -> list[datetime]:
    """Times of production auto-cutover log lines (newest 50) through the Admin Debug API."""
    query = {"stream": "default", "mode": "select", "since_minutes": since_minutes, "limit": 50,
             "filters": [{"field": "message", "op": "like", "value": f"%{START_LOGGER}%"},
                         {"field": "message", "op": "not_like", "value": "%ADMIN_LOG_QUERY%"},
                         {"field": "service", "op": "eq", "value": "api"}]}
    shown = subprocess.run(["docker", "exec", "api", "python", "/app/backend/scripts/debug.py", "logs", "--prod",
                            "--o2", "--json", "--query-json", json.dumps(query)],
                           capture_output=True, text=True, timeout=LOG_TIMEOUT_SECONDS, check=False)
    if shown.returncode:
        raise GuardUnavailable(f"production logs could not be read: {shown.stderr.strip()[-200:]}")
    try:
        rows = json.loads(shown.stdout)["rows"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise GuardUnavailable(f"production log answer not understood: {exc}") from exc
    return [datetime.fromtimestamp(int(r["_timestamp"]) / 1_000_000, UTC) for r in rows]


def current(marker_path: Path = MARKER) -> State:
    now = datetime.now(UTC)
    return State(now=now, marker=read_marker(marker_path, now), main_commit_at=main_commit_at(),
                 api_start_logs=api_start_logs())


def wait_until_clear(read=current, sleep=time.sleep, poll_seconds: int = WAIT_POLL_SECONDS,
                     max_wait: timedelta = WAIT_MAX, log=print) -> str | None:
    """Pause while production is updating; None once clear, else the reason after `max_wait` (skip)."""
    waited = 0.0
    while True:
        reason = blocker(read())
        if reason is None:
            return None
        if waited >= max_wait.total_seconds():
            return reason
        log(f"prod run paused: {reason}")
        sleep(poll_seconds)
        waited += poll_seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Production update state for AI test-user runs.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    begin = sub.add_parser("begin")
    begin.add_argument("--reason", required=True)
    sub.add_parser("end")
    args = parser.parse_args(argv)
    if args.command == "begin":
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text(json.dumps({"started_at": datetime.now(UTC).isoformat(), "reason": args.reason}),
                          encoding="utf-8")
        print(f"marker set: {MARKER}")
        return 0
    if args.command == "end":
        MARKER.unlink(missing_ok=True)
        print("marker cleared; prod runs still wait 45 min after the API start")
        return 0
    reason = blocker(current())
    print(reason or "clear: production AI test-user runs may start")
    return 1 if reason else 0


if __name__ == "__main__":
    sys.exit(main())
