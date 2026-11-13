"""Generic ``skill.requests@1`` contract for paused built-in skills.

A built-in skill that is paused because it has no provider (``provider_required:
true``, no built-in ``providers``, no ``provider_contract`` and a public
``tool_schema`` with properties) accepts installed providers through this one
contract. No per-skill contract or code exists in the repository:

- input: one request item of the skill's public request schema, validated by the
  skill's own request item model when one can be resolved. A skill whose schema
  has a top-level ``requests`` array runs providers once per item; a skill with a
  flat schema (no ``requests`` property) passes its whole validated tool input as
  the single item (``delegate_flat_skill``);
- output: a list of JSON objects. The server validates them structurally only
  (``validate_generic_result``) and stamps ``provider`` / ``provider_id``;
- regions: a provider may declare ``regions`` (ISO 3166-1 alpha-2); the delegates
  skip it when the request names regions (``country``, ``countries``, ``region``,
  ``regions``) it does not cover (``filter_providers_by_region``).

Architecture: docs/architecture/apps/instance-app-packages.md ("Generic contract").
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

SKILL_REQUESTS_V1 = "skill.requests@1"
GENERIC_CONTRACTS: FrozenSet[str] = frozenset({SKILL_REQUESTS_V1})
# Class that serves an eligible skill once an installed provider targets it.
DELEGATE_CLASS_PATH = "backend.shared.app_packages.delegate_skill.InstalledProviderSkill"
FLAT_DELEGATE_CLASS_PATH = "backend.shared.app_packages.delegate_flat_skill.InstalledProviderFlatSkill"

# Request item fields a caller may use to pick installed providers by id or name.
PROVIDER_SELECTOR_FIELDS: Tuple[str, ...] = ("provider", "providers", "provider_platform")
# Selector values with a generic meaning ("use every provider"); never usable as ids.
GENERIC_RESERVED_PROVIDER_IDS: FrozenSet[str] = frozenset({
    "auto", "all", "any", "none", "default", "unavailable", "multi",
})

# Request fields that name the regions a request is about (string or list of strings).
REGION_FIELDS: Tuple[str, ...] = ("country", "countries", "region", "regions")
WORLDWIDE_REGION = "WORLDWIDE"


def requested_regions(item: Any) -> List[str]:
    """Upper-cased, trimmed, unique region values the raw request item names."""
    if not isinstance(item, dict):
        return []
    found: List[str] = []
    for field in REGION_FIELDS:
        value = item.get(field)
        for entry in value if isinstance(value, list) else [value]:
            if isinstance(entry, str) and entry.strip():
                found.append(entry.strip().upper())
    return list(dict.fromkeys(found))


def filter_providers_by_region(
    provider_ids: Sequence[str], providers: Sequence[Any], item: Any,
) -> Tuple[List[str], List[str], Optional[str]]:
    """Drop selected providers that declare regions the request does not name.

    Returns (kept ids, one warning per skipped provider, error when every
    selected provider was skipped). Providers without declared regions always
    stay; a request with no region or ``WORLDWIDE`` keeps everything.
    """
    regions = requested_regions(item)
    if not regions or WORLDWIDE_REGION in regions:
        return list(provider_ids), [], None
    by_id = {provider.provider_id: provider for provider in providers}
    joined = ", ".join(regions)
    kept: List[str] = []
    warnings: List[str] = []
    for provider_id in provider_ids:
        provider = by_id.get(provider_id)
        declared = getattr(provider, "regions", ()) if provider is not None else ()
        if not declared or set(declared) & set(regions):
            kept.append(provider_id)
        else:
            warnings.append(f"{provider.name} was not searched: it does not cover {joined}.")
    if provider_ids and not kept:
        return [], [], f"No installed provider covers {joined}."
    return kept, warnings, None


MAX_DEPTH = 6                      # the result object itself is depth 1
MAX_KEYS_PER_OBJECT = 100
MAX_LIST_ITEMS = 100
MAX_STRING_CHARS = 20000
MAX_URL_CHARS = 2048
MAX_RESULT_BYTES = 64 * 1024       # serialized size of one sanitized result
MAX_TOTAL_BYTES = 1024 * 1024      # serialized size of all results of one call
MAX_SAFE_INTEGER = 2 ** 53
KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
# Keys the server owns in a result: attribution is stamped after validation, and
# embed, task and billing fields are never accepted from package code.
SERVER_OWNED_KEYS: FrozenSet[str] = frozenset({
    "provider", "provider_id", "embed_id", "embed_ids", "task_id", "credits_charged", "usage",
})


def _schema_properties(skill: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    schema = skill.get("tool_schema")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    return properties if isinstance(properties, dict) and properties else None

def has_requests_array(skill: Any) -> bool:
    """True when the skill's public tool schema has a top-level ``requests`` array."""
    properties = _schema_properties(skill) if isinstance(skill, dict) else None
    requests = properties.get("requests") if properties else None
    return isinstance(requests, dict) and requests.get("type") == "array"

def is_flat_schema(skill: Any) -> bool:
    """True when the public tool schema has properties but no ``requests`` property."""
    properties = _schema_properties(skill) if isinstance(skill, dict) else None
    return properties is not None and "requests" not in properties

def accepts_generic_contract(skill: Any) -> bool:
    """True when a raw built-in skill definition may be served by ``skill.requests@1``."""
    if not isinstance(skill, dict):
        return False
    if skill.get("provider_required") is not True or skill.get("provider_contract") or skill.get("providers"):
        return False
    if not str(skill.get("class_path") or "").strip():
        return False
    return has_requests_array(skill) or is_flat_schema(skill)

def delegate_class_path(skill: Dict[str, Any]) -> str:
    """Generic delegate for an eligible skill: per request item, or the flat tool input."""
    return DELEGATE_CLASS_PATH if has_requests_array(skill) else FLAT_DELEGATE_CLASS_PATH

def is_url_key(key: str) -> bool:
    return key == "url" or key.endswith("_url")


def _http_url(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > MAX_URL_CHARS:
        return None
    parts = urlsplit(text)
    return text if parts.scheme in ("http", "https") and parts.netloc else None


_DROP = object()


def _sanitize(value: Any, depth: int) -> Any:
    """Return a bounded JSON value, or ``_DROP`` when the value is not acceptable."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER else _DROP
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP
    if isinstance(value, str):
        return value[:MAX_STRING_CHARS]
    if depth >= MAX_DEPTH:
        return _DROP
    if isinstance(value, list):
        items = (_sanitize(item, depth + 1) for item in value[:MAX_LIST_ITEMS])
        return [item for item in items if item is not _DROP]
    if isinstance(value, dict):
        return _sanitize_object(value, depth + 1, top_level=False)
    return _DROP


def _sanitize_object(raw: Dict[Any, Any], depth: int, *, top_level: bool) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in raw.items():
        if len(cleaned) >= MAX_KEYS_PER_OBJECT:
            break
        if not isinstance(key, str) or not KEY_RE.match(key):
            continue
        if top_level and key in SERVER_OWNED_KEYS:
            continue
        if is_url_key(key):
            url = _http_url(value)
            if url is not None:
                cleaned[key] = url
            continue
        sanitized = _sanitize(value, depth)
        if sanitized is not _DROP:
            cleaned[key] = sanitized
    return cleaned


def validate_generic_result(raw: Any) -> Optional[Dict[str, Any]]:
    """Return a structurally sanitized result object, or None when nothing usable remains."""
    if not isinstance(raw, dict):
        return None
    result = _sanitize_object(raw, 1, top_level=True)
    return result or None
