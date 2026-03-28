"""
WG-Gesucht sitemap + detail API provider for German housing search.

Searches WG-Gesucht for WG rooms and apartment listings by:
  1. Fetching the gzipped sitemap XML to get all listing URLs
  2. Filtering URLs by city name (e.g. "in-Berlin" in URL path)
  3. Fetching listing details from the JSON API for the top N matches
  4. Normalizing results to the standard listing schema

The sitemap is cached at module level with a 1-hour TTL to avoid
re-fetching on every search. Detail API calls are limited to
max_results to avoid rate limiting.

Provider: WG-Gesucht (wg-gesucht.de)
No API key required.
"""

import gzip
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SITEMAP_URL = "https://www.wg-gesucht.de/sitemaps/offer_detail_views/offer_details_DE.xml.gz"
DETAIL_API_BASE = "https://www.wg-gesucht.de/api/offers"
BASE_URL = "https://www.wg-gesucht.de"
REQUEST_TIMEOUT_SECONDS = 15
DETAIL_TIMEOUT_SECONDS = 10

# Sitemap cache: (urls_list, timestamp)
SITEMAP_CACHE_TTL_SECONDS = 3600  # 1 hour
_sitemap_cache: Optional[Tuple[List[str], float]] = None

# Default max detail API calls per search to avoid rate limiting
DEFAULT_MAX_DETAIL_CALLS = 10

# Browser-like headers for API requests
API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


async def _fetch_sitemap(client: httpx.AsyncClient) -> List[str]:
    """
    Fetch and parse the WG-Gesucht sitemap XML to extract listing URLs.

    Uses module-level cache with 1-hour TTL to avoid redundant fetches.

    Args:
        client: httpx.AsyncClient instance for making the request.

    Returns:
        List of listing URL strings from the sitemap.
    """
    global _sitemap_cache

    # Check cache
    if _sitemap_cache is not None:
        urls, cached_at = _sitemap_cache
        if time.time() - cached_at < SITEMAP_CACHE_TTL_SECONDS:
            logger.debug("WG-Gesucht sitemap cache hit (%d URLs)", len(urls))
            return urls

    logger.info("WG-Gesucht fetching sitemap from %s", SITEMAP_URL)

    try:
        response = await client.get(
            SITEMAP_URL,
            headers={"User-Agent": API_HEADERS["User-Agent"]},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        # Decompress gzip content
        xml_bytes = gzip.decompress(response.content)
        xml_text = xml_bytes.decode("utf-8")

        # Extract URLs from <loc> tags
        urls = re.findall(r"<loc>(https://www\.wg-gesucht\.de/[^<]+)</loc>", xml_text)

        logger.info("WG-Gesucht sitemap parsed: %d URLs", len(urls))

        # Update cache
        _sitemap_cache = (urls, time.time())
        return urls

    except Exception as e:
        logger.error("WG-Gesucht sitemap fetch failed: %s", e, exc_info=True)
        # Return cached URLs if available (stale cache is better than nothing)
        if _sitemap_cache is not None:
            logger.warning("WG-Gesucht using stale sitemap cache")
            return _sitemap_cache[0]
        return []


def _extract_offer_id(url: str) -> Optional[str]:
    """
    Extract the numeric offer ID from a WG-Gesucht listing URL.

    URL patterns:
    - /wg-zimmer-in-Berlin-Kreuzberg.12345.html
    - /1-zimmer-wohnungen-in-Hamburg.67890.html

    Args:
        url: Full WG-Gesucht listing URL.

    Returns:
        Offer ID string, or None if not parseable.
    """
    match = re.search(r'\.(\d+)\.html', url)
    return match.group(1) if match else None


def _filter_urls_by_city(urls: List[str], city: str) -> List[str]:
    """
    Filter sitemap URLs to only include listings in the specified city.

    WG-Gesucht URLs contain the city name in the path, e.g.:
    - /wg-zimmer-in-Berlin-Kreuzberg.12345.html
    - /1-zimmer-wohnungen-in-Hamburg.67890.html

    Args:
        urls: List of all sitemap URLs.
        city: City name to filter by (case-insensitive).

    Returns:
        Filtered list of URLs matching the city.
    """
    city_lower = city.strip().lower()
    # Match "in-{City}" pattern in URL (case-insensitive)
    pattern = re.compile(rf'in-{re.escape(city_lower)}', re.IGNORECASE)
    return [url for url in urls if pattern.search(url)]


def _normalize_listing(offer_id: str, data: Dict[str, Any], url: str) -> Dict[str, Any]:
    """
    Normalize a WG-Gesucht API offer response to the standard listing schema.

    Args:
        offer_id: WG-Gesucht offer ID.
        data: JSON response from the WG-Gesucht offer detail API.
        url: Original listing URL from the sitemap.

    Returns:
        Normalized listing dict with standard schema fields.
    """
    title = data.get("offer_title") or data.get("title") or ""

    # Price: try rent_costs first, then total_costs
    rent_costs = data.get("rent_costs", {})
    if isinstance(rent_costs, dict):
        price_value = rent_costs.get("total_costs") or rent_costs.get("rent") or rent_costs.get("amount")
    else:
        price_value = rent_costs
    price: Optional[float] = None
    if price_value is not None:
        try:
            price = float(price_value)
        except (ValueError, TypeError):
            pass

    if price is not None:
        price_label = f"{price:,.0f} EUR/month".replace(",", ".")
    else:
        price_label = "Price on request"

    # Size
    property_size = data.get("property_size") or data.get("size")
    size_sqm: Optional[float] = None
    if property_size is not None:
        try:
            size_sqm = float(property_size)
        except (ValueError, TypeError):
            pass

    # Rooms
    num_rooms = data.get("number_of_rooms") or data.get("rooms")
    rooms: Optional[float] = None
    if num_rooms is not None:
        try:
            rooms = float(num_rooms)
        except (ValueError, TypeError):
            pass

    # Address
    postcode = data.get("postcode") or data.get("zip_code") or ""
    street = data.get("street") or ""
    city_name = data.get("city") or ""
    address_parts = [p for p in [street, postcode, city_name] if p]
    address = ", ".join(address_parts) if address_parts else ""

    # Image
    images = data.get("images") or data.get("photos") or []
    image_url: Optional[str] = None
    if isinstance(images, list) and images:
        first_img = images[0]
        if isinstance(first_img, dict):
            image_url = first_img.get("url") or first_img.get("src")
        elif isinstance(first_img, str):
            image_url = first_img

    return {
        "id": f"wg_{offer_id}",
        "title": title,
        "price": price,
        "price_label": price_label,
        "size_sqm": size_sqm,
        "rooms": rooms,
        "address": address,
        "image_url": image_url,
        "url": url,
        "provider": "WG-Gesucht",
        "listing_type": "rent",  # WG-Gesucht is rent-only
    }


async def search_listings(
    city: str,
    listing_type: str = "rent",
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """
    Search WG-Gesucht for room/apartment listings in a German city.

    Note: WG-Gesucht primarily lists rental properties (WG rooms,
    apartments). The listing_type parameter is accepted for interface
    consistency but only "rent" produces results.

    Args:
        city: City name (e.g. "Berlin", "Munich", "Hamburg").
        listing_type: "rent" or "buy" (only "rent" returns results).
        max_results: Maximum number of listings to return (default 10).
                     Also limits the number of detail API calls.

    Returns:
        List of normalized listing dicts with standard schema fields.
        Returns empty list for "buy" type or on error.
    """
    # WG-Gesucht only has rental listings
    if listing_type == "buy":
        logger.info("WG-Gesucht skipped: only rental listings available (requested type=%s)", listing_type)
        return []

    # Limit detail calls to avoid rate limiting
    effective_max = min(max_results, DEFAULT_MAX_DETAIL_CALLS)

    logger.info("WG-Gesucht search city=%s max_results=%d", city, effective_max)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            # Step 1: Get sitemap URLs
            all_urls = await _fetch_sitemap(client)
            if not all_urls:
                logger.warning("WG-Gesucht: no URLs from sitemap")
                return []

            # Step 2: Filter by city
            city_urls = _filter_urls_by_city(all_urls, city)
            if not city_urls:
                logger.info("WG-Gesucht: no listings found for city=%s", city)
                return []

            logger.info(
                "WG-Gesucht found %d URLs for city=%s (fetching top %d)",
                len(city_urls), city, effective_max,
            )

            # Step 3: Fetch details for top N listings
            listings: List[Dict[str, Any]] = []
            for listing_url in city_urls[:effective_max]:
                offer_id = _extract_offer_id(listing_url)
                if not offer_id:
                    continue

                try:
                    detail_response = await client.get(
                        f"{DETAIL_API_BASE}/{offer_id}",
                        headers=API_HEADERS,
                        timeout=DETAIL_TIMEOUT_SECONDS,
                    )
                    if detail_response.status_code == 200:
                        offer_data = detail_response.json()
                        listing = _normalize_listing(offer_id, offer_data, listing_url)
                        listings.append(listing)
                    else:
                        logger.debug(
                            "WG-Gesucht detail API status=%d for offer=%s",
                            detail_response.status_code, offer_id,
                        )
                except Exception as e:
                    logger.debug("WG-Gesucht detail fetch failed offer=%s: %s", offer_id, e)
                    continue

            logger.info(
                "WG-Gesucht search city=%s -> %d listings",
                city, len(listings),
            )
            return listings

    except Exception as e:
        logger.error("WG-Gesucht search failed city=%s: %s", city, e, exc_info=True)
        return []
