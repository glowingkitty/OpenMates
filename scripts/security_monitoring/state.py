"""SQLite dispatch state for the hourly security watcher (plan decision D-4).

The store lives at logs/security-monitoring/state.sqlite3 (override with
SECURITY_MONITORING_DIR), outside git. It records runs, observations, triage
dispatches with their material fingerprints, verdicts, incidents, notification
receipts and the single-row triage lease that keeps at most one triage chat
running. In DRY_RUN mode the persistent database is copied read-only into
memory so planned actions are realistic while nothing on disk changes.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source_statuses TEXT NOT NULL DEFAULT '[]',
    outcome TEXT NOT NULL DEFAULT 'running',
    summary TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS observations (
    identity TEXT PRIMARY KEY,
    material_fingerprint TEXT NOT NULL,
    disposition TEXT NOT NULL,
    suppression_reason TEXT,
    facts TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dispatches (
    dispatch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity TEXT NOT NULL,
    material_fingerprint TEXT NOT NULL,
    reason TEXT NOT NULL,
    facts TEXT NOT NULL,
    triage_run_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (identity, material_fingerprint)
);
CREATE TABLE IF NOT EXISTS verdicts (
    verdict_id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity TEXT NOT NULL,
    material_fingerprint TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    verdict_json TEXT NOT NULL,
    triage_run_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('advisory', 'intrusion', 'health')),
    incident_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('open', 'acknowledged', 'resolved')),
    severity TEXT NOT NULL,
    details TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS incidents_by_key ON incidents (incident_key, state);
CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (incident_id, channel)
);
CREATE TABLE IF NOT EXISTS agent_runs (
    agent_run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('triage', 'fix')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS triage_lock (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    holder TEXT,
    expires_at TEXT
);
"""

OPEN_STATES = ("open", "acknowledged")


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class Store:
    """Thin typed wrapper; every method is one short transaction."""

    def __init__(self, connection: sqlite3.Connection, *, persistent: bool):
        self.connection = connection
        self.persistent = persistent
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        connection.execute("INSERT OR IGNORE INTO triage_lock (singleton, holder, expires_at) VALUES (1, NULL, NULL)")
        if persistent:
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.commit()

    # -- construction -------------------------------------------------
    @classmethod
    def open(cls, path: Path, *, dry_run: bool = False) -> "Store":
        if dry_run:
            return cls.snapshot_in_memory(path)
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND, 0o600)
        os.close(descriptor)
        connection = sqlite3.connect(path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return cls(connection, persistent=True)

    @classmethod
    def snapshot_in_memory(cls, path: Path) -> "Store":
        """Copy existing state without creating or touching any file."""
        memory = sqlite3.connect(":memory:", isolation_level=None)
        if path.exists():
            uri = f"file:{path.resolve()}?mode=ro&immutable=1"
            with closing(sqlite3.connect(uri, uri=True)) as source:
                source.backup(memory)
        return cls(memory, persistent=False)

    def close(self) -> None:
        self.connection.close()

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, tuple(params))

    # -- runs -----------------------------------------------------------
    def start_run(self, run_id: str, started_at: datetime) -> None:
        self._execute("INSERT INTO runs (run_id, started_at) VALUES (?, ?)", (run_id, utc(started_at)))

    def finish_run(self, run_id: str, finished_at: datetime, outcome: str, source_statuses: list[dict[str, Any]], summary: dict[str, Any]) -> None:
        self._execute(
            "UPDATE runs SET finished_at = ?, outcome = ?, source_statuses = ?, summary = ? WHERE run_id = ?",
            (utc(finished_at), outcome, _dumps(source_statuses), _dumps(summary), run_id),
        )

    def last_run_started(self, *, excluding: str | None = None) -> datetime | None:
        row = self._execute(
            "SELECT started_at FROM runs WHERE run_id != ? ORDER BY started_at DESC LIMIT 1", (excluding or "",)
        ).fetchone()
        return parse_utc(row["started_at"]) if row else None

    def last_successful_run_started(self) -> datetime | None:
        row = self._execute(
            "SELECT started_at FROM runs WHERE outcome IN ('complete', 'complete_with_findings') ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return parse_utc(row["started_at"]) if row else None

    def runs_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM runs WHERE started_at >= ? AND started_at < ? ORDER BY started_at", (utc(start), utc(end))
        ).fetchall()
        return [{**dict(row), "source_statuses": json.loads(row["source_statuses"]), "summary": json.loads(row["summary"])} for row in rows]

    # -- observations ---------------------------------------------------
    def upsert_observation(self, identity: str, fingerprint: str, disposition: str, suppression_reason: str | None, facts: dict[str, Any], now: datetime) -> None:
        self._execute(
            """INSERT INTO observations (identity, material_fingerprint, disposition, suppression_reason, facts, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(identity) DO UPDATE SET material_fingerprint = excluded.material_fingerprint,
                 disposition = excluded.disposition, suppression_reason = excluded.suppression_reason,
                 facts = excluded.facts, last_seen = excluded.last_seen""",
            (identity, fingerprint, disposition, suppression_reason, _dumps(facts), utc(now), utc(now)),
        )

    def observation(self, identity: str) -> dict[str, Any] | None:
        row = self._execute("SELECT * FROM observations WHERE identity = ?", (identity,)).fetchone()
        return {**dict(row), "facts": json.loads(row["facts"])} if row else None

    def suppressed_counts_since(self, since: datetime) -> dict[str, int]:
        rows = self._execute(
            """SELECT COALESCE(suppression_reason, disposition) AS reason, COUNT(*) AS n FROM observations
               WHERE disposition LIKE 'suppressed_%' AND last_seen >= ? GROUP BY reason""",
            (utc(since),),
        ).fetchall()
        return {row["reason"]: int(row["n"]) for row in rows}

    # -- dispatches -----------------------------------------------------
    def latest_dispatch(self, identity: str) -> dict[str, Any] | None:
        row = self._execute(
            "SELECT * FROM dispatches WHERE identity = ? ORDER BY dispatch_id DESC LIMIT 1", (identity,)
        ).fetchone()
        return {**dict(row), "facts": json.loads(row["facts"])} if row else None

    def last_completed_dispatch(self, identity: str) -> dict[str, Any] | None:
        row = self._execute(
            "SELECT * FROM dispatches WHERE identity = ? AND status = 'done' ORDER BY dispatch_id DESC LIMIT 1", (identity,)
        ).fetchone()
        return {**dict(row), "facts": json.loads(row["facts"])} if row else None

    def queue_dispatch(self, identity: str, fingerprint: str, reason: str, facts: dict[str, Any], now: datetime) -> None:
        self._execute(
            """INSERT INTO dispatches (identity, material_fingerprint, reason, facts, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'queued', ?, ?)
               ON CONFLICT(identity, material_fingerprint) DO UPDATE SET
                 status = CASE WHEN dispatches.status = 'failed' THEN 'queued' ELSE dispatches.status END,
                 updated_at = excluded.updated_at""",
            (identity, fingerprint, reason, _dumps(facts), utc(now), utc(now)),
        )

    def set_dispatch_status(self, keys: list[tuple[str, str]], status: str, triage_run_id: str | None, now: datetime, *, count_attempt: bool = False) -> None:
        for identity, fingerprint in keys:
            self._execute(
                """UPDATE dispatches SET status = ?, triage_run_id = COALESCE(?, triage_run_id), updated_at = ?,
                   attempts = attempts + ? WHERE identity = ? AND material_fingerprint = ?""",
                (status, triage_run_id, utc(now), 1 if count_attempt else 0, identity, fingerprint),
            )

    def dispatches_with_status(self, status: str) -> list[dict[str, Any]]:
        rows = self._execute("SELECT * FROM dispatches WHERE status = ? ORDER BY dispatch_id", (status,)).fetchall()
        return [{**dict(row), "facts": json.loads(row["facts"])} for row in rows]

    # -- verdicts -------------------------------------------------------
    def record_verdict(self, identity: str, fingerprint: str, outcome: str, reason: str | None, verdict: dict[str, Any], triage_run_id: str, now: datetime) -> None:
        self._execute(
            """INSERT INTO verdicts (identity, material_fingerprint, outcome, reason, verdict_json, triage_run_id, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (identity, fingerprint, outcome, reason, _dumps(verdict), triage_run_id, utc(now)),
        )

    def latest_verdict(self, identity: str) -> dict[str, Any] | None:
        row = self._execute(
            "SELECT * FROM verdicts WHERE identity = ? ORDER BY verdict_id DESC LIMIT 1", (identity,)
        ).fetchone()
        return {**dict(row), "verdict": json.loads(row["verdict_json"])} if row else None

    def not_affected_fingerprints(self) -> dict[str, str]:
        """Observation identity -> fingerprint of its latest verdict, if that verdict was not_affected."""
        rows = self._execute(
            """SELECT v.identity, v.material_fingerprint, v.outcome FROM verdicts v
               JOIN (SELECT identity, MAX(verdict_id) AS latest FROM verdicts GROUP BY identity) l
                 ON v.identity = l.identity AND v.verdict_id = l.latest"""
        ).fetchall()
        return {row["identity"]: row["material_fingerprint"] for row in rows if row["outcome"] == "not_affected"}

    def verdict_counts_since(self, since: datetime) -> dict[str, int]:
        rows = self._execute(
            "SELECT outcome, COUNT(*) AS n FROM verdicts WHERE recorded_at >= ? GROUP BY outcome", (utc(since),)
        ).fetchall()
        return {row["outcome"]: int(row["n"]) for row in rows}

    # -- incidents ------------------------------------------------------
    def open_incident(self, kind: str, key: str, severity: str, details: dict[str, Any], now: datetime) -> tuple[str, bool]:
        """Return (incident_id, created). An unresolved incident with the same key is reused."""
        row = self._execute(
            "SELECT incident_id FROM incidents WHERE incident_key = ? AND state IN ('open', 'acknowledged')", (key,)
        ).fetchone()
        if row:
            self._execute(
                "UPDATE incidents SET details = ?, updated_at = ? WHERE incident_id = ?",
                (_dumps(details), utc(now), row["incident_id"]),
            )
            return row["incident_id"], False
        sequence = self._execute("SELECT COUNT(*) FROM incidents WHERE incident_key = ?", (key,)).fetchone()[0]
        incident_id = f"{kind}-{abs(hash_key(key))}-{int(sequence) + 1}"
        self._execute(
            """INSERT INTO incidents (incident_id, kind, incident_key, state, severity, details, opened_at, updated_at)
               VALUES (?, ?, ?, 'open', ?, ?, ?, ?)""",
            (incident_id, kind, key, severity, _dumps(details), utc(now), utc(now)),
        )
        return incident_id, True

    def update_incident(self, incident_id: str, *, severity: str | None = None, details: dict[str, Any] | None = None, now: datetime) -> None:
        current = self.incident(incident_id)
        if current is None:
            raise KeyError(incident_id)
        merged = {**current["details"], **(details or {})}
        self._execute(
            "UPDATE incidents SET severity = ?, details = ?, updated_at = ? WHERE incident_id = ?",
            (severity or current["severity"], _dumps(merged), utc(now), incident_id),
        )

    def resolve_incident_key(self, key: str, now: datetime) -> list[str]:
        rows = self._execute(
            "SELECT incident_id FROM incidents WHERE incident_key = ? AND state IN ('open', 'acknowledged')", (key,)
        ).fetchall()
        for row in rows:
            self._execute(
                "UPDATE incidents SET state = 'resolved', resolved_at = ?, updated_at = ? WHERE incident_id = ?",
                (utc(now), utc(now), row["incident_id"]),
            )
        return [row["incident_id"] for row in rows]

    def resolve_incidents_with_prefix(self, prefix: str, keep: set[str], now: datetime) -> list[str]:
        rows = self._execute(
            "SELECT incident_key FROM incidents WHERE incident_key LIKE ? AND state IN ('open', 'acknowledged')",
            (prefix.replace("%", "") + "%",),
        ).fetchall()
        resolved: list[str] = []
        for row in rows:
            if row["incident_key"] not in keep:
                resolved.extend(self.resolve_incident_key(row["incident_key"], now))
        return resolved

    def acknowledge(self, incident_id: str, now: datetime) -> bool:
        cursor = self._execute(
            "UPDATE incidents SET state = 'acknowledged', updated_at = ? WHERE incident_id = ? AND state = 'open'",
            (utc(now), incident_id),
        )
        return cursor.rowcount == 1

    def incident(self, incident_id: str) -> dict[str, Any] | None:
        row = self._execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        return {**dict(row), "details": json.loads(row["details"])} if row else None

    def unresolved_incidents(self, kind: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM incidents WHERE state IN ('open', 'acknowledged')"
        params: tuple[Any, ...] = ()
        if kind:
            sql += " AND kind = ?"
            params = (kind,)
        rows = self._execute(sql + " ORDER BY opened_at", params).fetchall()
        return [{**dict(row), "details": json.loads(row["details"])} for row in rows]

    # -- notifications --------------------------------------------------
    def notification_state(self, incident_id: str, channel: str) -> str | None:
        row = self._execute(
            "SELECT state FROM notifications WHERE incident_id = ? AND channel = ?", (incident_id, channel)
        ).fetchone()
        return row["state"] if row else None

    def record_notification(self, notification_id: str, incident_id: str, channel: str, state: str, reason: str | None, now: datetime) -> None:
        self._execute(
            """INSERT INTO notifications (notification_id, incident_id, channel, state, reason, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(incident_id, channel) DO UPDATE SET state = excluded.state, reason = excluded.reason,
                 updated_at = excluded.updated_at""",
            (notification_id, incident_id, channel, state, reason, utc(now)),
        )

    def notifications(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._execute("SELECT * FROM notifications ORDER BY updated_at").fetchall()]

    # -- agent runs and limits -----------------------------------------
    def record_agent_run(self, agent_run_id: str, kind: str, started_at: datetime) -> None:
        self._execute(
            "INSERT INTO agent_runs (agent_run_id, kind, started_at, status) VALUES (?, ?, ?, 'running')",
            (agent_run_id, kind, utc(started_at)),
        )

    def finish_agent_run(self, agent_run_id: str, status: str, finished_at: datetime, detail: dict[str, Any]) -> None:
        self._execute(
            "UPDATE agent_runs SET status = ?, finished_at = ?, detail = ? WHERE agent_run_id = ?",
            (status, utc(finished_at), _dumps(detail), agent_run_id),
        )

    def agent_runs_on(self, kind: str, day: datetime) -> int:
        start = day.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        row = self._execute(
            "SELECT COUNT(*) FROM agent_runs WHERE kind = ? AND started_at >= ? AND started_at < ?",
            (kind, utc(start), utc(start + timedelta(days=1))),
        ).fetchone()
        return int(row[0])

    # -- triage lease ---------------------------------------------------
    def acquire_lease(self, holder: str, now: datetime, ttl: timedelta) -> bool:
        self._execute("BEGIN IMMEDIATE")
        row = self._execute("SELECT holder, expires_at FROM triage_lock WHERE singleton = 1").fetchone()
        if row["holder"] and row["expires_at"] and parse_utc(row["expires_at"]) > now and row["holder"] != holder:
            self._execute("COMMIT")
            return False
        self._execute(
            "UPDATE triage_lock SET holder = ?, expires_at = ? WHERE singleton = 1", (holder, utc(now + ttl))
        )
        self._execute("COMMIT")
        return True

    def release_lease(self, holder: str) -> None:
        self._execute("UPDATE triage_lock SET holder = NULL, expires_at = NULL WHERE singleton = 1 AND holder = ?", (holder,))

    def lease_holder(self, now: datetime) -> str | None:
        row = self._execute("SELECT holder, expires_at FROM triage_lock WHERE singleton = 1").fetchone()
        if row["holder"] and row["expires_at"] and parse_utc(row["expires_at"]) > now:
            return row["holder"]
        return None


def hash_key(key: str) -> int:
    """Deterministic short integer for readable incident ids (not security relevant)."""
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:10], 16)
