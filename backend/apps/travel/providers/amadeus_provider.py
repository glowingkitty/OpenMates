"""
Amadeus flight search provider for the travel app.

Implements BaseTransportProvider to search for flight connections via the
Amadeus Self-Service API. Handles OAuth2 authentication, city-name-to-IATA
resolution, and mapping of Amadeus responses to the unified ConnectionResult format.

Supports:
- One-way flights (1 leg, GET endpoint)
- Round-trip flights (2 symmetric legs, GET endpoint with returnDate)
- Multi-city flights (N legs, POST endpoint)
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
    LegResult,
    SegmentResult,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AMADEUS_BASE_URL_TEST = "https://test.api.amadeus.com"
AMADEUS_BASE_URL_PROD = "https://api.amadeus.com"

# Vault path for Amadeus API credentials
AMADEUS_SECRET_PATH = "kv/data/providers/amadeus"
AMADEUS_API_KEY_NAME = "api_key"
AMADEUS_API_SECRET_NAME = "api_secret"

# Travel class mapping: our names -> Amadeus cabin codes
TRAVEL_CLASS_MAP = {
    "economy": "ECONOMY",
    "premium_economy": "PREMIUM_ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST",
}

# Token cache: shared across provider instances within the same process
_token_cache: Dict[str, Any] = {
    "access_token": None,
    "expires_at": 0,
}

# IATA code cache: city name -> IATA code (persists for process lifetime)
_iata_cache: Dict[str, str] = {}

# Airport coordinate cache: IATA code -> (latitude, longitude)
_coord_cache: Dict[str, Tuple[float, float]] = {}


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

async def _get_amadeus_credentials(secrets_manager: SecretsManager) -> Optional[Tuple[str, str]]:
    """
    Retrieve Amadeus API credentials (api_key + api_secret) from Vault,
    with fallback to environment variables.

    Returns:
        Tuple of (api_key, api_secret) if found, None otherwise.
    """
    # Try Vault first (single request for both keys)
    try:
        secrets = await secrets_manager.get_secrets_from_path(AMADEUS_SECRET_PATH)
        if secrets:
            api_key = secrets.get(AMADEUS_API_KEY_NAME)
            api_secret = secrets.get(AMADEUS_API_SECRET_NAME)
            if api_key and api_secret:
                logger.debug("Successfully retrieved Amadeus credentials from Vault")
                return (api_key.strip(), api_secret.strip())
            else:
                logger.debug("Amadeus credentials incomplete in Vault, checking env vars")
    except Exception as e:
        logger.warning(f"Error retrieving Amadeus credentials from Vault: {e}, checking env vars", exc_info=True)

    # Fallback to environment variables
    api_key = os.getenv("SECRET__AMADEUS__API_KEY")
    api_secret = os.getenv("SECRET__AMADEUS__API_SECRET")
    if api_key and api_key.strip() and api_secret and api_secret.strip():
        logger.info("Successfully retrieved Amadeus credentials from environment variables")
        return (api_key.strip(), api_secret.strip())

    logger.error(
        "Amadeus API credentials not found in Vault or environment variables. "
        "Set SECRET__AMADEUS__API_KEY and SECRET__AMADEUS__API_SECRET in .env."
    )
    return None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _format_duration(iso_duration: str) -> str:
    """Convert ISO 8601 duration (e.g., 'PT2H30M') to human-readable '2h 30m'."""
    if not iso_duration:
        return "N/A"
    duration = iso_duration.replace("PT", "")
    hours = 0
    minutes = 0
    if "H" in duration:
        h_parts = duration.split("H")
        hours = int(h_parts[0])
        duration = h_parts[1]
    if "M" in duration:
        minutes = int(duration.replace("M", ""))
    if hours and minutes:
        return f"{hours}h {minutes}m"
    elif hours:
        return f"{hours}h"
    else:
        return f"{minutes}m"


def _is_round_trip(legs: List[dict]) -> bool:
    """
    Detect whether the legs form a round trip:
    exactly 2 legs where leg[1].origin == leg[0].destination and
    leg[1].destination == leg[0].origin.
    """
    if len(legs) != 2:
        return False
    return (
        legs[1].get("origin", "").lower() == legs[0].get("destination", "").lower()
        and legs[1].get("destination", "").lower() == legs[0].get("origin", "").lower()
    )


# ---------------------------------------------------------------------------
# AmadeusProvider
# ---------------------------------------------------------------------------

class AmadeusProvider(BaseTransportProvider):
    """
    Flight search provider using the Amadeus Self-Service API.

    Authenticates via OAuth2, resolves city names to IATA codes, and returns
    unified ConnectionResult objects.
    """

    def __init__(self, use_production: bool = False) -> None:
        self.base_url = AMADEUS_BASE_URL_PROD if use_production else AMADEUS_BASE_URL_TEST
        self._secrets_manager: Optional[SecretsManager] = None

    def supports_transport_method(self, method: str) -> bool:
        return method == "airplane"

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _ensure_token(self, secrets_manager: SecretsManager) -> str:
        """
        Return a valid OAuth2 access token, refreshing if expired.

        Uses a process-level cache to avoid re-authenticating on every request.
        """
        global _token_cache

        # Return cached token if still valid (with 60s safety margin)
        if _token_cache["access_token"] and time.time() < (_token_cache["expires_at"] - 60):
            return _token_cache["access_token"]

        credentials = await _get_amadeus_credentials(secrets_manager)
        if not credentials:
            raise ValueError("Amadeus API credentials not available")

        api_key, api_secret = credentials

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/security/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": api_key,
                    "client_secret": api_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            logger.error(f"Amadeus OAuth2 authentication failed ({response.status_code}): {response.text[:300]}")
            raise ValueError(f"Amadeus authentication failed: {response.status_code}")

        token_data = response.json()
        _token_cache["access_token"] = token_data["access_token"]
        _token_cache["expires_at"] = time.time() + token_data.get("expires_in", 1799)
        logger.debug(f"Amadeus OAuth2 token refreshed (expires in {token_data.get('expires_in', '?')}s)")

        return _token_cache["access_token"]

    # ------------------------------------------------------------------
    # IATA code resolution
    # ------------------------------------------------------------------

    async def _resolve_iata_code(self, city_name: str, token: str) -> Optional[str]:
        """
        Resolve a city name to its primary IATA airport code using the
        Amadeus location search API. Results are cached in-process.
        Also caches geographic coordinates for map display.

        Args:
            city_name: City name (e.g., 'Munich', 'London').
            token: Valid Amadeus OAuth2 access token.

        Returns:
            IATA code (e.g., 'MUC') or None if not found.
        """
        cache_key = city_name.strip().lower()
        if cache_key in _iata_cache:
            return _iata_cache[cache_key]

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/v1/reference-data/locations",
                params={
                    "subType": "AIRPORT,CITY",
                    "keyword": city_name.strip(),
                    "page[limit]": 5,
                    "view": "FULL",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )

        if response.status_code != 200:
            logger.warning(f"Amadeus location search failed for '{city_name}': {response.status_code}")
            return None

        data = response.json()
        locations = data.get("data", [])

        if not locations:
            logger.warning(f"No IATA location found for '{city_name}'")
            return None

        # Prefer CITY type for broad coverage, fall back to first AIRPORT result
        iata_code = None
        selected_loc = None
        for loc in locations:
            if loc.get("subType") == "CITY":
                iata_code = loc.get("iataCode")
                selected_loc = loc
                break
        if not iata_code:
            iata_code = locations[0].get("iataCode")
            selected_loc = locations[0]

        if iata_code:
            _iata_cache[cache_key] = iata_code
            # Cache geographic coordinates from the FULL view response
            geo_code = selected_loc.get("geoCode", {}) if selected_loc else {}
            lat = geo_code.get("latitude")
            lon = geo_code.get("longitude")
            if lat is not None and lon is not None:
                _coord_cache[iata_code] = (float(lat), float(lon))
                logger.debug(f"Resolved '{city_name}' -> IATA '{iata_code}' ({lat}, {lon})")
            else:
                logger.debug(f"Resolved '{city_name}' -> IATA '{iata_code}' (no coordinates)")

        return iata_code

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
        Search for flight connections via the Amadeus API.

        Routing logic:
        - 1 leg -> GET /v2/shopping/flight-offers (one-way)
        - 2 symmetric legs -> GET with returnDate (round trip)
        - N legs or non-symmetric -> POST /v2/shopping/flight-offers (multi-city)
        """
        if not legs:
            return []

        secrets_manager = self._secrets_manager
        if not secrets_manager:
            raise ValueError("SecretsManager not set on AmadeusProvider")

        token = await self._ensure_token(secrets_manager)

        # Resolve all city names to IATA codes
        resolved_legs = []
        for leg in legs:
            origin_iata = await self._resolve_iata_code(leg["origin"], token)
            dest_iata = await self._resolve_iata_code(leg["destination"], token)
            if not origin_iata:
                raise ValueError(f"Could not resolve origin location: '{leg['origin']}'")
            if not dest_iata:
                raise ValueError(f"Could not resolve destination location: '{leg['destination']}'")
            resolved_legs.append({
                "origin_iata": origin_iata,
                "destination_iata": dest_iata,
                "origin_name": leg["origin"],
                "destination_name": leg["destination"],
                "date": leg["date"],
            })

        cabin_class = TRAVEL_CLASS_MAP.get(travel_class, "ECONOMY")
        is_rt = _is_round_trip(legs)

        # Choose API strategy based on leg count and symmetry
        if len(resolved_legs) == 1 or is_rt:
            return await self._search_get(
                resolved_legs=resolved_legs,
                passengers=passengers,
                cabin_class=cabin_class,
                max_results=max_results,
                non_stop_only=non_stop_only,
                currency=currency,
                is_round_trip=is_rt,
                token=token,
            )
        else:
            return await self._search_post(
                resolved_legs=resolved_legs,
                passengers=passengers,
                cabin_class=cabin_class,
                max_results=max_results,
                currency=currency,
                token=token,
            )

    async def _search_get(
        self,
        resolved_legs: List[dict],
        passengers: int,
        cabin_class: str,
        max_results: int,
        non_stop_only: bool,
        currency: str,
        is_round_trip: bool,
        token: str,
    ) -> List[ConnectionResult]:
        """
        Search using the GET endpoint for one-way or round-trip flights.
        GET /v2/shopping/flight-offers
        """
        params: Dict[str, Any] = {
            "originLocationCode": resolved_legs[0]["origin_iata"],
            "destinationLocationCode": resolved_legs[0]["destination_iata"],
            "departureDate": resolved_legs[0]["date"],
            "adults": passengers,
            "travelClass": cabin_class,
            "nonStop": "true" if non_stop_only else "false",
            "currencyCode": currency,
            "max": max_results,
        }

        if is_round_trip and len(resolved_legs) >= 2:
            params["returnDate"] = resolved_legs[1]["date"]

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/v2/shopping/flight-offers",
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )

        if response.status_code != 200:
            logger.error(f"Amadeus GET flight search failed ({response.status_code}): {response.text[:300]}")
            return []

        data = response.json()
        return self._parse_flight_offers(data, resolved_legs, is_round_trip)

    async def _search_post(
        self,
        resolved_legs: List[dict],
        passengers: int,
        cabin_class: str,
        max_results: int,
        currency: str,
        token: str,
    ) -> List[ConnectionResult]:
        """
        Search using the POST endpoint for multi-city flights.
        POST /v2/shopping/flight-offers
        """
        origin_destinations = []
        for i, leg in enumerate(resolved_legs):
            origin_destinations.append({
                "id": str(i + 1),
                "originLocationCode": leg["origin_iata"],
                "destinationLocationCode": leg["destination_iata"],
                "departureDateTimeRange": {"date": leg["date"]},
            })

        travelers = [{"id": str(i + 1), "travelerType": "ADULT"} for i in range(passengers)]

        od_ids = [str(i + 1) for i in range(len(resolved_legs))]
        body = {
            "originDestinations": origin_destinations,
            "travelers": travelers,
            "sources": ["GDS"],
            "searchCriteria": {
                "maxFlightOffers": max_results,
                "flightFilters": {
                    "cabinRestrictions": [
                        {
                            "cabin": cabin_class,
                            "coverage": "MOST_SEGMENTS",
                            "originDestinationIds": od_ids,
                        }
                    ]
                },
            },
            "currencyCode": currency,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/v2/shopping/flight-offers",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/vnd.amadeus+json",
                    "X-HTTP-Method-Override": "GET",
                },
            )

        if response.status_code != 200:
            logger.error(f"Amadeus POST flight search failed ({response.status_code}): {response.text[:300]}")
            return []

        data = response.json()
        return self._parse_flight_offers(data, resolved_legs, is_round_trip=False)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_flight_offers(
        self,
        data: dict,
        resolved_legs: List[dict],
        is_round_trip: bool,
    ) -> List[ConnectionResult]:
        """
        Parse Amadeus flight offers response into unified ConnectionResult objects.

        The Amadeus response structure is:
        - data[].itineraries[]: one itinerary per leg
        - data[].itineraries[].segments[]: individual flight segments
        - dictionaries.carriers: IATA code -> airline name mapping
        """
        offers = data.get("data", [])
        carriers = data.get("dictionaries", {}).get("carriers", {})

        results: List[ConnectionResult] = []

        for offer in offers:
            price = offer.get("price", {})
            itineraries = offer.get("itineraries", [])

            legs_out: List[LegResult] = []
            for leg_idx, itinerary in enumerate(itineraries):
                segments_raw = itinerary.get("segments", [])
                total_duration = _format_duration(itinerary.get("duration", ""))
                stops = len(segments_raw) - 1

                # Build segment list
                segments_out: List[SegmentResult] = []
                for seg in segments_raw:
                    carrier_code = seg.get("carrierCode", "")
                    carrier_name = carriers.get(carrier_code, carrier_code)
                    dep = seg.get("departure", {})
                    arr = seg.get("arrival", {})

                    # Look up cached coordinates for departure and arrival airports
                    dep_iata = dep.get("iataCode", "")
                    arr_iata = arr.get("iataCode", "")
                    dep_coords = _coord_cache.get(dep_iata)
                    arr_coords = _coord_cache.get(arr_iata)

                    segments_out.append(SegmentResult(
                        carrier=carrier_name,
                        carrier_code=carrier_code,
                        number=f"{carrier_code}{seg.get('number', '')}",
                        departure_station=dep_iata,
                        departure_time=dep.get("at", ""),
                        departure_latitude=dep_coords[0] if dep_coords else None,
                        departure_longitude=dep_coords[1] if dep_coords else None,
                        arrival_station=arr_iata,
                        arrival_time=arr.get("at", ""),
                        arrival_latitude=arr_coords[0] if arr_coords else None,
                        arrival_longitude=arr_coords[1] if arr_coords else None,
                        duration=_format_duration(seg.get("duration", "")),
                    ))

                # Build origin/destination display strings
                # Use the first/last segment's airport codes with the original city name
                first_seg = segments_raw[0] if segments_raw else {}
                last_seg = segments_raw[-1] if segments_raw else {}
                origin_code = first_seg.get("departure", {}).get("iataCode", "")
                dest_code = last_seg.get("arrival", {}).get("iataCode", "")

                # Try to get city name from resolved_legs if available
                origin_city = resolved_legs[leg_idx]["origin_name"] if leg_idx < len(resolved_legs) else ""
                dest_city = resolved_legs[leg_idx]["destination_name"] if leg_idx < len(resolved_legs) else ""

                origin_display = f"{origin_city} ({origin_code})" if origin_city else origin_code
                dest_display = f"{dest_city} ({dest_code})" if dest_city else dest_code

                legs_out.append(LegResult(
                    leg_index=leg_idx,
                    origin=origin_display,
                    destination=dest_display,
                    departure=first_seg.get("departure", {}).get("at", ""),
                    arrival=last_seg.get("arrival", {}).get("at", ""),
                    duration=total_duration,
                    stops=stops,
                    segments=segments_out,
                ))

            # Extract the validating airline code from the offer.
            # validatingAirlineCodes is an array; the first entry is the primary
            # ticketing/validating airline for the entire itinerary.
            validating_codes = offer.get("validatingAirlineCodes", [])
            validating_code = validating_codes[0] if validating_codes else None

            results.append(ConnectionResult(
                transport_method="airplane",
                total_price=price.get("total"),
                currency=price.get("currency"),
                bookable_seats=offer.get("numberOfBookableSeats"),
                last_ticketing_date=offer.get("lastTicketingDate"),
                validating_airline_code=validating_code,
                legs=legs_out,
            ))

        logger.info(f"Amadeus returned {len(results)} flight offer(s)")
        return results
