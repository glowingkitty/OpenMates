"""Validate assistant-authored, account-free calendar event content.

Only explicit OpenMates JSON fences create calendar artifacts. Dates and context
are data, never calendar permissions; malformed primary events cannot be exported.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CALENDAR_EVENT_FENCE_LANGUAGES = frozenset({"openmates_calendar_event", "omcalendar"})
MAX_SOURCE_BYTES = 256 * 1024
MAX_CONTEXT_EVENTS = 50
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})\Z")


@dataclass(frozen=True)
class CalendarEventNormalizationResult:
    status: str
    model: dict[str, Any] | None
    source_json: str
    title: str
    warnings: list[dict[str, str]]
    parse_error: str | None = None


def is_calendar_event_fence(language: str | None) -> bool:
    return (language or "").strip().lower() in CALENDAR_EVENT_FENCE_LANGUAGES


def _text(value: Any, limit: int, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError("invalid_text")
    # Keep ordinary description paragraphs, but never transport control bytes.
    if any(ord(char) < 32 and char not in "\r\n\t" for char in value):
        raise ValueError("invalid_control_character")
    return value.strip() or None


def _time(value: Any) -> date | datetime:
    if not isinstance(value, str):
        raise ValueError("invalid_date")
    if DATE.fullmatch(value):
        return date.fromisoformat(value)
    if TIMESTAMP.fullmatch(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed
    raise ValueError("invalid_date_or_offset")


def normalize_calendar_event(raw: Any) -> dict[str, Any]:
    """Allowlisted event fields; never derive dates, durations, or permissions."""
    if not isinstance(raw, dict):
        raise ValueError("event_not_object")
    title = _text(raw.get("title"), 240, required=True)
    start = _time(raw.get("start"))
    event: dict[str, Any] = {"title": title, "start": raw["start"]}
    end = None
    if raw.get("end") is not None:
        end = _time(raw["end"])
        if type(start) is not type(end) or end <= start:
            raise ValueError("invalid_end")
        event["end"] = raw["end"]
    timezone = _text(raw.get("timezone"), 100)
    if timezone:
        try:
            zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("invalid_timezone") from exc
        for instant in (start, end):
            if isinstance(instant, datetime) and instant.astimezone(zone).utcoffset() != instant.utcoffset():
                raise ValueError("timezone_offset_mismatch")
        event["timezone"] = timezone
    for field, limit in (("description", 20_000), ("location", 2_000)):
        value = _text(raw.get(field), limit)
        if value:
            event[field] = value
    source = _text(raw.get("source_url"), 2_048)
    if source:
        try:
            parsed = urlsplit(source)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in source):
                raise ValueError("invalid_source_url")
        except ValueError as exc:
            raise ValueError("invalid_source_url") from exc
        event["source_url"] = source
    return event


def normalize_calendar_event_source(source: str) -> CalendarEventNormalizationResult:
    warnings: list[dict[str, str]] = []
    try:
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("source_too_large")
        raw = json.loads(source)
        if not isinstance(raw, dict) or raw.get("openmatesType") != "calendar_event" or type(raw.get("schemaVersion")) is not int or raw["schemaVersion"] != 1:
            raise ValueError("invalid_calendar_event_schema")
        primary = normalize_calendar_event(raw.get("primary_event"))
        supplied_context = raw.get("context_events", [])
        if not isinstance(supplied_context, list):
            supplied_context = []
            warnings.append({"code": "invalid_context", "path": "context_events"})
        context = []
        seen = {(primary["title"], primary["start"], primary.get("end"))}
        for index, item in enumerate(supplied_context[:MAX_CONTEXT_EVENTS]):
            try:
                event = normalize_calendar_event(item)
                identity = (event["title"], event["start"], event.get("end"))
                if identity not in seen:
                    context.append(event)
                    seen.add(identity)
            except ValueError:
                warnings.append({"code": "invalid_context_event", "path": f"context_events[{index}]"})
        if len(supplied_context) > MAX_CONTEXT_EVENTS:
            warnings.append({"code": "context_limit", "path": "context_events"})
        model = {"openmatesType": "calendar_event", "schemaVersion": 1, "primary_event": primary, "context_events": context}
        return CalendarEventNormalizationResult(
            "partial" if warnings else "valid", model,
            json.dumps(model, ensure_ascii=False, indent=2), primary["title"], warnings,
        )
    except (ValueError, TypeError, OverflowError, RecursionError):
        return CalendarEventNormalizationResult(
            "invalid_source", None, source[:MAX_SOURCE_BYTES],
            "Calendar event unavailable", [], "Invalid calendar event content",
        )
