"""Local primary-only iCalendar export for decoded event embeds.

No API request, account lookup, provider write, invitation, or context export is
performed. This current-client adapter follows the shared export fixtures; the
native Rust integration is tracked separately during the client migration.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, TypedDict
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


class CalendarEvent(TypedDict, total=False):
    title: str
    start: str
    end: str
    timezone: str
    description: str
    location: str
    source_url: str


class CalendarEventDocument(TypedDict):
    openmatesType: Literal["calendar_event"]
    schemaVersion: int
    primary_event: CalendarEvent
    context_events: list[CalendarEvent]


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})\Z")


def _time(value: Any) -> date | datetime:
    if not isinstance(value, str):
        raise ValueError("Invalid date")
    if _DATE.fullmatch(value):
        return date.fromisoformat(value)
    if _TIMESTAMP.fullmatch(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError("An explicit date or offset timestamp is required")


def _text(value: Any, limit: int, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in "\r\n\t" for c in value):
        raise ValueError("Invalid event text")
    value = value.strip()
    if required and not value:
        raise ValueError("Missing title")
    return value or None


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def _fold(value: str) -> str:
    chunks, current, length = [], "", 0
    for character in value:
        size = len(character.encode("utf-8"))
        if length + size > 75:
            chunks.append(current)
            current, length = " ", 1
        current += character
        length += size
    return "\r\n".join([*chunks, current])


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("-", "").replace(":", "").replace("+0000", "Z")


def build_calendar_event_file(embed_id: str, content: Any) -> str | None:
    """Return one VEVENT for a valid finished primary event, or None.

    The embed identity is the stable UID. Optional context events are never
    serialized. Timed starts without a known end stay without an invented end.
    """
    try:
        if not isinstance(embed_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", embed_id) or not isinstance(content, dict):
            return None
        if "status" in content and content["status"] != "finished":
            return None
        model = content["model"] if isinstance(content.get("model"), dict) else content
        if not model.get("primary_event") and isinstance(content.get("source_json"), str):
            if len(content["source_json"].encode("utf-8")) > 262_144:
                return None
            model = json.loads(content["source_json"])
        if not isinstance(model, dict) or (model.get("openmatesType") != "calendar_event" and model.get("type") != "calendar_event"):
            return None
        if "schemaVersion" in model and (type(model["schemaVersion"]) is not int or model["schemaVersion"] != 1):
            return None
        event = model.get("primary_event")
        if not isinstance(event, dict):
            return None
        title = _text(event.get("title"), 240, True)
        start = _time(event.get("start"))
        end = _time(event["end"]) if event.get("end") is not None else None
        if end is not None and (type(start) is not type(end) or end <= start):
            return None
        zone_name = _text(event.get("timezone"), 100)
        if zone_name:
            zone = ZoneInfo(zone_name)
            for value in (start, end):
                if isinstance(value, datetime) and value.astimezone(zone).utcoffset() != value.utcoffset():
                    return None
        extras = {key: _text(event.get(key), limit) for key, limit in [("description", 20_000), ("location", 2_000), ("source_url", 2_048)]}
        if extras["source_url"]:
            source = extras["source_url"]
            url = urlsplit(source)
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or any(c.isspace() for c in source):
                return None
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OpenMates//Embeds//EN", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
                 f"UID:{embed_id}@openmates", f"DTSTAMP:{_utc(datetime.now(timezone.utc))}"]
        if isinstance(start, datetime):
            lines.append(f"DTSTART:{_utc(start)}")
            if isinstance(end, datetime):
                lines.append(f"DTEND:{_utc(end)}")
        else:
            lines.extend([f"DTSTART;VALUE=DATE:{start.isoformat().replace('-', '')}",
                          f"DTEND;VALUE=DATE:{(end or start + timedelta(days=1)).isoformat().replace('-', '')}"])
        lines.append(f"SUMMARY:{_escape(title or '')}")
        for field, key in [("LOCATION", "location"), ("DESCRIPTION", "description"), ("URL", "source_url")]:
            if extras[key]:
                lines.append(f"{field}:{extras[key] if field == 'URL' else _escape(extras[key])}")
        return "\r\n".join(_fold(line) for line in [*lines, "END:VEVENT", "END:VCALENDAR"]) + "\r\n"
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError):
        return None
