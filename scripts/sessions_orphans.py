"""Find and remove orphan sessions left behind by half-created ``start`` runs.

An orphan has no worktree, no tracked modified files and no write claim, so
removing it cannot lose work. Sessions that own a worktree (even a missing
directory with recorded metadata) or any tracked change are never touched.
"""

from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_MIN_AGE_SECONDS = 300


def _age_seconds(record: dict, now: datetime) -> float:
    stamp = record.get("last_active") or record.get("started") or ""
    try:
        parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return float("inf")
    return (now - parsed).total_seconds()


def is_orphan(record: dict, now: datetime, min_age_seconds: float) -> bool:
    """True when the session holds no worktree, changes or write claim."""
    if not isinstance(record, dict):
        return False
    worktree = record.get("worktree")
    if isinstance(worktree, dict) and worktree.get("path"):
        return False
    if record.get("modified_files") or record.get("writing"):
        return False
    return _age_seconds(record, now) >= min_age_seconds


def find_orphans(
    data: dict,
    *,
    session_id: str | None = None,
    min_age_seconds: float = DEFAULT_MIN_AGE_SECONDS,
    now: datetime | None = None,
) -> list[str]:
    """Return orphan session ids, optionally restricted to one session."""
    now = now or datetime.now(timezone.utc)
    sessions = data.get("sessions") or {}
    candidates = [session_id] if session_id else list(sessions)
    return [sid for sid in candidates if sid in sessions and is_orphan(sessions[sid], now, min_age_seconds)]


def remove_orphans(
    data: dict,
    *,
    session_id: str | None = None,
    min_age_seconds: float = DEFAULT_MIN_AGE_SECONDS,
    now: datetime | None = None,
) -> list[str]:
    """Delete orphan sessions from ``data`` in place; return their ids."""
    removed = find_orphans(data, session_id=session_id, min_age_seconds=min_age_seconds, now=now)
    for sid in removed:
        del data["sessions"][sid]
    return removed
