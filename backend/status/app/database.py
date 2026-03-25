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


async def get_daily_service_status(
    db_path: str, *, environment: str, service_id: str, days: int = 90
) -> list[dict[str, Any]]:
    """Get per-day worst status for a service over N days.

    Returns a list of {date, status} dicts for each day, filling gaps with 'unknown'.
    Used for the 90-day uptime bar on the status page.
    """
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()

    # Get all events in the time range
    query = """
    SELECT new_status, created_at
    FROM status_events
    WHERE environment = ? AND service_id = ? AND created_at >= ?
    ORDER BY created_at ASC;
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(query, (environment, service_id, since))
        rows = await cursor.fetchall()

    # Also get current status for today
    current_query = """
    SELECT status FROM service_status
    WHERE environment = ? AND service_id = ?
    LIMIT 1;
    """
    current_status = "unknown"
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(current_query, (environment, service_id))
        row = await cursor.fetchone()
        if row:
            current_status = str(row[0])

    # Build day -> worst status map
    STATUS_PRIORITY = {"down": 3, "degraded": 2, "operational": 1, "unknown": 0}
    day_status: dict[str, str] = {}

    for new_status, created_at in rows:
        date_str = str(created_at)[:10]
        existing = day_status.get(date_str, "operational")
        if STATUS_PRIORITY.get(str(new_status), 0) > STATUS_PRIORITY.get(existing, 0):
            day_status[date_str] = str(new_status)

    # Fill all days in the range
    result: list[dict[str, Any]] = []
    for i in range(days):
        date = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        status = day_status.get(date, "unknown")
        # If no events for a day and we have current status, assume operational
        if status == "unknown" and current_status == "operational":
            status = "operational"
        result.append({"date": date, "status": status})

    # Override today with current live status
    today = now.strftime("%Y-%m-%d")
    if result and result[-1]["date"] == today:
        result[-1]["status"] = current_status

    return result


async def get_response_time_series_hourly(
    db_path: str, *, environment: str, service_id: str, hours: int = 168
) -> list[dict[str, Any]]:
    """Get hourly average response times for a service over N hours (default 7 days).

    Returns a list of {timestamp, avg_ms} dicts.
    Used for the provider response time graph.
    """
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).isoformat()

    query = """
    SELECT
        strftime('%Y-%m-%dT%H:00:00Z', checked_at) as hour_bucket,
        AVG(response_time_ms) as avg_ms,
        MIN(response_time_ms) as min_ms,
        MAX(response_time_ms) as max_ms,
        COUNT(*) as sample_count
    FROM response_times
    WHERE environment = ? AND service_id = ? AND checked_at >= ?
    GROUP BY hour_bucket
    ORDER BY hour_bucket ASC;
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, (environment, service_id, since))
        rows = await cursor.fetchall()

    return [
        {
            "timestamp": row["hour_bucket"],
            "avg_ms": round(float(row["avg_ms"]), 1),
            "min_ms": round(float(row["min_ms"]), 1),
            "max_ms": round(float(row["max_ms"]), 1),
            "samples": int(row["sample_count"]),
        }
        for row in rows
    ]


async def get_intraday_checks(
    db_path: str, *, environment: str, service_id: str, date: str
) -> list[dict[str, Any]]:
    """Get all health checks for a service on a specific date.

    Returns a list of individual checks with exact timestamps, status, response time, and error.
    Used for intra-day drill-down when clicking a day on the uptime bar.
    """
    # Get response time samples for this day (these are recorded on every check)
    rt_query = """
    SELECT response_time_ms, checked_at
    FROM response_times
    WHERE environment = ? AND service_id = ? AND checked_at LIKE ?
    ORDER BY checked_at ASC;
    """
    # Get status events for this day (recorded only on status change)
    ev_query = """
    SELECT new_status, error_message, response_time_ms, created_at
    FROM status_events
    WHERE environment = ? AND service_id = ? AND created_at LIKE ?
    ORDER BY created_at ASC;
    """
    date_pattern = f"{date}%"

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(rt_query, (environment, service_id, date_pattern))
        rt_rows = await cursor.fetchall()

        cursor = await db.execute(ev_query, (environment, service_id, date_pattern))
        ev_rows = await cursor.fetchall()

    # Build a map of event timestamps to status changes
    event_map: dict[str, dict[str, Any]] = {}
    for row in ev_rows:
        ts = str(row["created_at"])
        event_map[ts] = {
            "status": str(row["new_status"]),
            "error": row["error_message"],
        }

    # Build check list from response time samples + overlay status changes
    checks: list[dict[str, Any]] = []
    last_known_status = "operational"

    # Get status at start of day from the last event before this date
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """SELECT new_status FROM status_events
            WHERE environment = ? AND service_id = ? AND created_at < ?
            ORDER BY created_at DESC LIMIT 1""",
            (environment, service_id, f"{date}T00:00:00"),
        )
        row = await cursor.fetchone()
        if row:
            last_known_status = str(row[0])

    for rt_row in rt_rows:
        ts = str(rt_row["checked_at"])
        time_part = ts[11:19] if len(ts) >= 19 else ts[11:]

        # Check if there's a status event close to this timestamp
        status = last_known_status
        error = None
        for evt_ts, evt_data in event_map.items():
            if evt_ts[:16] == ts[:16]:  # Same minute
                status = evt_data["status"]
                error = evt_data["error"]
                last_known_status = status
                break

        check_entry: dict[str, Any] = {
            "time": time_part,
            "status": status,
            "response_time_ms": round(float(rt_row["response_time_ms"]), 1),
        }
        if error:
            check_entry["error"] = error
        checks.append(check_entry)

    # Add any status events that don't have matching response time samples
    for evt_ts, evt_data in event_map.items():
        time_part = evt_ts[11:19] if len(evt_ts) >= 19 else evt_ts[11:]
        # Check if we already have a check at this time
        already_covered = any(c["time"][:5] == time_part[:5] for c in checks)
        if not already_covered:
            check_entry = {
                "time": time_part,
                "status": evt_data["status"],
                "response_time_ms": None,
            }
            if evt_data["error"]:
                check_entry["error"] = evt_data["error"]
            checks.append(check_entry)

    checks.sort(key=lambda c: c["time"])
    return checks


async def get_incidents(
    db_path: str, *, environment: str, since_days: int = 14
) -> list[dict[str, Any]]:
    """Get incidents (status transitions to degraded/down) grouped with resolution.

    An incident starts when a service transitions to degraded/down and ends when
    it transitions back to operational.
    Returns reverse-chronological list of incidents.
    """
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=since_days)).isoformat()

    query = """
    SELECT service_id, service_name, group_name, new_status, previous_status,
           error_message, created_at
    FROM status_events
    WHERE environment = ? AND created_at >= ?
    ORDER BY created_at ASC;
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, (environment, since))
        rows = await cursor.fetchall()

    # Group events into incidents
    open_incidents: dict[str, dict[str, Any]] = {}  # service_id -> open incident
    closed_incidents: list[dict[str, Any]] = []

    for row in rows:
        sid = str(row["service_id"])
        new_status = str(row["new_status"])
        created_at = str(row["created_at"])

        if new_status in ("down", "degraded"):
            if sid not in open_incidents:
                open_incidents[sid] = {
                    "component": str(row["service_name"]),
                    "group": str(row["group_name"]),
                    "severity": new_status,
                    "started_at": created_at,
                    "resolved_at": None,
                    "duration_minutes": None,
                    "updates": [],
                }
            incident = open_incidents[sid]
            # Update severity to worst
            if new_status == "down":
                incident["severity"] = "down"
            incident["updates"].append({
                "status": new_status,
                "timestamp": created_at,
            })
        elif new_status == "operational" and sid in open_incidents:
            incident = open_incidents.pop(sid)
            incident["resolved_at"] = created_at
            incident["updates"].append({
                "status": "operational",
                "timestamp": created_at,
            })
            # Calculate duration
            try:
                start = datetime.fromisoformat(incident["started_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                incident["duration_minutes"] = int((end - start).total_seconds() / 60)
            except (ValueError, TypeError):
                pass
            closed_incidents.append(incident)

    # Add still-open incidents
    for incident in open_incidents.values():
        try:
            start = datetime.fromisoformat(incident["started_at"].replace("Z", "+00:00"))
            incident["duration_minutes"] = int((now - start).total_seconds() / 60)
        except (ValueError, TypeError):
            pass
        closed_incidents.append(incident)

    # Sort by start time, most recent first
    closed_incidents.sort(key=lambda i: i["started_at"], reverse=True)
    return closed_incidents


async def compute_uptime_pct(
    db_path: str, *, environment: str, service_id: str, days: int = 90
) -> float:
    """Compute uptime percentage for a service over N days.

    Uses the daily status data: operational = 100%, degraded = 50%, down = 0%.
    Days with no data are counted as operational.
    """
    daily = await get_daily_service_status(db_path, environment=environment, service_id=service_id, days=days)
    if not daily:
        return 100.0

    score = 0.0
    for day in daily:
        status = day["status"]
        if status == "operational":
            score += 1.0
        elif status == "degraded":
            score += 0.5
        # down and unknown = 0

    return round(100.0 * score / len(daily), 1)


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
