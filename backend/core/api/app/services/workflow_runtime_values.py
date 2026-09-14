"""Resolve deterministic calendar inputs when a workflow actually executes."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone as utc_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_workflow_runtime_values(value: Any, *, now: int | float | datetime | None = None, timezone: str = "UTC") -> Any:
    """Resolve {$date: today|next_week_start|next_week_end, format: date|datetime}.

    Upcoming week means the next Monday through Sunday in the workflow timezone.
    End datetimes are inclusive Sunday 23:59:59, suitable for event search bounds.
    The same supplied `now` must be used throughout a run and its node tests.
    """
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("Workflow runtime timezone is invalid") from exc
    if isinstance(now, datetime):
        current = now if now.tzinfo else now.replace(tzinfo=utc_timezone.utc)
    else:
        current = datetime.fromtimestamp(now, utc_timezone.utc) if now is not None else datetime.now(utc_timezone.utc)
    local = current.astimezone(zone)

    def resolve(item: Any) -> Any:
        if isinstance(item, list):
            return [resolve(child) for child in item]
        if not isinstance(item, dict):
            return item
        if "$date" not in item:
            return {key: resolve(child) for key, child in item.items()}
        if set(item) - {"$date", "format"}:
            raise ValueError("Runtime date input contains unsupported fields")
        name, output_format = item["$date"], item.get("format", "datetime")
        next_monday = local.date() + timedelta(days=7 - local.weekday())
        dates = {"today": local.date(), "next_week_start": next_monday, "next_week_end": next_monday + timedelta(days=6)}
        if not isinstance(name, str) or not isinstance(output_format, str) or name not in dates or output_format not in {"date", "datetime"}:
            raise ValueError("Runtime date input is invalid")
        day = dates[name]
        if output_format == "date":
            return day.isoformat()
        boundary = time(23, 59, 59) if name == "next_week_end" else time.min
        return datetime.combine(day, boundary, zone).isoformat()

    return resolve(value)
