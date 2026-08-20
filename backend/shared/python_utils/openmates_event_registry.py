"""Shared OpenMates event registry loader.

The events newsletter uses a versioned repo YAML file as its deterministic
source of truth. This module validates only public event metadata and safe local
asset references; it does not read subscribers, campaign recipients, or email
provider state.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

REPO_ROOT = Path(os.getenv("OPENMATES_REPO_ROOT", Path(__file__).resolve().parents[3]))
DEFAULT_REGISTRY_PATH = REPO_ROOT / "shared" / "events" / "openmates_events.yml"
SUPPORTED_LANGUAGES = ("en", "de")
REQUIRED_EVENT_FIELDS = (
    "id",
    "slug",
    "status",
    "event_type",
    "starts_at",
    "ends_at",
    "timezone",
    "localized_content",
    "luma_url",
    "assets",
)


class EventRegistryError(ValueError):
    """Raised when the shared OpenMates event registry is invalid."""


def load_openmates_events(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the canonical OpenMates events registry."""

    registry_path = path or DEFAULT_REGISTRY_PATH
    if not registry_path.exists():
        raise EventRegistryError(f"OpenMates event registry not found: {registry_path}")

    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    _validate_registry(payload)
    return payload


def _validate_registry(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != 1:
        raise EventRegistryError("openmates_events.yml schema_version must be 1")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise EventRegistryError("openmates_events.yml must define a non-empty events list")

    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise EventRegistryError("each event must be a mapping")
        _validate_event(event, seen_ids, seen_slugs)


def _validate_event(event: dict[str, Any], seen_ids: set[str], seen_slugs: set[str]) -> None:
    for field in REQUIRED_EVENT_FIELDS:
        if field not in event:
            raise EventRegistryError(f"event missing required field: {field}")

    event_id = str(event["id"])
    slug = str(event["slug"])
    if event_id in seen_ids:
        raise EventRegistryError(f"duplicate event id: {event_id}")
    if slug in seen_slugs:
        raise EventRegistryError(f"duplicate event slug: {slug}")
    seen_ids.add(event_id)
    seen_slugs.add(slug)

    starts_at = _parse_aware_datetime(str(event["starts_at"]), f"{event_id}.starts_at")
    ends_at = _parse_aware_datetime(str(event["ends_at"]), f"{event_id}.ends_at")
    if ends_at <= starts_at:
        raise EventRegistryError(f"event end must be after start: {event_id}")
    if str(event["timezone"]) != "Europe/Berlin":
        raise EventRegistryError(f"event timezone must be Europe/Berlin: {event_id}")

    _validate_luma_url(str(event.get("luma_url") or ""), event_id)
    _validate_localized_content(event["localized_content"], event_id)
    _validate_assets(event["assets"], event_id)


def _parse_aware_datetime(value: str, field: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise EventRegistryError(f"{field} must include timezone offset")
    return parsed


def _validate_luma_url(value: str, event_id: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "luma.com" or not parsed.path.strip("/"):
        raise EventRegistryError(f"event must define a valid Luma URL: {event_id}")


def _validate_localized_content(value: Any, event_id: str) -> None:
    if not isinstance(value, dict):
        raise EventRegistryError(f"localized_content must be a language map: {event_id}")
    for language in SUPPORTED_LANGUAGES:
        content = value.get(language)
        if not isinstance(content, dict):
            raise EventRegistryError(f"missing localized content {language}: {event_id}")
        for field in ("title", "summary", "description"):
            if not str(content.get(field) or "").strip():
                raise EventRegistryError(f"missing {language}.{field}: {event_id}")


def _validate_assets(value: Any, event_id: str) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("card"), dict):
        raise EventRegistryError(f"event assets.card must be a language map: {event_id}")
    for language in SUPPORTED_LANGUAGES:
        asset = value["card"].get(language)
        if not isinstance(asset, dict):
            raise EventRegistryError(f"missing {language} card asset: {event_id}")
        path = Path(str(asset.get("path") or ""))
        if path.is_absolute() or ".." in path.parts or path.suffix != ".png":
            raise EventRegistryError(f"unsafe asset path for {event_id}.{language}")
        if len(path.parts) < 4 or path.parts[:3] != ("shared", "events", "assets"):
            raise EventRegistryError(f"asset path must stay under shared/events/assets: {event_id}.{language}")
        if not str(asset.get("alt") or "").strip():
            raise EventRegistryError(f"missing asset alt text for {event_id}.{language}")
