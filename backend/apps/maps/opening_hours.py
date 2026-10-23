"""Enforce place-local closing times using structured Google opening periods.

Localized weekday descriptions are display text, never filter evidence. Current
hours override the regular schedule inside Google's seven-day coverage window.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any

MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
LOCAL_TIME_PATTERN = r"(?:[01]\d|2[0-3]):[0-5]\d"
LOCAL_DATE_PATTERN = r"\d{4}-\d{2}-\d{2}"


@dataclass(frozen=True)
class ClosingTimeConstraint:
    """A minimum closing time on a place-local calendar date (today by default)."""

    until: time
    on: date | None = None

    @classmethod
    def from_request(cls, request: dict[str, Any]) -> "ClosingTimeConstraint | None":
        """Validate raw skill calls as well as typed REST requests."""
        until, on = request.get("openUntil"), request.get("openOn")
        if until is None:
            if on is not None:
                raise ValueError("openOn requires openUntil")
            return None
        if not isinstance(until, str) or not re.fullmatch(LOCAL_TIME_PATTERN, until):
            raise ValueError("openUntil must be a local time in HH:MM format")
        if on is not None and (not isinstance(on, str) or not re.fullmatch(LOCAL_DATE_PATTERN, on)):
            raise ValueError("openOn must be a local date in YYYY-MM-DD format")
        try:
            return cls(time.fromisoformat(until), date.fromisoformat(on) if on else None)
        except ValueError as exc:
            raise ValueError("openOn must be a valid local date in YYYY-MM-DD format") from exc


def _point_minutes(point: Any) -> int | None:
    """Read a weekly endpoint, rejecting missing or malformed provider data."""
    if not isinstance(point, dict):
        return None
    day, hour, minute = point.get("day"), point.get("hour", 0), point.get("minute", 0)
    if not all(type(value) is int for value in (day, hour, minute)):
        return None
    if not (0 <= day <= 6 and 0 <= hour < 24 and 0 <= minute < 60):
        return None
    return day * MINUTES_PER_DAY + hour * 60 + minute


def _dated_point(point: dict[str, Any]) -> datetime | None:
    """Read an exact current-hours endpoint when its local date is available."""
    value = point.get("date")
    if not isinstance(value, dict) or _point_minutes(point) is None:
        return None
    try:
        return datetime(value["year"], value["month"], value["day"], point.get("hour", 0), point.get("minute", 0))
    except (KeyError, TypeError, ValueError):
        return None


def matches_closing_time(
    place: dict[str, Any], constraint: ClosingTimeConstraint, *, now: datetime | None = None,
) -> bool | None:
    """Return True for verified matches, False for conflicts, None for unknowns.

    A close exactly at the threshold meets "open until at least". Overnight
    periods wrap into the next day/week. An omitted close only means 24/7 for
    Google's documented regular Sunday-midnight sentinel, not arbitrary data.
    """
    if place.get("business_status") in {"CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY", "FUTURE_OPENING"}:
        return False
    raw = place.get("_raw")
    if not isinstance(raw, dict):
        return None
    offset = raw.get("utcOffsetMinutes")
    local_today = None
    if type(offset) is int and -MINUTES_PER_DAY < offset < MINUTES_PER_DAY:
        local_today = ((now or datetime.now(timezone.utc)) + timedelta(minutes=offset)).date()
    target_date = constraint.on or local_today
    if target_date is None:
        return None
    current = raw.get("currentOpeningHours")
    use_current = (
        local_today is not None and 0 <= (target_date - local_today).days < 7
        and isinstance(current, dict) and isinstance(current.get("periods"), list)
    )
    hours = current if use_current else raw.get("regularOpeningHours")
    if not isinstance(hours, dict) or not isinstance(hours.get("periods"), list):
        return None
    target = datetime.combine(target_date, constraint.until)
    target_week_minute = ((target_date.weekday() + 1) % 7) * MINUTES_PER_DAY + constraint.until.hour * 60 + constraint.until.minute
    unknown = False
    for period in hours["periods"]:
        if not isinstance(period, dict):
            unknown = True
            continue
        start, end = period.get("open"), period.get("close")
        start_minute = _point_minutes(start)
        if start_minute is None:
            unknown = True
            continue
        if end is None:
            if not use_current and start_minute == 0 and not start.get("truncated"):
                return True
            unknown = True
            continue
        end_minute = _point_minutes(end)
        if end_minute is None:
            unknown = True
            continue
        if use_current and ("date" in start or "date" in end):
            dated_start, dated_end = _dated_point(start), _dated_point(end)
            if dated_start is None or dated_end is None or dated_end <= dated_start:
                unknown = True
            elif dated_start <= target <= dated_end:
                return True
            continue
        if end_minute <= start_minute:
            end_minute += MINUTES_PER_WEEK
        if any(start_minute <= candidate <= end_minute for candidate in (target_week_minute, target_week_minute + MINUTES_PER_WEEK)):
            return True
    return None if unknown else False
