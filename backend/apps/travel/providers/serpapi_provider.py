"""
SerpAPI Google Flights provider for the travel app.

Implements BaseTransportProvider to search for flight connections via
the SerpAPI Google Flights engine. This provides access to Google's
comprehensive flight search with real-time pricing, booking links to
airline websites and OTAs, and rich metadata (CO2, legroom, delays).

Key features:
- Google Flights data: comprehensive airline coverage and pricing
- Booking links: direct URLs to airlines and OTAs (via booking_token)
- Rich metadata: CO2 emissions, legroom, delay warnings, price insights
- Multi-step search: one-way, round-trip (departure_token), multi-city
- City name to IATA resolution via built-in fallback mapping

API docs: https://serpapi.com/google-flights-api
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import httpx

from airports import airport_data as _airport_db

from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
    LayoverResult,
    LegResult,
    SegmentResult,
)

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERPAPI_BASE = "https://serpapi.com/search"

# Regex to detect if a string is already an IATA code (2-4 uppercase letters)
_IATA_CODE_RE = re.compile(r"^[A-Z]{2,4}$")

# SerpAPI travel_class mapping
_TRAVEL_CLASS_MAP: Dict[str, str] = {
    "economy": "1",
    "premium_economy": "2",
    "business": "3",
    "first": "4",
}



# Map IATA airport codes to Google Flights gl (geolocation) country codes.
# Used to set the gl parameter so SerpAPI returns results matching the
# departure country (same as visiting google.com/flights from that country).
_IATA_TO_GL: Dict[str, str] = {
    # Germany
    "BER": "de", "MUC": "de", "FRA": "de", "HAM": "de", "DUS": "de",
    "CGN": "de", "STR": "de", "NUE": "de", "HAJ": "de", "LEJ": "de",
    "DRS": "de", "DTM": "de", "PAD": "de", "FMO": "de", "SCN": "de",
    # UK
    "LHR": "uk", "LGW": "uk", "STN": "uk", "LTN": "uk", "LCY": "uk",
    "MAN": "uk", "EDI": "uk", "BHX": "uk", "GLA": "uk", "BRS": "uk",
    # France
    "CDG": "fr", "ORY": "fr", "NCE": "fr", "LYS": "fr", "MRS": "fr",
    "TLS": "fr", "BOD": "fr",
    # Netherlands
    "AMS": "nl",
    # Belgium
    "BRU": "be",
    # Switzerland
    "ZRH": "ch", "GVA": "ch",
    # Austria
    "VIE": "at",
    # Italy
    "FCO": "it", "MXP": "it", "VCE": "it", "FLR": "it", "NAP": "it",
    "BLQ": "it", "TRN": "it",
    # Spain
    "MAD": "es", "BCN": "es", "AGP": "es", "SVQ": "es", "VLC": "es",
    "PMI": "es", "IBZ": "es", "TFS": "es",
    # Portugal
    "LIS": "pt", "OPO": "pt",
    # Ireland
    "DUB": "ie",
    # Scandinavia
    "CPH": "dk", "ARN": "se", "OSL": "no", "HEL": "fi",
    # Eastern Europe
    "WAW": "pl", "KRK": "pl", "PRG": "cz", "BUD": "hu",
    "OTP": "ro", "SOF": "bg", "BEG": "rs", "ZAG": "hr",
    # Baltics
    "RIX": "lv", "VNO": "lt", "TLL": "ee",
    # Greece / Turkey
    "ATH": "gr", "SKG": "gr", "IST": "tr", "ESB": "tr", "AYT": "tr",
    "ADB": "tr",
    # Iceland
    "KEF": "is",
    # US
    "JFK": "us", "EWR": "us", "LGA": "us", "LAX": "us", "SFO": "us",
    "ORD": "us", "MIA": "us", "DFW": "us", "IAH": "us", "ATL": "us",
    "BOS": "us", "IAD": "us", "SEA": "us", "DEN": "us", "LAS": "us",
    "MCO": "us", "PHX": "us", "PHL": "us", "SAN": "us", "MSP": "us",
    "DTW": "us", "CLT": "us", "TPA": "us", "PDX": "us",
    # Canada
    "YYZ": "ca", "YUL": "ca", "YVR": "ca", "YYC": "ca", "YOW": "ca",
    # Mexico
    "MEX": "mx", "CUN": "mx",
    # Asia
    "NRT": "jp", "HND": "jp", "KIX": "jp", "ICN": "kr",
    "PEK": "cn", "PVG": "cn", "HKG": "hk", "TPE": "tw",
    "SIN": "sg", "BKK": "th", "KUL": "my", "CGK": "id",
    "DEL": "in", "BOM": "in", "BLR": "in", "MAA": "in",
    "DXB": "ae", "AUH": "ae", "DOH": "qa", "RUH": "sa", "JED": "sa",
    "TLV": "il", "MNL": "ph", "HAN": "vn", "SGN": "vn",
    # Oceania
    "SYD": "au", "MEL": "au", "BNE": "au", "PER": "au", "AKL": "nz",
    # Africa
    "CAI": "eg", "JNB": "za", "CPT": "za", "NBO": "ke",
    "LOS": "ng", "CMN": "ma", "RAK": "ma",
    # South America
    "GRU": "br", "GIG": "br", "EZE": "ar", "BOG": "co", "LIM": "pe",
    "SCL": "cl",
}


def _get_airport_coords(iata_code: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Look up airport coordinates by IATA code using the airports-py package.

    Returns (latitude, longitude) as floats, or (None, None) if unknown.
    The airports-py package provides a comprehensive offline database of
    ~28 000 airports with coordinates.
    """
    if not iata_code or len(iata_code) != 3:
        return (None, None)
    try:
        results = _airport_db.get_airport_by_iata(iata_code)
        if results and len(results) > 0:
            entry = results[0]
            lat = entry.get("latitude")
            lng = entry.get("longitude")
            if lat is not None and lng is not None:
                return (float(lat), float(lng))
    except (ValueError, KeyError, TypeError) as e:
        logger.debug(f"Could not look up coordinates for IATA '{iata_code}': {e}")
    return (None, None)


def _get_gl_from_iata(iata_code: str) -> str:
    """
    Derive the Google Flights 'gl' (geolocation) parameter from an IATA
    airport code. Falls back to 'us' if unknown.

    This ensures SerpAPI returns results matching what a user would see
    when searching from that country on google.com/flights.
    """
    return _IATA_TO_GL.get(iata_code, "us")


# ---------------------------------------------------------------------------
# Built-in city name -> IATA fallback mapping
# Keys are lowercase city names; values are primary airport IATA codes.
# ---------------------------------------------------------------------------
_CITY_IATA_FALLBACK: Dict[str, str] = {
    # Europe
    "london": "LHR", "london heathrow": "LHR", "london gatwick": "LGW",
    "london stansted": "STN", "london luton": "LTN", "london city": "LCY",
    "paris": "CDG", "paris charles de gaulle": "CDG", "paris orly": "ORY",
    "berlin": "BER", "munich": "MUC", "frankfurt": "FRA", "hamburg": "HAM",
    "düsseldorf": "DUS", "dusseldorf": "DUS", "cologne": "CGN", "köln": "CGN",
    "stuttgart": "STR", "nuremberg": "NUE", "nürnberg": "NUE",
    "hannover": "HAJ", "hanover": "HAJ", "leipzig": "LEJ", "dresden": "DRS",
    "amsterdam": "AMS", "brussels": "BRU", "zurich": "ZRH", "zürich": "ZRH",
    "geneva": "GVA", "genf": "GVA", "vienna": "VIE", "wien": "VIE",
    "rome": "FCO", "milan": "MXP", "milano": "MXP", "venice": "VCE",
    "florence": "FLR", "naples": "NAP", "bologna": "BLQ", "turin": "TRN",
    "madrid": "MAD", "barcelona": "BCN", "lisbon": "LIS", "porto": "OPO",
    "malaga": "AGP", "seville": "SVQ", "valencia": "VLC", "palma": "PMI",
    "palma de mallorca": "PMI", "ibiza": "IBZ", "tenerife": "TFS",
    "dublin": "DUB", "edinburgh": "EDI", "manchester": "MAN",
    "birmingham": "BHX", "glasgow": "GLA", "bristol": "BRS",
    "copenhagen": "CPH", "stockholm": "ARN", "oslo": "OSL", "helsinki": "HEL",
    "warsaw": "WAW", "krakow": "KRK", "prague": "PRG", "budapest": "BUD",
    "bucharest": "OTP", "sofia": "SOF", "belgrade": "BEG", "zagreb": "ZAG",
    "athens": "ATH", "thessaloniki": "SKG", "istanbul": "IST",
    "ankara": "ESB", "antalya": "AYT", "izmir": "ADB",
    "moscow": "SVO", "saint petersburg": "LED", "st petersburg": "LED",
    "reykjavik": "KEF", "riga": "RIX", "vilnius": "VNO", "tallinn": "TLL",
    "nice": "NCE", "lyon": "LYS", "marseille": "MRS", "toulouse": "TLS",
    "bordeaux": "BOD",
    # North America
    "new york": "JFK", "new york city": "JFK", "nyc": "JFK",
    "newark": "EWR", "laguardia": "LGA",
    "los angeles": "LAX", "la": "LAX",
    "san francisco": "SFO", "chicago": "ORD", "miami": "MIA",
    "dallas": "DFW", "houston": "IAH", "atlanta": "ATL",
    "boston": "BOS", "washington": "IAD", "washington dc": "IAD",
    "seattle": "SEA", "denver": "DEN", "las vegas": "LAS",
    "orlando": "MCO", "phoenix": "PHX", "philadelphia": "PHL",
    "san diego": "SAN", "minneapolis": "MSP", "detroit": "DTW",
    "charlotte": "CLT", "tampa": "TPA", "portland": "PDX",
    "toronto": "YYZ", "montreal": "YUL", "vancouver": "YVR",
    "calgary": "YYC", "ottawa": "YOW",
    "mexico city": "MEX", "cancun": "CUN",
    # Asia
    "tokyo": "NRT", "tokyo narita": "NRT", "tokyo haneda": "HND",
    "osaka": "KIX", "seoul": "ICN", "incheon": "ICN",
    "beijing": "PEK", "shanghai": "PVG", "hong kong": "HKG",
    "taipei": "TPE", "singapore": "SIN", "bangkok": "BKK",
    "kuala lumpur": "KUL", "jakarta": "CGK",
    "delhi": "DEL", "new delhi": "DEL", "mumbai": "BOM", "bangalore": "BLR",
    "chennai": "MAA", "kolkata": "CCU", "hyderabad": "HYD",
    "dubai": "DXB", "abu dhabi": "AUH", "doha": "DOH", "riyadh": "RUH",
    "jeddah": "JED", "tel aviv": "TLV", "amman": "AMM", "beirut": "BEY",
    "manila": "MNL", "hanoi": "HAN", "ho chi minh city": "SGN",
    "saigon": "SGN",
    # Oceania
    "sydney": "SYD", "melbourne": "MEL", "brisbane": "BNE",
    "perth": "PER", "auckland": "AKL",
    # Africa
    "cairo": "CAI", "johannesburg": "JNB", "cape town": "CPT",
    "nairobi": "NBO", "lagos": "LOS", "casablanca": "CMN",
    "marrakech": "RAK", "tunis": "TUN", "accra": "ACC",
    # South America
    "sao paulo": "GRU", "são paulo": "GRU", "rio de janeiro": "GIG",
    "buenos aires": "EZE", "bogota": "BOG", "lima": "LIM",
    "santiago": "SCL", "medellin": "MDE", "quito": "UIO",
    "caracas": "CCS", "montevideo": "MVD",
}


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

# Vault path for the SerpAPI key (follows the standard provider path convention)
SERPAPI_VAULT_PATH = "kv/data/providers/serpapi"
SERPAPI_VAULT_KEY = "api_key"

# Module-level cache so we only fetch from Vault once per process
_serpapi_api_key_cache: Optional[str] = None


async def _get_serpapi_key_async(
    secrets_manager: Optional["SecretsManager"] = None,
) -> Optional[str]:
    """
    Retrieve the SerpAPI key, preferring Vault (via SecretsManager) over env vars.

    Falls back to the SECRET__SERPAPI__API_KEY environment variable only if
    SecretsManager is not provided or Vault lookup fails. Caches the result
    in-process so subsequent calls are instant.

    Returns:
        The API key string if found, None otherwise.
    """
    global _serpapi_api_key_cache

    # Return cached key if available
    if _serpapi_api_key_cache:
        return _serpapi_api_key_cache

    # 1. Try Vault via SecretsManager (preferred path)
    if secrets_manager:
        try:
            key = await secrets_manager.get_secret(
                secret_path=SERPAPI_VAULT_PATH,
                secret_key=SERPAPI_VAULT_KEY,
            )
            if key and key.strip():
                _serpapi_api_key_cache = key.strip()
                logger.info("Successfully retrieved SerpAPI key from Vault")
                return _serpapi_api_key_cache
            else:
                logger.warning(
                    f"SerpAPI key not found in Vault at path '{SERPAPI_VAULT_PATH}' "
                    f"with key '{SERPAPI_VAULT_KEY}'. Falling back to env var."
                )
        except Exception as e:
            logger.warning(
                f"Failed to retrieve SerpAPI key from Vault: {e}. "
                "Falling back to env var."
            )

    # 2. Fallback to environment variable
    env_key = os.getenv("SECRET__SERPAPI__API_KEY")
    if env_key and env_key.strip() and env_key.strip() != "IMPORTED_TO_VAULT":
        _serpapi_api_key_cache = env_key.strip()
        logger.debug("Retrieved SerpAPI key from environment variable")
        return _serpapi_api_key_cache

    logger.error(
        "SerpAPI key not found in Vault or environment variables. "
        "Ensure the key is stored in Vault at 'kv/data/providers/serpapi' "
        "with key 'api_key', or set SECRET__SERPAPI__API_KEY in .env. "
        "Get a key from: https://serpapi.com/manage-api-key"
    )
    return None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _resolve_iata_code(location: str) -> Optional[str]:
    """
    Resolve a city/airport name to an IATA code using the built-in
    fallback mapping.

    If the input already looks like an IATA code (2-4 uppercase letters),
    it is returned as-is.

    Args:
        location: City or airport name (e.g., 'Munich', 'London Heathrow')
                  or IATA code (e.g., 'MUC').

    Returns:
        IATA code (e.g., 'MUC') or None if not found.
    """
    stripped = location.strip()

    # Short-circuit if already an IATA code
    if _IATA_CODE_RE.match(stripped):
        return stripped

    cache_key = stripped.lower()
    fallback = _CITY_IATA_FALLBACK.get(cache_key)
    if fallback:
        logger.debug(f"Resolved '{location}' -> IATA '{fallback}' (fallback mapping)")
        return fallback

    logger.warning(f"Could not resolve '{location}' to IATA code")
    return None


def _format_duration_minutes(total_minutes: int) -> str:
    """Convert total minutes to human-readable '2h 30m' format."""
    if total_minutes <= 0:
        return "N/A"
    hours = total_minutes // 60
    mins = total_minutes % 60
    if hours and mins:
        return f"{hours}h {mins}m"
    elif hours:
        return f"{hours}h"
    else:
        return f"{mins}m"


def _post_to_get_url(base_url: str, post_data: str) -> str:
    """
    Convert a SerpAPI POST-based booking URL to a clickable GET URL.

    SerpAPI booking_request objects contain a URL (e.g.,
    'https://www.google.com/travel/clk/f') and POST data
    (e.g., 'u=ADow...'). Per SerpAPI docs, we can convert
    from POST to GET by appending the post_data key-value
    pairs as query parameters.

    Args:
        base_url: The booking URL from SerpAPI (e.g., Google redirect URL).
        post_data: The URL-encoded POST body (e.g., 'u=value&key2=value2').

    Returns:
        A clickable GET URL with post_data appended as query params.
    """
    if not base_url:
        return ""
    if not post_data:
        return base_url

    # The post_data is already URL-encoded key=value pairs joined by &
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{post_data}"


def _extract_airport_name(airport_dict: dict) -> str:
    """
    Build a display string from a SerpAPI airport object.
    e.g. {'name': 'Munich Airport', 'id': 'MUC'} -> 'Munich Airport (MUC)'
    """
    name = airport_dict.get("name", "")
    code = airport_dict.get("id", "")
    if name and code:
        return f"{name} ({code})"
    return code or name or ""


# ---------------------------------------------------------------------------
# SerpApiProvider
# ---------------------------------------------------------------------------

class SerpApiProvider(BaseTransportProvider):
    """
    Flight search provider using the SerpAPI Google Flights engine.

    Resolves city names to IATA codes via a built-in fallback mapping,
    then searches for flights using the Google Flights API through SerpAPI.
    Returns unified ConnectionResult objects with booking URLs where available.

    SerpAPI flow for different trip types:
    - One-way: Single search (type=2), 1 API credit
    - Round-trip: Search outbound (type=1) -> no departure_token needed for
      basic results. Each search returns full round-trip pricing.
    - Multi-city: Search with multi_city_json (type=3), 1 API credit per leg

    Args:
        secrets_manager: Optional SecretsManager instance for loading the
            SerpAPI key from Vault. If not provided, falls back to env vars.
    """

    def __init__(self, secrets_manager: Optional["SecretsManager"] = None) -> None:
        self._secrets_manager = secrets_manager

    def supports_transport_method(self, method: str) -> bool:
        return method == "airplane"

    # ------------------------------------------------------------------
    # Flight search
    # ------------------------------------------------------------------

    async def search_connections(
        self,
        legs: List[dict],
        passengers: int,
        travel_class: str,
        max_results: int,
        non_stop_only: bool,
        currency: str,
    ) -> List[ConnectionResult]:
        """
        Search for flight connections via the SerpAPI Google Flights engine.

        For one-way and round-trip searches, uses the standard departure_id /
        arrival_id parameters. For multi-city, uses multi_city_json.
        Returns up to max_results ConnectionResult objects sorted by price.
        """
        if not legs:
            return []

        api_key = await _get_serpapi_key_async(self._secrets_manager)
        if not api_key:
            raise ValueError("SerpAPI key not available")

        # Resolve all origins/destinations to IATA codes
        resolved_legs: List[Dict[str, str]] = []
        for leg in legs:
            origin_iata = _resolve_iata_code(leg["origin"])
            dest_iata = _resolve_iata_code(leg["destination"])
            if not origin_iata:
                raise ValueError(
                    f"Could not resolve origin location: '{leg['origin']}'"
                )
            if not dest_iata:
                raise ValueError(
                    f"Could not resolve destination location: '{leg['destination']}'"
                )
            resolved_legs.append({
                "origin": origin_iata,
                "destination": dest_iata,
                "date": leg["date"],
            })

        # Determine trip type and search accordingly
        num_legs = len(resolved_legs)

        if num_legs == 1:
            # One-way search
            return await self._search_one_way(
                api_key, resolved_legs[0], legs[0],
                passengers, travel_class, max_results, non_stop_only, currency,
            )
        elif num_legs == 2:
            # Round-trip search
            return await self._search_round_trip(
                api_key, resolved_legs, legs,
                passengers, travel_class, max_results, non_stop_only, currency,
            )
        else:
            # Multi-city search (3+ legs)
            return await self._search_multi_city(
                api_key, resolved_legs, legs,
                passengers, travel_class, max_results, non_stop_only, currency,
            )

    # ------------------------------------------------------------------
    # One-way search
    # ------------------------------------------------------------------

    async def _search_one_way(
        self,
        api_key: str,
        resolved_leg: Dict[str, str],
        original_leg: dict,
        passengers: int,
        travel_class: str,
        max_results: int,
        non_stop_only: bool,
        currency: str,
    ) -> List[ConnectionResult]:
        """Search for one-way flights. Costs 1 SerpAPI credit.
        Booking URLs are fetched on-demand via the /v1/apps/travel/booking-link
        REST endpoint using the booking_token stored in each result."""
        # Derive gl from departure airport for locale-accurate results
        gl = _get_gl_from_iata(resolved_leg["origin"])

        params: Dict[str, Any] = {
            "engine": "google_flights",
            "api_key": api_key,
            "departure_id": resolved_leg["origin"],
            "arrival_id": resolved_leg["destination"],
            "outbound_date": resolved_leg["date"],
            "type": "2",  # One-way
            "currency": currency,
            "hl": "en",
            "gl": gl,
            "adults": str(passengers),
            "travel_class": _TRAVEL_CLASS_MAP.get(travel_class, "1"),
            "deep_search": "true",
        }
        if non_stop_only:
            params["stops"] = "1"  # Non-stop only

        data = await self._serpapi_get(params)
        if not data:
            return []

        if data.get("error"):
            logger.error(f"SerpAPI error: {data['error']}")
            return []

        # Parse all flight groups (best + other)
        flight_groups = (
            data.get("best_flights", []) + data.get("other_flights", [])
        )

        # Build booking_context — the original search params needed for
        # on-demand booking_token lookup (same params minus deep_search/stops).
        booking_ctx: Dict[str, str] = {
            "departure_id": resolved_leg["origin"],
            "arrival_id": resolved_leg["destination"],
            "outbound_date": resolved_leg["date"],
            "type": "2",
            "currency": currency,
            "gl": gl,
            "adults": str(passengers),
            "travel_class": _TRAVEL_CLASS_MAP.get(travel_class, "1"),
        }

        # Convert to ConnectionResult objects, passing booking_token from
        # each flight group for on-demand booking URL lookup
        results = []
        for fg in flight_groups[:max_results]:
            connection = self._parse_flight_group(
                fg, [original_leg], currency, booking_context=booking_ctx,
            )
            if connection:
                results.append(connection)

        logger.info(f"SerpAPI one-way returned {len(results)} flight(s)")
        return results

    # ------------------------------------------------------------------
    # Round-trip search
    # ------------------------------------------------------------------

    async def _search_round_trip(
        self,
        api_key: str,
        resolved_legs: List[Dict[str, str]],
        original_legs: List[dict],
        passengers: int,
        travel_class: str,
        max_results: int,
        non_stop_only: bool,
        currency: str,
    ) -> List[ConnectionResult]:
        """
        Search for round-trip flights. Costs 1 SerpAPI credit.

        Google Flights returns round-trip pricing in a single request.
        Each flight group already includes the full round-trip price.
        We search outbound flights and return results with round-trip prices.
        Booking URLs are fetched on-demand via the booking_token.
        """
        outbound = resolved_legs[0]
        return_leg = resolved_legs[1]

        # Derive gl from departure airport for locale-accurate results
        gl = _get_gl_from_iata(outbound["origin"])

        params: Dict[str, Any] = {
            "engine": "google_flights",
            "api_key": api_key,
            "departure_id": outbound["origin"],
            "arrival_id": outbound["destination"],
            "outbound_date": outbound["date"],
            "return_date": return_leg["date"],
            "type": "1",  # Round trip
            "currency": currency,
            "hl": "en",
            "gl": gl,
            "adults": str(passengers),
            "travel_class": _TRAVEL_CLASS_MAP.get(travel_class, "1"),
            "deep_search": "true",
        }
        if non_stop_only:
            params["stops"] = "1"

        data = await self._serpapi_get(params)
        if not data:
            return []

        if data.get("error"):
            logger.error(f"SerpAPI error: {data['error']}")
            return []

        # Parse outbound flight groups
        flight_groups = (
            data.get("best_flights", []) + data.get("other_flights", [])
        )

        # Build booking_context for on-demand booking_token lookup
        booking_ctx: Dict[str, str] = {
            "departure_id": outbound["origin"],
            "arrival_id": outbound["destination"],
            "outbound_date": outbound["date"],
            "return_date": return_leg["date"],
            "type": "1",
            "currency": currency,
            "gl": gl,
            "adults": str(passengers),
            "travel_class": _TRAVEL_CLASS_MAP.get(travel_class, "1"),
        }

        results = []
        for fg in flight_groups[:max_results]:
            connection = self._parse_flight_group(
                fg, original_legs, currency, booking_context=booking_ctx,
            )
            if connection:
                results.append(connection)

        logger.info(f"SerpAPI round-trip returned {len(results)} flight(s)")
        return results

    # ------------------------------------------------------------------
    # Multi-city search
    # ------------------------------------------------------------------

    async def _search_multi_city(
        self,
        api_key: str,
        resolved_legs: List[Dict[str, str]],
        original_legs: List[dict],
        passengers: int,
        travel_class: str,
        max_results: int,
        non_stop_only: bool,
        currency: str,
    ) -> List[ConnectionResult]:
        """
        Search for multi-city flights. Costs 1 SerpAPI credit.

        Multi-city uses the multi_city_json parameter. The initial search
        returns pricing for the full itinerary on the first leg results.
        Booking URLs are fetched on-demand via the booking_token.
        """
        import json

        multi_city_data = [
            {
                "departure_id": leg["origin"],
                "arrival_id": leg["destination"],
                "date": leg["date"],
            }
            for leg in resolved_legs
        ]

        # Derive gl from first leg's departure airport
        gl = _get_gl_from_iata(resolved_legs[0]["origin"])

        params: Dict[str, Any] = {
            "engine": "google_flights",
            "api_key": api_key,
            "type": "3",  # Multi-city
            "multi_city_json": json.dumps(multi_city_data),
            "currency": currency,
            "hl": "en",
            "gl": gl,
            "adults": str(passengers),
            "travel_class": _TRAVEL_CLASS_MAP.get(travel_class, "1"),
            "deep_search": "true",
        }
        if non_stop_only:
            params["stops"] = "1"

        data = await self._serpapi_get(params)
        if not data:
            return []

        if data.get("error"):
            logger.error(f"SerpAPI error: {data['error']}")
            return []

        flight_groups = (
            data.get("best_flights", []) + data.get("other_flights", [])
        )

        # Build booking_context for multi-city. Use first leg's departure/arrival
        # as the primary context; SerpAPI needs these for the booking_token lookup.
        booking_ctx: Dict[str, str] = {
            "departure_id": resolved_legs[0]["origin"],
            "arrival_id": resolved_legs[0]["destination"],
            "outbound_date": resolved_legs[0]["date"],
            "type": "3",
            "currency": currency,
            "gl": gl,
            "adults": str(passengers),
            "travel_class": _TRAVEL_CLASS_MAP.get(travel_class, "1"),
        }

        results = []
        for fg in flight_groups[:max_results]:
            connection = self._parse_flight_group(
                fg, original_legs, currency, booking_context=booking_ctx,
            )
            if connection:
                results.append(connection)

        logger.info(f"SerpAPI multi-city returned {len(results)} flight(s)")
        return results

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    async def _serpapi_get(self, params: Dict[str, Any]) -> Optional[dict]:
        """Make an async GET request to the SerpAPI endpoint."""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(SERPAPI_BASE, params=params)

            if response.status_code != 200:
                logger.error(
                    f"SerpAPI request failed ({response.status_code}): "
                    f"{response.text[:500]}"
                )
                return None

            return response.json()

        except httpx.TimeoutException:
            logger.error("SerpAPI request timed out (120s)")
            return None
        except Exception as e:
            logger.error(f"SerpAPI request error: {e}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_flight_group(
        self,
        flight_group: dict,
        original_legs: List[dict],
        currency: str,
        booking_context: Optional[Dict[str, str]] = None,
    ) -> Optional[ConnectionResult]:
        """
        Parse a single SerpAPI flight group into a ConnectionResult.

        A flight group contains:
        - flights[]: individual segments (each flight in the itinerary)
        - layovers[]: layover info between segments
        - total_duration: total trip time in minutes
        - price: price in the requested currency
        - type: 'One way', 'Round trip', 'Multi-city'
        - booking_token: token to retrieve booking links (optional)
        - departure_token: token for selecting this flight in multi-step flows
        - carbon_emissions: CO2 data

        Args:
            flight_group: Raw SerpAPI flight group dict.
            original_legs: User-provided leg dicts with origin/destination names.
            currency: Currency code (e.g., 'EUR').
            booking_context: Original SerpAPI search parameters to store with
                each result for on-demand booking_token lookup.
        """
        flights = flight_group.get("flights", [])
        if not flights:
            return None

        total_duration = flight_group.get("total_duration", 0)
        price = flight_group.get("price")
        raw_layovers = flight_group.get("layovers", [])

        # Build segments from the flights array, capturing all rich metadata
        segments: List[SegmentResult] = []
        for seg in flights:
            dep_airport = seg.get("departure_airport", {})
            arr_airport = seg.get("arrival_airport", {})
            airline = seg.get("airline", "")
            flight_number = seg.get("flight_number", "")
            duration = seg.get("duration", 0)

            # Extract carrier code from flight number (e.g., "BA 945" -> "BA")
            carrier_code = ""
            if flight_number:
                parts = flight_number.split()
                if parts:
                    carrier_code = parts[0]

            # SerpAPI returns time as "YYYY-MM-DD HH:MM" in the airport objects
            dep_time = dep_airport.get("time", "")
            arr_time = arr_airport.get("time", "")

            # Rich metadata from Google Flights
            airplane = seg.get("airplane")  # e.g., "Airbus A321neo"
            airline_logo = seg.get("airline_logo")  # URL to 70px logo
            legroom = seg.get("legroom")  # e.g., "29 in"
            travel_class = seg.get("travel_class")  # e.g., "Economy"
            extensions = seg.get("extensions")  # list of feature tags
            often_delayed = seg.get("often_delayed_by_over_30_min", False)

            # Look up airport coordinates for map display
            dep_iata = dep_airport.get("id", "")
            arr_iata = arr_airport.get("id", "")
            dep_lat, dep_lng = _get_airport_coords(dep_iata)
            arr_lat, arr_lng = _get_airport_coords(arr_iata)

            segments.append(SegmentResult(
                carrier=airline,
                carrier_code=carrier_code if carrier_code else None,
                number=flight_number if flight_number else None,
                departure_station=dep_iata,
                departure_time=dep_time,
                departure_latitude=dep_lat,
                departure_longitude=dep_lng,
                arrival_station=arr_iata,
                arrival_time=arr_time,
                arrival_latitude=arr_lat,
                arrival_longitude=arr_lng,
                duration=_format_duration_minutes(duration),
                airplane=airplane,
                airline_logo=airline_logo,
                legroom=legroom,
                travel_class=travel_class,
                extensions=extensions if extensions else None,
                often_delayed=often_delayed if often_delayed else None,
            ))

        # Build layover details from the raw layovers array
        layover_results: List[LayoverResult] = []
        for lay in raw_layovers:
            lay_duration_min = lay.get("duration", 0)
            layover_results.append(LayoverResult(
                airport=lay.get("name", ""),
                airport_code=lay.get("id"),
                duration=_format_duration_minutes(lay_duration_min) if lay_duration_min else None,
                duration_minutes=lay_duration_min if lay_duration_min else None,
                overnight=lay.get("overnight"),
            ))

        stops = len(raw_layovers)

        # Origin/destination display: use airport names from first/last segment
        if segments:
            first_seg_raw = flights[0]
            last_seg_raw = flights[-1]

            first_dep = first_seg_raw.get("departure_airport", {})
            last_arr = last_seg_raw.get("arrival_airport", {})

            origin_display = _extract_airport_name(first_dep)
            dest_display = _extract_airport_name(last_arr)

            # Override with user's original city names where appropriate
            if original_legs:
                user_origin = original_legs[0].get("origin", "")
                if user_origin and not _IATA_CODE_RE.match(user_origin.strip()):
                    origin_code = first_dep.get("id", "")
                    origin_display = f"{user_origin.strip()} ({origin_code})" if origin_code else user_origin.strip()

                last_original = original_legs[-1] if len(original_legs) > 1 else original_legs[0]
                user_dest = last_original.get("destination", "")
                if user_dest and not _IATA_CODE_RE.match(user_dest.strip()):
                    dest_code = last_arr.get("id", "")
                    dest_display = f"{user_dest.strip()} ({dest_code})" if dest_code else user_dest.strip()

            departure_time = segments[0].departure_time
            arrival_time = segments[-1].arrival_time
        else:
            origin_display = ""
            dest_display = ""
            departure_time = ""
            arrival_time = ""

        leg = LegResult(
            leg_index=0,
            origin=origin_display,
            destination=dest_display,
            departure=departure_time,
            arrival=arrival_time,
            duration=_format_duration_minutes(total_duration),
            stops=stops,
            segments=segments,
            layovers=layover_results if layover_results else None,
        )

        # Store the booking_token from the flight group so the frontend
        # can request the booking URL on-demand via /v1/apps/travel/booking-link.
        # This avoids spending SerpAPI credits on booking lookups during search.
        booking_token = flight_group.get("booking_token")
        booking_url = None
        booking_provider = None

        # Determine the validating/primary airline for this connection
        carrier_codes = set()
        for seg in segments:
            if seg.carrier_code:
                carrier_codes.add(seg.carrier_code)

        validating_code = None
        if len(carrier_codes) == 1:
            validating_code = carrier_codes.pop()
        elif carrier_codes and segments:
            validating_code = segments[0].carrier_code

        # Carbon emissions data from Google Flights
        carbon = flight_group.get("carbon_emissions", {})
        co2_this = carbon.get("this_flight")  # grams
        co2_typical = carbon.get("typical_for_this_route")  # grams
        co2_diff = carbon.get("difference_percent")  # e.g., -7

        # Primary airline logo (flight group level)
        group_airline_logo = flight_group.get("airline_logo")

        return ConnectionResult(
            transport_method="airplane",
            total_price=str(price) if price is not None else None,
            currency=currency,
            bookable_seats=None,
            last_ticketing_date=None,
            booking_url=booking_url,
            booking_provider=booking_provider,
            booking_token=booking_token,
            booking_context=booking_context,
            validating_airline_code=validating_code,
            legs=[leg],
            airline_logo=group_airline_logo,
            co2_kg=round(co2_this / 1000) if co2_this else None,
            co2_typical_kg=round(co2_typical / 1000) if co2_typical else None,
            co2_difference_percent=co2_diff,
        )


# ---------------------------------------------------------------------------
# Standalone booking URL lookup (used by REST endpoint, not during search)
# ---------------------------------------------------------------------------

def _pick_best_booking_option(
    booking_options: List[dict],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Pick the best booking option from SerpAPI's booking_options array.

    Strategy:
    1. Prefer direct airline bookings (ticket.airline == True)
    2. Among airlines, pick the cheapest
    3. If no airline option, pick the cheapest OTA

    Returns:
        Tuple of (clickable_url, provider_name) or (None, None).
    """
    airline_options: List[Tuple[float, str, str]] = []  # (price, url, name)
    ota_options: List[Tuple[float, str, str]] = []

    for opt in booking_options:
        # Handle both "together" and "departing"/"returning" structures.
        # For simplicity, prefer "together" (full itinerary) over split.
        tickets = []
        if opt.get("together"):
            tickets.append(opt["together"])
        elif opt.get("departing"):
            tickets.append(opt["departing"])

        for ticket in tickets:
            booking_req = ticket.get("booking_request", {})
            raw_url = booking_req.get("url", "")
            post_data = booking_req.get("post_data", "")
            if not raw_url:
                continue

            # Convert POST-based Google redirect to a clickable GET URL
            # by appending post_data as query parameters.
            clickable_url = _post_to_get_url(raw_url, post_data)

            book_with = ticket.get("book_with", "Unknown")
            is_airline = ticket.get("airline", False)

            try:
                price = float(ticket.get("price", float("inf")))
            except (ValueError, TypeError):
                price = float("inf")

            if is_airline:
                airline_options.append((price, clickable_url, book_with))
            else:
                ota_options.append((price, clickable_url, book_with))

    # Prefer airline, then OTA, sorted by price
    if airline_options:
        airline_options.sort()
        return airline_options[0][1], airline_options[0][2]
    if ota_options:
        ota_options.sort()
        return ota_options[0][1], ota_options[0][2]

    return None, None


async def lookup_booking_url(
    booking_token: str,
    booking_context: Optional[Dict[str, str]] = None,
    secrets_manager: Optional["SecretsManager"] = None,
) -> Dict[str, Optional[str]]:
    """
    Look up a booking URL for a flight using its SerpAPI booking_token.

    This is the on-demand booking lookup called by the REST endpoint
    /v1/apps/travel/booking-link. It costs 1 SerpAPI credit per call.

    SerpAPI's booking_token lookup requires the original search parameters
    (departure_id, arrival_id, outbound_date, type, currency, gl, adults,
    travel_class) alongside the booking_token. These are passed via the
    booking_context dict, which was stored in each search result.

    Args:
        booking_token: The booking_token from a SerpAPI flight search result.
        booking_context: Dict of original search parameters needed by SerpAPI
            for the booking lookup. Keys: departure_id, arrival_id,
            outbound_date, return_date (optional), type, currency, gl,
            adults, travel_class.
        secrets_manager: Optional SecretsManager for loading the SerpAPI key
            from Vault. Falls back to env vars if not provided.

    Returns:
        Dict with 'booking_url' and 'booking_provider' keys.
        Values are None if no booking link could be found.

    Raises:
        ValueError: If the SerpAPI key is not configured.
    """
    api_key = await _get_serpapi_key_async(secrets_manager)
    if not api_key:
        raise ValueError("SerpAPI key not available")

    # SerpAPI booking_token lookup requires the original search parameters
    # (same params as the initial search, minus deep_search and stops).
    # These are passed via booking_context from the search result.
    params: Dict[str, Any] = {
        "engine": "google_flights",
        "api_key": api_key,
        "booking_token": booking_token,
        "hl": "en",
    }

    # Merge in the original search context params required by SerpAPI.
    # booking_context carries the original search parameters (departure_id,
    # arrival_id, etc.) that SerpAPI requires alongside the booking_token.
    if booking_context:
        for key in (
            "departure_id", "arrival_id", "outbound_date", "return_date",
            "type", "currency", "gl", "adults", "travel_class",
        ):
            val = booking_context.get(key)
            if val:
                params[key] = val
        # Verify that the critical departure_id parameter is present
        if "departure_id" not in params:
            logger.error(
                "booking_context provided but missing 'departure_id'. "
                f"Context keys: {list(booking_context.keys())}. "
                "SerpAPI will reject this request."
            )
    else:
        logger.warning(
            "No booking_context provided for booking lookup. "
            "Required search parameters (departure_id, arrival_id, etc.) "
            "will be missing from the SerpAPI request. This likely means "
            "the frontend did not receive booking_context from the embed data "
            "(possible TOON encoding issue)."
        )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(SERPAPI_BASE, params=params)

        if response.status_code != 200:
            logger.error(
                f"SerpAPI booking lookup failed ({response.status_code}): "
                f"{response.text[:500]}"
            )
            return {"booking_url": None, "booking_provider": None}

        data = response.json()

    except httpx.TimeoutException:
        logger.error("SerpAPI booking lookup timed out (60s)")
        return {"booking_url": None, "booking_provider": None}
    except Exception as e:
        logger.error(f"SerpAPI booking lookup error: {e}", exc_info=True)
        return {"booking_url": None, "booking_provider": None}

    if data.get("error"):
        logger.error(f"SerpAPI booking lookup error: {data['error']}")
        return {"booking_url": None, "booking_provider": None}

    booking_options = data.get("booking_options", [])
    if not booking_options:
        logger.debug("No booking options returned by SerpAPI")
        return {"booking_url": None, "booking_provider": None}

    url, provider_name = _pick_best_booking_option(booking_options)
    logger.info(
        f"Booking lookup: {provider_name or 'none'} -> {url[:80] + '...' if url and len(url) > 80 else url}"
    )
    return {"booking_url": url, "booking_provider": provider_name}
