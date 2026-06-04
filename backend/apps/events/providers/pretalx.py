# backend/apps/events/providers/pretalx.py
#
# pretalx/C3VOC conference schedule provider for Chaos events.
#
# Fetches public schedule exports, caches them briefly, and searches locally.
# This is intentionally scoped to known conference schedules, not generic city
# event discovery. The public export includes enough metadata for event cards
# without requiring authenticated pretalx API access or per-result enrichment.

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

from backend.shared.testing.caching_http_transport import create_http_client

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 20.0
_CACHE_TTL_SECONDS = 2 * 60 * 60
_MAX_DESCRIPTION_CHARS = 2000
_LOCAL_TZ = ZoneInfo("Europe/Berlin")


CONFERENCES: Dict[str, Dict[str, Any]] = {
    "gpn24": {
        "title": "GPN24",
        "location": "Karlsruhe, Germany",
        "schedule_url": "https://cfp.gulas.ch/gpn24/schedule/export/schedule.json",
        "aliases": {"gpn", "gpn24", "gulasch", "gulaschprogrammiernacht"},
    },
    "39c3": {
        "title": "39C3",
        "location": "Hamburg, Germany",
        "schedule_url": "https://cfp.cccv.de/39c3/schedule/export/schedule.json",
        "aliases": {"39c3", "ccc congress", "chaos congress", "chaos communication congress"},
    },
    "38c3": {
        "title": "38C3",
        "location": "Hamburg, Germany",
        "schedule_url": "https://cfp.cccv.de/38c3/schedule/export/schedule.json",
        "aliases": {"38c3"},
    },
    "37c3": {
        "title": "37C3",
        "location": "Hamburg, Germany",
        "schedule_url": "https://pretalx.com/37c3/schedule/export/schedule.json",
        "aliases": {"37c3"},
    },
}

_ALIAS_TO_CONFERENCE: Dict[str, str] = {
    alias: key
    for key, conference in CONFERENCES.items()
    for alias in conference["aliases"] | {key}
}

_SCHEDULE_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


def resolve_conference(value: Optional[str], query: str = "", location: str = "") -> Optional[str]:
    """Resolve a conference key from explicit input, query text, or location."""
    candidates = [value or "", query or "", location or ""]
    for candidate in candidates:
        normalized = candidate.lower().replace("-", " ").replace("_", " ")
        compact = normalized.replace(" ", "")
        if compact in _ALIAS_TO_CONFERENCE:
            return _ALIAS_TO_CONFERENCE[compact]
        for alias, conference_key in _ALIAS_TO_CONFERENCE.items():
            if alias in normalized or alias.replace(" ", "") in compact:
                return conference_key
    return None


def is_conference_query(query: str, location: str = "") -> bool:
    """Return true if the text explicitly references a known conference."""
    return resolve_conference(None, query=query, location=location) is not None


async def search_events_async(
    query: str,
    conference: Optional[str] = None,
    location: str = "",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    count: int = 10,
    past_events: bool = False,
    now: Optional[datetime] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Search a known pretalx/C3VOC schedule export."""
    conference_key = resolve_conference(conference, query=query, location=location)
    if not conference_key:
        raise ValueError("Missing or unknown conference. Try GPN24, 39C3, 38C3, or 37C3.")

    count = max(1, min(count, 50))
    events = await _get_schedule_events(conference_key)
    current_time = now or datetime.now(timezone.utc)
    normalized = [
        _normalize_event(raw, conference_key)
        for raw in events
    ]

    filtered = [
        event
        for event in normalized
        if _passes_date_filters(event, start_date, end_date, past_events, current_time)
    ]
    ranked = _rank_events(filtered, query=query, conference_key=conference_key)
    return ranked[:count], len(ranked)


async def _get_schedule_events(conference_key: str) -> List[Dict[str, Any]]:
    cached = _SCHEDULE_CACHE.get(conference_key)
    now_monotonic = time.monotonic()
    if cached and now_monotonic - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    schedule_url = CONFERENCES[conference_key]["schedule_url"]
    try:
        async with create_http_client("pretalx", timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(schedule_url, headers={"User-Agent": "OpenMates event search"})
        response.raise_for_status()
        payload = response.json()
        events = _extract_schedule_events(payload)
        _SCHEDULE_CACHE[conference_key] = (now_monotonic, events)
        logger.info("Loaded %d pretalx events for %s", len(events), conference_key)
        return events
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        if cached:
            logger.warning(
                "Failed to refresh pretalx schedule for %s; returning stale cache: %s",
                conference_key,
                exc,
            )
            return cached[1]
        raise RuntimeError(f"Failed to load pretalx schedule for {conference_key}: {exc}") from exc


def _extract_schedule_events(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    days = payload.get("schedule", {}).get("conference", {}).get("days", [])
    events: List[Dict[str, Any]] = []
    for day in days:
        for talks in (day.get("rooms") or {}).values():
            events.extend(talk for talk in talks if isinstance(talk, dict))
    return events


def _normalize_event(raw: Dict[str, Any], conference_key: str) -> Dict[str, Any]:
    conference = CONFERENCES[conference_key]
    date_start = raw.get("date") or None
    date_end = _derive_end(date_start, raw.get("duration"))
    speakers = [
        person.get("public_name") or person.get("name") or ""
        for person in raw.get("persons") or []
        if isinstance(person, dict)
    ]
    description = raw.get("abstract") or raw.get("description") or ""
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[:_MAX_DESCRIPTION_CHARS] + "..."

    room = raw.get("room") or ""
    location = f"{room}, {conference['title']}, {conference['location']}" if room else f"{conference['title']}, {conference['location']}"

    return {
        "id": raw.get("guid") or raw.get("id") or raw.get("code"),
        "provider": conference_key,
        "title": raw.get("title") or "",
        "description": description,
        "url": raw.get("url") or raw.get("origin_url") or "",
        "date_start": date_start,
        "date_end": date_end,
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "location": location,
        "venue": {
            "name": room or conference["title"],
            "address": conference["location"],
            "city": conference["location"].split(",", 1)[0],
            "state": None,
            "country": "Germany",
            "lat": None,
            "lon": None,
        },
        "organizer": {"name": conference["title"]},
        "rsvp_count": None,
        "is_paid": None,
        "fee": None,
        "image_url": raw.get("logo"),
        "source": f"{conference['title']} official schedule",
        "conference": conference_key,
        "conference_title": conference["title"],
        "code": raw.get("code"),
        "track": raw.get("track"),
        "session_type": raw.get("type"),
        "language": raw.get("language"),
        "speakers": speakers,
        "duration": raw.get("duration"),
        "room": room,
    }


def _derive_end(date_start: Optional[str], duration: Optional[str]) -> Optional[str]:
    if not date_start or not duration:
        return None
    try:
        start = datetime.fromisoformat(date_start.replace("Z", "+00:00"))
        hours, minutes = [int(part) for part in str(duration).split(":")[:2]]
        return (start + timedelta(hours=hours, minutes=minutes)).isoformat()
    except (TypeError, ValueError):
        return None


def _passes_date_filters(
    event: Dict[str, Any],
    start_date: Optional[str],
    end_date: Optional[str],
    past_events: bool,
    now: datetime,
) -> bool:
    event_start = _parse_datetime(event.get("date_start"))
    event_end = _parse_datetime(event.get("date_end")) or event_start
    if not event_start:
        return True

    now_local = now.astimezone(_LOCAL_TZ) if now.tzinfo else now.replace(tzinfo=_LOCAL_TZ)
    if not past_events and event_end and event_end < now_local:
        return False

    requested_start = _parse_datetime(start_date)
    if requested_start and event_end and event_end < requested_start:
        return False

    requested_end = _parse_datetime(end_date)
    if requested_end and event_start > requested_end:
        return False

    return True


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=_LOCAL_TZ)
        return parsed.astimezone(_LOCAL_TZ)
    except (TypeError, ValueError):
        return None


def _rank_events(events: List[Dict[str, Any]], query: str, conference_key: str) -> List[Dict[str, Any]]:
    terms = _search_terms(query, conference_key)
    if not terms:
        return sorted(events, key=lambda event: event.get("date_start") or "9999")

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for event in events:
        score = _score_event(event, terms)
        if score > 0:
            scored.append((score, event))

    scored.sort(key=lambda item: (-item[0], item[1].get("date_start") or "9999"))
    return [event for _, event in scored]


def _search_terms(query: str, conference_key: str) -> List[str]:
    terms = [term.lower() for term in re.findall(r"[\w+#.-]+", query or "") if len(term) > 1]
    aliases = CONFERENCES[conference_key]["aliases"] | {conference_key}
    stopwords = {
        "at", "in", "on", "for", "the", "and", "or", "of", "to",
        "event", "events", "talk", "talks", "workshop", "workshops", "schedule",
    }
    return [term for term in terms if term not in aliases and term not in stopwords]


def _score_event(event: Dict[str, Any], terms: List[str]) -> int:
    fields = [
        (event.get("title") or "", 5),
        (event.get("description") or "", 3),
        (event.get("track") or "", 2),
        (event.get("session_type") or "", 2),
        (" ".join(event.get("speakers") or []), 2),
        (event.get("room") or "", 1),
    ]
    score = 0
    for text, weight in fields:
        text_lower = text.lower()
        for term in terms:
            if len(term) <= 2 and re.search(rf"\b{re.escape(term)}\b", text_lower):
                score += weight
            elif len(term) > 2 and term in text_lower:
                score += weight
    return score
