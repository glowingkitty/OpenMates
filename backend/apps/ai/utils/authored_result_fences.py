"""Pure validation of explicitly authored rich results, without executing skills.

The shared catalog owns the eligible schemas. Admission into an assistant prompt
and ownership checks for existing embed references belong to the caller. This
module neither fetches media nor infers facts, resource access, or operation state.
Warnings contain only fixed codes and structural paths, never supplied content.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker

AUTHORED_RESULTS_FENCE = "openmates_embeds"
CATALOG_PATHS = (
    Path(__file__).resolve().parents[4] / "shared/config/authored_result_types.json",
    Path("/shared/config/authored_result_types.json"),
)
_LOCAL_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_MEDIA_FIELDS = frozenset({
    "image_url", "public_image_url", "thumbnail_url", "public_thumbnail_url",
    "thumbnail", "class_image_url", "preview_image_url", "favicon", "favicon_url",
    "author_avatar_url", "owner_avatar_url", "media_url", "poster_url",
})
_SOCIAL_OBSERVATIONS = frozenset({
    "published_at", "engagement", "likes", "likes_count", "comments", "comments_count",
    "shares", "shares_count", "views", "views_count", "reposts", "reposts_count",
})
_FORMATS = FormatChecker()


@dataclass(frozen=True)
class AuthoredResultItem:
    """One accepted item with legacy flat content and explicit provenance."""

    local_id: str
    kind: str
    backend_type: str
    app_id: str
    skill_id: str
    content: dict[str, Any]


@dataclass(frozen=True)
class AuthoredResultsNormalizationResult:
    """A bounded block outcome; independent valid items retain their order."""

    source_json: str
    title: str
    items: list[AuthoredResultItem]
    view: dict[str, Any] | None
    status: str
    warnings: list[dict[str, str]]
    parse_error: str | None = None


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    """Load the same catalog in a repository checkout or the worker image."""
    for path in CATALOG_PATHS:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise RuntimeError("Authored result schema catalog is unavailable")


def get_authoring_definitions() -> dict[str, dict[str, Any]]:
    """Return eligible canonical kinds; callers additionally enforce app admission.

    Each definition has schema_id, app_id, skill_id, backend_type, display_name,
    details_schema (a reference into the shared $defs), and real_asset. Returned
    dictionaries are copies so prompt consumers cannot mutate global validation.
    """
    return copy.deepcopy(_catalog()["kinds"])


def is_authored_results_fence(language: str | None) -> bool:
    """Only an explicit versioned authoring fence enters this dispatch path."""
    return (language or "").strip().lower() == AUTHORED_RESULTS_FENCE


def _text_schema(limit: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": limit, "pattern": r"\S"}


def _common_item_schema() -> dict[str, Any]:
    limits = _catalog()["limits"]
    return {
        "type": "object",
        "required": ["id", "kind", "title", "origin", "details"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"},
            "kind": _text_schema(100),
            "title": _text_schema(500),
            "origin": {"enum": ["researched", "user_provided", "draft"]},
            "sources": {
                "type": "array", "items": {"$ref": "#/$defs/source"},
                "maxItems": limits["sources"],
            },
            "observed_at": {"type": "string", "format": "offset-datetime"},
            "images": {
                "type": "array", "items": {"$ref": "#/$defs/image"},
                "maxItems": limits["images"],
            },
            "details": {"type": "object"},
        },
    }


def get_authored_results_schema(kinds: Iterable[str] | None = None) -> dict[str, Any]:
    """Return complete JSON Schema with only selected kinds and needed definitions.

    Pass the app-metadata-admitted selection when injecting prompt instructions.
    Empty selections admit nothing. Shared schemas (including web/news) appear
    once; unrelated kind details do not increase the selected instruction context.
    """
    catalog = _catalog()
    selected = list(dict.fromkeys(catalog["kinds"] if kinds is None else kinds))
    variants = []
    for kind in selected:
        definition = catalog["kinds"].get(kind)
        if definition is None:
            raise ValueError("Unknown authored result kind")
        item = _common_item_schema()
        item["properties"]["kind"] = {"const": kind}
        item["properties"]["details"] = copy.deepcopy(definition["details_schema"])
        variants.append(item)
    schema = {
        "$schema": catalog["$schema"],
        "type": "object", "required": ["schemaVersion", "items"],
        "additionalProperties": False,
        "properties": {
            "schemaVersion": {"const": 1, "type": "integer"},
            "title": _text_schema(500),
            "items": {
                "type": "array", "minItems": 1, "maxItems": catalog["limits"]["items"],
                "items": {"oneOf": variants} if variants else False,
            },
            "view": {
                "type": "object", "additionalProperties": False, "required": ["mode"],
                "properties": {
                    "mode": {"enum": ["auto", "cards", "map"]},
                    "items": {
                        "type": "array", "minItems": 1, "maxItems": catalog["limits"]["items"],
                        "uniqueItems": True,
                        "items": {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"},
                    },
                },
            },
        },
    }
    needed: dict[str, Any] = {}

    def add_references(node: Any) -> None:
        if isinstance(node, dict):
            reference = node.get("$ref", "")
            if reference.startswith("#/$defs/"):
                key = reference.removeprefix("#/$defs/")
                if key not in needed:
                    needed[key] = copy.deepcopy(catalog["$defs"][key])
                    add_references(needed[key])
            for value in node.values():
                add_references(value)
        elif isinstance(node, list):
            for value in node:
                add_references(value)

    add_references(schema)
    schema["$defs"] = needed
    return schema


def _safe_url(value: object, *, https_only: bool = False) -> bool:
    """Check URL syntax/public literal hosts; delivery must recheck resolved IPs."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in unquote(value)):
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").lower()
        if (parsed.scheme not in ({"https"} if https_only else {"http", "https"})
                or not host or parsed.username is not None or parsed.password is not None
                or parsed.port == 0 or "%" in host):
            return False
        # Accessing port also rejects malformed/out-of-range values.
        _ = parsed.port
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            ascii_host = host.encode("idna").decode("ascii")
            labels = ascii_host.split(".")
            if (len(labels) < 2 or len(ascii_host) > 253
                    or re.fullmatch(r"[0-9.]+", ascii_host)
                    or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                           for label in labels)
                    or ascii_host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))):
                return False
        else:
            if not address.is_global:
                return False
    except (ValueError, UnicodeError):
        return False
    return True


@_FORMATS.checks("public-http-url")
def _public_http_url(value: object) -> bool:
    return not isinstance(value, str) or _safe_url(value)


@_FORMATS.checks("public-https-url")
def _public_https_url(value: object) -> bool:
    return not isinstance(value, str) or _safe_url(value, https_only=True)


def _parse_time(value: str) -> date | datetime:
    if _DATE.fullmatch(value):
        return date.fromisoformat(value)
    if _TIMESTAMP.fullmatch(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed
    raise ValueError("invalid_date_or_offset")


@_FORMATS.checks("date-or-offset-datetime")
def _date_or_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return True
    try:
        _parse_time(value)
        return True
    except ValueError:
        return False


@_FORMATS.checks("offset-datetime")
def _offset_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return True
    return bool(_TIMESTAMP.fullmatch(value)) and _date_or_timestamp(value)


@_FORMATS.checks("iana-timezone")
def _iana_timezone(value: object) -> bool:
    if not isinstance(value, str):
        return True
    try:
        ZoneInfo(value)
        return True
    except (ValueError, ZoneInfoNotFoundError):
        return False


@_FORMATS.checks("embed-reference")
def _embed_reference(value: object) -> bool:
    if not isinstance(value, str):
        return True
    schema = _catalog()["$defs"]["embed_reference"]
    # Context references include exact filenames, Unicode, spaces and duplicate
    # suffixes. Preserve their identity; the caller authorizes the exact string.
    return len(value) <= schema["maxLength"] and bool(re.fullmatch(schema["pattern"], value))


def _validate(value: Any, schema: dict[str, Any]) -> bool:
    return Draft202012Validator(schema, format_checker=_FORMATS).is_valid(value)


def _check_tree(value: Any, depth: int = 0) -> None:
    """Reject nonfinite numbers/control bytes/deep trees before schema traversal."""
    if depth > _catalog()["limits"]["depth"]:
        raise ValueError("item_depth_limit")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite_number")
    if isinstance(value, str) and any(ord(c) < 32 and c not in "\r\n\t" for c in value):
        raise ValueError("invalid_control_character")
    if isinstance(value, dict):
        for key, entry in value.items():
            _check_tree(key, depth + 1)
            _check_tree(entry, depth + 1)
    elif isinstance(value, list):
        for entry in value:
            _check_tree(entry, depth + 1)


def _check_schedule(details: dict[str, Any]) -> None:
    """Reject impossible ordering and offsets while retaining all-day/unknown dates."""
    for start_key, end_key in (("date_start", "date_end"), ("departure", "arrival"),
                               ("check_in", "check_out")):
        start_value, end_value = details.get(start_key), details.get(end_key)
        if start_value is not None and end_value is not None:
            start, end = _parse_time(start_value), _parse_time(end_value)
            same_all_day = start_key == "date_start" and type(start) is date and type(end) is date
            if type(start) is not type(end) or end < start or (end == start and not same_all_day):
                raise ValueError("invalid_schedule_order")
    for time_key, zone_key in (("date_start", "timezone"), ("date_end", "timezone"),
                               ("slot_datetime", "timezone"),
                               ("departure", "departure_timezone"), ("arrival", "arrival_timezone")):
        if details.get(time_key) and details.get(zone_key):
            instant = _parse_time(details[time_key])
            if isinstance(instant, datetime):
                if instant.astimezone(ZoneInfo(details[zone_key])).utcoffset() != instant.utcoffset():
                    raise ValueError("timezone_offset_mismatch")
    if "temperature_min_c" in details and "temperature_max_c" in details:
        if details["temperature_min_c"] > details["temperature_max_c"]:
            raise ValueError("invalid_temperature_range")
    for leg in details.get("legs", []):
        _check_schedule(leg)


def _check_tv_details(kind: str, details: dict[str, Any]) -> None:
    """Keep sourced scores and partial season facts consistent without filling gaps."""
    score = details.get("score")
    if score is not None and score["value"] > score["scale"]:
        raise ValueError("score_exceeds_scale")
    if kind == "tv.movie":
        if "release_date" in details and "year" in details:
            if date.fromisoformat(details["release_date"]).year != details["year"]:
                raise ValueError("conflicting_release_year")
        return
    first = date.fromisoformat(details["first_air_date"]) if "first_air_date" in details else None
    last = date.fromisoformat(details["last_air_date"]) if "last_air_date" in details else None
    if first is not None and last is not None and last < first:
        raise ValueError("invalid_air_date_order")
    for instant, year_key in ((first, "start_year"), (last, "end_year")):
        if instant is not None and year_key in details and instant.year != details[year_key]:
            raise ValueError("conflicting_air_year")
    first_year = first.year if first else details.get("start_year")
    last_year = last.year if last else details.get("end_year")
    if first_year is not None and last_year is not None and last_year < first_year:
        raise ValueError("invalid_series_year_order")
    seasons = details.get("seasons", [])
    season_numbers = [season["season_number"] for season in seasons]
    if len(set(season_numbers)) != len(season_numbers):
        raise ValueError("duplicate_season_number")
    # Specials numbered zero do not count as a regular season. A supplied
    # season N establishes at least N regular seasons, but never a full guide.
    if "season_count" in details and details["season_count"] < max(season_numbers, default=0):
        raise ValueError("conflicting_season_total")
    known_episodes = sum(season.get("episode_count", 0) for season in seasons)
    if "episode_count" in details and details["episode_count"] < known_episodes:
        raise ValueError("conflicting_episode_total")


def _normalize_images(
    value: Any, path: str, warnings: list[dict[str, str]],
) -> list[Any]:
    if not isinstance(value, list):
        warnings.append({"code": "invalid_images", "path": path})
        return []
    limit = _catalog()["limits"]["images"]
    schema = {"$defs": _catalog()["$defs"], "$ref": "#/$defs/image"}
    images = []
    for index, image in enumerate(value[:limit]):
        if _validate(image, schema):
            images.append(copy.deepcopy(image))
        else:
            warnings.append({"code": "invalid_image", "path": f"{path}[{index}]"})
    if len(value) > limit:
        warnings.append({"code": "image_limit", "path": path})
    return images


def _normalize_item(
    raw: Any, index: int, warnings: list[dict[str, str]],
) -> tuple[AuthoredResultItem, dict[str, Any]]:
    path = f"items[{index}]"
    limits = _catalog()["limits"]
    _check_tree(raw)
    if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > limits["item_bytes"]:
        raise ValueError("item_size_limit")
    if not isinstance(raw, dict):
        raise ValueError("invalid_item")
    definition = _catalog()["kinds"].get(raw.get("kind")) if isinstance(raw.get("kind"), str) else None
    if definition is None:
        raise ValueError("unsupported_kind")
    if not isinstance(raw.get("id"), str) or not _LOCAL_ID.fullmatch(raw["id"]):
        raise ValueError("invalid_local_label")
    model = copy.deepcopy(raw)
    # A failed optional image leaves readable content. Identity-critical media
    # fields below are subsequently checked by their kind's required schema.
    if "images" in model:
        model["images"] = _normalize_images(model["images"], f"{path}.images", warnings)
    details = model.get("details")
    if isinstance(details, dict):
        for key in list(details):
            if key in _MEDIA_FIELDS and not _safe_url(details[key], https_only=True):
                del details[key]
                warnings.append({"code": "invalid_image", "path": f"{path}.details.{key}"})
        if "images" in details:
            details["images"] = _normalize_images(details["images"], f"{path}.details.images", warnings)
        if isinstance(details.get("seasons"), list):
            for season_index, season in enumerate(details["seasons"]):
                if isinstance(season, dict) and "poster_url" in season:
                    if not _safe_url(season["poster_url"], https_only=True):
                        del season["poster_url"]
                        warnings.append({
                            "code": "invalid_image",
                            "path": f"{path}.details.seasons[{season_index}].poster_url",
                        })
    schema = _common_item_schema()
    schema["properties"]["details"] = definition["details_schema"]
    schema["$defs"] = _catalog()["$defs"]
    if not _validate(model, schema):
        raise ValueError("invalid_item_fields")
    _check_schedule(details)
    if model["kind"] in {"tv.movie", "tv.series"}:
        _check_tv_details(model["kind"], details)
    if model["kind"] == "social_media.social_post" and model["origin"] == "draft":
        if _SOCIAL_OBSERVATIONS.intersection(details):
            raise ValueError("draft_publication_or_engagement")
    if model["kind"] == "design.icon_result":
        icon_id = details.get("icon_id")
        if icon_id and not re.fullmatch(r"[A-Za-z0-9_-]+:[A-Za-z0-9_-]+", icon_id):
            raise ValueError("invalid_icon_identity")
    model["title"] = model["title"].strip()
    content = copy.deepcopy(details)
    content["title"] = model["title"]
    content["type"] = definition["backend_type"]
    authoring = {
        "schema_version": 1, "kind": model["kind"], "origin": model["origin"],
        "sources": copy.deepcopy(model.get("sources", [])),
    }
    if "observed_at" in model:
        authoring["observed_at"] = model["observed_at"]
    if "images" in model:
        content["images"] = copy.deepcopy(model["images"])
        authoring["images"] = copy.deepcopy(model["images"])
        if "image_url" not in content:
            for image in model["images"]:
                url = image if isinstance(image, str) else image.get("url")
                if url:
                    content["image_url"] = url
                    break
    content["authoring"] = authoring
    return AuthoredResultItem(
        local_id=model["id"], kind=model["kind"], backend_type=definition["backend_type"],
        app_id=definition["app_id"], skill_id=definition["skill_id"], content=content,
    ), model


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON fields rather than silently replacing supplied facts."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_field")
        result[key] = value
    return result


def normalize_authored_results_source(source: str) -> AuthoredResultsNormalizationResult:
    """Normalize a version-1 envelope; retain valid items when another fails.

    Duplicate local labels invalidate every occurrence. Views contain only valid,
    unambiguous labels; they are still local until the caller assigns real embed
    identities. This does not authorize any supplied source/image embed reference.
    """
    warnings: list[dict[str, str]] = []
    empty_title = "Authored results unavailable"
    try:
        if not isinstance(source, str) or len(source.encode("utf-8")) > _catalog()["limits"]["source_bytes"]:
            raise ValueError("source_size_limit")
        raw = json.loads(source, object_pairs_hook=_unique_object)
        if (not isinstance(raw, dict) or type(raw.get("schemaVersion")) is not int
                or raw["schemaVersion"] != 1 or set(raw) - {"schemaVersion", "title", "items", "view"}
                or not isinstance(raw.get("items"), list) or not raw["items"]):
            raise ValueError("invalid_envelope")
        if "title" in raw:
            _check_tree(raw["title"])
            if not _validate(raw["title"], _text_schema(500)):
                raise ValueError("invalid_title")
        limit = _catalog()["limits"]["items"]
        # Count the entire bounded source before truncation: a later duplicate
        # must never rebind an earlier accepted label or a same-response view.
        labels = Counter(
            item["id"] for item in raw["items"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        )
        items: list[AuthoredResultItem] = []
        models: list[dict[str, Any]] = []
        for index, entry in enumerate(raw["items"][:limit]):
            try:
                if isinstance(entry, dict) and isinstance(entry.get("id"), str) and labels[entry["id"]] > 1:
                    raise ValueError("duplicate_label")
                item, model = _normalize_item(entry, index, warnings)
                items.append(item)
                models.append(model)
            except (ValueError, TypeError, OverflowError, RecursionError):
                # Specific codes are selected without interpolating exception
                # text, which may originate in a parser containing private data.
                code = "duplicate_label" if (isinstance(entry, dict) and isinstance(entry.get("id"), str)
                                              and labels[entry["id"]] > 1) else "invalid_item"
                warnings.append({"code": code, "path": f"items[{index}]"})
        if len(raw["items"]) > limit:
            warnings.append({"code": "item_limit", "path": "items"})
        view = None
        if "view" in raw:
            view_schema = get_authored_results_schema([])["properties"]["view"]
            if _validate(raw["view"], view_schema):
                view = copy.deepcopy(raw["view"])
                if "items" in view:
                    accepted = {item.local_id for item in items}
                    resolved = [label for label in view["items"] if label in accepted]
                    if len(resolved) != len(view["items"]):
                        warnings.append({"code": "unresolved_view_label", "path": "view.items"})
                    if resolved:
                        view["items"] = resolved
                    else:
                        view = None
            else:
                warnings.append({"code": "invalid_view", "path": "view"})
        if not items:
            return AuthoredResultsNormalizationResult(
                "", empty_title, [], None, "invalid_source", warnings,
                "No valid authored result items",
            )
        model = {"schemaVersion": 1, "items": models}
        if "title" in raw:
            model["title"] = raw["title"].strip()
        if view is not None:
            model["view"] = view
        return AuthoredResultsNormalizationResult(
            json.dumps(model, ensure_ascii=False, separators=(",", ":")),
            model.get("title", items[0].content["title"]), items, view,
            "partial" if warnings else "valid", warnings,
        )
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        return AuthoredResultsNormalizationResult(
            "", empty_title, [], None, "invalid_source", warnings,
            "Invalid authored result envelope or content limit exceeded",
        )
