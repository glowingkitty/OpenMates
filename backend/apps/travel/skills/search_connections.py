"""Provider-independent connection schemas and filters; search is unavailable."""

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.travel.providers.base_provider import BaseTransportProvider
from backend.shared.providers.geoapify.places import GeoapifyPlacesProvider, GEOAPIFY_SOURCE_LABEL

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 20
MAX_RESULTS_LIMIT = 50
FILTER_OVERFETCH_MULTIPLIER = 3
DEFAULT_MIN_TRANSFER_MINUTES = 10
TRANSFER_AMENITY_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
TRANSFER_STATION_COORDINATE_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
TRANSFER_AMENITY_SEARCH_RADIUS_METERS = 350
TRANSFER_AMENITY_TIMEOUT_SECONDS = 3.0
TRANSFER_AMENITY_GROUPS = {
    "food_drink": {
        "label": "Food and drinks",
        "categories": ["catering"],
    },
    "shops": {
        "label": "Shops",
        "categories": [
            "commercial.supermarket",
            "commercial.convenience",
            "commercial.food_and_drink.bakery",
            "commercial.kiosk",
        ],
    },
    "toilets": {
        "label": "Toilets",
        "categories": ["amenity.toilet"],
    },
}
VALID_PROVIDER_IDS: set[str] = set()
VALID_RAIL_PRODUCTS = {
    "high_speed",
    "intercity",
    "regional_express",
    "regional",
    "s_bahn",
    "subway",
    "tram",
    "bus",
    "ferry",
}
FLAT_ROUTE_ORIGIN_KEYS = ("origin", "from", "from_location")
FLAT_ROUTE_DESTINATION_KEYS = ("destination", "to", "to_location")
FLAT_ROUTE_DATE_KEYS = ("date", "departure_date", "travel_date")


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class LegItem(BaseModel):
    """A single leg of a trip (origin → destination on a specific date)."""

    origin: str = Field(
        description="Origin city or location name (e.g. 'Munich', 'London Heathrow', 'Berlin'). "
        "The system resolves this to airport codes or coordinates internally."
    )
    destination: str = Field(description="Destination city or location name.")
    date: str = Field(description="Departure date in YYYY-MM-DD format.")


class SearchConnectionsRequestItem(BaseModel):
    """A single connection search request (one-way, round trip, or multi-stop)."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    legs: Optional[List[LegItem]] = Field(
        default=None,
        description="Ordered list of trip legs. One-way trip = 1 leg. "
        "Round trip = 2 legs (outbound + return). Multi-stop = N legs."
    )
    origin: Optional[str] = Field(
        default=None,
        description="Flat route origin accepted from LLM/CLI callers. Normalized into legs before execution.",
    )
    destination: Optional[str] = Field(
        default=None,
        description="Flat route destination accepted from LLM/CLI callers. Normalized into legs before execution.",
    )
    date: Optional[str] = Field(
        default=None,
        description="Flat route departure date in YYYY-MM-DD format. Normalized into legs before execution.",
    )
    transport_methods: List[str] = Field(
        default=["airplane"],
        description="Requested transport types. Connection search is currently unavailable.",
    )
    transport_method: Optional[str] = Field(
        default=None,
        description="Singular transport method alias accepted from LLM/CLI callers. Normalized into transport_methods.",
    )
    providers: Optional[List[str]] = Field(
        default=None,
        description="Optional provider IDs. No authorized connection-search provider is configured.",
    )
    provider: Optional[str] = Field(
        default=None,
        description="Singular provider alias accepted from LLM/CLI callers. Normalized into providers.",
    )
    countries: Optional[List[str]] = Field(
        default=None,
        description="Optional ISO 3166-1 alpha-2 country codes involved in the route. "
        "Country matching uses OR semantics: a country-limited provider is eligible if any requested country is supported.",
    )
    passengers: int = Field(default=1, description="Number of adult passengers.")
    children: int = Field(
        default=0,
        description="Number of child passengers (ages 2-11).",
    )
    infants_in_seat: int = Field(
        default=0,
        description="Number of infant passengers with their own seat (under 2).",
    )
    infants_on_lap: int = Field(
        default=0,
        description="Number of lap infants (under 2, seated on adult's lap).",
    )
    travel_class: str = Field(
        default="economy",
        description="Cabin class for flights. One of: economy, premium_economy, business, first.",
    )
    max_results: int = Field(
        default=DEFAULT_MAX_RESULTS,
        description="Maximum number of connection options to return per transport method. Default 20, maximum 50.",
    )
    non_stop_only: bool = Field(
        default=False,
        description="If true, only return direct/non-stop connections.",
    )
    max_stops: Optional[int] = Field(
        default=None,
        description="Maximum number of stops allowed: 0 (non-stop only), 1 (up to 1 stop), "
        "2 (up to 2 stops). When set, overrides non_stop_only.",
    )
    include_airlines: Optional[List[str]] = Field(
        default=None,
        description="Only show flights from these airlines (IATA codes, e.g. ['LH', 'BA']). "
        "Cannot be combined with exclude_airlines.",
    )
    exclude_airlines: Optional[List[str]] = Field(
        default=None,
        description="Exclude flights from these airlines (IATA codes, e.g. ['FR', 'W6']). "
        "Cannot be combined with include_airlines.",
    )
    owned_passes: List[str] = Field(
        default_factory=list,
        description="Fare or mobility pass IDs the traveller already owns, such as 'deutschland_ticket'.",
    )
    pass_only: bool = Field(
        default=False,
        description="If true, prefer routes covered by owned fare passes when the selected provider supports them.",
    )
    rail_products: Optional[List[str]] = Field(
        default=None,
        description="Stable rail product filters: high_speed, intercity, regional_express, regional, s_bahn, subway, tram, bus, ferry.",
    )
    currency: str = Field(
        default="EUR",
        description="Preferred currency for prices (ISO 4217 code).",
    )
    sort_by: str = Field(
        default="price_asc",
        description="How to sort the results. Options: price_asc, price_desc, duration_asc, "
        "duration_desc, departure_asc, departure_desc, stops_asc, stops_desc.",
    )
    min_departure_time: Optional[str] = Field(
        default=None,
        description="Earliest acceptable departure time in HH:MM local time. Supports overnight windows with max_departure_time.",
    )
    max_departure_time: Optional[str] = Field(
        default=None,
        description="Latest acceptable departure time in HH:MM local time. Supports overnight windows with min_departure_time.",
    )
    min_arrival_time: Optional[str] = Field(
        default=None,
        description="Earliest acceptable arrival time in HH:MM local time. Supports overnight windows with max_arrival_time.",
    )
    max_arrival_time: Optional[str] = Field(
        default=None,
        description="Latest acceptable arrival time in HH:MM local time. Supports overnight windows with min_arrival_time.",
    )
    max_duration_minutes: Optional[int] = Field(
        default=None,
        description="Maximum total duration for the first leg, in minutes.",
    )
    min_transfer_minutes: int = Field(
        default=DEFAULT_MIN_TRANSFER_MINUTES,
        description="Minimum acceptable layover/transfer duration, in minutes. Defaults to 10.",
    )
    max_layover_minutes: Optional[int] = Field(
        default=None,
        description="Maximum allowed layover/transfer duration, in minutes.",
    )
    avoid_overnight_layovers: bool = Field(
        default=False,
        description="If true, remove connections with any overnight layover/transfer.",
    )


class SearchConnectionsRequest(BaseModel):
    """Incoming request payload for the search_connections skill."""

    requests: List[SearchConnectionsRequestItem] = Field(
        description="Array of connection search requests. Each request searches for "
        "transport connections for a complete trip (one-way, round trip, or multi-stop)."
    )


# Registry of known transport providers with display metadata.
# Each provider that can return results should have an entry here.
# icon_url is used as a favicon in the search preview (like web search favicons).
PROVIDER_REGISTRY: Dict[str, Dict[str, str]] = {}


class SearchConnectionsResponse(BaseModel):
    """
    Response payload for the search_connections skill.

    Follows the standard OpenMates skill response structure with grouped results,
    provider info, suggestions, and optional error.
    """

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array",
    )
    provider: str = Field(default="")
    providers: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Providers that returned results, each with 'id', 'name', 'icon_url'",
    )
    provider_required: bool = True
    available: bool = False
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: ["type", "hash", "carrier_code", "segments"]
    )


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

def _create_providers(secrets_manager: Any = None) -> List[BaseTransportProvider]:
    """No authorized connection-search provider is configured."""
    return []


def _get_providers_for_request(
    all_providers: List[BaseTransportProvider],
    transport_methods: List[str],
    requested_providers: Optional[List[str]] = None,
    countries: Optional[List[str]] = None,
) -> List[BaseTransportProvider]:
    """Return providers matching transport methods, optional provider IDs, and route countries."""
    provider_values = requested_providers if isinstance(requested_providers, list) else []
    country_values = countries if isinstance(countries, list) else []
    requested_provider_ids = {
        str(provider).strip().lower()
        for provider in provider_values
        if str(provider).strip().lower() in VALID_PROVIDER_IDS
    }
    requested_countries = {
        str(country).strip().upper()
        for country in country_values
        if re.match(r"^[A-Za-z]{2}$", str(country).strip())
    }
    has_provider_filter = bool(provider_values)

    matched: List[BaseTransportProvider] = []
    for provider in all_providers:
        provider_id = getattr(provider, "provider_id", "")
        if has_provider_filter and provider_id not in requested_provider_ids:
            logger.info("Skipping provider %s because it was not requested", provider_id or type(provider).__name__)
            continue
        if not any(provider.supports_transport_method(method) for method in transport_methods):
            continue
        provider_countries = getattr(provider, "supported_countries", None)
        if requested_countries and provider_countries is not None and not requested_countries.intersection(provider_countries):
            logger.info(
                "Skipping provider %s because countries %s do not match supported countries %s",
                provider_id or type(provider).__name__,
                sorted(requested_countries),
                sorted(provider_countries),
            )
            continue
        matched.append(provider)
    return matched


def _provider_metadata(provider: BaseTransportProvider) -> Dict[str, str]:
    """Return display metadata for a searched provider."""
    provider_id = getattr(provider, "provider_id", "") or type(provider).__name__
    meta = PROVIDER_REGISTRY.get(provider_id)
    if meta:
        return {"id": provider_id, **meta}
    return {"id": provider_id, "name": provider_id, "icon_url": ""}


def _request_query_summary(req: Dict[str, Any]) -> str:
    """Build a compact route/date summary from the original request."""
    legs = req.get("legs", []) if isinstance(req.get("legs"), list) else []
    if not legs:
        return ""

    first_leg = legs[0]
    last_leg = legs[-1]
    origin = str(first_leg.get("origin") or "").strip()
    destination = str(last_leg.get("destination") or "").strip()
    date = str(first_leg.get("date") or "").strip()

    summary = f"{origin} → {destination}" if origin and destination else origin or destination
    if date:
        summary = f"{summary}, {date}" if summary else date
    return summary


def _first_string_value(req: Dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    for key in keys:
        value = req.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_connection_requests(requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Accept obvious flat LLM route args while keeping the canonical legs contract."""
    normalized_requests: List[Dict[str, Any]] = []
    for raw_request in requests:
        req = raw_request.model_dump() if hasattr(raw_request, "model_dump") else raw_request
        if not isinstance(req, dict):
            normalized_requests.append(req)
            continue

        req = dict(req)
        if not req.get("legs"):
            origin = _first_string_value(req, FLAT_ROUTE_ORIGIN_KEYS)
            destination = _first_string_value(req, FLAT_ROUTE_DESTINATION_KEYS)
            date = _first_string_value(req, FLAT_ROUTE_DATE_KEYS)
            if origin and destination and date:
                req["legs"] = [{"origin": origin, "destination": destination, "date": date}]

        transport_methods = req.get("transport_methods")
        has_default_transport_methods = transport_methods == ["airplane"]
        if (
            ("transport_methods" not in req or has_default_transport_methods)
            and isinstance(req.get("transport_method"), str)
        ):
            transport_method = req["transport_method"].strip().lower()
            if transport_method:
                req["transport_methods"] = [transport_method]

        if "providers" not in req and isinstance(req.get("provider"), str):
            provider = req["provider"].strip().lower()
            if provider:
                req["providers"] = [provider]

        normalized_requests.append(req)
    return normalized_requests


# ---------------------------------------------------------------------------
# SearchConnectionsSkill
# ---------------------------------------------------------------------------

class SearchConnectionsSkill(BaseSkill):
    """
    Skill that searches for transport connections between locations.

    Accepts a 'requests' array where each request contains:
    - legs: ordered list of trip legs (origin, destination, date)
    - transport_methods: list of transport types to search (default: ["airplane"])
    - passengers: number of adult passengers (default: 1)
    - travel_class: cabin/travel class (default: "economy")
    - max_results: max connection options per transport method (default: 20, max: 50)
    - non_stop_only: if true, only return direct connections (default: false)
    - currency: preferred currency for prices (default: "EUR")

    Returns connection results grouped by request ID, where each result
    represents one bookable connection option with legs, segments, prices, etc.
    """

    # Suggestions displayed after successful execution
    FOLLOW_UP_SUGGESTIONS = [
        "Search for cheaper dates",
        "Show only direct flights",
        "Search for trains instead",
    ]

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        return {"provider": "", "providers": [], "provider_required": True,
                "available": False, "query": _request_query_summary(request)}

    async def execute(self, requests: List[Dict[str, Any]], **kwargs: Any) -> SearchConnectionsResponse:
        message = "Connection search is unavailable: no authorized provider is configured."
        groups = [
            {"id": request.get("id", index), "results": [], "error": message}
            for index, request in enumerate(requests or [])
            if isinstance(request, dict)
        ]
        return SearchConnectionsResponse(results=groups, error=message)

    @staticmethod
    def _annotate_empty_result_group(group: Dict[str, Any], request: Dict[str, Any]) -> None:
        """Add no-result metadata for successful empty connection groups."""
        if group.get("results") or group.get("error"):
            return
        has_constraints = any(
            request.get(key) not in (None, "", False)
            for key in (
                "non_stop_only",
                "max_stops",
                "max_price",
                "include_airlines",
                "exclude_airlines",
                "min_departure_time",
                "max_departure_time",
                "min_arrival_time",
                "max_arrival_time",
                "max_duration_minutes",
                "min_transfer_minutes",
                "max_layover_minutes",
                "avoid_overnight_layovers",
            )
        )
        group["no_result_reason"] = "filtered_out" if has_constraints else "no_matches"
        group["suggestions"] = [
            "Increase the price limit",
            "Allow one stop or connection",
            "Try nearby dates or airports",
        ]

    async def _process_single_request(self, req: Dict[str, Any], request_id: Any, **kwargs: Any) -> tuple:
        return (request_id, [], "Connection search is unavailable: no authorized provider is configured.")

    # ------------------------------------------------------------------
    # Sorting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp_max_results(value: Any) -> int:
        """Clamp requested result count to the supported range."""
        try:
            requested = int(value)
        except (TypeError, ValueError):
            requested = DEFAULT_MAX_RESULTS
        return max(1, min(requested, MAX_RESULTS_LIMIT))

    @staticmethod
    def _extract_result_filters(req: Dict[str, Any]) -> Dict[str, Any]:
        """Return only supported result-level filters that were explicitly set."""
        filter_keys = (
            "max_stops",
            "max_price",
            "min_departure_time",
            "max_departure_time",
            "min_arrival_time",
            "max_arrival_time",
            "max_duration_minutes",
            "min_transfer_minutes",
            "max_layover_minutes",
            "avoid_overnight_layovers",
            "pass_only",
            "rail_products",
        )
        return {
            key: req[key]
            for key in filter_keys
            if req.get(key) not in (None, False, "")
        }

    @staticmethod
    def _provider_fetch_limit(max_results: int, result_filters: Dict[str, Any]) -> int:
        """Overfetch when post-provider filters are active so final results stay useful."""
        if not result_filters:
            return max_results
        return min(MAX_RESULTS_LIMIT, max_results * FILTER_OVERFETCH_MULTIPLIER)

    @staticmethod
    def _valid_rail_products(value: Any) -> Optional[List[str]]:
        """Return valid stable rail product filters or None when unset."""
        if not isinstance(value, list):
            return None
        products: List[str] = []
        for item in value:
            normalized = str(item).strip().lower()
            if normalized not in VALID_RAIL_PRODUCTS:
                continue
            if normalized not in products:
                products.append(normalized)
        return products or None

    @staticmethod
    def _normalize_min_transfer_minutes(value: Any) -> tuple[int, Optional[str]]:
        """Return the effective minimum transfer time or a validation error."""
        if value in (None, ""):
            return DEFAULT_MIN_TRANSFER_MINUTES, None
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return DEFAULT_MIN_TRANSFER_MINUTES, "min_transfer_minutes must be an integer"
        if minutes < 0:
            return DEFAULT_MIN_TRANSFER_MINUTES, "min_transfer_minutes must be greater than or equal to 0"
        return minutes, None

    @staticmethod
    def _fare_dict_for_connection(connection: Any) -> Optional[Dict[str, Any]]:
        """Return structured fare metadata, synthesizing it for legacy priced providers."""
        if getattr(connection, "fare", None):
            return connection.fare.model_dump()
        price = getattr(connection, "total_price", None)
        currency = getattr(connection, "currency", None)
        if price is not None:
            try:
                amount = float(price)
            except (TypeError, ValueError):
                amount = None
            return {
                "amount": amount,
                "currency": currency,
                "is_partial": bool(getattr(connection, "fare_is_partial", False)),
                "is_pass_only": False,
                "covered_by_passes": getattr(connection, "fare_passes_applied", None) or [],
                "pricing_provider": getattr(connection, "source_provider", None),
                "confidence": "partial" if getattr(connection, "fare_is_partial", False) else "confirmed",
                "summary": f"{currency or ''} {price} confirmed fare.".strip(),
            }
        return {
            "amount": None,
            "currency": None,
            "is_partial": False,
            "is_pass_only": False,
            "covered_by_passes": [],
            "pricing_provider": getattr(connection, "source_provider", None),
            "confidence": "unknown",
            "summary": "No fare returned for this connection.",
        }

    @staticmethod
    def _annotate_transfer_quality(
        result: Dict[str, Any],
        min_transfer_minutes: int,
        existing_quality: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Attach transfer-quality metadata and per-layover min-transfer flags."""

        has_transfers = False
        short_transfer_count = 0
        unknown_transfer_count = 0
        for leg in result.get("legs", []) or []:
            for layover in leg.get("layovers", []) or []:
                has_transfers = True
                duration = layover.get("duration_minutes")
                if duration is None:
                    unknown_transfer_count += 1
                    continue
                meets = int(duration) >= min_transfer_minutes
                layover["meets_min_transfer"] = meets
                if not meets:
                    short_transfer_count += 1

        quality = {
            "min_transfer_minutes": min_transfer_minutes,
            "has_transfers": has_transfers,
            "short_transfer_count": short_transfer_count,
        }
        if unknown_transfer_count:
            quality["unknown_transfer_count"] = unknown_transfer_count
        if existing_quality:
            quality.update(existing_quality)
            quality.setdefault("min_transfer_minutes", min_transfer_minutes)
            quality.setdefault("has_transfers", has_transfers)
            quality.setdefault("short_transfer_count", short_transfer_count)
        result["transfer_quality"] = quality

    async def _enrich_transfer_amenities(
        self,
        results: List[Dict[str, Any]],
        *,
        secrets_manager: Any,
        cache_service: Any,
    ) -> List[Dict[str, Any]]:
        """Add bounded Geoapify amenity summaries to train/bus transfer stops."""

        if not secrets_manager:
            return results
        provider: Optional[GeoapifyPlacesProvider] = None
        for result in results:
            if result.get("transport_method") not in {"train", "bus"}:
                continue
            min_transfer = (result.get("transfer_quality") or {}).get("min_transfer_minutes")
            for leg in result.get("legs", []) or []:
                for layover in leg.get("layovers", []) or []:
                    if layover.get("amenities"):
                        continue
                    duration = layover.get("duration_minutes")
                    if duration is not None and min_transfer is not None and int(duration) < int(min_transfer):
                        continue
                    coordinates = await self._resolve_transfer_coordinates(
                        cache_service=cache_service,
                        station=str(layover.get("airport") or ""),
                        latitude=layover.get("latitude"),
                        longitude=layover.get("longitude"),
                    )
                    if coordinates:
                        layover["latitude"] = coordinates["latitude"]
                        layover["longitude"] = coordinates["longitude"]
                    provider = provider or GeoapifyPlacesProvider(
                        secrets_manager=secrets_manager,
                        cache_service=cache_service,
                        timeout_seconds=TRANSFER_AMENITY_TIMEOUT_SECONDS,
                    )
                    layover["amenities"] = await self._transfer_amenity_summary(
                        provider,
                        cache_service=cache_service,
                        station=str(layover.get("airport") or ""),
                        latitude=layover.get("latitude"),
                        longitude=layover.get("longitude"),
                    )
        return results

    async def _transfer_amenity_summary(
        self,
        provider: GeoapifyPlacesProvider,
        *,
        cache_service: Any,
        station: str,
        latitude: Any,
        longitude: Any,
    ) -> Dict[str, Any]:
        """Return cached food/shop/toilet counts near one transfer station."""

        cache_key = self._transfer_amenity_cache_key(station, latitude, longitude)
        cached = await self._cache_get(cache_service, cache_key)
        if isinstance(cached, dict):
            cached = dict(cached)
            cached["cache_hit"] = True
            return cached

        geo_filter = self._geoapify_circle_filter(latitude, longitude)
        if not geo_filter:
            return self._transfer_amenity_status_summary("missing_coordinates")

        groups: Dict[str, Any] = {}
        for group_id, group in TRANSFER_AMENITY_GROUPS.items():
            search_result = await provider.search_places(
                query=station,
                limit=10,
                categories=group["categories"],
                geo_filter=geo_filter,
                bias=geo_filter,
            )
            if search_result.status != "ok":
                groups[group_id] = {
                    "label": group["label"],
                    "status": search_result.status,
                    "count": 0,
                    "items": [],
                }
                continue
            items = [
                self._geoapify_place_label(place)
                for place in search_result.places[:3]
            ]
            groups[group_id] = {
                "label": group["label"],
                "status": "matched" if search_result.places else "no_match",
                "count": len(search_result.places),
                "items": [item for item in items if item],
            }

        provider_error_status = next(
            (
                group["status"]
                for group in groups.values()
                if group["status"] not in {"matched", "no_match"}
            ),
            None,
        )
        summary = {
            "provider": "Geoapify",
            "data_source": GEOAPIFY_SOURCE_LABEL,
            "status": (
                "matched"
                if any(group["count"] for group in groups.values())
                else provider_error_status or "no_match"
            ),
            "cache_hit": False,
            "groups": groups,
        }
        await self._cache_set(cache_service, cache_key, summary, TRANSFER_AMENITY_CACHE_TTL_SECONDS)
        return summary

    async def _resolve_transfer_coordinates(
        self, *, cache_service: Any, station: str, latitude: Any, longitude: Any,
    ) -> Optional[Dict[str, float]]:
        """Only use coordinates supplied with historical transport data."""
        coordinates = self._coerce_coordinates(latitude, longitude)
        if not coordinates:
            return None
        lat, lon = coordinates
        return {"latitude": lat, "longitude": lon}

    @classmethod
    def _pick_transfer_location(cls, station: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        normalized_station = cls._normalize_transfer_station_name(station)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            normalized_name = cls._normalize_transfer_station_name(str(candidate.get("name") or ""))
            if normalized_name == normalized_station:
                return candidate
        return None

    @staticmethod
    def _normalize_transfer_station_name(value: str) -> str:
        normalized = value.lower().strip()
        replacements = {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
            "-": " ",
            "(": " ",
            ")": " ",
            ",": " ",
        }
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        words = [
            word
            for word in normalized.split()
            if word not in {"bf", "bhf", "bahnhof", "hbf", "hauptbahnhof"}
        ]
        return " ".join(words)

    @staticmethod
    def _transfer_amenity_status_summary(status: str) -> Dict[str, Any]:
        return {
            "provider": "Geoapify",
            "data_source": GEOAPIFY_SOURCE_LABEL,
            "status": status,
            "cache_hit": False,
            "groups": {
                group_id: {
                    "label": group["label"],
                    "status": status,
                    "count": 0,
                    "items": [],
                }
                for group_id, group in TRANSFER_AMENITY_GROUPS.items()
            },
        }

    @staticmethod
    def _geoapify_place_label(place: Dict[str, Any]) -> str:
        properties = place.get("properties") if isinstance(place, dict) else None
        if not isinstance(properties, dict):
            return ""
        return str(properties.get("name") or properties.get("formatted") or "")

    @staticmethod
    def _geoapify_circle_filter(latitude: Any, longitude: Any) -> Optional[str]:
        coordinates = SearchConnectionsSkill._coerce_coordinates(latitude, longitude)
        if not coordinates:
            return None
        lat, lon = coordinates
        return f"circle:{lon},{lat},{TRANSFER_AMENITY_SEARCH_RADIUS_METERS}"

    @staticmethod
    def _coerce_coordinates(latitude: Any, longitude: Any) -> Optional[tuple[float, float]]:
        try:
            lat = float(latitude)
            lon = float(longitude)
        except (TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return lat, lon

    @staticmethod
    def _transfer_amenity_cache_key(station: str, latitude: Any, longitude: Any) -> str:
        raw = json.dumps({"station": station, "lat": latitude, "lon": longitude}, sort_keys=True)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return f"travel:transfer_amenities:v1:{digest}"

    @staticmethod
    def _transfer_coordinate_cache_key(station: str) -> str:
        raw = json.dumps({"station": station.strip().lower()}, sort_keys=True)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return f"travel:transfer_coordinates:v1:{digest}"

    @staticmethod
    async def _cache_get(cache_service: Any, key: str) -> Any:
        if not cache_service:
            return None
        try:
            return await cache_service.get(key)
        except Exception as exc:
            logger.debug("Transfer amenity cache read failed for %s: %s", key, exc)
            return None

    @staticmethod
    async def _cache_set(cache_service: Any, key: str, value: Dict[str, Any], ttl: int) -> None:
        if not cache_service:
            return
        try:
            await cache_service.set(key, value, ttl=ttl)
        except Exception as exc:
            logger.debug("Transfer amenity cache write failed for %s: %s", key, exc)

    def _filter_results(
        self,
        results: List[Dict[str, Any]],
        result_filters: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Apply cross-provider filters to normalized connection result dicts."""
        filtered: List[Dict[str, Any]] = []
        for result in results:
            if not self._matches_max_stops(result, result_filters.get("max_stops")):
                continue
            if not self._matches_max_price(result, result_filters.get("max_price")):
                continue
            if not self._matches_time_window(
                result.get("departure"),
                result_filters.get("min_departure_time"),
                result_filters.get("max_departure_time"),
            ):
                continue
            if not self._matches_time_window(
                result.get("arrival"),
                result_filters.get("min_arrival_time"),
                result_filters.get("max_arrival_time"),
            ):
                continue
            if not self._matches_max_duration(result, result_filters.get("max_duration_minutes")):
                continue
            if not self._matches_layover_filters(
                result,
                result_filters.get("min_transfer_minutes"),
                result_filters.get("max_layover_minutes"),
                bool(result_filters.get("avoid_overnight_layovers")),
            ):
                continue
            filtered.append(result)
        return filtered

    @staticmethod
    def _matches_max_stops(result: Dict[str, Any], max_stops: Any) -> bool:
        if max_stops in (None, ""):
            return True
        try:
            max_stops_int = int(max_stops)
        except (TypeError, ValueError):
            return True
        stops = result.get("stops")
        if stops is None:
            return False
        try:
            return int(stops) <= max_stops_int
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _matches_max_price(result: Dict[str, Any], max_price: Any) -> bool:
        if max_price in (None, ""):
            return True
        try:
            max_price_float = float(max_price)
            price = float(result.get("total_price"))
        except (TypeError, ValueError):
            return False
        return price <= max_price_float

    @staticmethod
    def _matches_time_window(
        value: Any,
        min_time: Optional[str],
        max_time: Optional[str],
    ) -> bool:
        """Check a local HH:MM value against an optional inclusive time window."""
        if not min_time and not max_time:
            return True
        value_minutes = SearchConnectionsSkill._extract_time_minutes(value)
        if value_minutes is None:
            return False
        min_minutes = SearchConnectionsSkill._parse_time_minutes(min_time) if min_time else None
        max_minutes = SearchConnectionsSkill._parse_time_minutes(max_time) if max_time else None
        if min_time and min_minutes is None:
            min_minutes = None
        if max_time and max_minutes is None:
            max_minutes = None
        if min_minutes is not None and max_minutes is not None:
            if min_minutes <= max_minutes:
                return min_minutes <= value_minutes <= max_minutes
            return value_minutes >= min_minutes or value_minutes <= max_minutes
        if min_minutes is not None:
            return value_minutes >= min_minutes
        if max_minutes is not None:
            return value_minutes <= max_minutes
        return True

    @staticmethod
    def _matches_max_duration(result: Dict[str, Any], max_duration_minutes: Any) -> bool:
        if max_duration_minutes in (None, ""):
            return True
        try:
            max_minutes = int(max_duration_minutes)
        except (TypeError, ValueError):
            return True
        duration_minutes = SearchConnectionsSkill._parse_duration_minutes(str(result.get("duration", "")))
        if duration_minutes is None:
            return False
        return duration_minutes <= max_minutes

    @staticmethod
    def _matches_layover_filters(
        result: Dict[str, Any],
        min_transfer_minutes: Any,
        max_layover_minutes: Any,
        avoid_overnight_layovers: bool,
    ) -> bool:
        try:
            min_minutes = int(min_transfer_minutes) if min_transfer_minutes not in (None, "") else None
        except (TypeError, ValueError):
            min_minutes = None
        try:
            max_minutes = int(max_layover_minutes) if max_layover_minutes not in (None, "") else None
        except (TypeError, ValueError):
            max_minutes = None

        for leg in result.get("legs", []) or []:
            for layover in leg.get("layovers", []) or []:
                if avoid_overnight_layovers and layover.get("overnight"):
                    return False
                duration = layover.get("duration_minutes")
                if min_minutes is not None and duration is not None and duration < min_minutes:
                    return False
                if max_minutes is not None and duration is not None and duration > max_minutes:
                    return False
        return True

    @staticmethod
    def _parse_time_minutes(value: Optional[str]) -> Optional[int]:
        if not value or not isinstance(value, str):
            return None
        match = re.match(r"^(\d{1,2}):(\d{2})$", value.strip())
        if not match:
            return None
        hours = int(match.group(1))
        minutes = int(match.group(2))
        if hours > 23 or minutes > 59:
            return None
        return hours * 60 + minutes

    @staticmethod
    def _extract_time_minutes(value: Any) -> Optional[int]:
        if not value or not isinstance(value, str):
            return None
        match = re.search(r"(?:T|\s)(\d{2}):(\d{2})", value)
        if not match:
            match = re.match(r"^(\d{1,2}):(\d{2})$", value.strip())
        if not match:
            return None
        hours = int(match.group(1))
        minutes = int(match.group(2))
        if hours > 23 or minutes > 59:
            return None
        return hours * 60 + minutes

    # Valid sort_by values and their defaults
    VALID_SORT_OPTIONS = {
        "price_asc", "price_desc",
        "duration_asc", "duration_desc",
        "departure_asc", "departure_desc",
        "stops_asc", "stops_desc",
    }

    def _sort_results(self, results: List[Dict[str, Any]], sort_by: str) -> None:
        """
        Sort connection result dicts in-place according to the sort_by parameter.

        Supported values:
          - price_asc / price_desc     → by total_price (numeric)
          - duration_asc / duration_desc → by first-leg duration string (e.g., '2h 30m')
          - departure_asc / departure_desc → by first-leg departure ISO timestamp
          - stops_asc / stops_desc     → by number of stops on first leg

        Results missing the sort field are always placed at the end regardless of
        ascending/descending direction.
        """
        if sort_by not in self.VALID_SORT_OPTIONS:
            logger.warning(f"Unknown sort_by value '{sort_by}', falling back to 'price_asc'")
            sort_by = "price_asc"

        field, direction = sort_by.rsplit("_", 1)
        reverse = direction == "desc"

        if field == "price":
            priced = [result for result in results if self._sort_key_price(result)[0] == 0]
            unpriced = [result for result in results if self._sort_key_price(result)[0] != 0]
            priced.sort(key=lambda r: self._sort_key_price(r)[1], reverse=reverse)
            results[:] = priced + unpriced
        elif field == "duration":
            results.sort(key=lambda r: self._sort_key_duration(r), reverse=reverse)
        elif field == "departure":
            results.sort(key=lambda r: self._sort_key_departure(r), reverse=reverse)
        elif field == "stops":
            results.sort(key=lambda r: self._sort_key_stops(r), reverse=reverse)

    @staticmethod
    def _sort_key_price(result: Dict[str, Any]) -> tuple:
        """Sort key: (has_value, price). Missing prices sort last."""
        price_str = result.get("total_price")
        fare = result.get("fare") if isinstance(result.get("fare"), dict) else None
        if fare:
            confidence = fare.get("confidence")
            amount = fare.get("amount")
            if confidence in {"confirmed", "partial"} and amount is not None:
                try:
                    return (0, float(amount))
                except (ValueError, TypeError):
                    pass
        if price_str is not None:
            try:
                return (0, float(price_str))
            except (ValueError, TypeError):
                pass
        return (1, float("inf"))

    @staticmethod
    def _sort_key_duration(result: Dict[str, Any]) -> tuple:
        """Sort key: (has_value, duration_minutes). Missing durations sort last."""
        duration_str = result.get("duration")
        if duration_str:
            minutes = SearchConnectionsSkill._parse_duration_minutes(duration_str)
            if minutes is not None:
                return (0, minutes)
        return (1, float("inf"))

    @staticmethod
    def _sort_key_departure(result: Dict[str, Any]) -> tuple:
        """Sort key: (has_value, departure_iso). Missing departures sort last."""
        dep = result.get("departure")
        if dep and isinstance(dep, str):
            return (0, dep)
        return (1, "")

    @staticmethod
    def _sort_key_stops(result: Dict[str, Any]) -> tuple:
        """Sort key: (has_value, stops). Missing stops sort last."""
        stops = result.get("stops")
        if stops is not None and isinstance(stops, (int, float)):
            return (0, int(stops))
        return (1, float("inf"))

    @staticmethod
    def _parse_duration_minutes(duration_str: str) -> Optional[int]:
        """
        Parse a human-readable duration string like '2h 30m' or '14h 5m' into
        total minutes. Returns None if the string cannot be parsed.
        """
        import re
        total = 0
        found = False
        # Match hours
        h_match = re.search(r"(\d+)\s*h", duration_str)
        if h_match:
            total += int(h_match.group(1)) * 60
            found = True
        # Match minutes
        m_match = re.search(r"(\d+)\s*m", duration_str)
        if m_match:
            total += int(m_match.group(1))
            found = True
        return total if found else None

    @staticmethod
    def _generate_connection_hash(connection: Any) -> str:
        """Generate a unique hash for a connection based on its key attributes."""
        hash_input = json.dumps({
            "transport": connection.transport_method,
            "price": connection.total_price,
            "currency": connection.currency,
            "legs": [
                {
                    "origin": leg.origin,
                    "dest": leg.destination,
                    "dep": leg.departure,
                    "arr": leg.arrival,
                }
                for leg in connection.legs
            ],
        }, sort_keys=True)
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
