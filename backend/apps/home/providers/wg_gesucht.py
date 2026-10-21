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

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from backend.apps.home.providers.results import ProviderListings
from backend.shared.providers.housing.details import (
    MAX_CANDIDATES, defaults, enrich, flag, html_details, location,
    merge_gallery, number, photos, response_text, text,
)

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

        link = re.search(r'href=["\']([^"\']*\.' + re.escape(offer_id) + r'\.html)["\']', block_html)
        listing = {"id": offer_id, "image_url": image_url}
        if link:
            from urllib.parse import urljoin, urlsplit
            candidate = urljoin(BASE_URL, link.group(1))
            if urlsplit(candidate).hostname in {"www.wg-gesucht.de", "wg-gesucht.de"}:
                listing["url"] = candidate
        listings.append(listing)

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
    district = text(data.get("district_custom"))
    category = str(data.get("category", "0"))
    slug = {"0": "wg-zimmer", "1": "1-zimmer-wohnungen", "2": "wohnungen", "3": "haeuser"}.get(category, "wg-zimmer")
    listing = defaults({
        "id": f"wg_{offer_id}", "title": text(data.get("offer_title")),
        "price": number(data.get("total_costs")) if number(data.get("total_costs")) is not None else number(data.get("rent_costs")),
        "size_sqm": number(data.get("property_size")), "rooms": number(data.get("number_of_rooms")),
        "address": ", ".join(text(data[key]) for key in ("street", "postcode", "district_custom") if data.get(key)),
        "image_url": image_url,
        "url": f"{BASE_URL}/{slug}-in-{district.replace(' ', '-').replace('/', '-') or 'listing'}.{offer_id}.html",
        "provider": "WG-Gesucht", "listing_type": "rent",
    })
    for source, target in {"rent_costs": "cold_rent_eur", "total_costs": "warm_rent_eur", "additional_costs": "utilities_eur", "heating_costs": "heating_costs_eur", "bond_costs": "deposit"}.items():
        listing[target] = number(data.get(source))
    listing["price_type"] = "warm" if listing["warm_rent_eur"] is not None else "cold" if listing["cold_rent_eur"] is not None else "unknown"
    listing["price_label"] = f"{listing['price']:,.0f} EUR/month".replace(",", ".") if listing['price'] is not None else "Price on request"
    for source, target in {"available_from_date": "available_from", "available_to_date": "available_to", "floor": "floor", "house_number": "house_number"}.items():
        listing[target] = data.get(source) if data.get(source) not in (None, "", "00.00.0000", "0000-00-00") else None
    descriptions = [text(data[key]) for key in ("offer_description", "description", "room_description", "property_description", "location_description", "flatshare_description", "miscellaneous_description", "freetext_property_description", "freetext_location", "freetext_flatshare", "freetext_other") if data.get(key)]
    listing["description"] = "\n\n".join(dict.fromkeys(descriptions)) or None
    for source, target in {"balcony": "balcony", "furnished": "furnished", "elevator": "elevator", "garden": "garden", "terrace": "terrace", "parking": "parking", "pets_allowed": "pets_allowed"}.items():
        listing["amenities"][target] = flag(data.get(source))
        listing[target] = listing["amenities"][target]
    location(listing, data)
    gallery_present = any(key in data for key in ("images", "pictures", "gallery"))
    gallery = [url for key in ("images", "pictures", "gallery") for url in photos(data.get(key))]
    merge_gallery(listing, gallery, complete=gallery_present)
    listing["detail_status"] = "available" if data else "unavailable"
    return listing


async def search_listings(
    city: str,
    listing_type: str = "rent",
    max_results: int = 10,
    property_type: str = "apartment",
    sort: str = "price_asc",
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
        raise ValueError("WG-Gesucht does not support this city")

    search_url = _build_search_url(city, city_id, category="2" if property_type == "apartment" else "0")
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

            # Keep search cards even when the API or optional gallery fails.
            entries = html_listings[:min(max(0, max_results), MAX_CANDIDATES)]
            listings = [_normalize_listing(entry["id"], {}, entry.get("image_url")) for entry in entries]
            for listing in listings:
                listing["city"] = city
            for listing, entry in zip(listings, entries):
                if entry.get("url"):
                    listing["url"] = entry["url"]

            async def fetch_detail(listing: Dict[str, Any]) -> None:
                offer_id = listing["id"][3:]
                api_error = None
                try:
                    raw = await response_text(client, f"{DETAIL_API_BASE}/{offer_id}", API_HEADERS)
                    data = json.loads(raw)
                    if not isinstance(data, dict) or not data.get("offer_title"):
                        raise ValueError("Unrecognized WG-Gesucht offer payload")
                    source_url = listing["url"]
                    listing.update(_normalize_listing(offer_id, data, image_url=listing.get("image_url")))
                    listing["url"] = source_url
                    listing["city"] = listing.get("city") or city
                except Exception as exc:
                    logger.debug("WG-Gesucht API unavailable offer=%s: %s", offer_id, exc)
                    api_error = exc
                # API often omits the photo collection: the public listing owns it.
                if listing["gallery_status"] != "complete" or api_error:
                    html = await response_text(client, listing["url"], BROWSER_HEADERS)
                    html_details(listing, html)

            detail_warnings = await enrich(listings, fetch_detail)
            logger.info("WG-Gesucht search city=%s -> %d listings", city, len(listings))
            return ProviderListings(listings, detail_warnings)

    except httpx.HTTPStatusError as e:
        logger.error("WG-Gesucht HTTP error status=%d city=%s: %s", e.response.status_code, city, e)
        raise RuntimeError(f"WG-Gesucht returned HTTP {e.response.status_code}") from e
    except Exception as e:
        logger.error("WG-Gesucht search failed city=%s: %s", city, e, exc_info=True)
        raise RuntimeError("WG-Gesucht search request failed") from e
