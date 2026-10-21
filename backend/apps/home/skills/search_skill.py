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
import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.apps.base_skill import BaseSkill
from backend.apps.home.providers.immoscout24 import search_listings as is24_search
from backend.apps.home.providers.kleinanzeigen import search_listings as ka_search
from backend.apps.home.providers.wg_gesucht import search_listings as wg_search
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.geo_utils import lookup_city
from backend.apps.home.evidence import assess_home_evidence, resolve_home_preferences
from backend.apps.home.location_enrichment import enrich_home_locations, requested_categories, set_city_fallback
from backend.shared.python_utils.search_relevance import (
    MAX_RELEVANCE_CRITERIA_CHARS,
    normalize_relevance_criteria,
    normalize_url_for_deduplication,
    rank_search_candidates,
    relevance_candidate_target,
    stable_deduplicate_candidates,
)

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
IGNORE_FIELDS_FOR_LLM: List[str] = ["type", "image_url", "image_urls", "id"]

Amenity = Literal["balcony", "terrace", "garden", "elevator", "furnished", "parking", "pets_allowed"]
NeighborhoodCategory = Literal["water", "park", "transit", "groceries", "school"]


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class SearchRequestItem(BaseModel):
    """A single housing search request."""
    model_config = ConfigDict(allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def omitted_defaults(cls, value):
        # Dynamic REST models project omitted optional fields as null. Normalize
        # only fields that already have a concrete default in this contract.
        if isinstance(value, dict):
            value = dict(value)
            for name in ("required_amenities", "excluded_amenities", "preferred_amenities", "neighborhood_categories",
                         "visual_analysis", "include_unconfirmed", "neighborhood_radius_m", "max_results",
                         "listing_type", "property_type", "sort"):
                if value.get(name) is None:
                    value.pop(name, None)
        return value

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
    min_price_eur: Optional[float] = Field(default=None, ge=0)
    max_rooms: Optional[float] = Field(default=None, ge=0)
    max_size_sqm: Optional[float] = Field(default=None, ge=0)
    max_warm_rent_eur: Optional[float] = Field(default=None, ge=0, description="Maximum explicitly advertised total monthly rent including known service costs; unknown total rent does not satisfy this requirement.")
    max_cold_rent_eur: Optional[float] = Field(default=None, ge=0)
    available_by: Optional[date] = Field(default=None, description="Listing must be available on or before this ISO date; missing availability remains unconfirmed.")
    required_amenities: List[Amenity] = Field(default_factory=list, max_length=7, description="Hard requirements. A missing amenity never counts as confirmed.")
    excluded_amenities: List[Amenity] = Field(default_factory=list, max_length=7)
    preferred_amenities: List[Amenity] = Field(default_factory=list, max_length=7, description="Soft preferences used for ranking, not exclusions.")
    include_unconfirmed: bool = Field(default=False, description="Also return clearly labelled listings with missing evidence for requirements; explicit conflicts stay excluded.")
    visual_analysis: bool = Field(default=True, description="Assess supplied photos only when requested amenities have a visually assessable component. Does not limit gallery photos.")
    neighborhood_categories: List[NeighborhoodCategory] = Field(default_factory=list, max_length=5)
    neighborhood_radius_m: int = Field(default=1500, ge=100, le=5000)
    max_water_distance_m: Optional[float] = Field(default=None, ge=0, le=5000, description="Maximum supported shoreline distance. Approximate locations or representative water points cannot confirm it.")
    max_water_walk_minutes: Optional[float] = Field(default=None, ge=0, le=120, description="Maximum supported walk to a public waterfront; a straight-line estimate cannot satisfy it.")
    providers: Optional[List[str]] = Field(
        default=None,
        description="Providers to search. Defaults to all three: ImmoScout24, Kleinanzeigen, WG-Gesucht.",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=MAX_RESULTS_HARD_LIMIT,
        description="Maximum number of listings to return (1-20, default 10).",
    )
    relevance_criteria: Optional[str] = Field(
        default=None,
        max_length=MAX_RELEVANCE_CRITERIA_CHARS,
        description=(
            "Optional concise natural-language housing preference used to rank a larger "
            "candidate pool. Populate it when the user states a material preference not fully "
            "expressed by structured filters; omit it for a plain search and never infer "
            "unstated amenities, commute, lease, accessibility, or neighborhood qualities."
        ),
    )

    @model_validator(mode="after")
    def consistent_constraints(self):
        for lower, upper in ((self.min_price_eur, self.max_price_eur), (self.min_rooms, self.max_rooms), (self.min_size_sqm, self.max_size_sqm)):
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("minimum cannot exceed maximum")
        if set(self.required_amenities) & set(self.excluded_amenities):
            raise ValueError("an amenity cannot be both required and excluded")
        return self


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


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _listing_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(value[:10], pattern).date()
            except ValueError:
                continue
    return None


def filter_home_listings(listings: List[Dict[str, Any]], request: Dict[str, Any], *, amenities: bool = True, geographic: bool = True) -> tuple[List[Dict[str, Any]], List[str]]:
    """Apply explicit constraints without confusing unknown evidence with a match."""
    kept: List[Dict[str, Any]] = []
    unconfirmed_count = 0
    constraints = (
        ("min_price_eur", "price", False), ("max_price_eur", "price", True),
        ("min_rooms", "rooms", False), ("max_rooms", "rooms", True),
        ("min_size_sqm", "size_sqm", False), ("max_size_sqm", "size_sqm", True),
        ("max_warm_rent_eur", "warm_rent_eur", True), ("max_cold_rent_eur", "cold_rent_eur", True),
    )
    for listing in listings:
        missing: List[str] = []
        conflict = False
        for name, field, maximum in constraints:
            limit = request.get(name)
            if limit is None:
                continue
            value = _number(listing.get(field))
            if value is None:
                missing.append(name)
            elif (value > limit if maximum else value < limit):
                conflict = True
        deadline = _listing_date(request.get("available_by"))
        if deadline:
            available = _listing_date(listing.get("available_from"))
            if available is None:
                missing.append("available_by")
            elif available > deadline:
                conflict = True
        evidence = listing.setdefault("match_evidence", {})
        if amenities:
            for mode, expected in (("required_amenities", True), ("excluded_amenities", False)):
                for feature in request.get(mode, []):
                    fact = (listing.get("amenities") or {}).get(feature, listing.get(feature))
                    assessment = evidence.get("amenities", {}).get(feature, {})
                    status = assessment.get("status")
                    text_status = assessment.get("text_status")
                    visual_status = assessment.get("visual_status")
                    contradictory = ((fact is False and (text_status == "present" or visual_status == "visible"))
                                     or (fact is True and text_status == "absent")
                                     or (text_status == "absent" and visual_status == "visible")
                                     or feature in (listing.get("amenity_conflicts") or {}))
                    if contradictory:
                        conflict = True
                    elif isinstance(fact, bool):
                        conflict |= fact != expected
                    elif text_status in {"present", "absent"}:
                        conflict |= (text_status == "present") != expected
                    elif expected and status == "confirmed":
                        continue
                    elif not expected and text_status in {"absent", "no", "excluded", "explicit_no"}:
                        continue
                    elif not expected and status == "confirmed":
                        conflict = True
                    else:
                        missing.append(feature)
        if geographic:
            water = (listing.get("neighborhood") or {}).get("features", {}).get("water", [])
            precise = listing.get("location_precision") == "building" and not listing.get("location_approximate", True)
            for name, field in (("max_water_distance_m", "distance_m"), ("max_water_walk_minutes", "walk_minutes")):
                limit = request.get(name)
                if limit is None:
                    continue
                values = [_number(row.get(field)) for row in water if precise and isinstance(row, dict)
                          and (row.get("distance_method") == "shoreline_geometry" if field == "distance_m"
                               else row.get("walk_status") == "routed" and row.get("walk_method") == "provider_walking_route")]
                values = [value for value in values if value is not None]
                if not values:
                    missing.append(name)
                elif min(values) > limit:
                    conflict = True
        if conflict:
            continue
        if missing:
            unconfirmed_count += 1
            evidence["status"] = "unconfirmed"
            evidence["unconfirmed_requirements"] = missing
            if not request.get("include_unconfirmed"):
                continue
        elif amenities and geographic:
            evidence.setdefault("status", "confirmed")
            evidence["requirements_status"] = "confirmed"
            evidence.pop("unconfirmed_requirements", None)
        kept.append(listing)
    warnings = [f"{unconfirmed_count} listing(s) have missing or uncertain evidence for explicit requirements; "
                + ("included as unconfirmed." if request.get("include_unconfirmed") else "not counted as confirmed matches. Set include_unconfirmed to inspect them.")] if unconfirmed_count else []
    return kept, warnings


def prioritize_location_candidates(listings: List[Dict[str, Any]], request: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Spend finite geocoding on supported, affordable matches before unknowns.

    Keep the existing price/newest ordering for equal evidence. This only orders
    optional enrichment, and does not replace final geographic relevance ranking.
    """
    preferred = request.get("preferred_amenities") or []

    def priority(listing: Dict[str, Any]) -> tuple[int, int]:
        evidence = listing.get("match_evidence") or {}
        assessments = evidence.get("amenities") or {}
        supported = 0
        for feature in preferred:
            fact = (listing.get("amenities") or {}).get(feature, listing.get(feature))
            assessment = assessments.get(feature) or {}
            if fact is True or assessment.get("status") == "confirmed" or assessment.get("text_status") == "present":
                supported += 1
        return bool(evidence.get("unconfirmed_requirements")), -supported

    return sorted(listings, key=priority)


def _listing_identity(listing: Dict[str, Any]) -> str:
    # Provider identity avoids merging unrelated flats with generic titles and district-only addresses.
    url = normalize_url_for_deduplication(listing.get("url"))
    if url:
        return f"url:{url}"
    return f"{listing.get('provider', '')}:{listing.get('id', '')}"


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
        secrets_manager: Optional[SecretsManager] = None,
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
            secrets_manager: Optional injected secrets manager for Jev relevance ranking.
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
            secrets_manager=secrets_manager,
            cache_service=kwargs.get("cache_service"),
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
        """Final local fallback only; never disguise a city center as a listing pin."""
        coords = lookup_city(city)
        for listing in listings:
            if _number(listing.get("latitude")) is not None and _number(listing.get("longitude")) is not None:
                continue
            if coords:
                set_city_fallback(listing, coords, source="OpenMates city lookup")


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
                 'providers', 'max_results', and 'relevance_criteria'.
            request_id: Unique ID for this request (for result grouping).
            **kwargs: Additional kwargs, including the optional secrets manager.

        Returns:
            Tuple of (request_id, results_list, error_string_or_none).
        """
        try:
            validated = SearchRequestItem.model_validate(req)
        except Exception as exc:
            return (request_id, [], f"Invalid housing search input: {exc}")
        req = validated.model_dump(mode="json", exclude_none=True)
        query: str = req.get("query", "").strip()
        listing_type: str = req.get("listing_type", "rent").strip().lower()
        providers_requested: Optional[List[str]] = req.get("providers")
        max_results: int = int(req.get("max_results", 10))
        relevance_criteria = normalize_relevance_criteria(req.get("relevance_criteria"))

        if not query:
            return (request_id, [], "Missing 'query' in request")

        req = await resolve_home_preferences(req, secrets_manager=kwargs.get("secrets_manager"))
        amenity_search = any(req.get(key) for key in ("required_amenities", "excluded_amenities", "preferred_amenities"))
        geographic_search = bool(requested_categories(req))
        filtered_search = any(req.get(key) is not None for key in (
            "min_price_eur", "max_price_eur", "min_rooms", "max_rooms", "min_size_sqm", "max_size_sqm",
            "max_warm_rent_eur", "max_cold_rent_eur", "available_by"))
        expanded_search = bool(relevance_criteria or amenity_search or geographic_search or filtered_search)

        # Clamp max_results
        max_results = max(1, min(MAX_RESULTS_HARD_LIMIT, max_results))
        candidate_target = relevance_candidate_target(max_results) if expanded_search else max_results

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

        if expanded_search:
            provider_count = max(1, len(selected_providers))
            discovery_limit = min(
                MAX_RESULTS_HARD_LIMIT,
                max(max_results, (candidate_target + provider_count - 1) // provider_count),
            )
        else:
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

        # Authoritative numeric constraints avoid spending inference on known conflicts.
        merged, numeric_warnings = filter_home_listings(merged, req, amenities=False, geographic=False)
        warnings.extend(numeric_warnings)
        if sort == "newest":
            merged.sort(key=lambda item: item["discovery_rank"])
            if any(name != "Kleinanzeigen" for name in selected_providers):
                warnings.append("ImmoScout24 and WG-Gesucht retain provider order; newest ordering is not guaranteed.")
        else:
            merged.sort(key=lambda item: (item.get("price") is None, item.get("price") or 0))
        merged = stable_deduplicate_candidates(merged, key=_listing_identity)[:candidate_target]

        if amenity_search:
            warnings.extend(await assess_home_evidence(
                merged, request=req, secrets_manager=kwargs.get("secrets_manager"),
                cache_service=kwargs.get("cache_service")))
        # Remove authoritative amenity conflicts and unresolved hard requirements
        # after assessment, before they consume the optional location budget.
        merged, amenity_warnings = filter_home_listings(merged, req, geographic=False)
        warnings.extend(amenity_warnings)
        if geographic_search:
            prioritized = prioritize_location_candidates(merged, req)
            warnings.extend(await enrich_home_locations(
                prioritized, city=query, request=req, secrets_manager=kwargs.get("secrets_manager"),
                cache_service=kwargs.get("cache_service")))

        merged, evidence_warnings = filter_home_listings(merged, req)
        warnings.extend(evidence_warnings)
        ranking_criteria = relevance_criteria or (
            "Prefer explicitly supported amenities: " + ", ".join(req.get("preferred_amenities", []))
            if req.get("preferred_amenities") else ""
        )
        if geographic_search and not ranking_criteria:
            ranking_criteria = "Prioritize supported nearby " + ", ".join(requested_categories(req)) + " evidence."
        if ranking_criteria:
            projections = []
            for listing in merged:
                neighborhood = (listing.get("neighborhood") or {}).get("features", {})
                nearby = {category: [{key: row.get(key) for key in ("name", "distance_m", "distance_method", "walk_minutes")}
                                     for row in rows[:2]] for category, rows in neighborhood.items() if isinstance(rows, list)}
                projections.append({
                    "title": listing.get("title"), "amenities": listing.get("amenities"),
                    "match_evidence": listing.get("match_evidence"), "nearby": nearby,
                    "location_precision": listing.get("location_precision"),
                    "price": listing.get("price"), "price_type": listing.get("price_type"),
                    "warm_rent_eur": listing.get("warm_rent_eur"), "cold_rent_eur": listing.get("cold_rent_eur"),
                    "rooms": listing.get("rooms"), "size_sqm": listing.get("size_sqm"),
                    "address": listing.get("address"), "available_from": listing.get("available_from"),
                    "description": listing.get("description"),
                })
            ranking = await rank_search_candidates(
                candidates=merged, candidate_projections=projections,
                relevance_criteria=ranking_criteria, search_parameters=req,
                profile="home", secrets_manager=kwargs.get("secrets_manager"))
            merged = ranking.candidates
            if not ranking.applied and merged:
                warnings.append("Relevance ranking was unavailable; provider/price order is retained.")

        # Never emit extra candidate embeds. Enrich neutral searches only after selection.
        merged = merged[:max_results]
        if not geographic_search:
            warnings.extend(await enrich_home_locations(
                merged, city=query, request=req, secrets_manager=kwargs.get("secrets_manager"),
                cache_service=kwargs.get("cache_service")))
        await self._geocode_listings(merged, city=query)
        if not merged and not provider_errors:
            warnings.append("No confirmed matches in the bounded provider results; broaden requirements or inspect unconfirmed listings.")
        warnings.append("Coverage is limited to the retrieved provider pages; this is not an exhaustive market search.")

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
