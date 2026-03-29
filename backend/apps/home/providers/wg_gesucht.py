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


def _extract_listings_from_html(html: str) -> List[Dict[str, Any]]:
    """
    Extract listing IDs and thumbnail image URLs from WG-Gesucht search HTML.

    Each listing block contains a data-id attribute and a thumbnail image from
    img.wg-gesucht.de. We split the HTML by data-id boundaries and extract both.

    Returns:
        List of dicts with 'id' (str) and 'image_url' (str or None), deduplicated by ID.
    """
    # Split HTML into blocks per listing using data-id as boundary
    block_pattern = re.compile(r'data-id="(\d{5,})"(.*?)(?=data-id="\d{5,}"|</main>|$)', re.DOTALL)
    blocks = block_pattern.findall(html)

    seen: Dict[str, bool] = {}
    listings: List[Dict[str, Any]] = []

    for offer_id, block_html in blocks:
        if offer_id in seen:
            continue
        seen[offer_id] = True

        # Extract thumbnail image from img.wg-gesucht.de within this block
        img_match = re.search(
            r'(https://img\.wg-gesucht\.de/media/[^\s"<>;]+\.(?:jpg|jpeg|png|webp|JPG|JPEG|PNG|WEBP))',
            block_html,
        )
        image_url = img_match.group(1) if img_match else None

        listings.append({"id": offer_id, "image_url": image_url})

    return listings


def _normalize_listing(
    offer_id: str,
    data: Dict[str, Any],
    image_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Normalize a WG-Gesucht API offer response to the standard listing schema.

    The /api/offers/{id} endpoint returns HAL+JSON with 100+ fields.
    We extract the key fields for our unified listing format.

    Args:
        offer_id: The WG-Gesucht offer ID.
        data: Full API response dict for this offer.
        image_url: Thumbnail image URL extracted from search HTML (the API
                   does not return images, but the search page does).
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

    # Available from/to dates
    available_from = data.get("available_from_date", "")
    if available_from == "00.00.0000":
        available_from = ""

    # Deposit (bond_costs)
    deposit: Optional[float] = None
    bond_costs = data.get("bond_costs")
    if bond_costs is not None:
        try:
            deposit = float(bond_costs)
            if deposit == 0:
                deposit = None
        except (ValueError, TypeError):
            pass

    # Amenities as boolean flags (API returns 0/1)
    furnished = bool(data.get("furnished", 0))

    return {
        "id": f"wg_{offer_id}",
        "title": title,
        "price": price,
        "price_label": price_label,
        "size_sqm": size_sqm,
        "rooms": rooms,
        "address": address,
        "image_url": image_url,
        "url": listing_url,
        "provider": "WG-Gesucht",
        "listing_type": "rent",
        "available_from": available_from if available_from else None,
        "deposit": deposit,
        "furnished": furnished,
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

            # Step 2: Extract listing IDs and thumbnail images from HTML
            html_listings = _extract_listings_from_html(search_resp.text)
            if not html_listings:
                logger.info("WG-Gesucht: no listings found for city=%s", city)
                return []

            logger.info("WG-Gesucht found %d listing IDs for city=%s", len(html_listings), city)

            # Step 3: Fetch details for top N listings in parallel
            to_fetch = html_listings[:max_results]

            async def fetch_detail(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                offer_id = entry["id"]
                try:
                    resp = await client.get(
                        f"{DETAIL_API_BASE}/{offer_id}",
                        headers=API_HEADERS,
                        timeout=DETAIL_TIMEOUT_SECONDS,
                    )
                    if resp.status_code == 200:
                        return _normalize_listing(offer_id, resp.json(), image_url=entry.get("image_url"))
                    logger.debug("WG-Gesucht detail API status=%d for offer=%s", resp.status_code, offer_id)
                except Exception as e:
                    logger.debug("WG-Gesucht detail fetch failed offer=%s: %s", offer_id, e)
                return None

            results = await asyncio.gather(*[fetch_detail(e) for e in to_fetch])
            listings = [r for r in results if r is not None]

            logger.info("WG-Gesucht search city=%s -> %d listings (from %d IDs)", city, len(listings), len(html_listings))
            return listings

    except httpx.HTTPStatusError as e:
        logger.error("WG-Gesucht HTTP error status=%d city=%s: %s", e.response.status_code, city, e)
        return []
    except Exception as e:
        logger.error("WG-Gesucht search failed city=%s: %s", city, e, exc_info=True)
        return []
