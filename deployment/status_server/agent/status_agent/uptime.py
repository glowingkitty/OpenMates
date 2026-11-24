"""Persistent outage and checker history shared by the status agent and host monitors."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .alerts import format_duration

SHORT_SECONDS = 600
MERGE_SECONDS = 180
Outcome = Literal["up", "down", "checker"]
Post = Callable[[str], bool]
SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    service TEXT NOT NULL, name TEXT NOT NULL, checked_at REAL NOT NULL,
    failed INTEGER NOT NULL, streak INTEGER NOT NULL,
    PRIMARY KEY (service, name)
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY, service TEXT NOT NULL, started_at REAL NOT NULL,
    check_name TEXT NOT NULL, error TEXT NOT NULL, recovered_at REAL, ended_at REAL,
    duration_seconds REAL GENERATED ALWAYS AS (ended_at - started_at) VIRTUAL,
    first_alert REAL, last_alert REAL, reminders INTEGER NOT NULL DEFAULT 0,
    recovery_sent INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_incident ON incidents(service) WHERE ended_at IS NULL;
CREATE TABLE IF NOT EXISTS checker_errors (
    service TEXT NOT NULL, check_name TEXT NOT NULL, checked_at REAL NOT NULL,
    error TEXT NOT NULL, PRIMARY KEY (service, check_name, checked_at)
);
"""


@dataclass(frozen=True)
class Observation:
    service: str
    check: str
    at: float
    outcome: Outcome
    error: str = ""
    notify: bool = True
    min_interval: int = 0
    max_gap: int | None = None


@dataclass(frozen=True)
class Policy:
    first_after: int = SHORT_SECONDS
    first_reminder: int = 1800
    repeat_every: int = 3600

    @classmethod
    def from_env(cls) -> Policy:
        return cls(
            max(SHORT_SECONDS, int(os.getenv("UPTIME_FIRST_ALERT_SECONDS", "600"))),
            max(1, int(os.getenv("UPTIME_FIRST_REMINDER_SECONDS", "1800"))),
            max(1, int(os.getenv("UPTIME_REPEAT_SECONDS", "3600"))),
        )


def _stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%d %b %H:%M UTC")


class Store:
    """SQLite serializes overlapping probes and retains closed incidents across restarts."""

    def __init__(self, path: Path, policy: Policy | None = None):
        self.path = path
        self.policy = policy or Policy.from_env()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=60)
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        return db

    def _observe(self, db: sqlite3.Connection, item: Observation) -> bool:
        previous = db.execute("SELECT * FROM checks WHERE service=? AND name=?",
                              (item.service, item.check)).fetchone()
        if previous and previous["checked_at"] >= item.at:
            return False
        failed = int(item.outcome == "down")
        if failed and previous and previous["streak"] and item.at - previous["checked_at"] < item.min_interval:
            return False
        prior_streak = previous["streak"] if previous else 0
        if previous and item.max_gap is not None and item.at - previous["checked_at"] > item.max_gap:
            prior_streak = 0
        streak = prior_streak + 1 if failed else 0
        if item.outcome == "checker":
            db.execute("INSERT OR IGNORE INTO checker_errors VALUES (?, ?, ?, ?)",
                       (item.service, item.check, item.at, item.error[:500]))
            failed = previous["failed"] if previous else 0
        db.execute("INSERT OR REPLACE INTO checks VALUES (?, ?, ?, ?, ?)",
                   (item.service, item.check, item.at, failed, streak))
        if item.outcome == "down":
            db.execute("""INSERT OR IGNORE INTO incidents(service, started_at, check_name, error)
                          VALUES (?, ?, ?, ?)""", (item.service, item.at, item.check, item.error[:500]))
            db.execute("UPDATE incidents SET recovered_at=NULL WHERE service=? AND ended_at IS NULL",
                       (item.service,))
        elif item.outcome == "up":
            db.execute("""UPDATE incidents SET recovered_at=?
                          WHERE service=? AND ended_at IS NULL AND recovered_at IS NULL
                          AND NOT EXISTS (SELECT 1 FROM checks WHERE service=? AND failed=1)""",
                       (item.at, item.service, item.service))
        return item.outcome == "down" and streak >= 2

    def record(self, observations: Iterable[Observation], now: float, post: Post) -> None:
        """Record observations once, then deliver messages supported by fresh evidence."""
        confirmed: dict[tuple[str, str], float] = {}
        with closing(self._connect()) as db:
            with db:
                db.execute("BEGIN IMMEDIATE")
                for item in sorted(observations, key=lambda item: item.at):
                    self._close_recovered(db, item.at)
                    if self._observe(db, item) and item.notify:
                        confirmed[item.service, item.check] = item.at
                self._close_recovered(db, now)
            # Commit observations before delivery and acknowledge each message
            # individually. A slow webhook cannot hold the lock across a batch.
            candidates = db.execute("""
                SELECT id FROM incidents WHERE
                (ended_at IS NULL AND recovered_at IS NULL)
                OR (ended_at IS NOT NULL AND first_alert IS NOT NULL AND recovery_sent=0)
                ORDER BY id
            """).fetchall()
            for candidate in candidates:
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT * FROM incidents WHERE id=?", (candidate["id"],)).fetchone()
                    self._notify(db, row, confirmed, now, post)

    @staticmethod
    def _close_recovered(db: sqlite3.Connection, at: float) -> None:
        db.execute("UPDATE incidents SET ended_at=recovered_at WHERE ended_at IS NULL AND recovered_at<=?",
                   (at - MERGE_SECONDS,))

    def _notify(self, db: sqlite3.Connection, row: sqlite3.Row, confirmed: dict[tuple[str, str], float], now: float, post: Post) -> None:
        start, end = row["started_at"], row["ended_at"]
        service = row["service"]
        if end is not None:
            if row["first_alert"] is None or row["recovery_sent"]:
                return
            message = f"✅ {service} recovered after {format_duration(end - start)} ({_stamp(start)} to {_stamp(end)})."
            if post(message):
                db.execute("UPDATE incidents SET recovery_sent=1 WHERE id=?", (row["id"],))
            return
        if row["recovered_at"] is not None or not confirmed:
            return
        latest = db.execute(
            "SELECT name, checked_at FROM checks WHERE service=? AND streak>=2", (service,)
        ).fetchall()
        confirmed_at = max((item["checked_at"] for item in latest
                            if confirmed.get((service, item["name"])) == item["checked_at"]), default=0)
        if confirmed_at < start + self.policy.first_after:
            return
        last = row["last_alert"]
        delay = self.policy.repeat_every if row["reminders"] else self.policy.first_reminder
        if last is not None and now - last < delay:
            return
        status = "still down" if last is not None else "down"
        if post(f"🚨 {service} {status} for {format_duration(now - start)}."):
            db.execute("""UPDATE incidents SET first_alert=coalesce(first_alert, ?), last_alert=?,
                          reminders=reminders+? WHERE id=?""", (now, now, int(last is not None), row["id"]))

    def active_services(self) -> set[str]:
        """Services awaiting confirmation or recovery."""
        if not self.path.is_file():
            return set()
        with closing(self._connect()) as db:
            return {row[0] for row in db.execute("SELECT service FROM incidents WHERE ended_at IS NULL")}

    def short_blips(self, since: float, until: float) -> tuple[int, float]:
        """Count recovered outages under ten minutes, using the observed recovery time."""
        if not self.path.is_file():
            return 0, 0.0
        with closing(self._connect()) as db:
            row = db.execute("""SELECT count(*), coalesce(sum(recovered_at-started_at), 0)
                                FROM incidents WHERE ended_at>=? AND ended_at<?
                                AND duration_seconds<?""", (since, until, SHORT_SECONDS)).fetchone()
        return row[0], row[1]
