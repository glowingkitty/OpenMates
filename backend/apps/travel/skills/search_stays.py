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
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.travel.providers.serpapi_hotels_provider import (
    search_hotels,
    StayResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class SearchStaysRequest(BaseModel):
    """Incoming request payload for the search_stays skill."""

    requests: List[Dict[str, Any]] = Field(
        description="Array of stay search request objects, each with 'query', "
        "'check_in_date', 'check_out_date', 'adults', etc."
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

        # 2. Validate requests array (require 'query' field per request)
        validated_requests, validation_error = self._validate_requests_array(
            requests=requests,
            required_field="query",
            field_display_name="query",
            empty_error_message="No stay search requests provided",
            logger=logger,
        )
        if validation_error:
            return SearchStaysResponse(results=[], error=validation_error)
        if not validated_requests:
            return SearchStaysResponse(results=[], error="No valid requests to process")

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
            requests=validated_requests,
            logger=logger,
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
