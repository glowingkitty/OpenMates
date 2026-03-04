"""
SQLite persistence for current service status and history.
Architecture: Status service stores its own independent event timeline.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status service tests not added yet)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from .config import EVENT_RETENTION_DAYS, RESPONSE_RETENTION_DAYS


@dataclass
class ServiceStatusRecord:
    environment: str
    group_name: str
    service_id: str
    service_name: str
    status: str
    response_time_ms: float | None
    last_error: str | None
    last_check_at: str


CREATE_SERVICE_STATUS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS service_status (
    id INTEGER PRIMARY KEY,
    environment TEXT NOT NULL,
    group_name TEXT NOT NULL,
    service_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    status TEXT NOT NULL,
    response_time_ms REAL,
    last_error TEXT,
    last_check_at TEXT NOT NULL,
    UNIQUE(environment, service_id)
);
"""

CREATE_STATUS_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS status_events (
    id INTEGER PRIMARY KEY,
    environment TEXT NOT NULL,
    group_name TEXT NOT NULL,
    service_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    response_time_ms REAL,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_RESPONSE_TIMES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS response_times (
    id INTEGER PRIMARY KEY,
    environment TEXT NOT NULL,
    service_id TEXT NOT NULL,
    response_time_ms REAL NOT NULL,
    checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_EVENTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_events_env_service_created
ON status_events (environment, service_id, created_at);
"""

CREATE_RESPONSE_TIMES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_response_env_service_checked
ON response_times (environment, service_id, checked_at);
"""


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(CREATE_SERVICE_STATUS_TABLE_SQL)
        await db.execute(CREATE_STATUS_EVENTS_TABLE_SQL)
        await db.execute(CREATE_RESPONSE_TIMES_TABLE_SQL)
        await db.execute(CREATE_EVENTS_INDEX_SQL)
        await db.execute(CREATE_RESPONSE_TIMES_INDEX_SQL)
        await db.commit()


async def upsert_service_status(db_path: str, record: ServiceStatusRecord) -> None:
    query = """
    INSERT INTO service_status (
        environment, group_name, service_id, service_name, status, response_time_ms, last_error, last_check_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(environment, service_id) DO UPDATE SET
        group_name = excluded.group_name,
        service_name = excluded.service_name,
        status = excluded.status,
        response_time_ms = excluded.response_time_ms,
        last_error = excluded.last_error,
        last_check_at = excluded.last_check_at;
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            query,
            (
                record.environment,
                record.group_name,
                record.service_id,
                record.service_name,
                record.status,
                record.response_time_ms,
                record.last_error,
                record.last_check_at,
            ),
        )
        await db.commit()


async def get_current_service_status(db_path: str, environment: str) -> list[dict[str, Any]]:
    query = """
    SELECT environment, group_name, service_id, service_name, status, response_time_ms, last_error, last_check_at
    FROM service_status
    WHERE environment = ?
    ORDER BY group_name, service_name;
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, (environment,))
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_previous_status(db_path: str, environment: str, service_id: str) -> str | None:
    query = """
    SELECT status
    FROM service_status
    WHERE environment = ? AND service_id = ?
    LIMIT 1;
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(query, (environment, service_id))
        row = await cursor.fetchone()
    if row is None:
        return None
    return str(row[0])


async def record_status_event_if_changed(
    db_path: str,
    *,
    environment: str,
    group_name: str,
    service_id: str,
    service_name: str,
    new_status: str,
    response_time_ms: float | None,
    error_message: str | None,
) -> None:
    previous_status = await get_previous_status(db_path, environment, service_id)
    if previous_status == new_status:
        return

    query = """
    INSERT INTO status_events (
        environment, group_name, service_id, service_name, previous_status, new_status, response_time_ms, error_message
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            query,
            (
                environment,
                group_name,
                service_id,
                service_name,
                previous_status,
                new_status,
                response_time_ms,
                error_message,
            ),
        )
        await db.commit()


async def add_response_time_sample(
    db_path: str, *, environment: str, service_id: str, response_time_ms: float | None
) -> None:
    if response_time_ms is None:
        return
    query = """
    INSERT INTO response_times (environment, service_id, response_time_ms)
    VALUES (?, ?, ?);
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(query, (environment, service_id, response_time_ms))
        await db.commit()


async def get_status_history(
    db_path: str,
    *,
    environment: str,
    service_id: str | None,
    since_iso: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    conditions = ["environment = ?"]
    params: list[Any] = [environment]
    if service_id:
        conditions.append("service_id = ?")
        params.append(service_id)
    if since_iso:
        conditions.append("created_at >= ?")
        params.append(since_iso)

    where_clause = " AND ".join(conditions)
    query = f"""
    SELECT id, environment, group_name, service_id, service_name, previous_status, new_status,
           response_time_ms, error_message, created_at
    FROM status_events
    WHERE {where_clause}
    ORDER BY created_at DESC
    LIMIT ?;
    """
    params.append(limit)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_response_time_series(
    db_path: str, *, environment: str, service_id: str, since_iso: str
) -> list[dict[str, Any]]:
    query = """
    SELECT response_time_ms, checked_at
    FROM response_times
    WHERE environment = ? AND service_id = ? AND checked_at >= ?
    ORDER BY checked_at ASC;
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, (environment, service_id, since_iso))
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def calculate_uptime_percentages(db_path: str, *, environment: str) -> list[dict[str, Any]]:
    statuses = await get_current_service_status(db_path, environment)
    now = datetime.now(timezone.utc)
    windows = {
        "24h": now - timedelta(hours=24),
        "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
    }

    results: list[dict[str, Any]] = []
    for status in statuses:
        service_id = str(status["service_id"])
        service_name = str(status["service_name"])
        group_name = str(status["group_name"])

        percentages: dict[str, float] = {}
        for label, start in windows.items():
            events = await get_status_history(
                db_path,
                environment=environment,
                service_id=service_id,
                since_iso=start.isoformat(),
                limit=10000,
            )
            if not events:
                current_status = str(status["status"])
                percentages[label] = 100.0 if current_status == "operational" else 0.0
                continue

            down_count = sum(1 for event in events if event["new_status"] == "down")
            degraded_count = sum(1 for event in events if event["new_status"] == "degraded")
            total_count = len(events)
            problem_ratio = (down_count + (degraded_count * 0.5)) / total_count
            percentages[label] = round(max(0.0, 100.0 * (1.0 - problem_ratio)), 2)

        results.append(
            {
                "service_id": service_id,
                "service_name": service_name,
                "group_name": group_name,
                "uptime": percentages,
            }
        )

    return results


async def cleanup_old_data(db_path: str) -> None:
    now = datetime.now(timezone.utc)
    cutoff_events = (now - timedelta(days=EVENT_RETENTION_DAYS)).isoformat()
    cutoff_response = (now - timedelta(days=RESPONSE_RETENTION_DAYS)).isoformat()

    delete_events_query = "DELETE FROM status_events WHERE created_at < ?"
    delete_response_query = "DELETE FROM response_times WHERE checked_at < ?"

    async with aiosqlite.connect(db_path) as db:
        await db.execute(delete_events_query, (cutoff_events,))
        await db.execute(delete_response_query, (cutoff_response,))
        await db.commit()
