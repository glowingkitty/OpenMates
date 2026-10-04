# backend/shared/providers/geoapify/places.py
#
# Geoapify Places and Place Details provider adapter.
# This module is a pure API wrapper: it owns secret lookup, bounded requests,
# typed provider status, safe demand-cache keys, and normalization of OSM-backed
# detail fields into source-labelled records for downstream app skills.
#
# Spec: docs/specs/maps-geoapify-osm-enrichment/spec.yml

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import httpx

from backend.shared.providers.geoapify.budget import reserve_credit

logger = logging.getLogger(__name__)

GEOAPIFY_SECRET_PATH = "kv/data/providers/geoapify"
GEOAPIFY_API_KEY_NAME = "api_key"
GEOAPIFY_API_KEY_ENV_VAR = "SECRET__GEOAPIFY__API_KEY"

GEOAPIFY_PLACES_URL = "https://api.geoapify.com/v2/places"
GEOAPIFY_PLACE_DETAILS_URL = "https://api.geoapify.com/v2/place-details"
GEOAPIFY_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
GEOAPIFY_SOURCE_LABEL = "OpenStreetMap via Geoapify"

DEFAULT_TIMEOUT_SECONDS = 1.2
MAX_PLACES_LIMIT = 20
DETAIL_POSITIVE_TTL_SECONDS = 30 * 24 * 60 * 60
DETAIL_NO_MATCH_TTL_SECONDS = 7 * 24 * 60 * 60
DETAIL_CACHE_VERSION = "v1"
SEARCH_TTL_SECONDS = 24 * 60 * 60
GEOCODE_TTL_SECONDS = 30 * 24 * 60 * 60

SUPPORTED_PLACES_CONDITIONS = {
    "internet_access.free",
    "internet_access",
    "wheelchair",
    "wheelchair.yes",
    "wheelchair.limited",
}

HttpGet = Callable[[str, dict[str, Any], float], Awaitable[httpx.Response]]


@dataclass(slots=True)
class GeoapifyPlacesSearchResult:
    status: str
    places: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    unsupported_conditions: list[str] = field(default_factory=list)
    cache_hit: bool = False


@dataclass(slots=True)
class GeoapifyPlaceDetailsResult:
    status: str
    enrichment: dict[str, Any]
    error: Optional[str] = None
    cache_hit: bool = False


class GeoapifyPlacesProvider:
    """Async wrapper for Geoapify Places and Place Details."""

    def __init__(
        self,
        *,
        secrets_manager: Any,
        cache_service: Any | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        http_get: HttpGet | None = None,
    ) -> None:
        self.secrets_manager = secrets_manager
        self.cache_service = cache_service
        self.timeout_seconds = timeout_seconds
        self._http_get = http_get or self._default_http_get

    async def get_api_key(self) -> Optional[str]:
        """Load the Geoapify API key from Vault first, then the environment."""

        try:
            get_secret = getattr(self.secrets_manager, "get_secret", None)
            if get_secret:
                api_key = await get_secret(
                    secret_path=GEOAPIFY_SECRET_PATH,
                    secret_key=GEOAPIFY_API_KEY_NAME,
                )
                cleaned = _clean_api_key(api_key)
                if cleaned:
                    return cleaned
        except Exception as exc:
            logger.warning("Geoapify API key Vault lookup failed; falling back to environment: %s", exc)

        return _clean_api_key(os.getenv(GEOAPIFY_API_KEY_ENV_VAR))

    async def search_places(
        self,
        *,
        query: str,
        limit: int = MAX_PLACES_LIMIT,
        categories: list[str] | None = None,
        geo_filter: str | None = None,
        bias: str | None = None,
        conditions: list[str] | None = None,
    ) -> GeoapifyPlacesSearchResult:
        """Search Geoapify Places with only supported `conditions` forwarded."""

        api_key = await self.get_api_key()
        if not api_key:
            return GeoapifyPlacesSearchResult(
                status="not_configured",
                error="Geoapify API key is not configured",
            )

        supported_conditions, unsupported_conditions = _partition_supported_conditions(conditions or [])
        params: dict[str, Any] = {
            "apiKey": api_key,
            "limit": max(1, min(int(limit or MAX_PLACES_LIMIT), MAX_PLACES_LIMIT)),
        }
        if query and not categories:
            params["text"] = query
        if categories:
            params["categories"] = ",".join(categories)
        if geo_filter:
            params["filter"] = geo_filter
        if bias:
            params["bias"] = bias
        if supported_conditions:
            params["conditions"] = ",".join(supported_conditions)

        cache_key = _request_cache_key("places", params)
        cached = await self._cache_get(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("features"), list):
            return GeoapifyPlacesSearchResult(
                status="ok", places=cached["features"],
                unsupported_conditions=unsupported_conditions, cache_hit=True,
            )
        budget_status = await reserve_credit(self.cache_service, api_key)
        if budget_status != "ok":
            return GeoapifyPlacesSearchResult(status=budget_status, error=_budget_error(budget_status))

        try:
            response = await self._http_get(GEOAPIFY_PLACES_URL, params, self.timeout_seconds)
        except httpx.TimeoutException:
            return GeoapifyPlacesSearchResult(
                status="timed_out",
                error="Geoapify Places request timed out",
                unsupported_conditions=unsupported_conditions,
            )
        except httpx.RequestError:
            return GeoapifyPlacesSearchResult(
                status="unavailable",
                error="Geoapify Places request failed",
                unsupported_conditions=unsupported_conditions,
            )

        if response.status_code == 429:
            return GeoapifyPlacesSearchResult(
                status="rate_limited",
                error=_safe_response_error(response),
                unsupported_conditions=unsupported_conditions,
            )
        if response.status_code >= 400:
            return GeoapifyPlacesSearchResult(
                status="unavailable",
                error=_safe_response_error(response),
                unsupported_conditions=unsupported_conditions,
            )

        try:
            payload = response.json()
        except ValueError:
            return GeoapifyPlacesSearchResult(status="unavailable", error="Invalid Geoapify response")
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            return GeoapifyPlacesSearchResult(status="unavailable", error="Invalid Geoapify response")
        places = features
        await self._cache_set(cache_key, {"features": places}, SEARCH_TTL_SECONDS)
        return GeoapifyPlacesSearchResult(
            status="ok",
            places=places,
            unsupported_conditions=unsupported_conditions,
        )

    async def geocode_area(self, name: str, language: str = "en") -> GeoapifyPlacesSearchResult:
        """Resolve a named area; return two candidates so callers can reject ambiguity."""
        api_key = await self.get_api_key()
        if not api_key:
            return GeoapifyPlacesSearchResult(status="not_configured", error="Geoapify API key is not configured")
        params = {"apiKey": api_key, "text": name.strip(), "lang": language, "limit": 2, "type": "locality"}
        key = _request_cache_key("geocode", params)
        cached = await self._cache_get(key)
        if isinstance(cached, dict) and isinstance(cached.get("features"), list):
            return GeoapifyPlacesSearchResult(status="ok", places=cached["features"], cache_hit=True)
        status = await reserve_credit(self.cache_service, api_key)
        if status != "ok":
            return GeoapifyPlacesSearchResult(status=status, error=_budget_error(status))
        try:
            response = await self._http_get(GEOAPIFY_GEOCODE_URL, params, self.timeout_seconds)
            if response.status_code >= 400:
                return GeoapifyPlacesSearchResult(
                    status="rate_limited" if response.status_code == 429 else "unavailable",
                    error=_safe_response_error(response),
                )
            payload = response.json()
            places = payload.get("features") if isinstance(payload, dict) else None
            if not isinstance(places, list):
                raise ValueError("Invalid features")
            await self._cache_set(key, {"features": places}, GEOCODE_TTL_SECONDS if places else 3600)
            return GeoapifyPlacesSearchResult(status="ok", places=places)
        except httpx.TimeoutException:
            return GeoapifyPlacesSearchResult(status="timed_out", error="Geoapify area lookup timed out")
        except (httpx.RequestError, ValueError, AttributeError):
            return GeoapifyPlacesSearchResult(status="unavailable", error="Geoapify area lookup failed")

    async def get_place_details(
        self,
        *,
        place_id: str,
        context: dict[str, Any] | None = None,
    ) -> GeoapifyPlaceDetailsResult:
        """Fetch and normalize Place Details for one Geoapify place id."""

        cache_key = _details_cache_key(place_id)
        cached = await self._cache_get(cache_key)
        if isinstance(cached, dict):
            cached.setdefault("match", {})["cache_hit"] = True
            return GeoapifyPlaceDetailsResult(
                status=str(cached.get("status") or "matched"),
                enrichment=cached,
                cache_hit=True,
            )

        api_key = await self.get_api_key()
        if not api_key:
            enrichment = build_status_enrichment("not_configured")
            return GeoapifyPlaceDetailsResult(
                status="not_configured",
                enrichment=enrichment,
                error="Geoapify API key is not configured",
            )

        params = {"apiKey": api_key, "id": place_id, "features": "details"}
        budget_status = await reserve_credit(self.cache_service, api_key)
        if budget_status != "ok":
            return GeoapifyPlaceDetailsResult(
                status=budget_status, enrichment=build_status_enrichment(budget_status),
                error=_budget_error(budget_status),
            )
        try:
            response = await self._http_get(GEOAPIFY_PLACE_DETAILS_URL, params, self.timeout_seconds)
        except httpx.TimeoutException:
            enrichment = build_status_enrichment("timed_out")
            return GeoapifyPlaceDetailsResult(
                status="timed_out",
                enrichment=enrichment,
                error="Geoapify Place Details request timed out",
            )
        except httpx.RequestError:
            enrichment = build_status_enrichment("unavailable")
            return GeoapifyPlaceDetailsResult(
                status="unavailable",
                enrichment=enrichment,
                error="Geoapify Place Details request failed",
            )

        if response.status_code == 429:
            enrichment = build_status_enrichment("rate_limited")
            return GeoapifyPlaceDetailsResult(
                status="rate_limited",
                enrichment=enrichment,
                error=_safe_response_error(response),
            )
        if response.status_code >= 400:
            enrichment = build_status_enrichment("unavailable")
            return GeoapifyPlaceDetailsResult(
                status="unavailable",
                enrichment=enrichment,
                error=_safe_response_error(response),
            )

        try:
            payload = response.json()
        except ValueError:
            return GeoapifyPlaceDetailsResult(status="unavailable", enrichment=build_status_enrichment("unavailable"), error="Invalid Geoapify response")
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            return GeoapifyPlaceDetailsResult(status="unavailable", enrichment=build_status_enrichment("unavailable"), error="Invalid Geoapify response")
        if not features:
            enrichment = build_status_enrichment("no_match")
            await self._cache_set(cache_key, enrichment, DETAIL_NO_MATCH_TTL_SECONDS)
            return GeoapifyPlaceDetailsResult(status="no_match", enrichment=enrichment)
        if not isinstance(features[0], dict):
            return GeoapifyPlaceDetailsResult(status="unavailable", enrichment=build_status_enrichment("unavailable"), error="Invalid Geoapify response")

        enrichment = normalize_place_details(features[0])
        enrichment.setdefault("match", {})["cache_hit"] = False
        await self._cache_set(cache_key, enrichment, DETAIL_POSITIVE_TTL_SECONDS)
        return GeoapifyPlaceDetailsResult(status="matched", enrichment=enrichment)

    async def _default_http_get(self, url: str, params: dict[str, Any], timeout: float) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.get(url, params=params)

    async def _cache_get(self, key: str) -> Any:
        if not self.cache_service:
            return None
        try:
            return await self.cache_service.get(key)
        except Exception as exc:
            logger.debug("Geoapify cache read failed for key %s: %s", key, exc)
            return None

    async def _cache_set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        if not self.cache_service:
            return
        try:
            await self.cache_service.set(key, value, ttl=ttl)
        except Exception as exc:
            logger.debug("Geoapify cache write failed for key %s: %s", key, exc)


def normalize_place_details(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Geoapify Place Details feature into `osm_enrichment`."""

    feature = _first_feature(payload)
    properties = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(properties, dict):
        return build_status_enrichment("no_match")

    place_id = (
        properties.get("place_id")
        or properties.get("id")
        or feature.get("id")
        or properties.get("osm_id")
    )

    fields = {
        "air_conditioning": _field_record(_pick(properties, (("facilities", "air_conditioning"), ("air_conditioning",)))),
        "internet_access": _field_record(_pick(properties, (("facilities", "internet_access"), ("internet_access",)))),
        "wheelchair": _field_record(_pick(properties, (("facilities", "wheelchair"), ("wheelchair",)))),
        "toilets": _field_record(_pick(properties, (("facilities", "toilets"), ("toilets",)))),
        "smoking": _field_record(_pick(properties, (("facilities", "smoking"), ("smoking",)))),
        "outdoor_seating": _field_record(_pick(properties, (("facilities", "outdoor_seating"), ("outdoor_seating",)))),
        "takeaway": _field_record(_pick(properties, (("facilities", "takeaway"), ("catering", "takeaway"), ("takeaway",)))),
        "delivery": _field_record(_pick(properties, (("facilities", "delivery"), ("catering", "delivery"), ("delivery",)))),
        "dogs": _field_record(_pick(properties, (("facilities", "dogs"), ("dogs",)))),
        "diet": _dict_field_record(_extract_prefixed_values(properties.get("catering"), "diet:")),
        "payment": _dict_field_record(properties.get("payment_options")),
    }

    return {
        "provider": "Geoapify",
        "data_source": GEOAPIFY_SOURCE_LABEL,
        "status": "matched",
        "match": {
            "geoapify_place_id": place_id,
            "method": "place_details",
            "confidence": "provider",
            "cache_hit": False,
        },
        "fields": fields,
    }


def build_status_enrichment(status: str) -> dict[str, Any]:
    """Build a source-labelled enrichment record when details are absent."""

    return {
        "provider": "Geoapify",
        "data_source": GEOAPIFY_SOURCE_LABEL,
        "status": status,
        "match": {"cache_hit": False},
        "fields": _unknown_fields(),
    }


def _clean_api_key(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (
        cleaned.startswith("'") and cleaned.endswith("'")
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned or None


def _partition_supported_conditions(conditions: list[str]) -> tuple[list[str], list[str]]:
    supported: list[str] = []
    unsupported: list[str] = []
    for condition in conditions:
        normalized = str(condition).strip()
        if not normalized:
            continue
        if normalized in SUPPORTED_PLACES_CONDITIONS:
            supported.append(normalized)
        else:
            unsupported.append(normalized)
    return supported, unsupported


def _details_cache_key(place_id: str) -> str:
    digest = hashlib.sha256(str(place_id).encode("utf-8")).hexdigest()
    return f"geoapify:place_details:{DETAIL_CACHE_VERSION}:{digest}"


def _safe_response_error(response: httpx.Response) -> str:
    return f"Geoapify API error {response.status_code}"


def _request_cache_key(endpoint: str, params: dict[str, Any]) -> str:
    # Hash all request parameters, including the key, without exposing them to Redis.
    digest = hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"geoapify:{endpoint}:v1:{digest}"


def _budget_error(status: str) -> str:
    return {
        "quota_exhausted": "Geoapify daily search allowance is exhausted. Try again tomorrow.",
        "quota_unavailable": "Geoapify quota checking is temporarily unavailable. Try again later.",
        "rate_limited": "Geoapify is receiving too many requests. Try again shortly.",
    }.get(status, "Geoapify search is temporarily unavailable")


def _first_feature(payload: dict[str, Any]) -> dict[str, Any]:
    if "properties" in payload:
        return payload
    features = payload.get("features")
    if isinstance(features, list) and features and isinstance(features[0], dict):
        return features[0]
    return {}


def _pick(properties: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        current: Any = properties
        for part in path:
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return None


def _field_record(value: Any) -> dict[str, Any]:
    normalized = _normalize_value(value)
    record = {"value": normalized, "source": GEOAPIFY_SOURCE_LABEL}
    if value is not None:
        record["raw_value"] = value
    return record


def _dict_field_record(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict) or not values:
        return {"value": "unknown", "source": GEOAPIFY_SOURCE_LABEL}
    normalized: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        clean_key = str(key).replace("diet:", "")
        normalized[clean_key] = _normalize_value(value)
        raw[clean_key] = value
    if not normalized:
        return {"value": "unknown", "source": GEOAPIFY_SOURCE_LABEL}
    return {"value": normalized, "source": GEOAPIFY_SOURCE_LABEL, "raw_value": raw}


def _normalize_value(value: Any) -> Any:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value.strip().lower() or "unknown"
    return value


def _extract_prefixed_values(values: Any, prefix: str) -> dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    return {
        key: value
        for key, value in values.items()
        if isinstance(key, str) and key.startswith(prefix)
    }


def _unknown_fields() -> dict[str, dict[str, str]]:
    field_names = [
        "air_conditioning",
        "internet_access",
        "wheelchair",
        "toilets",
        "smoking",
        "outdoor_seating",
        "takeaway",
        "delivery",
        "dogs",
        "diet",
        "payment",
    ]
    return {name: {"value": "unknown", "source": GEOAPIFY_SOURCE_LABEL} for name in field_names}
