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
import json
from typing import Any, Dict, List, Optional

import httpx

from backend.apps.home.providers.results import ProviderListings
from backend.shared.providers.housing.details import (
    MAX_CANDIDATES, amenity, defaults, enrich, location, merge_gallery,
    number, photos, response_text, text,
)

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


def _normalize_mobile_listing(item: Dict[str, Any], listing_type: str) -> Optional[Dict[str, Any]]:
    """Normalize a listing from the mobile API response format.

    The mobile API returns items with: id, title, attributes (array of {value}),
    address.line, titlePicture.full/preview.
    """
    listing_id = str(item.get("id") or "")
    title = item.get("title", "")
    if not listing_id:
        return None

    # Price, size, rooms from attributes array (0=price, 1=size, 2=rooms)
    attributes = item.get("attributes", [])
    price_str = attributes[0].get("value", "") if len(attributes) > 0 else ""
    size_str = attributes[1].get("value", "") if len(attributes) > 1 else ""
    rooms_str = attributes[2].get("value", "") if len(attributes) > 2 else ""

    # Parse numeric price from string like "1.249 €" or "250.000 €"
    price: Optional[float] = None
    if price_str:
        clean = price_str.replace(".", "").replace("€", "").replace(",", ".").strip()
        try:
            price = float(clean)
        except ValueError:
            pass

    price_label = price_str.strip() if price_str else "Price on request"

    # Parse size from string like "52,4 m²"
    size_sqm: Optional[float] = None
    if size_str:
        clean = size_str.replace("m²", "").replace(",", ".").strip()
        try:
            size_sqm = float(clean)
        except ValueError:
            pass

    # Rooms from attributes[2], e.g. "3 Zi." or "1,5 Zi."
    rooms: Optional[float] = None
    if rooms_str:
        clean_rooms = rooms_str.replace("Zi.", "").replace("Zi", "").replace(",", ".").strip()
        try:
            rooms = float(clean_rooms)
        except ValueError:
            pass

    # Address
    address_obj = item.get("address", {})
    address = address_obj.get("line", "") if isinstance(address_obj, dict) else ""

    # Image
    title_pic = item.get("titlePicture", {})
    image_url = None
    if isinstance(title_pic, dict):
        image_url = title_pic.get("full") or title_pic.get("preview")

    listing = defaults({
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
    })
    _merge_detail(listing, item, detail=False)
    return listing


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
    if not listing_id:
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

    listing = defaults({
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
    })
    _merge_detail(listing, real_estate, detail=False)
    return listing


def _merge_detail(listing: Dict[str, Any], data: Dict[str, Any], detail: bool = True) -> None:
    """Read mobile expose sections plus the documented realEstate response shape."""
    if not isinstance(data, dict):
        raise ValueError("Unrecognized ImmoScout24 expose payload")
    real = data.get("realEstate") or data.get("expose", {}).get("realEstate") or data.get("expose.expose", {}).get("realEstate") or data
    address = real.get("address", {})
    if isinstance(address, dict):
        location(listing, address)
    fields = {"baseRent": "cold_rent_eur", "totalRent": "warm_rent_eur", "additionalCosts": "utilities_eur", "serviceCharge": "utilities_eur", "heatingCosts": "heating_costs_eur", "deposit": "deposit", "securityDeposit": "deposit", "livingSpace": "size_sqm", "numberOfRooms": "rooms"}
    for source, target in fields.items():
        value = number(real.get(source))
        if value is not None:
            listing[target] = value
    for source, target in {"floor": "floor", "freeFrom": "available_from", "availableFrom": "available_from", "availableTo": "available_to"}.items():
        if real.get(source) not in (None, ""):
            listing[target] = real[source]
    descriptions = [text(real[key]) for key in ("descriptionNote", "furnishingNote", "locationNote", "otherNote", "description") if real.get(key)]
    if descriptions:
        listing["description"] = "\n\n".join(descriptions)
    for source, target in {"balcony": "balcony", "furnished": "furnished", "lift": "elevator", "garden": "garden", "terrace": "terrace", "parking": "parking", "petsAllowed": "pets_allowed"}.items():
        if source in real:
            amenity(listing, target, real[source])
    # Mobile API organizes labelled facts and text into expose sections.
    labels = {"Kaltmiete": "cold_rent_eur", "Warmmiete": "warm_rent_eur", "Gesamtmiete": "warm_rent_eur", "Nebenkosten": "utilities_eur", "Heizkosten": "heating_costs_eur", "Kaution": "deposit", "Etage": "floor", "Bezugsfrei ab": "available_from", "Wohnfläche": "size_sqm", "Zimmer": "rooms"}
    amenity_labels = {"Balkon": "balcony", "Möbliert": "furnished", "Aufzug": "elevator", "Garten": "garden", "Terrasse": "terrace", "Haustiere": "pets_allowed"}
    gallery: list[str] = []
    gallery_seen = False
    def sections(value: Any) -> None:
        nonlocal gallery_seen
        if isinstance(value, list):
            for child in value:
                sections(child)
        elif isinstance(value, dict):
            label = value.get("label") or value.get("name") or value.get("title")
            supplied = value.get("value")
            if label in labels and supplied is not None:
                target = labels[label]
                parsed = number(supplied) if target.endswith("_eur") or target in {"deposit", "size_sqm", "rooms"} else supplied
                if parsed is not None:
                    listing[target] = parsed
            if label in amenity_labels and supplied is not None:
                amenity(listing, amenity_labels[label], supplied)
            if label in {"Objektbeschreibung", "Ausstattung", "Lage", "Sonstiges"} and isinstance(value.get("text"), str):
                listing["description"] = "\n\n".join(filter(None, [listing.get("description"), text(value["text"])]))
            for key, child in value.items():
                if key in {"pictures", "images", "gallery", "attachments"}:
                    gallery_seen = True
                    gallery.extend(photos(child))
                elif key in {"sections", "items", "attributes", "data", "content"}:
                    sections(child)
    sections(real)
    gallery = photos(real.get("titlePicture")) + gallery
    merge_gallery(listing, gallery, complete=detail and gallery_seen)
    for key, value in listing["amenities"].items():
        listing[key] = value
    if listing.get("listing_type") != "buy":
        if listing.get("warm_rent_eur") is not None:
            listing.update(price=listing["warm_rent_eur"], price_type="warm")
        elif listing.get("cold_rent_eur") is not None:
            listing.update(price=listing["cold_rent_eur"], price_type="cold")
    if listing.get("price") is not None:
        suffix = "EUR" if listing.get("listing_type") == "buy" else "EUR/month"
        listing["price_label"] = f"{listing['price']:,.0f} {suffix}".replace(",", ".")
    if detail:
        if not gallery_seen and not descriptions and not any(key in real for key in ("sections", "baseRent", "totalRent", "address", "attributes")):
            raise ValueError("Unrecognized ImmoScout24 expose payload")
        listing["detail_status"] = "available"


async def search_listings(
    city: str,
    listing_type: str = "rent",
    max_results: int = 20,
    property_type: str = "apartment",
    sort: str = "price_asc",
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
    if property_type == "shared_room":
        raise ValueError("ImmoScout24 shared-room search is not supported")
    if max_results <= 0:
        return []
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
        raise RuntimeError(f"ImmoScout24 returned HTTP {e.response.status_code}") from e
    except Exception as e:
        logger.error("ImmoScout24 API request failed city=%s: %s", city, e, exc_info=True)
        raise RuntimeError("ImmoScout24 search request failed") from e

    # Parse response structure — the path varies by API version
    # Mobile API response: resultListItems array with type=EXPOSE_RESULT items
    raw_items = data.get("resultListItems", [])
    if not raw_items:
        logger.warning("ImmoScout24: no resultListItems in response for city=%s", city)
        return []

    listings: List[Dict[str, Any]] = []
    for item_wrapper in raw_items:
        if item_wrapper.get("type") != "EXPOSE_RESULT":
            continue
        item = item_wrapper.get("item", {})
        listing = _normalize_mobile_listing(item, listing_type)
        if listing:
            listings.append(listing)
            if len(listings) >= min(max(0, max_results), MAX_CANDIDATES):
                break

    logger.info(
        "ImmoScout24 search city=%s type=%s -> %d listings (raw=%d)",
        city, listing_type, len(listings), len(raw_items),
    )
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        async def fetch_detail(listing: Dict[str, Any]) -> None:
            raw = await response_text(client, f"{MOBILE_API_BASE}/expose/{listing['id'][5:]}", {"User-Agent": MOBILE_USER_AGENT, "Accept": "application/json"})
            _merge_detail(listing, json.loads(raw), detail=True)
        warnings = await enrich(listings, fetch_detail)
    return ProviderListings(listings, warnings)
