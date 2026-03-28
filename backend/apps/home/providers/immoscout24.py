"""
ImmoScout24 mobile API provider for German housing search.

Searches the ImmoScout24 mobile API for apartment/house listings.
Uses the public mobile API endpoint which does not require an API key.
Requires a specific User-Agent header to mimic the mobile app.

Data flow:
  1. Map city name to geocode path (e.g. "berlin" -> "/de/berlin/berlin")
  2. Map listing_type to realestatetype (e.g. "rent" -> "apartmentrent")
  3. POST to mobile search endpoint with geocode and realestatetype
  4. Parse JSON response, extract listings, normalize to standard schema

Provider: ImmoScout24 (immobilienscout24.de)
No API key required.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOBILE_API_BASE = "https://api.mobile.immobilienscout24.de"
SEARCH_ENDPOINT = "/search/list"
MOBILE_USER_AGENT = "ImmoScout_27.12_26.2_._"
REQUEST_TIMEOUT_SECONDS = 15

# Mapping from listing_type to ImmoScout24 realestatetype parameter
LISTING_TYPE_MAP: Dict[str, str] = {
    "rent": "apartmentrent",
    "buy": "apartmentbuy",
}

# Major German cities to ImmoScout24 geocode paths.
# Falls back to /de/{city} if not found in this dict.
CITY_GEOCODE_MAP: Dict[str, str] = {
    "berlin": "/de/berlin/berlin",
    "munich": "/de/bayern/muenchen",
    "muenchen": "/de/bayern/muenchen",
    "munchen": "/de/bayern/muenchen",
    "hamburg": "/de/hamburg/hamburg",
    "cologne": "/de/nordrhein-westfalen/koeln",
    "koeln": "/de/nordrhein-westfalen/koeln",
    "frankfurt": "/de/hessen/frankfurt-am-main",
    "stuttgart": "/de/baden-wuerttemberg/stuttgart",
    "dusseldorf": "/de/nordrhein-westfalen/duesseldorf",
    "duesseldorf": "/de/nordrhein-westfalen/duesseldorf",
    "dortmund": "/de/nordrhein-westfalen/dortmund",
    "essen": "/de/nordrhein-westfalen/essen",
    "leipzig": "/de/sachsen/leipzig",
    "bremen": "/de/bremen/bremen",
    "dresden": "/de/sachsen/dresden",
    "hannover": "/de/niedersachsen/hannover",
    "nuernberg": "/de/bayern/nuernberg",
    "nuremberg": "/de/bayern/nuernberg",
    "duisburg": "/de/nordrhein-westfalen/duisburg",
    "bochum": "/de/nordrhein-westfalen/bochum",
    "wuppertal": "/de/nordrhein-westfalen/wuppertal",
    "bonn": "/de/nordrhein-westfalen/bonn",
    "muenster": "/de/nordrhein-westfalen/muenster",
    "karlsruhe": "/de/baden-wuerttemberg/karlsruhe",
    "mannheim": "/de/baden-wuerttemberg/mannheim",
    "augsburg": "/de/bayern/augsburg",
    "wiesbaden": "/de/hessen/wiesbaden",
    "freiburg": "/de/baden-wuerttemberg/freiburg-im-breisgau",
    "potsdam": "/de/brandenburg/potsdam",
    "mainz": "/de/rheinland-pfalz/mainz",
    "kiel": "/de/schleswig-holstein/kiel",
    "rostock": "/de/mecklenburg-vorpommern/rostock",
}


def _get_geocode(city: str) -> str:
    """
    Resolve a city name to an ImmoScout24 geocode path.

    Args:
        city: City name (case-insensitive). Matches against known German cities.

    Returns:
        Geocode path string (e.g. "/de/berlin/berlin").
        Falls back to "/de/{city_lower}" for unknown cities.
    """
    normalized = city.strip().lower().replace(" ", "-").replace("ü", "ue").replace("ö", "oe").replace("ä", "ae")
    return CITY_GEOCODE_MAP.get(normalized, f"/de/{normalized}")


def _normalize_listing(raw: Dict[str, Any], listing_type: str) -> Optional[Dict[str, Any]]:
    """
    Normalize a raw ImmoScout24 API listing to the standard schema.

    Args:
        raw: Raw listing dict from the ImmoScout24 mobile API response.
        listing_type: "rent" or "buy" — used in the normalized output.

    Returns:
        Normalized listing dict, or None if the listing lacks essential data.
    """
    real_estate = raw.get("resultlistRealEstate") or raw.get("resultlistEntry", {}).get("realEstate", {})
    if not real_estate:
        # Try alternative structure
        real_estate = raw

    listing_id = str(real_estate.get("@id") or raw.get("@id") or raw.get("id", ""))
    title = real_estate.get("title") or ""
    if not listing_id and not title:
        return None

    # Price extraction
    price_obj = real_estate.get("price", {})
    price_value = price_obj.get("value") if isinstance(price_obj, dict) else None
    price: Optional[float] = float(price_value) if price_value is not None else None

    # Build human-readable price label
    if price is not None:
        if listing_type == "rent":
            price_label = f"{price:,.0f} EUR/month".replace(",", ".")
        else:
            price_label = f"{price:,.0f} EUR".replace(",", ".")
    else:
        price_label = "Price on request"

    # Size and rooms
    living_space = real_estate.get("livingSpace")
    size_sqm: Optional[float] = float(living_space) if living_space is not None else None
    num_rooms = real_estate.get("numberOfRooms")
    rooms: Optional[float] = float(num_rooms) if num_rooms is not None else None

    # Address
    address_obj = real_estate.get("address", {})
    if isinstance(address_obj, dict):
        city_name = address_obj.get("city", "")
        quarter = address_obj.get("quarter", "")
        street = address_obj.get("street", "")
        address_parts = [p for p in [street, quarter, city_name] if p]
        address = ", ".join(address_parts) if address_parts else ""
    else:
        address = str(address_obj) if address_obj else ""

    # Image
    pictures = real_estate.get("titlePicture", {})
    image_url: Optional[str] = None
    if isinstance(pictures, dict):
        # Try various image URL fields
        for url_key in ["url", "floorplan", "urls"]:
            candidate = pictures.get(url_key)
            if isinstance(candidate, str) and candidate.startswith("http"):
                image_url = candidate
                break
            if isinstance(candidate, list) and candidate:
                first = candidate[0]
                if isinstance(first, dict):
                    image_url = first.get("url", {}).get("@href") or first.get("url")
                elif isinstance(first, str):
                    image_url = first
                if image_url:
                    break

    return {
        "id": f"is24_{listing_id}",
        "title": title,
        "price": price,
        "price_label": price_label,
        "size_sqm": size_sqm,
        "rooms": rooms,
        "address": address,
        "image_url": image_url,
        "url": f"https://www.immobilienscout24.de/expose/{listing_id}",
        "provider": "ImmoScout24",
        "listing_type": listing_type,
    }


async def search_listings(
    city: str,
    listing_type: str = "rent",
    max_results: int = 20,
) -> List[Dict[str, Any]]:
    """
    Search ImmoScout24 for apartment/house listings in a German city.

    Args:
        city: City name (e.g. "Berlin", "Munich", "Hamburg").
        listing_type: "rent" or "buy" (default "rent").
        max_results: Maximum number of listings to return (default 20).

    Returns:
        List of normalized listing dicts with standard schema fields.
        Returns empty list on error (logs the error).
    """
    geocode = _get_geocode(city)
    realestatetype = LISTING_TYPE_MAP.get(listing_type, "apartmentrent")

    url = f"{MOBILE_API_BASE}{SEARCH_ENDPOINT}"
    params = {
        "searchType": "region",
        "realestatetype": realestatetype,
        "geocodes": geocode,
    }
    body = {"supportedResultListTypes": [], "userData": {}}

    logger.info(
        "ImmoScout24 search city=%s type=%s geocode=%s",
        city, listing_type, geocode,
    )

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                params=params,
                json=body,
                headers={
                    "User-Agent": MOBILE_USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            "ImmoScout24 API HTTP error status=%d city=%s: %s",
            e.response.status_code, city, e,
        )
        return []
    except Exception as e:
        logger.error("ImmoScout24 API request failed city=%s: %s", city, e, exc_info=True)
        return []

    # Parse response structure — the path varies by API version
    results_list = []
    try:
        search_response = data.get("searchResponseModel", data)
        result_list = search_response.get("resultlistResultList", search_response.get("resultList", {}))
        entries = result_list.get("resultlistEntries", [])

        # entries can be a list of groups, each with resultlistEntry items
        for group in entries:
            if isinstance(group, dict):
                items = group.get("resultlistEntry", [])
                if isinstance(items, dict):
                    items = [items]
                results_list.extend(items)
            elif isinstance(group, list):
                results_list.extend(group)
    except Exception as e:
        logger.error("ImmoScout24 response parse error city=%s: %s", city, e, exc_info=True)
        return []

    # Normalize and filter
    listings: List[Dict[str, Any]] = []
    for raw in results_list[:max_results]:
        normalized = _normalize_listing(raw, listing_type)
        if normalized:
            listings.append(normalized)

    logger.info(
        "ImmoScout24 search city=%s type=%s -> %d listings (raw=%d)",
        city, listing_type, len(listings), len(results_list),
    )
    return listings
