"""Versioned provider contracts implemented by installed app package providers.

``events.search@1``: input is one events search request item; output is a list
of event results. Results are validated field by field; invalid entries are
discarded and unknown fields are dropped. The worker, not the package, sets
each result's ``provider`` (contribution name) and ``provider_id``.

``jobs.search@1``: input is one validated jobs search request item (with the
resolved ``countries`` list, without provider selectors); output is a list of
``job_result`` objects (``id``, ``title`` and http(s) ``url`` required).

``skill.requests@1``: the generic contract for paused built-in skills without a
provider (``generic_contract.py``). Input is one request item of the target
skill; output is a list of JSON objects validated structurally.
"""
from __future__ import annotations

import importlib
import json
import math
from datetime import datetime
from typing import Any, Callable, Dict, FrozenSet, List, Optional
from urllib.parse import urlsplit

from backend.shared.app_packages.generic_contract import (
    GENERIC_RESERVED_PROVIDER_IDS,
    MAX_RESULT_BYTES,
    MAX_TOTAL_BYTES,
    SKILL_REQUESTS_V1,
    validate_generic_result,
)

EVENTS_SEARCH_V1 = "events.search@1"
MAX_RESULTS_PER_CALL = 50
MAX_TITLE_CHARS = 500
MAX_TEXT_CHARS = 2000
MAX_DESCRIPTION_CHARS = 20000
MAX_URL_CHARS = 2048
EVENTS_INPUT_FIELDS = (
    "query", "location", "lat", "lon", "start_date", "end_date", "event_type", "count", "past_events",
)
VENUE_TEXT_FIELDS = ("name", "address", "city", "country", "postal_code", "region")

JOBS_SEARCH_V1 = "jobs.search@1"
MAX_JOB_ID_CHARS = 256
# job_result text fields and their limits; id, title, url and apply_url are handled separately.
JOBS_TEXT_FIELDS: Dict[str, int] = {
    "company": MAX_TEXT_CHARS, "location": MAX_TEXT_CHARS, "country": 64, "employment_type": 64,
    "description": MAX_DESCRIPTION_CHARS, "sector": MAX_TEXT_CHARS, "role": MAX_TEXT_CHARS,
    "seniority": MAX_TEXT_CHARS, "organization_type": MAX_TEXT_CHARS, "work_arrangement": MAX_TEXT_CHARS,
    "salary_text": MAX_TEXT_CHARS, "impact": MAX_TEXT_CHARS, "detail_status": 64,
    "salary_currency": 16, "salary_period": 32,
}
JOBS_DATE_FIELDS = ("published_at", "valid_through")
JOBS_NUMBER_FIELDS = ("salary_min", "salary_max")
# Request fields the skill resolves itself: provider selectors and the singleton
# country (the input always carries the resolved ``countries`` list).
JOBS_INPUT_EXCLUDED_FIELDS = frozenset({"provider", "providers", "country"})


def _text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped[:limit] if stripped else None


def _http_url(value: Any) -> Optional[str]:
    text = _text(value, MAX_URL_CHARS)
    if text is None:
        return None
    parts = urlsplit(text)
    return text if parts.scheme in ("http", "https") and parts.netloc else None


def _iso_datetime(value: Any) -> Optional[str]:
    text = _text(value, 64)
    if text is None:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _venue(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    venue: Dict[str, Any] = {key: text for key in VENUE_TEXT_FIELDS if (text := _text(value.get(key), MAX_TEXT_CHARS))}
    for key in ("lat", "lon"):
        number = _number(value.get(key))
        if number is not None:
            venue[key] = number
    return venue or None


def _fee(value: Any) -> Any:
    if isinstance(value, str):
        return _text(value, MAX_TEXT_CHARS)
    if _number(value) is not None:
        return value
    if isinstance(value, dict):
        fee = {key: item for key, item in value.items()
               if key in ("amount", "currency", "display", "min", "max")
               and (isinstance(item, str) and len(item) <= MAX_TEXT_CHARS or _number(item) is not None)}
        return fee or None
    return None


def events_search_input(request_item: Dict[str, Any]) -> Dict[str, Any]:
    """Project one validated search request item onto the contract input fields."""
    return {key: request_item[key] for key in EVENTS_INPUT_FIELDS if request_item.get(key) is not None}


def validate_events_search_result(raw: Any) -> Optional[Dict[str, Any]]:
    """Return a sanitized EventResult or None when required fields are invalid."""
    if not isinstance(raw, dict):
        return None
    title, url, date_start = _text(raw.get("title"), MAX_TITLE_CHARS), _http_url(raw.get("url")), _iso_datetime(raw.get("date_start"))
    if not (title and url and date_start):
        return None
    result: Dict[str, Any] = {"title": title, "url": url, "date_start": date_start}
    optional = {
        "date_end": _iso_datetime(raw.get("date_end")),
        "description": _text(raw.get("description"), MAX_DESCRIPTION_CHARS),
        "venue": _venue(raw.get("venue")),
        "event_type": _text(raw.get("event_type"), 32),
        "organizer": _text(raw.get("organizer"), MAX_TEXT_CHARS)
        if not isinstance(raw.get("organizer"), dict)
        else _text(raw["organizer"].get("name"), MAX_TEXT_CHARS),
        "fee": _fee(raw.get("fee")),
        "image_url": _http_url(raw.get("image_url")),
    }
    result.update({key: value for key, value in optional.items() if value is not None})
    return result


def _finite_number(value: Any) -> Optional[float]:
    number = _number(value)
    return number if number is not None and math.isfinite(number) else None


def _job_id(value: Any) -> Optional[str]:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return _text(value, MAX_JOB_ID_CHARS)


def validate_jobs_search_result(raw: Any) -> Optional[Dict[str, Any]]:
    """Return a sanitized job result or None when ``id``, ``title`` or ``url`` is invalid.

    Only the ``job_result`` fields are kept; ``provider`` and ``provider_id``
    are set by the server. Descriptions keep up to 20,000 chars, more than the
    built-in source's 5,000, so full listing text is retained.
    """
    if not isinstance(raw, dict):
        return None
    job_id, title, url = _job_id(raw.get("id")), _text(raw.get("title"), MAX_TITLE_CHARS), _http_url(raw.get("url"))
    if not (job_id and title and url):
        return None
    result: Dict[str, Any] = {"id": job_id, "title": title, "url": url}
    optional: Dict[str, Any] = {
        key: _text(raw.get(key), limit) for key, limit in JOBS_TEXT_FIELDS.items()
    }
    optional.update({key: _iso_datetime(raw.get(key)) for key in JOBS_DATE_FIELDS})
    optional.update({key: _finite_number(raw.get(key)) for key in JOBS_NUMBER_FIELDS})
    optional["apply_url"] = _http_url(raw.get("apply_url"))
    optional["remote"] = raw.get("remote") if isinstance(raw.get("remote"), bool) else None
    result.update({key: value for key, value in optional.items() if value is not None})
    return result


def jobs_search_input(request_item: Dict[str, Any]) -> Dict[str, Any]:
    """Contract input: the validated request item without server-side provider selectors."""
    return {key: value for key, value in request_item.items()
            if value is not None and key not in JOBS_INPUT_EXCLUDED_FIELDS}


ResultValidator = Callable[[Any], Optional[Dict[str, Any]]]
CONTRACT_VALIDATORS: Dict[str, ResultValidator] = {
    EVENTS_SEARCH_V1: validate_events_search_result,
    JOBS_SEARCH_V1: validate_jobs_search_result,
    SKILL_REQUESTS_V1: validate_generic_result,
}
# Contracts whose results are bounded by serialized size (per result and per call).
SIZE_BOUNDED_CONTRACTS = frozenset({SKILL_REQUESTS_V1})


def validate_contract_results(contract: str, results: List[Any], *, provider_id: str, provider_name: str) -> List[Dict[str, Any]]:
    """Validate raw provider output and stamp server-side provider attribution."""
    validator = CONTRACT_VALIDATORS.get(contract)
    if validator is None:
        return []
    accepted: List[Dict[str, Any]] = []
    total_bytes = 0
    for raw in results[:MAX_RESULTS_PER_CALL]:
        result = validator(raw)
        if result is None:
            continue
        stamped = {**result, "provider": provider_name, "provider_id": provider_id}
        if contract in SIZE_BOUNDED_CONTRACTS:
            size = len(json.dumps(stamped, ensure_ascii=False).encode("utf-8"))
            if size > MAX_RESULT_BYTES or total_bytes + size > MAX_TOTAL_BYTES:
                continue
            total_bytes += size
        accepted.append(stamped)
    return accepted


# Provider selector values a target skill interprets itself ("module:function"
# returning a set of ids). Imported lazily so the loader stays light; the
# loader rejects installed provider ids in this set.
RESERVED_PROVIDER_ID_SOURCES: Dict[str, str] = {
    EVENTS_SEARCH_V1: "backend.apps.events.provider_aliases:reserved_provider_ids",
    JOBS_SEARCH_V1: "backend.apps.jobs.provider_aliases:reserved_provider_ids",
}
# Reserved selector values for contracts that are not owned by a single skill.
STATIC_RESERVED_PROVIDER_IDS: Dict[str, FrozenSet[str]] = {
    SKILL_REQUESTS_V1: GENERIC_RESERVED_PROVIDER_IDS,
}


def reserved_provider_ids(contract: str) -> FrozenSet[str]:
    """Per-skill reserved provider ids for a contract (empty when none are declared)."""
    if contract in STATIC_RESERVED_PROVIDER_IDS:
        return STATIC_RESERVED_PROVIDER_IDS[contract]
    source = RESERVED_PROVIDER_ID_SOURCES.get(contract)
    if source is None:
        return frozenset()
    module_name, _, function_name = source.partition(":")
    function = getattr(importlib.import_module(module_name), function_name)
    return frozenset(str(value).strip().lower() for value in function())
