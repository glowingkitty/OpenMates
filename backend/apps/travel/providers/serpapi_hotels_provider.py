"""
SerpAPI Google Hotels provider for the travel app.

Searches for hotels and other accommodation (hostels, vacation rentals) via
the SerpAPI Google Hotels engine. Returns structured results with pricing,
ratings, amenities, images, and GPS coordinates.

API docs: https://serpapi.com/google-hotels-api
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

# Reuse SerpAPI credential loading from the flights provider
from backend.apps.travel.providers.serpapi_provider import (
    SERPAPI_BASE,
    _get_serpapi_key_async,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SerpAPI sort_by mapping
# ---------------------------------------------------------------------------
_SORT_BY_MAP: Dict[str, str] = {
    "relevance": "",       # Default (no param)
    "price_asc": "3",      # Lowest price
    "rating_desc": "8",    # Highest rating
    "reviews_desc": "13",  # Most reviewed
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class StayResult:
    """A single accommodation result from the Google Hotels search."""

    def __init__(
        self,
        name: str,
        description: Optional[str] = None,
        property_type: str = "hotel",
        link: Optional[str] = None,
        property_token: Optional[str] = None,
        gps_coordinates: Optional[Dict[str, float]] = None,
        hotel_class: Optional[int] = None,
        overall_rating: Optional[float] = None,
        reviews: Optional[int] = None,
        rate_per_night: Optional[str] = None,
        extracted_rate_per_night: Optional[float] = None,
        total_rate: Optional[str] = None,
        extracted_total_rate: Optional[float] = None,
        currency: str = "EUR",
        check_in_time: Optional[str] = None,
        check_out_time: Optional[str] = None,
        amenities: Optional[List[str]] = None,
        images: Optional[List[Dict[str, str]]] = None,
        thumbnail: Optional[str] = None,
        nearby_places: Optional[List[Dict[str, Any]]] = None,
        eco_certified: bool = False,
        free_cancellation: bool = False,
    ):
        self.name = name
        self.description = description
        self.property_type = property_type
        self.link = link
        self.property_token = property_token
        self.gps_coordinates = gps_coordinates
        self.hotel_class = hotel_class
        self.overall_rating = overall_rating
        self.reviews = reviews
        self.rate_per_night = rate_per_night
        self.extracted_rate_per_night = extracted_rate_per_night
        self.total_rate = total_rate
        self.extracted_total_rate = extracted_total_rate
        self.currency = currency
        self.check_in_time = check_in_time
        self.check_out_time = check_out_time
        self.amenities = amenities or []
        self.images = images or []
        self.thumbnail = thumbnail
        self.nearby_places = nearby_places or []
        self.eco_certified = eco_certified
        self.free_cancellation = free_cancellation

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for the skill response / embed content."""
        result: Dict[str, Any] = {
            "type": "stay",
            "name": self.name,
            "property_type": self.property_type,
            "currency": self.currency,
        }
        if self.description:
            result["description"] = self.description
        if self.link:
            result["link"] = self.link
        if self.property_token:
            result["property_token"] = self.property_token
        if self.gps_coordinates:
            result["latitude"] = self.gps_coordinates.get("latitude")
            result["longitude"] = self.gps_coordinates.get("longitude")
        if self.hotel_class is not None:
            result["hotel_class"] = self.hotel_class
        if self.overall_rating is not None:
            result["overall_rating"] = self.overall_rating
        if self.reviews is not None:
            result["reviews"] = self.reviews
        if self.rate_per_night:
            result["rate_per_night"] = self.rate_per_night
        if self.extracted_rate_per_night is not None:
            result["extracted_rate_per_night"] = self.extracted_rate_per_night
        if self.total_rate:
            result["total_rate"] = self.total_rate
        if self.extracted_total_rate is not None:
            result["extracted_total_rate"] = self.extracted_total_rate
        if self.check_in_time:
            result["check_in_time"] = self.check_in_time
        if self.check_out_time:
            result["check_out_time"] = self.check_out_time
        if self.amenities:
            result["amenities"] = self.amenities
        if self.images:
            result["images"] = self.images[:5]  # Limit to 5 images for embed size
        if self.thumbnail:
            result["thumbnail"] = self.thumbnail
        if self.nearby_places:
            result["nearby_places"] = self.nearby_places[:3]  # Limit to 3
        if self.eco_certified:
            result["eco_certified"] = True
        if self.free_cancellation:
            result["free_cancellation"] = True
        return result


# ---------------------------------------------------------------------------
# SerpAPI Hotels search
# ---------------------------------------------------------------------------

async def search_hotels(
    query: str,
    check_in_date: str,
    check_out_date: str,
    adults: int = 2,
    children: int = 0,
    currency: str = "EUR",
    gl: str = "us",
    hl: str = "en",
    sort_by: str = "relevance",
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    hotel_class: Optional[str] = None,
    rating: Optional[str] = None,
    free_cancellation: bool = False,
    max_results: int = 10,
    secrets_manager: Optional["SecretsManager"] = None,
) -> List[StayResult]:
    """
    Search for hotels/accommodations via the SerpAPI Google Hotels engine.

    Args:
        query: Search query (e.g., "Hotels in Paris", "Hostels in Berlin").
        check_in_date: Check-in date in YYYY-MM-DD format.
        check_out_date: Check-out date in YYYY-MM-DD format.
        adults: Number of adults (default: 2).
        children: Number of children (default: 0).
        currency: Currency code (default: EUR).
        gl: Google geolocation code (default: us).
        hl: Language code (default: en).
        sort_by: Sort order (relevance, price_asc, rating_desc, reviews_desc).
        min_price: Minimum price filter.
        max_price: Maximum price filter.
        hotel_class: Hotel star class filter (e.g., "3,4,5").
        rating: Minimum rating filter ("7"=3.5+, "8"=4.0+, "9"=4.5+).
        free_cancellation: Only show free cancellation results.
        max_results: Maximum number of results to return.
        secrets_manager: Optional SecretsManager for API key retrieval.

    Returns:
        List of StayResult objects.
    """
    api_key = await _get_serpapi_key_async(secrets_manager)
    if not api_key:
        raise ValueError("SerpAPI key not available")

    params: Dict[str, Any] = {
        "engine": "google_hotels",
        "api_key": api_key,
        "q": query,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "adults": str(adults),
        "children": str(children),
        "currency": currency,
        "gl": gl,
        "hl": hl,
    }

    # Sort parameter
    sort_value = _SORT_BY_MAP.get(sort_by, "")
    if sort_value:
        params["sort_by"] = sort_value

    # Optional filters
    if min_price is not None:
        params["min_price"] = str(min_price)
    if max_price is not None:
        params["max_price"] = str(max_price)
    if hotel_class:
        params["hotel_class"] = hotel_class
    if rating:
        params["rating"] = rating
    if free_cancellation:
        params["free_cancellation"] = "true"

    # Make the API request
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(SERPAPI_BASE, params=params)

        if response.status_code != 200:
            logger.error(
                f"SerpAPI Hotels request failed ({response.status_code}): "
                f"{response.text[:500]}"
            )
            return []

        data = response.json()

    except httpx.TimeoutException:
        logger.error("SerpAPI Hotels request timed out (120s)")
        return []
    except Exception as e:
        logger.error(f"SerpAPI Hotels request error: {e}", exc_info=True)
        return []

    if data.get("error"):
        logger.error(f"SerpAPI Hotels error: {data['error']}")
        return []

    # Parse properties from the response
    properties = data.get("properties", [])
    if not properties:
        logger.info("SerpAPI Hotels returned no properties")
        return []

    results: List[StayResult] = []
    for prop in properties[:max_results]:
        stay = _parse_property(prop, currency)
        if stay:
            results.append(stay)

    logger.info(f"SerpAPI Hotels returned {len(results)} property/ies for query '{query}'")
    return results


def _parse_property(prop: dict, currency: str) -> Optional[StayResult]:
    """Parse a single property from the SerpAPI Google Hotels response."""
    name = prop.get("name")
    if not name:
        return None

    # Extract rate_per_night pricing
    rpn = prop.get("rate_per_night", {})
    rate_per_night = rpn.get("lowest")
    extracted_rate = rpn.get("extracted_lowest")

    # Extract total_rate pricing
    tr = prop.get("total_rate", {})
    total_rate = tr.get("lowest")
    extracted_total = tr.get("extracted_lowest")

    # GPS coordinates
    gps = prop.get("gps_coordinates")

    # Hotel class (star rating)
    hotel_class = prop.get("extracted_hotel_class")

    # Images
    raw_images = prop.get("images", [])
    images = []
    for img in raw_images[:5]:
        entry: Dict[str, str] = {}
        if img.get("thumbnail"):
            entry["thumbnail"] = img["thumbnail"]
        if img.get("original_image"):
            entry["original_image"] = img["original_image"]
        if entry:
            images.append(entry)

    # Nearby places
    raw_nearby = prop.get("nearby_places", [])
    nearby = []
    for place in raw_nearby[:3]:
        place_entry: Dict[str, Any] = {"name": place.get("name", "")}
        transports = place.get("transportations", [])
        if transports:
            place_entry["transportation"] = transports[0].get("type", "")
            place_entry["duration"] = transports[0].get("duration", "")
        nearby.append(place_entry)

    return StayResult(
        name=name,
        description=prop.get("description"),
        property_type=prop.get("type", "hotel"),
        link=prop.get("link"),
        property_token=prop.get("property_token"),
        gps_coordinates=gps,
        hotel_class=hotel_class,
        overall_rating=prop.get("overall_rating"),
        reviews=prop.get("reviews"),
        rate_per_night=rate_per_night,
        extracted_rate_per_night=extracted_rate,
        total_rate=total_rate,
        extracted_total_rate=extracted_total,
        currency=currency,
        check_in_time=prop.get("check_in_time"),
        check_out_time=prop.get("check_out_time"),
        amenities=prop.get("amenities", []),
        images=images,
        thumbnail=prop.get("thumbnail"),
        nearby_places=nearby,
        eco_certified=prop.get("eco_certified", False),
        free_cancellation=prop.get("free_cancellation", False),
    )
