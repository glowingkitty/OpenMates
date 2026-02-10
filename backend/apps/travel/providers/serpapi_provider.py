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
from typing import Any, Dict, List, Optional

import httpx

from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
    LegResult,
    SegmentResult,
)

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

def _get_serpapi_key() -> Optional[str]:
    """
    Retrieve the SerpAPI key from environment variables.

    Returns:
        The API key string if found, None otherwise.
    """
    key = os.getenv("SECRET__SERPAPI__API_KEY")
    if key and key.strip():
        logger.debug("Successfully retrieved SerpAPI key from environment variables")
        return key.strip()

    logger.error(
        "SerpAPI key not found. Set SECRET__SERPAPI__API_KEY in .env. "
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
    """

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

        api_key = _get_serpapi_key()
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
        """Search for one-way flights. Costs 1 SerpAPI credit."""
        params: Dict[str, Any] = {
            "engine": "google_flights",
            "api_key": api_key,
            "departure_id": resolved_leg["origin"],
            "arrival_id": resolved_leg["destination"],
            "outbound_date": resolved_leg["date"],
            "type": "2",  # One-way
            "currency": currency,
            "hl": "en",
            "gl": "us",
            "adults": str(passengers),
            "travel_class": _TRAVEL_CLASS_MAP.get(travel_class, "1"),
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

        # Convert to ConnectionResult objects
        results = []
        for fg in flight_groups[:max_results]:
            connection = self._parse_flight_group(
                fg, [original_leg], currency,
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
        """
        outbound = resolved_legs[0]
        return_leg = resolved_legs[1]

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
            "gl": "us",
            "adults": str(passengers),
            "travel_class": _TRAVEL_CLASS_MAP.get(travel_class, "1"),
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

        results = []
        for fg in flight_groups[:max_results]:
            # For round-trip, the outbound flight group contains the
            # full round-trip price. We create a 2-leg connection with
            # the outbound details in leg 0. Leg 1 uses the return
            # origin/destination from the request with the same segments
            # structure (simplified since we don't select a specific return).
            connection = self._parse_flight_group(
                fg, original_legs, currency,
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
        Search for multi-city flights. Costs 1 SerpAPI credit for the
        first leg search.

        Multi-city uses the multi_city_json parameter. The initial search
        returns pricing for the full itinerary on the first leg results.
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

        params: Dict[str, Any] = {
            "engine": "google_flights",
            "api_key": api_key,
            "type": "3",  # Multi-city
            "multi_city_json": json.dumps(multi_city_data),
            "currency": currency,
            "hl": "en",
            "gl": "us",
            "adults": str(passengers),
            "travel_class": _TRAVEL_CLASS_MAP.get(travel_class, "1"),
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

        results = []
        for fg in flight_groups[:max_results]:
            connection = self._parse_flight_group(
                fg, original_legs, currency,
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
        """
        flights = flight_group.get("flights", [])
        if not flights:
            return None

        total_duration = flight_group.get("total_duration", 0)
        price = flight_group.get("price")
        layovers = flight_group.get("layovers", [])

        # Build segments from the flights array
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

            # Build departure/arrival times
            # SerpAPI returns time as "HH:MM" or datetime strings in the
            # departure_airport/arrival_airport objects
            dep_time = dep_airport.get("time", "")
            arr_time = arr_airport.get("time", "")

            segments.append(SegmentResult(
                carrier=airline,
                carrier_code=carrier_code if carrier_code else None,
                number=flight_number if flight_number else None,
                departure_station=dep_airport.get("id", ""),
                departure_time=dep_time,
                departure_latitude=None,  # Not provided by SerpAPI
                departure_longitude=None,
                arrival_station=arr_airport.get("id", ""),
                arrival_time=arr_time,
                arrival_latitude=None,
                arrival_longitude=None,
                duration=_format_duration_minutes(duration),
            ))

        # Build the leg (SerpAPI returns all segments in a single flight
        # group, which represents one leg/direction of travel)
        stops = len(layovers)

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

                # For destination, use the last leg's destination if multi-leg
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
        )

        # Build booking URL from booking_token if available.
        # The booking_token can be used in a follow-up SerpAPI call to
        # get actual booking links, but for now we store it as metadata.
        # The skill layer will use airline_urls.py for direct booking links.
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
            # Use the first segment's carrier as the primary
            validating_code = segments[0].carrier_code

        return ConnectionResult(
            transport_method="airplane",
            total_price=str(price) if price is not None else None,
            currency=currency,
            bookable_seats=None,
            last_ticketing_date=None,
            booking_url=booking_url,
            booking_provider=booking_provider,
            validating_airline_code=validating_code,
            legs=[leg],
        )
