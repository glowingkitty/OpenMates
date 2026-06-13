"""
Search Stays skill for the travel app.

Searches for hotels, hostels, and other accommodations at a destination
using the SerpAPI Google Hotels engine. Returns results with pricing,
ratings, amenities, images, and GPS coordinates.

The skill follows the standard BaseSkill request/response pattern with the
'requests' array convention used by all OpenMates skills.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.app_skill_helpers import sanitize_long_text_fields_in_payload
from backend.apps.travel.providers.serpapi_hotels_provider import (
    search_hotels,
    StayResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class SearchStaysRequestItem(BaseModel):
    """A single accommodation search request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    query: str = Field(
        description="Search query describing the destination or property "
        "(e.g. 'Hotels in Paris', 'Hostels near Eiffel Tower', 'Barcelona beachfront hotel')."
    )
    check_in_date: str = Field(description="Check-in date in YYYY-MM-DD format (e.g. '2026-03-15').")
    check_out_date: str = Field(description="Check-out date in YYYY-MM-DD format (e.g. '2026-03-18').")
    adults: int = Field(default=2, description="Number of adult guests.")
    children: int = Field(default=0, description="Number of children.")
    currency: str = Field(default="EUR", description="Price currency (ISO 4217 code, e.g. 'EUR', 'USD').")
    sort_by: str = Field(
        default="relevance",
        description="Sort order for results. Options: 'relevance' (default), 'price_asc', 'rating_desc', 'reviews_desc'.",
    )
    min_price: Optional[float] = Field(default=None, description="Minimum nightly price filter.")
    max_price: Optional[float] = Field(default=None, description="Maximum nightly price filter.")
    hotel_class: Optional[str] = Field(
        default=None,
        description="Comma-separated star rating filter (e.g. '3,4,5' for 3-star and above).",
    )
    max_results: int = Field(default=10, description="Maximum number of results to return.")


class SearchStaysRequest(BaseModel):
    """Incoming request payload for the search_stays skill."""

    requests: List[SearchStaysRequestItem] = Field(
        description="Array of stay search requests. Each request searches for "
        "accommodation at a specific destination for given dates."
    )


class SearchStaysResponse(BaseModel):
    """
    Response payload for the search_stays skill.

    Follows the standard OpenMates skill response structure with grouped results,
    provider info, suggestions, and optional error.
    """

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array",
    )
    provider: str = Field(default="Google")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: ["property_token", "images", "nearby_places"]
    )


# ---------------------------------------------------------------------------
# SearchStaysSkill
# ---------------------------------------------------------------------------

class SearchStaysSkill(BaseSkill):
    """
    Skill that searches for hotels, hostels, and accommodations.

    Accepts a 'requests' array where each request contains:
    - query: search query (e.g., "Hotels in Paris", "Hostels near Eiffel Tower")
    - check_in_date: check-in date (YYYY-MM-DD)
    - check_out_date: check-out date (YYYY-MM-DD)
    - adults: number of adults (default: 2)
    - children: number of children (default: 0)
    - currency: preferred currency (default: "EUR")
    - sort_by: sort order (default: "relevance")
    - min_price: minimum nightly price filter
    - max_price: maximum nightly price filter
    - hotel_class: star rating filter (e.g., "3,4,5")
    - max_results: maximum number of results (default: 10)

    Returns accommodation results grouped by request ID, where each result
    represents a bookable property with pricing, ratings, and amenities.
    """

    # Suggestions displayed after successful execution
    FOLLOW_UP_SUGGESTIONS = [
        "Show cheaper options",
        "Filter by 4+ star rating",
        "Show only hotels with free cancellation",
    ]

    @staticmethod
    def _has_pool_intent(query: str) -> bool:
        return "pool" in query.lower()

    @staticmethod
    def _has_beach_intent(query: str) -> bool:
        lowered = query.lower()
        return "beach" in lowered or "beachfront" in lowered or "near beach" in lowered

    @staticmethod
    def _apply_quality_filters(
        results: List[Dict[str, Any]],
        *,
        max_price: Optional[float],
        query: str,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Apply deterministic stay filters and annotate constraint confidence."""
        filtered: List[Dict[str, Any]] = []
        filtered_out_count = 0
        pool_intent = SearchStaysSkill._has_pool_intent(query)
        beach_intent = SearchStaysSkill._has_beach_intent(query)

        for result in results:
            copy = dict(result)
            nightly_price = copy.get("extracted_rate_per_night")
            if max_price is not None:
                if not isinstance(nightly_price, (int, float)) or float(nightly_price) > float(max_price):
                    filtered_out_count += 1
                    continue

            amenities = " ".join(str(item) for item in copy.get("amenities", [])).lower()
            description = str(copy.get("description") or "").lower()
            constraint_matches = dict(copy.get("constraint_matches") or {})
            if max_price is not None:
                constraint_matches["budget"] = "matched"
            if pool_intent:
                constraint_matches["pool"] = "mentioned" if "pool" in amenities else "unknown"
            if beach_intent:
                constraint_matches["beach_proximity"] = (
                    "mentioned" if "beach" in amenities or "beach" in description else "unknown"
                )
            if constraint_matches:
                copy["constraint_matches"] = constraint_matches
            filtered.append(copy)

        metadata: Dict[str, Any] = {
            "filtered_out_count": filtered_out_count,
            "applied_filters": ["max_price"] if max_price is not None else [],
            "no_result_reason": "filtered_out" if results and not filtered else None,
            "pool_intent": pool_intent,
            "beach_intent": beach_intent,
        }
        if metadata["no_result_reason"]:
            metadata["suggestions"] = [
                "Increase the nightly budget",
                "Search farther from the beach",
                "Include hostels or private rooms",
                "Try nearby dates",
            ]
        return filtered, metadata

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Any = None,
        **kwargs: Any,
    ) -> SearchStaysResponse:
        """
        Execute the search stays skill.

        1. Obtains SecretsManager for API credential access
        2. Validates the requests array (requires 'query' field)
        3. Processes each request via _process_single_request
        4. Groups results by request ID
        5. Returns SearchStaysResponse
        """
        # 1. Get or create SecretsManager
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="SearchStaysSkill",
            error_response_factory=lambda msg: SearchStaysResponse(results=[], error=msg),
            logger=logger,
        )
        if error_response:
            return error_response

        validated_requests, invalid_grouped_results, validation_errors, validation_error = self._partition_requests_by_required_fields(
            requests=requests,
            required_fields=["query"],
            field_display_names={"query": "query"},
            empty_error_message="No stay search requests provided",
            logger=logger,
        )
        if validation_error:
            return SearchStaysResponse(results=[], error=validation_error)
        if not validated_requests:
            return self._build_response_with_errors(
                response_class=SearchStaysResponse,
                grouped_results=invalid_grouped_results,
                errors=validation_errors,
                provider="Google",
                suggestions=self.FOLLOW_UP_SUGGESTIONS,
                logger=logger,
            )

        # 3. Process requests in parallel
        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            skill_name="SearchStaysSkill",
            logger=logger,
            secrets_manager=secrets_manager,
        )

        # 4. Group results by request ID
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

        # 5. Build and return response
        return self._build_response_with_errors(
            response_class=SearchStaysResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Google",
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
        Process a single stay search request.

        Args:
            req: The request dict with query, check_in_date, check_out_date, etc.
            request_id: The request ID
            **kwargs: Additional keyword arguments (e.g., secrets_manager)

        Returns:
            Tuple of (request_id, results_list, error_string_or_none)
        """
        secrets_manager = kwargs.get("secrets_manager")

        # Extract parameters with defaults
        query = req.get("query", "")
        check_in_date = req.get("check_in_date", "")
        check_out_date = req.get("check_out_date", "")
        adults = req.get("adults", 2)
        children = req.get("children", 0)
        currency = req.get("currency", "EUR")
        sort_by = req.get("sort_by", "relevance")
        min_price = req.get("min_price")
        max_price = req.get("max_price")
        hotel_class = req.get("hotel_class")
        rating = req.get("rating")
        free_cancellation = req.get("free_cancellation", False)
        max_results = req.get("max_results", 10)

        # Validate required fields
        if not query:
            return (request_id, [], "Missing 'query' field in request")
        if not check_in_date:
            return (request_id, [], "Missing 'check_in_date' field in request")
        if not check_out_date:
            return (request_id, [], "Missing 'check_out_date' field in request")

        try:
            stays = await search_hotels(
                query=query,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                adults=adults,
                children=children,
                currency=currency,
                sort_by=sort_by,
                min_price=min_price,
                max_price=max_price,
                hotel_class=hotel_class,
                rating=rating,
                free_cancellation=free_cancellation,
                max_results=max_results,
                secrets_manager=secrets_manager,
            )
        except Exception as e:
            error_msg = f"Hotel search failed: {e}"
            logger.error(error_msg, exc_info=True)
            return (request_id, [], error_msg)

        if not stays:
            return (request_id, [], None)

        # Convert StayResult objects to dicts for the response
        results = []
        for stay in stays:
            result_dict = stay.to_dict()
            # Add a hash for deduplication
            result_dict["hash"] = self._generate_stay_hash(stay)
            results.append(result_dict)

        results, quality_metadata = self._apply_quality_filters(
            results,
            max_price=max_price,
            query=query,
        )
        if quality_metadata.get("filtered_out_count"):
            logger.info(
                "Stay quality filters removed %d result(s) for request %s",
                quality_metadata["filtered_out_count"],
                request_id,
            )

        try:
            results = await sanitize_long_text_fields_in_payload(
                payload=results,
                task_id=f"travel_stays_{request_id}",
                secrets_manager=secrets_manager,
                cache_service=kwargs.get("cache_service"),
            )
        except Exception as sanitize_error:
            logger.error(
                "Stay search content sanitization failed for request %s: %s",
                request_id,
                sanitize_error,
                exc_info=True,
            )
            return (request_id, [], "Content sanitization failed")

        return (request_id, results, None)

    @staticmethod
    def _generate_stay_hash(stay: StayResult) -> str:
        """Generate a unique hash for a stay based on its key attributes."""
        hash_input = json.dumps({
            "name": stay.name,
            "rate": stay.extracted_rate_per_night,
            "lat": stay.gps_coordinates.get("latitude") if stay.gps_coordinates else None,
            "lng": stay.gps_coordinates.get("longitude") if stay.gps_coordinates else None,
        }, sort_keys=True)
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
