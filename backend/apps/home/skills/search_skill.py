import logging
import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.geo_utils import lookup_city
from backend.apps.home.location_enrichment import set_city_fallback
from backend.shared.python_utils.search_relevance import (
    MAX_RELEVANCE_CRITERIA_CHARS,
    normalize_url_for_deduplication,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# All available providers and their search functions
PROVIDER_MAP: Dict[str, Any] = {}

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
        description="Optional source identifiers; housing search is currently unavailable.",
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
    """Housing contract retained while no permitted source is configured."""

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        return {"provider": "Unavailable", "providers": []}

    async def execute(self, requests: List[Dict[str, Any]], secrets_manager: Any = None,
                      **kwargs: Any) -> SearchResponse:
        error = "Housing search is unavailable: no permitted provider is configured."
        groups = [{"id": item.get("id", index + 1), "results": [], "error": error}
                  for index, item in enumerate(requests or [])]
        return SearchResponse(results=groups, provider="Unavailable", providers=[], error=error)

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
