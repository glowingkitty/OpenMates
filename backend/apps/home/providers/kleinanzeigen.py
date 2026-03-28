"""
Kleinanzeigen SSR HTML scraping provider for German housing search.

Searches Kleinanzeigen (formerly eBay Kleinanzeigen) for apartment/house
listings by scraping the server-side rendered HTML pages. Uses regex-based
parsing to extract listing data — no BeautifulSoup dependency required.

Data flow:
  1. Map city name to Kleinanzeigen location code (e.g. "berlin" -> "l3331")
  2. Map listing_type to category (e.g. "rent" -> "wohnungen-mieten" / "c203")
  3. GET the search results HTML page
  4. Parse listings from HTML using regex (data-adid, titles, prices)
  5. Normalize to standard listing schema

Provider: Kleinanzeigen (kleinanzeigen.de)
No API key required.
"""

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.kleinanzeigen.de"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SECONDS = 15

# Mapping from listing_type to (category_slug, category_code)
CATEGORY_MAP: Dict[str, tuple] = {
    "rent": ("wohnungen-mieten", "c203"),
    "buy": ("eigentumswohnungen", "c196"),
}

# Major German cities to Kleinanzeigen location codes.
# These are extracted from Kleinanzeigen's URL structure.
CITY_LOCATION_MAP: Dict[str, str] = {
    "berlin": "l3331",
    "munich": "l6411",
    "muenchen": "l6411",
    "munchen": "l6411",
    "hamburg": "l9409",
    "cologne": "l4267",
    "koeln": "l4267",
    "frankfurt": "l4790",
    "stuttgart": "l941",
    "dusseldorf": "l4152",
    "duesseldorf": "l4152",
    "dortmund": "l4225",
    "essen": "l4254",
    "leipzig": "l8819",
    "bremen": "l3440",
    "dresden": "l8457",
    "hannover": "l3680",
    "nuernberg": "l6355",
    "nuremberg": "l6355",
    "duisburg": "l4195",
    "bochum": "l4234",
    "wuppertal": "l4166",
    "bonn": "l4294",
    "muenster": "l4068",
    "karlsruhe": "l1181",
    "mannheim": "l1280",
    "augsburg": "l5862",
    "wiesbaden": "l4850",
    "freiburg": "l1405",
    "potsdam": "l3518",
    "mainz": "l7484",
    "kiel": "l10044",
    "rostock": "l8991",
}


def _get_location_code(city: str) -> Optional[str]:
    """
    Resolve a city name to a Kleinanzeigen location code.

    Args:
        city: City name (case-insensitive).

    Returns:
        Location code string (e.g. "l3331") or None if city not found.
    """
    normalized = city.strip().lower().replace(" ", "").replace("ü", "ue").replace("ö", "oe").replace("ä", "ae")
    return CITY_LOCATION_MAP.get(normalized)


def _parse_listings_from_html(html: str, listing_type: str, city: str) -> List[Dict[str, Any]]:
    """
    Parse listing data from Kleinanzeigen search results HTML using regex.

    Extracts listings from the ad-list HTML structure. Each listing item
    has a data-adid attribute and contains title, price, and address info.

    Args:
        html: Raw HTML string from Kleinanzeigen search page.
        listing_type: "rent" or "buy" — included in normalized output.
        city: City name for address field.

    Returns:
        List of normalized listing dicts.
    """
    listings: List[Dict[str, Any]] = []

    # Find all ad items with data-adid
    # Pattern: <article ... data-adid="NNNN" ...> ... </article>
    re.compile(
        r'data-adid="(\d+)".*?'
        r'<a[^>]*class="[^"]*ellipsis[^"]*"[^>]*>([^<]*)</a>.*?'
        r'(?:<p[^>]*class="[^"]*aditem-main--middle--price[^"]*"[^>]*>([^<]*)</p>)?',
        re.DOTALL,
    )

    # Alternative pattern for different HTML structure
    ad_block_pattern = re.compile(
        r'data-adid="(\d+)"(.*?)(?=data-adid="|$)',
        re.DOTALL,
    )

    blocks = ad_block_pattern.findall(html)

    for ad_id, block_html in blocks:
        # Extract title from link with ellipsis class
        title_match = re.search(
            r'<a[^>]*class="[^"]*ellipsis[^"]*"[^>]*>\s*(.*?)\s*</a>',
            block_html,
            re.DOTALL,
        )
        title = title_match.group(1).strip() if title_match else ""
        # Clean HTML entities from title
        title = title.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")

        if not title:
            continue

        # Extract price — the price element has multi-line whitespace around the value
        price_match = re.search(
            r'class="[^"]*aditem-main--middle--price[^"]*"[^>]*>\s*'
            r'([\d.,]+\s*€)',
            block_html,
            re.DOTALL,
        )
        price_text = price_match.group(1).strip() if price_match else ""
        price = _parse_price(price_text)

        if price is not None:
            if listing_type == "rent":
                price_label = f"{price:,.0f} EUR/month".replace(",", ".")
            else:
                price_label = f"{price:,.0f} EUR".replace(",", ".")
        elif price_text:
            price_label = price_text
        else:
            price_label = "Price on request"

        # Extract address/location
        address_match = re.search(
            r'class="[^"]*aditem-main--top--left[^"]*"[^>]*>\s*(.*?)\s*</div>',
            block_html,
            re.DOTALL,
        )
        address = ""
        if address_match:
            address = re.sub(r'<[^>]+>', '', address_match.group(1)).strip()
            address = re.sub(r'\s+', ' ', address)
        if not address:
            address = city.title()

        # Extract image URL
        image_match = re.search(
            r'<img[^>]*(?:data-)?src="(https://[^"]*\.(?:jpg|jpeg|png|webp)[^"]*)"',
            block_html,
            re.IGNORECASE,
        )
        image_url = image_match.group(1) if image_match else None

        # Extract size and rooms from description
        size_sqm = _extract_size(block_html)
        rooms = _extract_rooms(block_html)

        listings.append({
            "id": f"ka_{ad_id}",
            "title": title,
            "price": price,
            "price_label": price_label,
            "size_sqm": size_sqm,
            "rooms": rooms,
            "address": address,
            "image_url": image_url,
            "url": f"{BASE_URL}/s-anzeige/{ad_id}",
            "provider": "Kleinanzeigen",
            "listing_type": listing_type,
        })

    return listings


def _parse_price(text: str) -> Optional[float]:
    """
    Extract numeric price from a Kleinanzeigen price string.

    Handles formats like "850 EUR", "1.200 EUR", "VB", etc.

    Args:
        text: Raw price text from HTML.

    Returns:
        Price as float, or None if not parseable.
    """
    if not text:
        return None
    # Remove common non-numeric parts
    cleaned = text.replace("€", "").replace("EUR", "").replace("VB", "").strip()
    # Handle German number format: 1.200,50 -> 1200.50
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_size(html: str) -> Optional[float]:
    """Extract apartment size in m2 from listing HTML block."""
    size_match = re.search(r'(\d+(?:[.,]\d+)?)\s*m[²2]', html)
    if size_match:
        try:
            return float(size_match.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def _extract_rooms(html: str) -> Optional[float]:
    """Extract number of rooms from listing HTML block."""
    rooms_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:Zimmer|Zi\.?|rooms?)', html, re.IGNORECASE)
    if rooms_match:
        try:
            return float(rooms_match.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


async def search_listings(
    city: str,
    listing_type: str = "rent",
    max_results: int = 20,
) -> List[Dict[str, Any]]:
    """
    Search Kleinanzeigen for apartment/house listings in a German city.

    Args:
        city: City name (e.g. "Berlin", "Munich", "Hamburg").
        listing_type: "rent" or "buy" (default "rent").
        max_results: Maximum number of listings to return (default 20).

    Returns:
        List of normalized listing dicts with standard schema fields.
        Returns empty list on error or if city is not supported.
    """
    location_code = _get_location_code(city)
    if not location_code:
        logger.warning("Kleinanzeigen: city %r not in location map, skipping", city)
        return []

    category_slug, category_code = CATEGORY_MAP.get(listing_type, ("wohnungen-mieten", "c203"))
    city_slug = city.strip().lower().replace(" ", "-")

    # Build search URL: /s-{category}/{city}/{code}{location}
    search_url = f"{BASE_URL}/s-{category_slug}/{city_slug}/{category_code}{location_code}"

    logger.info(
        "Kleinanzeigen search city=%s type=%s url=%s",
        city, listing_type, search_url,
    )

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(
                search_url,
                headers={
                    "User-Agent": BROWSER_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                },
                follow_redirects=True,
            )
            response.raise_for_status()
            html = response.text
    except httpx.HTTPStatusError as e:
        logger.error(
            "Kleinanzeigen HTTP error status=%d city=%s: %s",
            e.response.status_code, city, e,
        )
        return []
    except Exception as e:
        logger.error("Kleinanzeigen request failed city=%s: %s", city, e, exc_info=True)
        return []

    listings = _parse_listings_from_html(html, listing_type, city)

    logger.info(
        "Kleinanzeigen search city=%s type=%s -> %d listings",
        city, listing_type, len(listings),
    )
    return listings[:max_results]
