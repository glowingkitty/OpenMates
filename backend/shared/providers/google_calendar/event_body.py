# backend/shared/providers/google_calendar/event_body.py
#
# Pure builders for Google Calendar event request bodies.
# Validates event times (timed with explicit offset or IANA timezone, all-day
# with date-only start and exclusive end, no nonexistent/ambiguous DST times)
# and keeps partial updates partial: omitted fields are never sent.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

import base64
import hashlib
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_TITLE_LENGTH = 1024
MAX_DESCRIPTION_LENGTH = 8192
MAX_LOCATION_LENGTH = 1024
MAX_ATTENDEES = 100
SEND_UPDATES_VALUES = frozenset({"none", "all", "externalOnly"})


class EventInputError(ValueError):
    """User-correctable event input problem with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise EventInputError("invalid_timezone", f"Unknown IANA timezone: {name}") from exc


def is_all_day(value: str) -> bool:
    return bool(_DATE_ONLY.match(value or ""))


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00") if value.endswith("Z") else value)
    except ValueError as exc:
        raise EventInputError("invalid_time", f"Not an ISO 8601 date-time: {value}") from exc


def _check_local_time(local: datetime, zone: ZoneInfo, raw: str) -> None:
    first = local.replace(tzinfo=zone, fold=0)
    second = local.replace(tzinfo=zone, fold=1)
    # A skipped (spring-forward) time does not survive a UTC round trip; check it
    # first, because fold=0/1 also report different offsets inside the gap.
    round_trip = first.astimezone(dt_timezone.utc).astimezone(zone).replace(tzinfo=None)
    if round_trip != local:
        raise EventInputError(
            "nonexistent_local_time", f"{raw} does not exist in {zone.key} (DST change).",
        )
    if first.utcoffset() != second.utcoffset():
        raise EventInputError(
            "ambiguous_local_time",
            f"{raw} happens twice in {zone.key} (DST change); give an explicit UTC offset.",
        )


def event_time(value: str, timezone_name: str | None) -> tuple[dict[str, str], datetime | date]:
    """Return Google's start/end object and a comparable value."""

    if not isinstance(value, str) or not value.strip():
        raise EventInputError("invalid_time", "Event start and end are required.")
    value = value.strip()
    if is_all_day(value):
        try:
            return {"date": value}, date.fromisoformat(value)
        except ValueError as exc:
            raise EventInputError("invalid_time", f"Not a calendar date: {value}") from exc
    parsed = _parse_datetime(value)
    if parsed.tzinfo is None:
        if not timezone_name:
            raise EventInputError(
                "timezone_required",
                f"{value} has no UTC offset; give an offset or an IANA timezone. "
                "OpenMates never guesses a timezone.",
            )
        zone = _zone(timezone_name)
        _check_local_time(parsed, zone, value)
        return {"dateTime": value, "timeZone": zone.key}, parsed.replace(tzinfo=zone)
    body = {"dateTime": value}
    if timezone_name:
        body["timeZone"] = _zone(timezone_name).key
    return body, parsed


def event_range(
    start: str, end: str | None, timezone_name: str | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Validate a start/end pair. A single all-day event may omit end."""

    start_body, start_value = event_time(start, timezone_name)
    if end is None or (isinstance(end, str) and not end.strip()):
        if isinstance(start_value, datetime):
            raise EventInputError("end_required", "Timed events need an end time.")
        return start_body, {"date": (start_value + timedelta(days=1)).isoformat()}
    end_body, end_value = event_time(end, timezone_name)
    if isinstance(start_value, datetime) != isinstance(end_value, datetime):
        raise EventInputError(
            "mixed_all_day", "Start and end must both be dates (all-day) or both date-times.",
        )
    if end_value <= start_value:  # type: ignore[operator]  # same kind checked above
        raise EventInputError(
            "end_before_start",
            "End must be after start (all-day end dates are exclusive: a one-day event on "
            "2026-11-20 ends 2026-11-21).",
        )
    return start_body, end_body


def _bounded(value: str, limit: int, field: str) -> str:
    if len(value) > limit:
        raise EventInputError("field_too_long", f"{field} is longer than {limit} characters.")
    return value


def _attendees(emails: list[str]) -> list[dict[str, str]]:
    if len(emails) > MAX_ATTENDEES:
        raise EventInputError("too_many_attendees", f"At most {MAX_ATTENDEES} attendees.")
    cleaned = []
    for email in emails:
        email = str(email).strip()
        if "@" not in email or " " in email:
            raise EventInputError("invalid_attendee", f"Not an email address: {email}")
        cleaned.append({"email": email})
    return cleaned


def create_body(
    *,
    title: str,
    start: str,
    end: str | None,
    timezone_name: str | None = None,
    location: str | None = None,
    description: str | None = None,
    attendees: list[str] | None = None,
    reminder_minutes: list[int] | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    if not title or not title.strip():
        raise EventInputError("title_required", "Event title is required.")
    start_body, end_body = event_range(start, end, timezone_name)
    body: dict[str, Any] = {
        "summary": _bounded(title.strip(), MAX_TITLE_LENGTH, "title"),
        "start": start_body,
        "end": end_body,
    }
    if location:
        body["location"] = _bounded(location, MAX_LOCATION_LENGTH, "location")
    if description:
        body["description"] = _bounded(description, MAX_DESCRIPTION_LENGTH, "description")
    if attendees:
        body["attendees"] = _attendees(attendees)
    if reminder_minutes is not None:
        body["reminders"] = _reminders(reminder_minutes)
    if event_id:
        body["id"] = event_id
    return body


def patch_body(
    *,
    current: dict[str, Any],
    title: str | None = None,
    start: str | None = None,
    end: str | None = None,
    timezone_name: str | None = None,
    location: str | None = None,
    description: str | None = None,
    attendees: list[str] | None = None,
    reminder_minutes: list[int] | None = None,
) -> dict[str, Any]:
    """Build a PATCH body holding only the fields the caller asked to change.

    ``location``/``description`` set to "" clear the value; None leaves it alone.
    Changing only start or end validates against the current other bound.
    """

    body: dict[str, Any] = {}
    if title is not None:
        if not title.strip():
            raise EventInputError("title_required", "Event title cannot be empty.")
        body["summary"] = _bounded(title.strip(), MAX_TITLE_LENGTH, "title")
    if start is not None or end is not None:
        current_start = current.get("start") or {}
        current_end = current.get("end") or {}
        new_start = start or current_start.get("dateTime") or current_start.get("date")
        new_end = end or current_end.get("dateTime") or current_end.get("date")
        zone = timezone_name or current_start.get("timeZone")
        if not new_start:
            raise EventInputError("invalid_time", "The event has no start to keep.")
        body["start"], body["end"] = event_range(new_start, new_end, zone)
    if location is not None:
        body["location"] = _bounded(location, MAX_LOCATION_LENGTH, "location")
    if description is not None:
        body["description"] = _bounded(description, MAX_DESCRIPTION_LENGTH, "description")
    if attendees is not None:
        body["attendees"] = _attendees(attendees)
    if reminder_minutes is not None:
        body["reminders"] = _reminders(reminder_minutes)
    if not body:
        raise EventInputError("nothing_to_update", "No event field to change was given.")
    return body


def _reminders(minutes: list[int]) -> dict[str, Any]:
    if len(minutes) > 5:
        raise EventInputError("too_many_reminders", "Google Calendar allows at most 5 reminders.")
    for value in minutes:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 40320:
            raise EventInputError("invalid_reminder", "Reminders are 0 to 40320 minutes before start.")
    return {"useDefault": False, "overrides": [{"method": "popup", "minutes": m} for m in minutes]}


def idempotent_event_id(operation_key: str) -> str:
    """Stable Google event id (base32hex alphabet a-v, 0-9) for one create operation."""

    digest = hashlib.sha256(operation_key.encode("utf-8")).digest()
    return "om" + base64.b32hexencode(digest).decode("ascii").rstrip("=").lower()


def validate_send_updates(value: str | None) -> str:
    """Notifications stay off unless the caller explicitly chose a policy."""

    if value is None:
        return "none"
    if value not in SEND_UPDATES_VALUES:
        raise EventInputError("invalid_send_updates", "send_updates must be none, all or externalOnly.")
    return value
