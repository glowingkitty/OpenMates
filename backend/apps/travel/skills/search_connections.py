"""
Search Connections skill for the travel app.

Searches for transport connections (flights and trains) between locations.
Uses a provider abstraction layer where each transport method is handled
by a dedicated provider (SerpApiProvider for flights via Google Flights,
DeutscheBahnProvider for trains via the DB Navigator API).

The skill follows the standard BaseSkill request/response pattern with the
'requests' array convention used by all OpenMates skills.
"""

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.app_skill_helpers import sanitize_long_text_fields_in_payload
from backend.apps.travel.providers.base_provider import BaseTransportProvider
from backend.apps.travel.providers.serpapi_provider import SerpApiProvider
from backend.apps.travel.providers.db_provider import DeutscheBahnProvider
from backend.apps.travel.providers.flix_provider import FlixProvider

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 20
MAX_RESULTS_LIMIT = 50
FILTER_OVERFETCH_MULTIPLIER = 3
VALID_PROVIDER_IDS = {"google_flights", "deutsche_bahn", "flix"}


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

    legs: List[LegItem] = Field(
        description="Ordered list of trip legs. One-way trip = 1 leg. "
        "Round trip = 2 legs (outbound + return). Multi-stop = N legs."
    )
    transport_methods: List[str] = Field(
        default=["airplane"],
        description="Transport types to search. Supported: 'airplane' (worldwide via Google Flights), "
        "'train' (Germany + select European routes via Deutsche Bahn and FlixTrain), "
        "'bus' (FlixBus / Greyhound network where available).",
    )
    providers: Optional[List[str]] = Field(
        default=None,
        description="Optional provider IDs to search. Supported: google_flights, deutsche_bahn, flix. "
        "If omitted, all providers for the selected transport method are used, then filtered by countries if provided.",
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
PROVIDER_REGISTRY: Dict[str, Dict[str, str]] = {
    "google_flights": {
        "name": "Google Flights",
        "icon_url": "https://www.gstatic.com/flights/airline_logos/70px/dark/multi.png",
    },
    "deutsche_bahn": {
        "name": "Deutsche Bahn",
        "icon_url": "https://www.bahn.de/favicon.ico",
    },
    "flix": {
        "name": "FlixBus / FlixTrain",
        "icon_url": "https://www.flixbus.com/favicon.ico",
    },
    # Add new providers here as they are integrated:
    # "trainline": {
    #     "name": "Trainline",
    #     "icon_url": "https://www.thetrainline.com/favicon.ico",
    # },
}


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
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: ["type", "hash", "carrier_code", "segments"]
    )


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

def _create_providers(
    secrets_manager: Optional["SecretsManager"] = None,
) -> List[BaseTransportProvider]:
    """
    Instantiate all available transport providers.

    SerpApiProvider handles flights via Google Flights (comprehensive coverage,
    real-time pricing, booking links). DeutscheBahnProvider handles trains via
    the DB Navigator API (German + select European routes, real-time pricing).

    Args:
        secrets_manager: Optional SecretsManager for providers that need
            to load API keys from Vault.
    """
    providers: List[BaseTransportProvider] = [
        SerpApiProvider(secrets_manager=secrets_manager),
        DeutscheBahnProvider(),
    ]
    if os.getenv("ENABLE_FLIX_PROVIDER", "true").lower() not in {"0", "false", "no"}:
        providers.extend([
            FlixProvider(supported_methods={"bus"}),
            FlixProvider(supported_methods={"train"}),
        ])
    return providers


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
        """Resolve selected transport providers before network search starts."""
        transport_methods = request.get("transport_methods")
        if not isinstance(transport_methods, list) or not transport_methods:
            transport_methods = ["airplane"]

        requested_providers = request.get("providers")
        requested_ids = (
            {
                str(provider).strip().lower()
                for provider in requested_providers
                if str(provider).strip().lower() in VALID_PROVIDER_IDS
            }
            if isinstance(requested_providers, list)
            else set()
        )

        selected_ids: list[str] = []
        for method in transport_methods:
            if method == "airplane":
                selected_ids.append("google_flights")
            elif method == "train":
                selected_ids.extend(["deutsche_bahn", "flix"])
            elif method == "bus":
                selected_ids.append("flix")

        if requested_ids:
            selected_ids = [provider_id for provider_id in selected_ids if provider_id in requested_ids]

        seen: set[str] = set()
        providers: list[Dict[str, str]] = []
        for provider_id in selected_ids:
            if provider_id in seen or provider_id not in PROVIDER_REGISTRY:
                continue
            seen.add(provider_id)
            providers.append({"id": provider_id, **PROVIDER_REGISTRY[provider_id]})

        provider = providers[0]["name"] if len(providers) == 1 else ""
        return {
            "provider": provider,
            "providers": providers,
            "query": _request_query_summary(request),
        }

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Any = None,
        **kwargs: Any,
    ) -> SearchConnectionsResponse:
        """
        Execute the search connections skill.

        1. Obtains SecretsManager for API credential access
        2. Validates the requests array (requires 'legs' field)
        3. Processes each request via _process_single_request
        4. Groups results by request ID
        5. Returns SearchConnectionsResponse
        """
        # 1. Get or create SecretsManager
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="SearchConnectionsSkill",
            error_response_factory=lambda msg: SearchConnectionsResponse(results=[], error=msg),
            logger=logger,
        )
        if error_response:
            return error_response

        validated_requests, invalid_grouped_results, validation_errors, validation_error = self._partition_requests_by_required_fields(
            requests=requests,
            required_fields=["legs"],
            field_display_names={"legs": "legs"},
            empty_error_message="No connection search requests provided",
            logger=logger,
        )
        if validation_error:
            return SearchConnectionsResponse(results=[], error=validation_error)
        if not validated_requests:
            return self._build_response_with_errors(
                response_class=SearchConnectionsResponse,
                grouped_results=invalid_grouped_results,
                errors=validation_errors,
                provider="",
                providers=[],
                suggestions=self.FOLLOW_UP_SUGGESTIONS,
                logger=logger,
            )

        # 3. Create providers (SerpApiProvider loads its API key from Vault)
        all_providers = _create_providers(secrets_manager=secrets_manager)

        # 4. Process requests in parallel
        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            skill_name="SearchConnectionsSkill",
            logger=logger,
            all_providers=all_providers,
            secrets_manager=secrets_manager,
            cache_service=kwargs.get("cache_service"),
        )

        # 5. Group results by request ID
        grouped_results, errors = self._group_results_by_request_id(
            results=all_results,
            requests=requests,
            logger=logger,
        )
        grouped_results = self._merge_grouped_results_preserving_request_order(
            grouped_results,
            invalid_grouped_results,
            requests,
        )

        request_by_id = {req.get("id"): req for req in requests}
        searched_provider_ids: set[str] = set()
        for group in grouped_results:
            req = request_by_id.get(group.get("id"))
            if not req:
                continue
            transport_methods = [
                method
                for method in req.get("transport_methods", ["airplane"])
                if method in {"airplane", "train", "bus", "boat"}
            ] or ["airplane"]
            matched_providers = _get_providers_for_request(
                all_providers,
                transport_methods,
                requested_providers=req.get("providers"),
                countries=req.get("countries"),
            )
            group_providers: List[Dict[str, str]] = []
            seen_group_provider_ids: set[str] = set()
            for provider in matched_providers:
                metadata = _provider_metadata(provider)
                if metadata["id"] in seen_group_provider_ids:
                    continue
                seen_group_provider_ids.add(metadata["id"])
                group_providers.append(metadata)
            searched_provider_ids.update(provider["id"] for provider in group_providers)
            group["query"] = _request_query_summary(req)
            group["legs"] = req.get("legs", [])
            group["transport_methods"] = transport_methods
            group["providers"] = group_providers
            group["result_count"] = len(group.get("results", []))

        # 6. Determine provider attribution from searched providers first, falling
        # back to actual results for legacy embeds that lack request metadata.
        seen_provider_ids: set[str] = set()
        seen_provider_ids.update(searched_provider_ids)
        for group in grouped_results:
            for result in group.get("results", []):
                sp = result.get("source_provider")
                if sp:
                    seen_provider_ids.add(sp)

        # Build providers list with display metadata from the registry
        providers_list: List[Dict[str, str]] = []
        for pid in sorted(seen_provider_ids):
            meta = PROVIDER_REGISTRY.get(pid)
            if meta:
                providers_list.append({"id": pid, **meta})
            else:
                # Unknown provider — use ID as fallback display name
                providers_list.append({"id": pid, "name": pid, "icon_url": ""})

        # Legacy provider string for older renderers. Keep it empty when no
        # provider metadata exists so empty states do not claim a fake source.
        provider_name = ", ".join(p["name"] for p in providers_list)

        # 7. Build and return response
        return self._build_response_with_errors(
            response_class=SearchConnectionsResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider=provider_name,
            providers=providers_list,
            suggestions=self.FOLLOW_UP_SUGGESTIONS,
            logger=logger,
        )

    async def _process_single_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        **kwargs: Any,
    ) -> tuple:
        """
        Process a single connection search request.

        Args:
            req: The request dict (named 'req' to match BaseSkill._process_requests_in_parallel)
            request_id: The request ID
            **kwargs: Additional keyword arguments (e.g., all_providers)

        Returns:
            Tuple of (request_id, results_list, error_string_or_none)
        """
        all_providers: List[BaseTransportProvider] = kwargs.get("all_providers", [])
        secrets_manager = kwargs.get("secrets_manager")
        cache_service = kwargs.get("cache_service")

        # Extract parameters with defaults
        legs = req.get("legs", [])
        transport_methods = req.get("transport_methods", ["airplane"])
        requested_providers = req.get("providers")
        countries = req.get("countries")
        passengers = req.get("passengers", 1)
        children = req.get("children", 0)
        infants_in_seat = req.get("infants_in_seat", 0)
        infants_on_lap = req.get("infants_on_lap", 0)
        travel_class = req.get("travel_class", "economy")
        max_results = self._clamp_max_results(req.get("max_results", DEFAULT_MAX_RESULTS))
        non_stop_only = req.get("non_stop_only", False)
        max_stops = req.get("max_stops")
        include_airlines = req.get("include_airlines")
        exclude_airlines = req.get("exclude_airlines")
        currency = req.get("currency", "EUR")
        sort_by = req.get("sort_by", "price_asc")
        result_filters = self._extract_result_filters(req)
        provider_max_results = self._provider_fetch_limit(max_results, result_filters)

        # Validate legs
        if not legs or not isinstance(legs, list):
            return (request_id, [], "No legs provided in request")

        for i, leg in enumerate(legs):
            if not leg.get("origin"):
                return (request_id, [], f"Leg {i}: missing 'origin'")
            if not leg.get("destination"):
                return (request_id, [], f"Leg {i}: missing 'destination'")
            if not leg.get("date"):
                return (request_id, [], f"Leg {i}: missing 'date'")

        # Validate transport methods
        valid_methods = {"airplane", "train", "bus", "boat"}
        transport_methods = [m for m in transport_methods if m in valid_methods]
        if not transport_methods:
            transport_methods = ["airplane"]

        # Find matching providers
        matched_providers = _get_providers_for_request(
            all_providers,
            transport_methods,
            requested_providers=requested_providers,
            countries=countries,
        )
        if not matched_providers:
            return (request_id, [], f"No providers available for transport methods: {transport_methods}")

        # Search across all matched providers and merge results
        all_connections = []
        errors = []

        for provider in matched_providers:
            try:
                connections = await provider.search_connections(
                    legs=legs,
                    passengers=passengers,
                    children=children,
                    infants_in_seat=infants_in_seat,
                    infants_on_lap=infants_on_lap,
                    travel_class=travel_class,
                    max_results=provider_max_results,
                    non_stop_only=non_stop_only,
                    max_stops=max_stops,
                    include_airlines=include_airlines,
                    exclude_airlines=exclude_airlines,
                    currency=currency,
                )
                all_connections.extend(connections)
            except Exception as e:
                provider_name = type(provider).__name__
                error_msg = f"{provider_name} search failed: {e}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)

        if not all_connections and errors:
            return (request_id, [], "; ".join(errors))

        # If we got results from at least one provider, don't propagate
        # errors from other providers (partial success is still success).
        # Only report errors when ALL providers failed (handled above).
        if all_connections and errors:
            for err in errors:
                logger.info(f"Ignoring provider error (other providers succeeded): {err}")
            errors = []

        # Convert ConnectionResult objects to dicts for the response
        results = []
        for connection in all_connections:
            # Determine trip type from legs
            num_legs = len(connection.legs)
            if num_legs == 1:
                trip_type = "one_way"
            elif num_legs == 2:
                trip_type = "round_trip"
            else:
                trip_type = "multi_city"

            # Build a flat result dict suitable for embed rendering
            result_dict: Dict[str, Any] = {
                "type": "connection",
                "transport_method": connection.transport_method,
                "source_provider": connection.source_provider,
                "trip_type": trip_type,
                "total_price": connection.total_price,
                "currency": connection.currency,
                "bookable_seats": connection.bookable_seats,
                "last_ticketing_date": connection.last_ticketing_date,
                "legs": [leg.model_dump() for leg in connection.legs],
                "hash": self._generate_connection_hash(connection),
            }

            # Add compact summary fields for easy LLM consumption
            if connection.legs:
                first_leg = connection.legs[0]
                last_leg = connection.legs[-1]
                result_dict["origin"] = first_leg.origin
                result_dict["destination"] = last_leg.destination if trip_type != "round_trip" else first_leg.destination
                result_dict["departure"] = first_leg.departure
                result_dict["arrival"] = first_leg.arrival
                result_dict["duration"] = first_leg.duration
                result_dict["stops"] = first_leg.stops

                # Carrier summary (unique carriers across all segments)
                carriers = set()
                carrier_codes = set()
                for leg in connection.legs:
                    for seg in leg.segments:
                        carriers.add(seg.carrier)
                        if seg.carrier_code:
                            carrier_codes.add(seg.carrier_code)
                result_dict["carriers"] = list(carriers)
                result_dict["carrier_codes"] = list(carrier_codes)

                # Booking token: SerpAPI token for on-demand booking URL lookup.
                # The frontend calls /v1/apps/travel/booking-link with this
                # token when the user clicks the booking button, avoiding
                # upfront SerpAPI credit spending on booking lookups.
                if connection.booking_token:
                    result_dict["booking_token"] = connection.booking_token

                # Booking context: original SerpAPI search parameters needed
                # for the booking_token lookup. Stored alongside each result
                # so the frontend can send them back to the booking-link endpoint.
                if connection.booking_context:
                    result_dict["booking_context"] = connection.booking_context

                # Booking URL: populated if booking was already resolved
                # (not used in the on-demand flow, kept for API compatibility)
                if connection.booking_url:
                    result_dict["booking_url"] = connection.booking_url
                    result_dict["booking_provider"] = connection.booking_provider

            # Rich metadata from Google Flights (CO2, airline logo)
            if connection.airline_logo:
                result_dict["airline_logo"] = connection.airline_logo
            if connection.co2_kg is not None:
                result_dict["co2_kg"] = connection.co2_kg
            if connection.co2_typical_kg is not None:
                result_dict["co2_typical_kg"] = connection.co2_typical_kg
            if connection.co2_difference_percent is not None:
                result_dict["co2_difference_percent"] = connection.co2_difference_percent

            results.append(result_dict)

        if result_filters:
            results = self._filter_results(results, result_filters)

        # Sort results according to the requested sort_by parameter
        self._sort_results(results, sort_by)
        results = results[:max_results]

        try:
            results = await sanitize_long_text_fields_in_payload(
                payload=results,
                task_id=f"travel_connections_{request_id}",
                secrets_manager=secrets_manager,
                cache_service=cache_service,
            )
        except Exception as sanitize_error:
            logger.error(
                "Connection search content sanitization failed for request %s: %s",
                request_id,
                sanitize_error,
                exc_info=True,
            )
            return (request_id, [], "Content sanitization failed")

        error_str = "; ".join(errors) if errors else None
        return (request_id, results, error_str)

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
            "max_layover_minutes",
            "avoid_overnight_layovers",
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
        max_layover_minutes: Any,
        avoid_overnight_layovers: bool,
    ) -> bool:
        try:
            max_minutes = int(max_layover_minutes) if max_layover_minutes not in (None, "") else None
        except (TypeError, ValueError):
            max_minutes = None

        for leg in result.get("legs", []) or []:
            for layover in leg.get("layovers", []) or []:
                if avoid_overnight_layovers and layover.get("overnight"):
                    return False
                duration = layover.get("duration_minutes")
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
            results.sort(key=lambda r: self._sort_key_price(r), reverse=reverse)
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
