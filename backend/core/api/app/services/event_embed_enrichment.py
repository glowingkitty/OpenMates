"""Server-side coordinates for event embeds before they are encrypted and saved.

Both event producers use this one function: app-skill results
(``EmbedService.create_embeds_from_skill_results``) call it right before
encoding a child event; assistant-authored cards (``authored_result_service``)
are published first without coordinates and call it afterwards in the
background, republishing the same card with coordinates. Coordinates are
therefore deterministic server data, never a model guess.

Geocoding reuses ``geo_utils.geocode_address`` (OpenStreetMap Nominatim search
API, https://nominatim.org/release-docs/latest/api/Search/, used under
https://operations.osmfoundation.org/policies/nominatim/: identified
User-Agent, at most 1 request/second, cached results). Only the public venue
name/address/city/country is sent. A miss or timeout leaves the event without
coordinates, which the renderers show as "no map".
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import OrderedDict
from typing import Any

from backend.shared.python_utils.geo_utils import geocode_address

logger = logging.getLogger(__name__)

EVENT_EMBED_TYPES = {"event", "event_result"}
GEOCODE_TIMEOUT_SECONDS = 10.0
_CACHE_MAX_ENTRIES = 512
_cache: "OrderedDict[tuple[str, str, str, str], tuple[float, float] | None]" = OrderedDict()


def valid_coordinates(lat: Any, lon: Any) -> tuple[float, float] | None:
    """Return a finite, in-range, non-null-island pair or None."""
    try:
        lat_value, lon_value = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat_value) and math.isfinite(lon_value)):
        return None
    if not (-90 <= lat_value <= 90 and -180 <= lon_value <= 180):
        return None
    if lat_value == 0 and lon_value == 0:
        return None
    return lat_value, lon_value


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _venue(content: dict[str, Any]) -> dict[str, Any] | None:
    """Return the mutable venue record, creating one from a string location."""
    venue = content.get("venue")
    if isinstance(venue, dict):
        return venue
    location = content.get("location")
    if isinstance(location, dict):
        return location
    if _text(location):
        content["venue"] = {"name": location.strip()}
        return content["venue"]
    return None


async def _venue_geocode(address: str, name: str, city: str, country: str) -> tuple[float, float] | None:
    """Most precise first: street address, then venue/campus name, then city centre."""
    for query in dict.fromkeys(q for q in (address, name) if q):
        coords = await geocode_address(
            query, city=city or None, country=country or None, allow_city_fallback=False,
        )
        if coords:
            return coords
    return await geocode_address(address or name or None, city=city or None, country=country or None)

async def _cached_geocode(address: str, name: str, city: str, country: str) -> tuple[float, float] | None:
    key = (address.lower(), name.lower(), city.lower(), country.lower())
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    try:
        coords = await asyncio.wait_for(
            _venue_geocode(address, name, city, country), timeout=GEOCODE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.info("Event geocoding timed out; event keeps no map")
        return None
    result = valid_coordinates(*coords) if coords else None
    _cache[key] = result
    if len(_cache) > _CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)
    return result

def discard_untrusted_event_coordinates(
    embed_type: str, content: dict[str, Any], *, keep_supplied: bool = False,
) -> bool:
    """Drop model-written venue coordinates; return whether a venue lookup is warranted.

    Assistant-authored cards are published right away without coordinates; a
    later ``enrich_event_coordinates(..., trust_supplied=False)`` adds them.
    ``keep_supplied`` keeps a valid pair that comes from user-supplied facts, so
    no lookup replaces it. Online events and events without a named place never
    get a lookup.
    """
    if embed_type not in EVENT_EMBED_TYPES or not isinstance(content, dict):
        return False
    venue = _venue(content)
    if venue is None or content.get("online") is True or venue.get("online") is True:
        return False
    if keep_supplied and valid_coordinates(venue.get("lat"), venue.get("lon")):
        return False
    venue.pop("lat", None)
    venue.pop("lon", None)
    return bool(_text(venue.get("address")) or _text(venue.get("name")) or _text(venue.get("city")))


async def enrich_event_coordinates(
    embed_type: str, content: dict[str, Any], log_prefix: str = "", *, trust_supplied: bool = True,
) -> dict[str, Any]:
    """Add venue lat/lon to an in-person event that has a place but no valid coordinates.

    Invalid supplied coordinates (0/0, NaN, out of range) are removed so no
    renderer can show a map for them. Online events are left unchanged.
    ``trust_supplied=False`` (assistant-authored cards) discards any model-written
    pair and geocodes the named venue instead, so a map is never a model guess.
    """
    if embed_type not in EVENT_EMBED_TYPES or not isinstance(content, dict):
        return content
    venue = _venue(content)
    if venue is None or content.get("online") is True or venue.get("online") is True:
        return content
    if trust_supplied and valid_coordinates(venue.get("lat"), venue.get("lon")):
        return content
    venue.pop("lat", None)
    venue.pop("lon", None)
    address, name = _text(venue.get("address")), _text(venue.get("name"))
    city, country = _text(venue.get("city")), _text(venue.get("country"))
    # Prefer the street address; a named venue (e.g. a campus) is the next most
    # precise query. The helper falls back to the city when neither resolves.
    if not (address or name or city):
        return content
    coords = await _cached_geocode(address, name, city, country)
    if coords:
        venue["lat"], venue["lon"] = coords
        logger.debug("%s Event venue geocoded server-side", log_prefix)
    return content
