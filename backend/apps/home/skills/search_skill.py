"""
Search skill for the Home app — German apartment and housing search.

Searches ImmoScout24, Kleinanzeigen, and WG-Gesucht in parallel for
apartment, house, and WG room listings. Results are merged, sorted by
price (ascending, nulls last), and returned as a SearchResponse.

The skill follows the standard BaseSkill request/response pattern with
the 'requests' array convention used by all OpenMates skills.

Data flow:
  1. LLM calls skill with requests=[{query: "Berlin", listing_type: "rent"}]
  2. Skill validates input with _validate_requests_array (requires 'query')
  3. Each request is processed in parallel via _process_requests_in_parallel
  4. For each request: calls selected providers in parallel with asyncio.gather
  5. Results merged, sorted by price, truncated to max_results
  6. Results grouped by request ID and returned as SearchResponse
  7. Frontend renders listings in HomeSearchEmbedPreview / Fullscreen

See: backend/apps/home/providers/ for individual provider implementations.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.home.providers.immoscout24 import search_listings as is24_search
from backend.apps.home.providers.kleinanzeigen import search_listings as ka_search
from backend.apps.home.providers.wg_gesucht import search_listings as wg_search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# All available providers and their search functions
PROVIDER_MAP: Dict[str, Any] = {
    "ImmoScout24": is24_search,
    "Kleinanzeigen": ka_search,
    "WG-Gesucht": wg_search,
}

ALL_PROVIDER_NAMES: List[str] = list(PROVIDER_MAP.keys())

# Maximum results per request (hard limit to avoid excessive API calls)
MAX_RESULTS_HARD_LIMIT = 20

# Follow-up suggestions shown to users after search results
FOLLOW_UP_SUGGESTIONS: List[str] = [
    "Show only apartments under 1000 EUR",
    "Search in a different city",
    "Show larger apartments (3+ rooms)",
    "Compare prices across providers",
]

# Fields excluded from LLM context (kept in UI results for rendering)
IGNORE_FIELDS_FOR_LLM: List[str] = ["type", "image_url", "id"]


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class SearchRequestItem(BaseModel):
    """A single housing search request."""

    query: str = Field(
        description="City or location to search in (e.g. 'Berlin', 'Munich', 'Hamburg')."
    )
    listing_type: str = Field(
        default="rent",
        description="Type of listing: 'rent' for rentals, 'buy' for purchases.",
    )
    providers: Optional[List[str]] = Field(
        default=None,
        description="Providers to search. Defaults to all three: ImmoScout24, Kleinanzeigen, WG-Gesucht.",
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of listings to return (1-20, default 10).",
    )


class SearchResponse(BaseModel):
    """
    Response payload for the home search skill.

    Follows the standard OpenMates skill response structure with grouped
    results, provider info, follow-up suggestions, and optional error.
    """

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array.",
    )
    provider: str = Field(default="Multi")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_llm: Optional[List[str]] = Field(
        default_factory=lambda: IGNORE_FIELDS_FOR_LLM.copy()
    )


# ---------------------------------------------------------------------------
# SearchSkill
# ---------------------------------------------------------------------------


class SearchSkill(BaseSkill):
    """
    Skill that searches German housing platforms for apartment and room listings.

    Accepts a 'requests' array where each request contains:
    - query: City/location name (required), e.g. "Berlin", "Munich"
    - listing_type: "rent" | "buy" (default: "rent")
    - providers: Optional list of provider names to search
      (default: all three — ImmoScout24, Kleinanzeigen, WG-Gesucht)
    - max_results: Maximum listings per search (1–20, default 10)

    Returns merged results sorted by price (ascending, nulls last).
    Each listing includes: title, price, size, rooms, address, image, URL, provider.
    """

    FOLLOW_UP_SUGGESTIONS = FOLLOW_UP_SUGGESTIONS

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> SearchResponse:
        """
        Execute the home search skill.

        1. Validate the requests array (requires 'query' field)
        2. Process each request via _process_single_request in parallel
        3. Group results by request ID
        4. Return SearchResponse

        Args:
            requests: Array of search request dicts, each requiring 'query'.
            **kwargs: Additional kwargs (passed through to BaseSkill helpers).

        Returns:
            SearchResponse with grouped, sorted listing results.
        """
        # 1. Validate requests array — each must have a 'query' field
        validated_requests, validation_error = self._validate_requests_array(
            requests=requests,
            required_field="query",
            field_display_name="query",
            empty_error_message="No search requests provided",
            logger=logger,
        )
        if validation_error:
            return SearchResponse(results=[], error=validation_error)
        if not validated_requests:
            return SearchResponse(results=[], error="No valid requests to process")

        # 2. Process requests in parallel
        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            logger=logger,
        )

        # 3. Group results by request ID
        grouped_results, errors = self._group_results_by_request_id(
            results=all_results,
            requests=validated_requests,
            logger=logger,
        )

        # 4. Build and return response
        return self._build_response_with_errors(
            response_class=SearchResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Multi",
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
        Process a single housing search request across multiple providers.

        Args:
            req: Request dict with 'query' (city), optional 'listing_type',
                 'providers', 'max_results'.
            request_id: Unique ID for this request (for result grouping).
            **kwargs: Additional kwargs (unused).

        Returns:
            Tuple of (request_id, results_list, error_string_or_none).
        """
        query: str = req.get("query", "").strip()
        listing_type: str = req.get("listing_type", "rent").strip().lower()
        providers_requested: Optional[List[str]] = req.get("providers")
        max_results: int = int(req.get("max_results", 10))

        if not query:
            return (request_id, [], "Missing 'query' in request")

        # Clamp max_results
        max_results = max(1, min(MAX_RESULTS_HARD_LIMIT, max_results))

        # Validate listing_type
        if listing_type not in ("rent", "buy"):
            listing_type = "rent"

        # Determine which providers to search
        if providers_requested:
            selected_providers = {
                name: func
                for name, func in PROVIDER_MAP.items()
                if name in providers_requested
            }
            if not selected_providers:
                selected_providers = PROVIDER_MAP
        else:
            selected_providers = PROVIDER_MAP

        logger.info(
            "Home search query=%r type=%s providers=%s max=%d",
            query, listing_type, list(selected_providers.keys()), max_results,
        )

        # Call all selected providers in parallel
        try:
            provider_tasks = [
                func(city=query, listing_type=listing_type, max_results=max_results)
                for func in selected_providers.values()
            ]
            provider_results = await asyncio.gather(*provider_tasks, return_exceptions=True)
        except Exception as e:
            logger.error("Home search gather failed query=%r: %s", query, e, exc_info=True)
            return (request_id, [], f"Search failed: {e}")

        # Merge results from all providers
        merged: List[Dict[str, Any]] = []
        provider_errors: List[str] = []

        for provider_name, result in zip(selected_providers.keys(), provider_results):
            if isinstance(result, Exception):
                error_msg = f"{provider_name} failed: {result}"
                logger.error("Home search provider error: %s", error_msg)
                provider_errors.append(error_msg)
            elif isinstance(result, list):
                merged.extend(result)
                logger.info("Home search %s returned %d listings", provider_name, len(result))
            else:
                logger.warning("Home search %s returned unexpected type: %s", provider_name, type(result))

        # Sort by price ascending (nulls last)
        merged.sort(key=lambda x: (x.get("price") is None, x.get("price") or 0))

        # Truncate to max_results
        merged = merged[:max_results]

        # Build error string if some providers failed (but we still have results)
        error = "; ".join(provider_errors) if provider_errors and not merged else None

        logger.info(
            "Home search query=%r -> %d merged listings (%d provider errors)",
            query, len(merged), len(provider_errors),
        )

        return (request_id, merged, error)
