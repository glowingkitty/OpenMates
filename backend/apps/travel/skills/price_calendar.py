"""
Price Calendar skill for the travel app.

Returns the cheapest cached flight prices for every day of a given month
on a route, using the Travelpayouts (Aviasales) free month-matrix API.

Ideal for a "when is it cheapest to fly?" heatmap overview. Prices are
cached (~48h old) search history data — NOT live fares. For real-time
pricing and booking links, the user should follow up with the
search_connections skill for a specific date.

This is a non-composite skill: it returns a single embed per request
containing the full month's data array (no child embeds).
"""

import calendar
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.travel.providers.serpapi_provider import _resolve_iata_code
from backend.apps.travel.providers.travelpayouts_provider import TravelpayoutsProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class PriceCalendarRequest(BaseModel):
    """Incoming request payload for the price_calendar skill."""

    requests: List[Dict[str, Any]] = Field(
        description="Array of price calendar request objects, each with "
        "'origin', 'destination', 'month', and optionally 'currency'."
    )


class PriceCalendarResponse(BaseModel):
    """
    Response payload for the price_calendar skill.

    Follows the standard OpenMates skill response structure with grouped
    results, provider info, suggestions, and optional error.
    """

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array",
    )
    provider: str = Field(default="Travelpayouts")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# PriceCalendarSkill
# ---------------------------------------------------------------------------

class PriceCalendarSkill(BaseSkill):
    """
    Skill that retrieves a monthly price calendar for a flight route.

    Accepts a 'requests' array where each request contains:
    - origin: City name or IATA code (e.g., 'Munich' or 'MUC')
    - destination: City name or IATA code (e.g., 'London' or 'LON')
    - month: Month in YYYY-MM format (e.g., '2026-03')
    - currency: Price currency code (default: 'EUR')

    Returns one result per request containing the full month's price data,
    summary statistics (cheapest/most expensive price, days with data),
    and follow-up suggestions.
    """

    FOLLOW_UP_SUGGESTIONS = [
        "Search flights for the cheapest date",
        "Show next month",
        "Show previous month",
    ]

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Any = None,
        **kwargs: Any,
    ) -> PriceCalendarResponse:
        """
        Execute the price calendar skill.

        1. Validates the requests array (requires 'origin' field)
        2. Processes each request via _process_single_request
        3. Groups results by request ID
        4. Returns PriceCalendarResponse
        """
        # 1. Validate requests array (require 'origin' field per request)
        validated_requests, validation_error = self._validate_requests_array(
            requests=requests,
            required_field="origin",
            field_display_name="origin",
            empty_error_message="No price calendar requests provided",
            logger=logger,
        )
        if validation_error:
            return PriceCalendarResponse(results=[], error=validation_error)
        if not validated_requests:
            return PriceCalendarResponse(results=[], error="No valid requests to process")

        # 2. Create provider
        provider = TravelpayoutsProvider()

        # 3. Process requests in parallel
        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            logger=logger,
            provider=provider,
        )

        # 4. Group results by request ID
        grouped_results, errors = self._group_results_by_request_id(
            results=all_results,
            requests=validated_requests,
            logger=logger,
        )

        # 5. Build and return response
        return self._build_response_with_errors(
            response_class=PriceCalendarResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Travelpayouts",
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
        Process a single price calendar request.

        Resolves city names to IATA codes, calls the Travelpayouts provider,
        and builds a result dict with the full month's data plus summary stats.

        Args:
            req: The request dict with 'origin', 'destination', 'month', 'currency'.
            request_id: The request ID.
            **kwargs: Must contain 'provider' (TravelpayoutsProvider instance).

        Returns:
            Tuple of (request_id, results_list, error_string_or_none).
        """
        provider: TravelpayoutsProvider = kwargs["provider"]

        # Extract parameters
        origin_raw = req.get("origin", "").strip()
        destination_raw = req.get("destination", "").strip()
        month = req.get("month", "").strip()
        currency = req.get("currency", "EUR").strip().upper()

        # Validate required fields
        if not origin_raw:
            return (request_id, [], "Missing 'origin' in request")
        if not destination_raw:
            return (request_id, [], "Missing 'destination' in request")
        if not month:
            return (request_id, [], "Missing 'month' in request")

        # Resolve city names to IATA codes
        origin_iata = _resolve_iata_code(origin_raw)
        if not origin_iata:
            return (request_id, [], f"Could not resolve origin '{origin_raw}' to IATA code")

        destination_iata = _resolve_iata_code(destination_raw)
        if not destination_iata:
            return (request_id, [], f"Could not resolve destination '{destination_raw}' to IATA code")

        # Fetch price calendar from Travelpayouts
        try:
            entries = await provider.get_price_calendar(
                origin=origin_iata,
                destination=destination_iata,
                month=month,
                currency=currency.lower(),
            )
        except ValueError as e:
            # API token not available
            return (request_id, [], str(e))
        except Exception as e:
            logger.error(f"Price calendar request failed: {e}", exc_info=True)
            return (request_id, [], f"Failed to fetch price calendar: {e}")

        # Calculate total days in the month for completeness stats
        try:
            year, month_num = month.split("-")[:2]
            total_days = calendar.monthrange(int(year), int(month_num))[1]
        except (ValueError, IndexError):
            total_days = 31

        # Build result dict with full month data
        if entries:
            prices = [e.price for e in entries]
            cheapest_price = min(prices)
            most_expensive_price = max(prices)
        else:
            cheapest_price = None
            most_expensive_price = None

        result_dict: Dict[str, Any] = {
            "type": "price_calendar",
            "origin": origin_iata,
            "origin_name": origin_raw,
            "destination": destination_iata,
            "destination_name": destination_raw,
            "month": month,
            "currency": currency,
            "cheapest_price": cheapest_price,
            "most_expensive_price": most_expensive_price,
            "days_with_data": len(entries),
            "total_days_in_month": total_days,
            "entries": [e.model_dump() for e in entries],
        }

        return (request_id, [result_dict], None)
