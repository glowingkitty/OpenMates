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
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.home.providers.immoscout24 import search_listings as is24_search
from backend.apps.home.providers.kleinanzeigen import search_listings as ka_search
from backend.apps.home.providers.wg_gesucht import search_listings as wg_search
from backend.shared.python_utils.geo_utils import geocode_address

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
IGNORE_FIELDS_FOR_LLM: List[str] = ["type", "image_url", "id", "latitude", "longitude"]


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class SearchRequestItem(BaseModel):
    """A single housing search request."""

    query: str = Field(
        description="City or location to search in (e.g. 'Berlin', 'Munich', 'Hamburg')."
    )
    listing_type: Literal["rent", "buy"] = Field(
        default="rent",
        description="Type of listing: 'rent' for rentals, 'buy' for purchases.",
    )
    property_type: Literal["apartment", "shared_room"] = Field(default="apartment", description="Entire apartment or shared room.")
    sort: Literal["price_asc", "newest"] = Field(default="price_asc", description="Price order or provider discovery order for monitoring new listings.")
    max_price_eur: Optional[float] = Field(default=None, ge=0, description="Maximum advertised monthly rent or purchase price in EUR; provider price basis is retained.")
    min_rooms: Optional[float] = Field(default=None, ge=0, description="Minimum advertised room count; unknown values are excluded when set.")
    min_size_sqm: Optional[float] = Field(default=None, ge=0, description="Minimum advertised area; unknown values are excluded when set.")
    providers: Optional[List[str]] = Field(
        default=None,
        description="Providers to search. Defaults to all three: ImmoScout24, Kleinanzeigen, WG-Gesucht.",
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of listings to return (1-20, default 10).",
    )


class SearchRequest(BaseModel):
    """Typed public request matching the app skill schema."""
    requests: List[SearchRequestItem] = Field(description="Housing searches to execute.")


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
    providers: List[str] = Field(
        default_factory=list,
        description="Names of providers that successfully returned results.",
    )
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list, description="Provider failures or coverage limitations in a partial search.")
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

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve selected housing providers before network search starts."""
        requested = request.get("providers")
        if isinstance(requested, list) and requested:
            providers = [str(provider) for provider in requested if str(provider) in PROVIDER_MAP]
        else:
            providers = ALL_PROVIDER_NAMES.copy()
        if not providers:
            providers = ALL_PROVIDER_NAMES.copy()
        return {"provider": "Multi", "providers": providers}

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
        requests = [item.model_dump(exclude_none=True) if isinstance(item, BaseModel) else item for item in requests]
        validated_requests, invalid_grouped_results, validation_errors, validation_error = self._partition_requests_by_required_fields(
            requests=requests,
            required_fields=["query"],
            field_display_names={"query": "query"},
            empty_error_message="No search requests provided",
            logger=logger,
        )
        if validation_error:
            return SearchResponse(results=[], error=validation_error)
        if not validated_requests:
            return self._build_response_with_errors(
                response_class=SearchResponse,
                grouped_results=invalid_grouped_results,
                errors=validation_errors,
                provider="Multi",
                suggestions=self.FOLLOW_UP_SUGGESTIONS,
                logger=logger,
                providers=[],
            )

        # 2. Process requests in parallel
        all_results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_request,
            logger=logger,
        )

        warnings: List[str] = []
        normalized_results = []
        for result in all_results:
            if isinstance(result, tuple) and len(result) == 4:
                warnings.extend(result[3])
                result = result[:3]
            normalized_results.append(result)
        all_results = normalized_results

        # 3. Group results by request ID
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

        # 4. Collect unique provider names from results that actually returned listings
        successful_providers: List[str] = []
        seen_providers: set = set()
        for group in grouped_results:
            for listing in group.get("results", []):
                prov = listing.get("provider")
                if prov and prov not in seen_providers:
                    seen_providers.add(prov)
                    successful_providers.append(prov)

        # 5. Build and return response
        return self._build_response_with_errors(
            response_class=SearchResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="Multi",
            suggestions=self.FOLLOW_UP_SUGGESTIONS,
            logger=logger,
            providers=successful_providers,
            warnings=sorted(set(warnings)),
        )

    async def _geocode_listings(
        self,
        listings: List[Dict[str, Any]],
        city: str,
    ) -> None:
        """
        Attach latitude/longitude to each listing by geocoding its address.

        Uses geocode_address() from geo_utils which tries Nominatim first for
        address-level precision, then falls back to the local city table. Listings
        without a resolvable address are left without coordinates — the frontend
        will simply hide the map for those.

        Geocoding is done sequentially; _nominatim_query auto-throttles to
        respect Nominatim's 1 req/s rate limit.

        Args:
            listings: Mutable list of listing dicts — latitude/longitude keys
                      are added in-place.
            city: The search city name (used as fallback for geocoding).
        """
        for listing in listings:
            address = listing.get("address", "")
            coords = await geocode_address(address=address, city=city)
            if coords:
                listing["latitude"] = coords[0]
                listing["longitude"] = coords[1]

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
        try:
            validated = SearchRequestItem.model_validate(req)
        except Exception as exc:
            return (request_id, [], f"Invalid housing search input: {exc}")
        req = validated.model_dump(exclude_none=True)
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

        property_type = req.get("property_type", "apartment")
        sort = req.get("sort", "price_asc")

        # Determine which providers to search
        if providers_requested:
            selected_providers = {
                name: func
                for name, func in PROVIDER_MAP.items()
                if name in providers_requested
            }
            if len(selected_providers) != len(set(providers_requested)):
                return (request_id, [], "Unknown housing search provider")
        else:
            selected_providers = PROVIDER_MAP

        if property_type == "shared_room":
            selected_providers = {name: func for name, func in selected_providers.items() if name == "WG-Gesucht"}
            if not selected_providers:
                return (request_id, [], "Shared-room searches require WG-Gesucht")

        logger.info(
            "Home search query=%r type=%s providers=%s max=%d",
            query, listing_type, list(selected_providers.keys()), max_results,
        )

        discovery_limit = MAX_RESULTS_HARD_LIMIT if sort == "newest" or any(
            req.get(key) is not None for key in ("max_price_eur", "min_rooms", "min_size_sqm")
        ) else max_results

        # Call all selected providers in parallel
        try:
            provider_tasks = [
                func(city=query, listing_type=listing_type, max_results=discovery_limit,
                     property_type=property_type, sort=sort)
                for func in selected_providers.values()
            ]
            provider_results = await asyncio.gather(*provider_tasks, return_exceptions=True)
        except Exception as e:
            logger.error("Home search gather failed query=%r: %s", query, e, exc_info=True)
            return (request_id, [], f"Search failed: {e}")

        # Merge results from all providers
        merged: List[Dict[str, Any]] = []
        provider_errors: List[str] = []
        warnings: List[str] = []

        for provider_name, result in zip(selected_providers.keys(), provider_results):
            if isinstance(result, Exception):
                error_msg = f"{provider_name} failed: {result}"
                logger.error("Home search provider error: %s", error_msg)
                provider_errors.append(error_msg)
            elif isinstance(result, list):
                warnings.extend(getattr(result, "warnings", []))
                for rank, listing in enumerate(result):
                    listing["discovery_rank"] = rank
                    listing["property_type"] = property_type
                    merged.append(listing)
                logger.info("Home search %s returned %d listings", provider_name, len(result))
            else:
                logger.warning("Home search %s returned unexpected type: %s", provider_name, type(result))
                provider_errors.append(f"{provider_name} returned an invalid response")

        # Criteria belong to the skill, before its bounded result limit.
        for input_name, field, maximum in (("max_price_eur", "price", True), ("min_rooms", "rooms", False), ("min_size_sqm", "size_sqm", False)):
            threshold = req.get(input_name)
            if threshold is not None:
                merged = [item for item in merged if isinstance(item.get(field), (int, float))
                          and (item[field] <= threshold if maximum else item[field] >= threshold)]
        if sort == "newest":
            # Interleave providers fairly without inventing cross-provider posting dates.
            merged.sort(key=lambda item: item["discovery_rank"])
            if any(name != "Kleinanzeigen" for name in selected_providers):
                warnings.append("ImmoScout24 and WG-Gesucht retain provider order; newest ordering is not guaranteed.")
        else:
            merged.sort(key=lambda x: (x.get("price") is None, x.get("price") or 0))

        # Truncate to max_results
        merged = merged[:max_results]

        # Geocode listing addresses for map display.
        # Each listing has a text address (e.g. "Berlin Kreuzberg") but no GPS
        # coordinates. We resolve lat/lon so the frontend can show a map via
        # EntryWithMapTemplate — same pattern as events and health appointments.
        await self._geocode_listings(merged, city=query)

        # Build error string if some providers failed (but we still have results)
        error = "; ".join(provider_errors) if len(provider_errors) == len(selected_providers) else None
        if not error:
            warnings.extend(provider_errors)

        if property_type == "shared_room":
            selected_providers = {name: func for name, func in selected_providers.items() if name == "WG-Gesucht"}
            if not selected_providers:
                return (request_id, [], "Shared-room searches require WG-Gesucht")

        logger.info(
            "Home search query=%r -> %d merged listings (%d provider errors)",
            query, len(merged), len(provider_errors),
        )

        return (request_id, merged, error, warnings)
