"""
Search Connections skill for the travel app.

Searches for transport connections (flights, and in the future trains/buses/boats)
between locations. Uses a provider abstraction layer where each transport method
is handled by a dedicated provider (AmadeusProvider for flights, TransitousProvider
for trains/buses).

The skill follows the standard BaseSkill request/response pattern with the
'requests' array convention used by all OpenMates skills.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.travel.providers.amadeus_provider import AmadeusProvider
from backend.apps.travel.providers.base_provider import BaseTransportProvider
from backend.apps.travel.providers.transitous_provider import TransitousProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class SearchConnectionsRequest(BaseModel):
    """Incoming request payload for the search_connections skill."""

    requests: List[Dict[str, Any]] = Field(
        description="Array of connection search request objects, each with 'legs', "
        "'transport_methods', 'passengers', 'travel_class', etc."
    )


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
    provider: str = Field(default="Amadeus")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: ["type", "hash", "carrier_code", "segments"]
    )


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

def _create_providers() -> List[BaseTransportProvider]:
    """
    Instantiate all available transport providers.

    Currently: AmadeusProvider (flights) + TransitousProvider (stub).
    """
    return [
        AmadeusProvider(use_production=False),
        TransitousProvider(),
    ]


def _get_providers_for_methods(
    all_providers: List[BaseTransportProvider],
    transport_methods: List[str],
) -> List[BaseTransportProvider]:
    """Return providers that support at least one of the requested transport methods."""
    matched: List[BaseTransportProvider] = []
    for provider in all_providers:
        for method in transport_methods:
            if provider.supports_transport_method(method):
                matched.append(provider)
                break
    return matched


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
    - max_results: max connection options per transport method (default: 5)
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

        # 2. Validate requests array (require 'legs' field per request)
        validated_requests, validation_error = self._validate_requests_array(
            requests=requests,
            required_field="legs",
            skill_name="SearchConnectionsSkill",
            logger=logger,
        )
        if validation_error:
            return SearchConnectionsResponse(results=[], error=validation_error)
        if not validated_requests:
            return SearchConnectionsResponse(results=[], error="No valid requests to process")

        # 3. Create providers and inject secrets_manager
        all_providers = _create_providers()
        for provider in all_providers:
            if isinstance(provider, AmadeusProvider):
                provider._secrets_manager = secrets_manager

        # 4. Process requests in parallel
        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            skill_name="SearchConnectionsSkill",
            logger=logger,
            all_providers=all_providers,
        )

        # 5. Group results by request ID
        grouped_results, errors = self._group_results_by_request_id(
            results=all_results,
            requests=validated_requests,
            skill_name="SearchConnectionsSkill",
            logger=logger,
        )

        # 6. Build and return response
        return self._build_response_with_errors(
            response_class=SearchConnectionsResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Amadeus",
            suggestions=self.FOLLOW_UP_SUGGESTIONS,
            logger=logger,
        )

    async def _process_single_request(
        self,
        request: Dict[str, Any],
        request_id: Any,
        **kwargs: Any,
    ) -> tuple:
        """
        Process a single connection search request.

        Returns:
            Tuple of (request_id, results_list, error_string_or_none)
        """
        all_providers: List[BaseTransportProvider] = kwargs.get("all_providers", [])

        # Extract parameters with defaults
        legs = request.get("legs", [])
        transport_methods = request.get("transport_methods", ["airplane"])
        passengers = request.get("passengers", 1)
        travel_class = request.get("travel_class", "economy")
        max_results = request.get("max_results", 5)
        non_stop_only = request.get("non_stop_only", False)
        currency = request.get("currency", "EUR")

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
        matched_providers = _get_providers_for_methods(all_providers, transport_methods)
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
                    travel_class=travel_class,
                    max_results=max_results,
                    non_stop_only=non_stop_only,
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
                for leg in connection.legs:
                    for seg in leg.segments:
                        carriers.add(seg.carrier)
                result_dict["carriers"] = list(carriers)

            results.append(result_dict)

        error_str = "; ".join(errors) if errors else None
        return (request_id, results, error_str)

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
