"""
WG-Gesucht search + detail API provider for German housing search.

Searches WG-Gesucht for WG rooms and apartment listings by:
  1. Fetching the search results HTML page (server-rendered, no JS needed)
  2. Extracting listing IDs from data-id attributes in the HTML
  3. Fetching listing details from the undocumented JSON API (/api/offers/{id})
  4. Normalizing results to the standard listing schema

The search HTML is lightweight (~500KB) and returns ~27 listings per page.
The detail API returns 100+ fields per listing as HAL+JSON.
Neither endpoint requires authentication or cookies.

Provider: WG-Gesucht (wg-gesucht.de)
No API key required.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.wg-gesucht.de"
DETAIL_API_BASE = f"{BASE_URL}/api/offers"
REQUEST_TIMEOUT_SECONDS = 15
DETAIL_TIMEOUT_SECONDS = 10

# City ID mapping — WG-Gesucht uses numeric IDs in URLs
# Format: /wg-zimmer-in-{City}.{city_id}.{category}.1.0.html
CITY_IDS: Dict[str, int] = {
    "berlin": 8,
    "munich": 90,
    "muenchen": 90,
    "münchen": 90,
    "hamburg": 55,
    "cologne": 73,
    "köln": 73,
    "koeln": 73,
    "frankfurt": 41,
    "düsseldorf": 30,
    "duesseldorf": 30,
    "stuttgart": 124,
    "dortmund": 26,
    "essen": 35,
    "leipzig": 77,
    "bremen": 17,
    "dresden": 27,
    "hannover": 57,
    "nuremberg": 96,
    "nürnberg": 96,
    "freiburg": 44,
    "heidelberg": 60,
    "bonn": 13,
    "münster": 91,
    "aachen": 1,
    "augsburg": 2,
    "karlsruhe": 69,
    "mannheim": 84,
    "wiesbaden": 140,
    "mainz": 82,
    "regensburg": 111,
    "potsdam": 107,
    "rostock": 113,
    "kiel": 71,
}

# Category mapping for URL construction
# Category 0 = WG rooms, 1 = 1-room apartments, 2 = apartments, 3 = houses
CATEGORY_MAP: Dict[str, str] = {
    "wg": "wg-zimmer",
    "1_room": "1-zimmer-wohnungen",
    "apartment": "wohnungen",
    "house": "haeuser",
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.7",
}

API_HEADERS = {
    "User-Agent": BROWSER_HEADERS["User-Agent"],
    "Accept": "application/json",
    "Accept-Language": "de-DE,de;q=0.9",
}


def _get_city_id(city: str) -> Optional[int]:
    """Resolve a city name to its WG-Gesucht numeric ID."""
    return CITY_IDS.get(city.strip().lower())


def _build_search_url(city: str, city_id: int, category: str = "0") -> str:
    """
    Build a WG-Gesucht search URL.

    URL format: /{type}-in-{City}.{city_id}.{category}.1.0.html
    With filter params: ?offer_filter=1&city_id={id}&categories[]={cat}&rent_types[]=0&noDeact=1
    """
    city_title = city.strip().title()
    slug = CATEGORY_MAP.get("wg", "wg-zimmer")
    if category == "2":
        slug = CATEGORY_MAP["apartment"]
    elif category == "1":
        slug = CATEGORY_MAP["1_room"]

    base = f"{BASE_URL}/{slug}-in-{city_title}.{city_id}.{category}.1.0.html"
    params = f"?offer_filter=1&city_id={city_id}&categories%5B%5D={category}&rent_types%5B%5D=0&noDeact=1"
    return base + params


def _extract_listing_ids_from_html(html: str) -> List[str]:
    """Extract numeric listing IDs from WG-Gesucht search results HTML."""
    ids = re.findall(r'data-id="(\d{5,})"', html)
    return list(dict.fromkeys(ids))


def _normalize_listing(offer_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a WG-Gesucht API offer response to the standard listing schema.

    The /api/offers/{id} endpoint returns HAL+JSON with 100+ fields.
    We extract the key fields for our unified listing format.
    """
    title = data.get("offer_title", "")

    # Price: rent_costs is Kaltmiete, total_costs is Warmmiete
    price: Optional[float] = None
    total_costs = data.get("total_costs")
    rent_costs = data.get("rent_costs")
    price_source = total_costs or rent_costs
    if price_source is not None:
        try:
            price = float(price_source)
        except (ValueError, TypeError):
            pass

    if price is not None:
        price_label = f"{price:,.0f} EUR/month".replace(",", ".")
    else:
        price_label = "Price on request"

    # Size
    size_sqm: Optional[float] = None
    property_size = data.get("property_size")
    if property_size is not None:
        try:
            size_sqm = float(property_size)
        except (ValueError, TypeError):
            pass

    # Rooms
    rooms: Optional[float] = None
    num_rooms = data.get("number_of_rooms")
    if num_rooms is not None:
        try:
            rooms = float(num_rooms)
        except (ValueError, TypeError):
            pass

    # Address
    street = data.get("street", "")
    postcode = data.get("postcode", "")
    district = data.get("district_custom", "")
    address_parts = [p for p in [street, postcode] if p]
    address = ", ".join(address_parts)
    if district:
        address = f"{address} ({district})" if address else district

    # Build listing URL from category and district
    category = data.get("category", "0")
    category_slugs = {"0": "wg-zimmer", "1": "1-zimmer-wohnungen", "2": "wohnungen", "3": "haeuser"}
    slug = category_slugs.get(str(category), "wg-zimmer")
    district_slug = district.replace(" ", "-").replace("/", "-") if district else "listing"
    listing_url = f"{BASE_URL}/{slug}-in-{district_slug}.{offer_id}.html"

    return {
        "id": f"wg_{offer_id}",
        "title": title,
        "price": price,
        "price_label": price_label,
        "size_sqm": size_sqm,
        "rooms": rooms,
        "address": address,
        "image_url": None,  # Images require auth on WG-Gesucht
        "url": listing_url,
        "provider": "WG-Gesucht",
        "listing_type": "rent",
    }


async def search_listings(
    city: str,
    listing_type: str = "rent",
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """
    Search WG-Gesucht for room/apartment listings in a German city.

    Approach:
      1. Fetch search HTML page (lightweight, ~500KB, no JS needed)
      2. Extract listing IDs from data-id attributes
      3. Fetch details for top N listings via /api/offers/{id}

    WG-Gesucht only has rental listings — returns empty for "buy" type.

    Args:
        city: City name (e.g. "Berlin", "Munich", "Hamburg").
        listing_type: "rent" or "buy" (only "rent" returns results).
        max_results: Maximum listings to return (default 10).

    Returns:
        List of normalized listing dicts. Empty list on error or for "buy" type.
    """
    if listing_type == "buy":
        logger.info("WG-Gesucht skipped: only rental listings available (requested type=%s)", listing_type)
        return []

    city_id = _get_city_id(city)
    if city_id is None:
        logger.warning("WG-Gesucht: unknown city '%s' — no city_id mapping", city)
        return []

    search_url = _build_search_url(city, city_id)
    logger.info("WG-Gesucht search city=%s city_id=%d url=%s", city, city_id, search_url)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            # Step 1: Fetch search HTML
            search_resp = await client.get(search_url, headers=BROWSER_HEADERS, follow_redirects=True)
            search_resp.raise_for_status()

            # Step 2: Extract listing IDs
            listing_ids = _extract_listing_ids_from_html(search_resp.text)
            if not listing_ids:
                logger.info("WG-Gesucht: no listings found for city=%s", city)
                return []

            logger.info("WG-Gesucht found %d listing IDs for city=%s", len(listing_ids), city)

            # Step 3: Fetch details for top N listings in parallel
            ids_to_fetch = listing_ids[:max_results]

            async def fetch_detail(offer_id: str) -> Optional[Dict[str, Any]]:
                try:
                    resp = await client.get(
                        f"{DETAIL_API_BASE}/{offer_id}",
                        headers=API_HEADERS,
                        timeout=DETAIL_TIMEOUT_SECONDS,
                    )
                    if resp.status_code == 200:
                        return _normalize_listing(offer_id, resp.json())
                    logger.debug("WG-Gesucht detail API status=%d for offer=%s", resp.status_code, offer_id)
                except Exception as e:
                    logger.debug("WG-Gesucht detail fetch failed offer=%s: %s", offer_id, e)
                return None

            results = await asyncio.gather(*[fetch_detail(oid) for oid in ids_to_fetch])
            listings = [r for r in results if r is not None]

            logger.info("WG-Gesucht search city=%s -> %d listings (from %d IDs)", city, len(listings), len(listing_ids))
            return listings

    except httpx.HTTPStatusError as e:
        logger.error("WG-Gesucht HTTP error status=%d city=%s: %s", e.response.status_code, city, e)
        return []
    except Exception as e:
        logger.error("WG-Gesucht search failed city=%s: %s", city, e, exc_info=True)
        return []
