#!/usr/bin/env python3
"""
scripts/session-cleanup.py

Periodic cleanup of stale Claude sessions based on Linear activity.

A session is considered stale if its linked Linear issue has not been
updated in the last 2 hours AND the Zellij session still exists. Before
killing, posts a resume comment on the Linear issue so work can be
continued later.

Protected sessions (containing 'claude', 'zellij', 'openmates', or
'opencode' in their Zellij session name) are never killed — these are
infrastructure/management sessions, not task-specific ones.

Designed to run every 5 minutes via systemd timer (see linear-cron-setup.sh).

Usage:
    python3 scripts/session-cleanup.py            # normal run
    python3 scripts/session-cleanup.py --dry-run   # show what would be cleaned
    python3 scripts/session-cleanup.py --threshold 1  # custom staleness (hours)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Ensure sibling modules are importable
_SCRIPTS_DIR = str(Path(__file__).parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _linear_client import (
    get_issue,
    get_issue_updated_at,
    post_comment,
    remove_label,
)
from _zellij_utils import (
    cleanup_exited_sessions,
    enforce_session_limit,
    kill_session,
    list_sessions,
    list_sessions_with_state,
)

PROJECT_ROOT = Path(__file__).parent.parent
SESSIONS_FILE = PROJECT_ROOT / ".claude" / "sessions.json"
STALE_THRESHOLD_HOURS = 2
LOG_PREFIX = "[session-cleanup]"

# Poller session tracking file (written by linear-poller.py)
POLLER_SESSIONS_FILE = PROJECT_ROOT / "scripts" / ".tmp" / "poller-sessions.json"
POLLER_SESSIONS_LOCK = PROJECT_ROOT / "scripts" / ".tmp" / "poller-sessions.lock"

# Minimum age (seconds) before treating a missing session as dead.
# Protects against race conditions during slow Zellij startup.
POLLER_DEAD_THRESHOLD_SECS = 300  # 5 minutes

# Session names containing any of these substrings are protected from cleanup.
# These are infrastructure/management sessions, not task-specific ones.
PROTECTED_NAME_PARTS = ("claude", "zellij", "openmates", "opencode")


def _is_protected_session(session_name: str) -> bool:
    """Check if a Zellij session name is protected from cleanup."""
    name_lower = session_name.lower()
    return any(part in name_lower for part in PROTECTED_NAME_PARTS)


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string to datetime. Returns None on failure."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def cleanup_stale_sessions(
    dry_run: bool = False,
    threshold_hours: float = STALE_THRESHOLD_HOURS,
) -> int:
    """
    Check all sessions linked to Linear issues and kill stale ones.

    A session is stale when:
    - It has a linear_issue_id
    - The Linear issue's updatedAt is older than threshold_hours
    - The Zellij session still exists
    - The session name is NOT protected

    Returns count of sessions cleaned.
    """
    if not SESSIONS_FILE.exists():
        return 0

    try:
        data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    sessions = data.get("sessions", {})
    if not sessions:
        return 0

    # Get active Zellij sessions for cross-reference
    active_zellij = set(list_sessions())
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=threshold_hours)

    cleaned = 0
    to_remove = []

    for sid, info in sessions.items():
        linear_id = info.get("linear_issue_id")
        if not linear_id:
            continue  # No Linear link — handled by existing 24h staleness

        zellij_name = info.get("zellij_session")

        # Skip protected sessions
        if zellij_name and _is_protected_session(zellij_name):
            continue

        # Check Linear updatedAt
        updated_at_str = get_issue_updated_at(linear_id)
        if not updated_at_str:
            continue  # Can't determine — skip

        updated_at = _parse_iso(updated_at_str)
        if not updated_at:
            continue

        if updated_at >= threshold:
            continue  # Still active — regular progress comments keep this fresh

        hours_stale = (now - updated_at).total_seconds() / 3600

        print(
            f"{LOG_PREFIX} {sid} ({linear_id}): stale — "
            f"Linear not updated for {hours_stale:.1f}h"
        )

        if dry_run:
            print(f"{LOG_PREFIX} [DRY RUN] Would kill session {sid}")
            continue

        # Post resume comment before killing
        linear_uuid = info.get("linear_uuid")
        if linear_uuid:
            resume_body = (
                f"**Session `{sid}` auto-cleaned** "
                f"(no Linear activity for {hours_stale:.1f}h)\n\n"
                f"**Resume:** `claude --resume {sid}`\n"
            )
            if zellij_name:
                resume_body += f"**Attach:** `zellij attach {zellij_name}`\n"
            resume_body += (
                "\nTo restart, add the `claude-plan` or `claude-fix` label again."
            )

            post_comment(linear_uuid, resume_body)

            # Remove claude-is-working label
            issue_data = get_issue(linear_id)
            if issue_data:
                remove_label(
                    issue_data["id"],
                    current_label_ids=issue_data.get("label_ids", []),
                )

        # Kill Zellij session if it exists
        if zellij_name and zellij_name in active_zellij:
            kill_session(zellij_name)
            print(f"{LOG_PREFIX}   Killed Zellij session: {zellij_name}")

        to_remove.append(sid)
        cleaned += 1

    # Remove cleaned sessions from sessions.json (with file lock)
    if to_remove:
        lock_path = SESSIONS_FILE.with_suffix(".lock")
        try:
            with open(lock_path, "w") as lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                fresh_data = json.loads(
                    SESSIONS_FILE.read_text(encoding="utf-8")
                )
                for sid in to_remove:
                    fresh_data.get("sessions", {}).pop(sid, None)
                tmp = SESSIONS_FILE.with_suffix(".tmp")
                with open(tmp, "w") as f:
                    json.dump(fresh_data, f, indent=2)
                    f.write("\n")
                tmp.replace(SESSIONS_FILE)
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError as e:
            print(
                f"{LOG_PREFIX} Warning: failed to update sessions.json: {e}",
                file=sys.stderr,
            )

    if cleaned:
        print(f"{LOG_PREFIX} Cleaned {cleaned} stale session(s)")
    return cleaned


# ── Poller Session Cleanup ──────────────────────────────────────────────────


def _read_poller_sessions() -> dict:
    """Read the poller sessions tracking file. Returns {} if missing."""
    try:
        if POLLER_SESSIONS_FILE.exists():
            return json.loads(POLLER_SESSIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _write_poller_sessions(data: dict) -> None:
    """Atomically write the poller sessions tracking file with file locking."""
    POLLER_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(POLLER_SESSIONS_LOCK, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            tmp = POLLER_SESSIONS_FILE.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            tmp.replace(POLLER_SESSIONS_FILE)
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except OSError as e:
        print(f"{LOG_PREFIX} Warning: failed to write poller-sessions.json: {e}", file=sys.stderr)


def cleanup_dead_poller_sessions(dry_run: bool = False) -> int:
    """
    Detect poller-spawned sessions that have exited or disappeared,
    update their Linear issues, and remove them from tracking.

    Returns count of sessions cleaned.
    """
    tracked = _read_poller_sessions()
    if not tracked:
        return 0

    zellij_state = list_sessions_with_state()
    now = datetime.now(timezone.utc)
    cleaned = 0
    to_remove: list[str] = []

    for session_name, info in tracked.items():
        state = zellij_state.get(session_name)
        identifier = info.get("identifier", "?")
        started_str = info.get("started", "")

        # Still running — skip
        if state == "ACTIVE":
            continue

        # If session is missing from Zellij entirely, enforce a minimum age
        # to avoid killing sessions that are still starting up
        if state is None:
            started = _parse_iso(started_str)
            if started and (now - started).total_seconds() < POLLER_DEAD_THRESHOLD_SECS:
                continue  # Too young — might still be starting

        status_desc = "EXITED" if state == "EXITED" else "disappeared"
        print(f"{LOG_PREFIX} {identifier}: session '{session_name}' {status_desc}")

        if dry_run:
            print(f"{LOG_PREFIX} [DRY RUN] Would clean up {session_name}")
            continue

        issue_id = info.get("issue_id")
        if issue_id:
            # Post completion comment
            mode = info.get("mode", "unknown")
            claude_sid = info.get("claude_session_id")
            resume_hint = ""
            if claude_sid:
                resume_hint = f"**Resume:** `claude --resume {claude_sid}`\n"

            post_comment(
                issue_id,
                f"**Session auto-completed** (Zellij session {status_desc})\n\n"
                f"Mode: {mode} | Session: `{session_name}`\n"
                f"{resume_hint}\n"
                f"To retry, re-add the `claude-fix`, `claude-research`, or `claude-plan` label."
            )

            # Remove claude-is-working label and set status to In Review
            issue_data = get_issue(identifier)
            if issue_data:
                remove_label(
                    issue_data["id"],
                    current_label_ids=issue_data.get("label_ids", []),
                )
                from _linear_client import update_issue_status
                update_issue_status(issue_data["id"], "In Review")

        # Delete EXITED Zellij session if it still exists
        if state == "EXITED":
            kill_session(session_name)

        to_remove.append(session_name)
        cleaned += 1

    # Update tracking file
    if to_remove:
        fresh = _read_poller_sessions()
        for name in to_remove:
            fresh.pop(name, None)
        _write_poller_sessions(fresh)

    if cleaned:
        print(f"{LOG_PREFIX} Cleaned {cleaned} dead poller session(s)")
    return cleaned


# ── Entry Point ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean up stale Claude sessions based on Linear activity"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be cleaned"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=STALE_THRESHOLD_HOURS,
        help=f"Staleness threshold in hours (default: {STALE_THRESHOLD_HOURS})",
    )
    args = parser.parse_args()
    cleanup_stale_sessions(dry_run=args.dry_run, threshold_hours=args.threshold)
    cleanup_dead_poller_sessions(dry_run=args.dry_run)
    # Enforce global session limit — kills EXITED first, then oldest idle
    if not args.dry_run:
        enforce_session_limit()


if __name__ == "__main__":
    main()
