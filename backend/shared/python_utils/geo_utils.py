# backend/shared/python_utils/geo_utils.py
#
# Shared geographic utilities: city coordinate lookup and address geocoding.
#
# Used by event providers (Meetup, Luma) to attach lat/lon to venue data so
# the frontend can render an interactive map in EventEmbedFullscreen.
#
# Geocoding strategy (cheapest-first):
#   1. CITY_COORDS local table — zero network cost, covers ~60 major cities.
#   2. Nominatim (OpenStreetMap) free geocoding API — for full street addresses
#      that include a city we don't have in CITY_COORDS.
#   3. Returns None on failure — callers must handle gracefully (no map shown).
#
# See docs/architecture/embeds.md

import logging
import urllib.parse
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local city lookup table
# Format: normalised_city_key → (lat, lon, display_name, ISO 3166-1 alpha-2)
# ---------------------------------------------------------------------------

CITY_COORDS: dict[str, Tuple[float, float, str, str]] = {
    "berlin": (52.52, 13.405, "Berlin", "de"),
    "munich": (48.137, 11.576, "Munich", "de"),
    "hamburg": (53.551, 9.993, "Hamburg", "de"),
    "cologne": (50.938, 6.957, "Cologne", "de"),
    "frankfurt": (50.110, 8.682, "Frankfurt", "de"),
    "stuttgart": (48.775, 9.182, "Stuttgart", "de"),
    "dusseldorf": (51.227, 6.773, "Düsseldorf", "de"),
    "london": (51.507, -0.128, "London", "gb"),
    "manchester": (53.480, -2.242, "Manchester", "gb"),
    "birmingham": (52.480, -1.902, "Birmingham", "gb"),
    "paris": (48.857, 2.352, "Paris", "fr"),
    "lyon": (45.764, 4.836, "Lyon", "fr"),
    "amsterdam": (52.374, 4.898, "Amsterdam", "nl"),
    "rotterdam": (51.924, 4.477, "Rotterdam", "nl"),
    "zurich": (47.376, 8.548, "Zurich", "ch"),
    "vienna": (48.208, 16.373, "Vienna", "at"),
    "brussels": (50.851, 4.352, "Brussels", "be"),
    "stockholm": (59.333, 18.065, "Stockholm", "se"),
    "oslo": (59.913, 10.752, "Oslo", "no"),
    "copenhagen": (55.676, 12.568, "Copenhagen", "dk"),
    "helsinki": (60.169, 24.938, "Helsinki", "fi"),
    "madrid": (40.416, -3.703, "Madrid", "es"),
    "barcelona": (41.386, 2.170, "Barcelona", "es"),
    "rome": (41.902, 12.496, "Rome", "it"),
    "milan": (45.464, 9.189, "Milan", "it"),
    "lisbon": (38.716, -9.139, "Lisbon", "pt"),
    "warsaw": (52.229, 21.012, "Warsaw", "pl"),
    "prague": (50.087, 14.421, "Prague", "cz"),
    "budapest": (47.498, 19.040, "Budapest", "hu"),
    "new york": (40.713, -74.006, "New York", "us"),
    "new york city": (40.713, -74.006, "New York", "us"),
    "nyc": (40.713, -74.006, "New York", "us"),
    "los angeles": (34.052, -118.244, "Los Angeles", "us"),
    "chicago": (41.878, -87.630, "Chicago", "us"),
    "san francisco": (37.775, -122.418, "San Francisco", "us"),
    "sf": (37.775, -122.418, "San Francisco", "us"),
    "seattle": (47.606, -122.332, "Seattle", "us"),
    "boston": (42.360, -71.059, "Boston", "us"),
    "austin": (30.267, -97.743, "Austin", "us"),
    "toronto": (43.651, -79.347, "Toronto", "ca"),
    "vancouver": (49.283, -123.121, "Vancouver", "ca"),
    "montreal": (45.508, -73.588, "Montreal", "ca"),
    "sydney": (-33.868, 151.209, "Sydney", "au"),
    "melbourne": (-37.814, 144.963, "Melbourne", "au"),
    "tokyo": (35.689, 139.691, "Tokyo", "jp"),
    "osaka": (34.694, 135.502, "Osaka", "jp"),
    "seoul": (37.566, 126.978, "Seoul", "kr"),
    "beijing": (39.906, 116.391, "Beijing", "cn"),
    "shanghai": (31.228, 121.474, "Shanghai", "cn"),
    "singapore": (1.352, 103.820, "Singapore", "sg"),
    "bangalore": (12.972, 77.594, "Bangalore", "in"),
    "mumbai": (19.076, 72.877, "Mumbai", "in"),
    "delhi": (28.614, 77.209, "Delhi", "in"),
    "dubai": (25.204, 55.270, "Dubai", "ae"),
    "cape town": (-33.925, 18.424, "Cape Town", "za"),
    "sao paulo": (-23.548, -46.637, "São Paulo", "br"),
    "buenos aires": (-34.608, -58.437, "Buenos Aires", "ar"),
    "mexico city": (19.432, -99.133, "Mexico City", "mx"),
    "tel aviv": (32.080, 34.780, "Tel Aviv", "il"),
    "tel-aviv": (32.080, 34.780, "Tel Aviv", "il"),
    "nairobi": (-1.286, 36.820, "Nairobi", "ke"),
    "lagos": (6.452, 3.396, "Lagos", "ng"),
    "waterloo": (43.466, -80.520, "Waterloo", "ca"),
    "philadelphia": (39.952, -75.165, "Philadelphia", "us"),
    "washington": (38.907, -77.036, "Washington DC", "us"),
    "washington dc": (38.907, -77.036, "Washington DC", "us"),
    "dc": (38.907, -77.036, "Washington DC", "us"),
    "minneapolis": (44.977, -93.265, "Minneapolis", "us"),
    "new delhi": (28.614, 77.209, "New Delhi", "in"),
    "bengaluru": (12.972, 77.594, "Bengaluru", "in"),
    "lausanne": (46.519, 6.633, "Lausanne", "ch"),
    "geneva": (46.204, 6.143, "Geneva", "ch"),
    "istanbul": (41.013, 28.978, "Istanbul", "tr"),
    "dublin": (53.333, -6.249, "Dublin", "ie"),
}

# Nominatim user-agent — must identify the app per OSM usage policy.
_NOMINATIM_UA = "OpenMates/1.0 (https://openmates.org)"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_HTTP_TIMEOUT = 8.0


def lookup_city(city: str) -> Optional[Tuple[float, float]]:
    """
    Return (lat, lon) for a city name from the local table, or None.
    Normalises by lowercasing and stripping whitespace.
    """
    key = city.lower().strip()
    entry = CITY_COORDS.get(key)
    if entry:
        return entry[0], entry[1]
    return None


async def geocode_address(
    address: Optional[str],
    city: Optional[str] = None,
    country: Optional[str] = None,
) -> Optional[Tuple[float, float]]:
    """
    Resolve a street address (or city) to (lat, lon).

    Strategy:
    1. If city is provided, try the local CITY_COORDS table first (zero cost).
    2. If address is provided, query Nominatim with the full address string.
    3. If that fails, fall back to querying Nominatim with just the city name.
    4. Returns None on any failure — callers should degrade gracefully.

    This function is I/O-bound so it must be awaited. Never call it in a
    tight loop — Nominatim enforces a 1 req/s rate limit per IP.
    """
    # Step 1: fast local city lookup
    if city:
        coords = lookup_city(city)
        if coords:
            logger.debug("geo_utils: local city hit for %r → %s", city, coords)
            return coords

    # Step 2: full address via Nominatim
    if address:
        query_parts = [address]
        if city:
            query_parts.append(city)
        if country:
            query_parts.append(country)
        query = ", ".join(p for p in query_parts if p)
        coords = await _nominatim_query(query)
        if coords:
            return coords

    # Step 3: city-only Nominatim fallback (if city lookup above failed)
    if city:
        city_query = city
        if country:
            city_query += f", {country}"
        coords = await _nominatim_query(city_query)
        if coords:
            return coords

    logger.debug(
        "geo_utils: could not resolve coordinates for address=%r city=%r",
        address,
        city,
    )
    return None


async def _nominatim_query(query: str) -> Optional[Tuple[float, float]]:
    """
    Query Nominatim (OpenStreetMap) geocoding API.
    Returns (lat, lon) of the first result, or None on failure.
    """
    params = {
        "q": query,
        "format": "json",
        "limit": "1",
    }
    url = f"{_NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": _NOMINATIM_UA}

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            results = resp.json()
            if results:
                lat = float(results[0]["lat"])
                lon = float(results[0]["lon"])
                logger.debug(
                    "geo_utils: Nominatim resolved %r → (%.5f, %.5f)", query, lat, lon
                )
                return lat, lon
    except Exception as exc:
        logger.warning("geo_utils: Nominatim query failed for %r: %s", query, exc)

    return None
