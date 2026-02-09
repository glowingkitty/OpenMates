"""
Duffel flight search provider for the travel app.

Implements BaseTransportProvider to search for flight connections via the
Duffel API. Duffel provides access to 300+ airlines including low-cost
carriers (easyJet, Vueling, Spirit, etc.) via NDC direct-connect, GDS
(Travelport), and Hahn Air interline ticketing.

Key differences from Amadeus:
- Better LCC coverage and more competitive pricing
- Airport coordinates included in every response (no separate cache needed)
- Bearer token auth (no OAuth2 flow)
- Slices (legs) support city and airport IATA codes natively
- Places API for city-name-to-IATA resolution

API docs: https://duffel.com/docs/api
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
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DUFFEL_API_BASE = "https://api.duffel.com"
DUFFEL_API_VERSION = "v2"

# Vault path for Duffel API token
DUFFEL_SECRET_PATH = "kv/data/providers/duffel"
DUFFEL_TOKEN_KEY = "api_token"

# Place suggestion cache: city name -> IATA code (persists for process lifetime)
_place_cache: Dict[str, str] = {}

# Regex to detect if a string is already an IATA code (2-4 uppercase letters)
_IATA_CODE_RE = re.compile(r"^[A-Z]{2,4}$")


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

async def _get_duffel_token(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Retrieve the Duffel API bearer token from Vault,
    with fallback to environment variables.

    Returns:
        The API token string if found, None otherwise.
    """
    # Try Vault first
    try:
        secrets = await secrets_manager.get_secrets_from_path(DUFFEL_SECRET_PATH)
        if secrets:
            token = secrets.get(DUFFEL_TOKEN_KEY)
            if token and token.strip():
                logger.debug("Successfully retrieved Duffel token from Vault")
                return token.strip()
            else:
                logger.debug("Duffel token incomplete in Vault, checking env vars")
    except Exception as e:
        logger.warning(
            f"Error retrieving Duffel token from Vault: {e}, checking env vars",
            exc_info=True,
        )

    # Fallback to environment variable
    token = os.getenv("SECRET__DUFFEL__API_TOKEN")
    if token and token.strip():
        logger.info("Successfully retrieved Duffel token from environment variables")
        return token.strip()

    logger.error(
        "Duffel API token not found in Vault or environment variables. "
        "Set SECRET__DUFFEL__API_TOKEN in .env."
    )
    return None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _format_duration(iso_duration: str) -> str:
    """Convert ISO 8601 duration (e.g., 'PT7H30M') to human-readable '7h 30m'."""
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


def _build_headers(token: str) -> Dict[str, str]:
    """Build the standard Duffel API request headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Duffel-Version": DUFFEL_API_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
    }


# ---------------------------------------------------------------------------
# DuffelProvider
# ---------------------------------------------------------------------------

class DuffelProvider(BaseTransportProvider):
    """
    Flight search provider using the Duffel API.

    Resolves city names to IATA codes via the Places Suggestions API,
    then searches for flight offers using the Offer Requests endpoint.
    Returns unified ConnectionResult objects with full airport coordinates.
    """

    def __init__(self) -> None:
        self._secrets_manager: Optional[SecretsManager] = None

    def supports_transport_method(self, method: str) -> bool:
        return method == "airplane"

    # ------------------------------------------------------------------
    # Place resolution (city name -> IATA code)
    # ------------------------------------------------------------------

    async def _resolve_iata_code(
        self, location: str, token: str
    ) -> Optional[str]:
        """
        Resolve a city/airport name to an IATA code using the Duffel
        Places Suggestions API. Results are cached in-process.

        If the input already looks like an IATA code (2-4 uppercase letters),
        it is returned as-is.

        Args:
            location: City or airport name (e.g., 'Munich', 'London Heathrow')
                      or IATA code (e.g., 'MUC').
            token: Duffel API bearer token.

        Returns:
            IATA code (e.g., 'MUC') or None if not found.
        """
        stripped = location.strip()

        # Short-circuit if already an IATA code
        if _IATA_CODE_RE.match(stripped):
            return stripped

        cache_key = stripped.lower()
        if cache_key in _place_cache:
            return _place_cache[cache_key]

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{DUFFEL_API_BASE}/air/places/suggestions",
                params={"query": stripped},
                headers=_build_headers(token),
            )

        if response.status_code != 200:
            logger.warning(
                f"Duffel places search failed for '{location}': "
                f"{response.status_code} {response.text[:300]}"
            )
            return None

        data = response.json().get("data", [])
        if not data:
            logger.warning(f"No Duffel place found for '{location}'")
            return None

        # Prefer airports over cities for more precise results,
        # but accept city codes as fallback
        iata_code = None
        for place in data:
            if place.get("type") == "airport" and place.get("iata_code"):
                iata_code = place["iata_code"]
                break
        if not iata_code:
            # Fall back to first result with an IATA code (could be a city)
            for place in data:
                if place.get("iata_code"):
                    iata_code = place["iata_code"]
                    break

        if iata_code:
            _place_cache[cache_key] = iata_code
            logger.debug(f"Resolved '{location}' -> IATA '{iata_code}' (Duffel)")

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
        Search for flight connections via the Duffel Offer Requests API.

        Builds slices from the provided legs, resolves city names to IATA
        codes, and returns up to max_results ConnectionResult objects.
        """
        if not legs:
            return []

        secrets_manager = self._secrets_manager
        if not secrets_manager:
            raise ValueError("SecretsManager not set on DuffelProvider")

        token = await _get_duffel_token(secrets_manager)
        if not token:
            raise ValueError("Duffel API token not available")

        # Resolve all origins/destinations to IATA codes
        slices = []
        for leg in legs:
            origin_iata = await self._resolve_iata_code(leg["origin"], token)
            dest_iata = await self._resolve_iata_code(leg["destination"], token)
            if not origin_iata:
                raise ValueError(
                    f"Could not resolve origin location: '{leg['origin']}'"
                )
            if not dest_iata:
                raise ValueError(
                    f"Could not resolve destination location: '{leg['destination']}'"
                )

            slice_obj: Dict[str, Any] = {
                "origin": origin_iata,
                "destination": dest_iata,
                "departure_date": leg["date"],
            }
            slices.append(slice_obj)

        # Build passenger list (all adults for now)
        passenger_list = [{"type": "adult"} for _ in range(passengers)]

        # Map travel class
        cabin_class = travel_class if travel_class in (
            "economy", "premium_economy", "business", "first"
        ) else "economy"

        # Max connections: 0 = non-stop only, 1 = up to 1 layover
        max_connections = 0 if non_stop_only else 1

        body = {
            "data": {
                "slices": slices,
                "passengers": passenger_list,
                "cabin_class": cabin_class,
                "max_connections": max_connections,
            }
        }

        # Make the API request
        # supplier_timeout=20000 gives airlines 20s to respond
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{DUFFEL_API_BASE}/air/offer_requests"
                f"?return_offers=true&supplier_timeout=20000",
                json=body,
                headers=_build_headers(token),
            )

        # Duffel returns 201 (Created) for offer_requests, not 200
        if response.status_code not in (200, 201):
            logger.error(
                f"Duffel offer request failed ({response.status_code}): "
                f"{response.text[:500]}"
            )
            return []

        resp_data = response.json().get("data", {})
        offers = resp_data.get("offers", [])

        # Sort by price and limit to max_results
        def _price_sort_key(offer: dict) -> float:
            try:
                return float(offer.get("total_amount", "999999"))
            except (ValueError, TypeError):
                return 999999.0

        offers.sort(key=_price_sort_key)
        offers = offers[:max_results]

        # Parse offers into ConnectionResult objects
        return self._parse_offers(offers, legs)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_offers(
        self,
        offers: List[dict],
        original_legs: List[dict],
    ) -> List[ConnectionResult]:
        """
        Parse Duffel offer objects into unified ConnectionResult objects.

        Each Duffel offer contains:
        - slices[]: one per leg, each with segments[]
        - segments have full origin/destination objects with coordinates
        - owner: the validating airline
        """
        results: List[ConnectionResult] = []

        for offer in offers:
            duffel_slices = offer.get("slices", [])
            owner = offer.get("owner", {})
            validating_code = owner.get("iata_code")

            legs_out: List[LegResult] = []
            for leg_idx, duffel_slice in enumerate(duffel_slices):
                segments_raw = duffel_slice.get("segments", [])
                slice_duration = _format_duration(
                    duffel_slice.get("duration", "")
                )
                stops = len(segments_raw) - 1

                # Build segments
                segments_out: List[SegmentResult] = []
                for seg in segments_raw:
                    origin = seg.get("origin", {})
                    destination = seg.get("destination", {})
                    operating = seg.get("operating_carrier", {})
                    marketing = seg.get("marketing_carrier", {})

                    # Prefer operating carrier info, fall back to marketing
                    carrier_code = (
                        operating.get("iata_code")
                        or marketing.get("iata_code", "")
                    )
                    carrier_name = (
                        operating.get("name")
                        or marketing.get("name", carrier_code)
                    )
                    flight_number = (
                        seg.get("operating_carrier_flight_number")
                        or seg.get("marketing_carrier_flight_number", "")
                    )

                    segments_out.append(SegmentResult(
                        carrier=carrier_name,
                        carrier_code=carrier_code,
                        number=f"{carrier_code}{flight_number}" if flight_number else None,
                        departure_station=origin.get("iata_code", ""),
                        departure_time=seg.get("departing_at", ""),
                        departure_latitude=origin.get("latitude"),
                        departure_longitude=origin.get("longitude"),
                        arrival_station=destination.get("iata_code", ""),
                        arrival_time=seg.get("arriving_at", ""),
                        arrival_latitude=destination.get("latitude"),
                        arrival_longitude=destination.get("longitude"),
                        duration=_format_duration(seg.get("duration", "")),
                    ))

                # Build origin/destination display strings
                if segments_raw:
                    first_seg = segments_raw[0]
                    last_seg = segments_raw[-1]
                    first_origin = first_seg.get("origin", {})
                    last_dest = last_seg.get("destination", {})

                    origin_city = first_origin.get("city_name", "")
                    origin_code = first_origin.get("iata_code", "")
                    dest_city = last_dest.get("city_name", "")
                    dest_code = last_dest.get("iata_code", "")

                    # Also try to use the user's original city name if available
                    if leg_idx < len(original_legs):
                        user_origin = original_legs[leg_idx].get("origin", "")
                        user_dest = original_legs[leg_idx].get("destination", "")
                        # Use user's name if it looks like a city name (not an IATA code)
                        if user_origin and not _IATA_CODE_RE.match(user_origin.strip()):
                            origin_city = user_origin.strip()
                        if user_dest and not _IATA_CODE_RE.match(user_dest.strip()):
                            dest_city = user_dest.strip()

                    origin_display = (
                        f"{origin_city} ({origin_code})"
                        if origin_city else origin_code
                    )
                    dest_display = (
                        f"{dest_city} ({dest_code})"
                        if dest_city else dest_code
                    )

                    departure_time = first_seg.get("departing_at", "")
                    arrival_time = last_seg.get("arriving_at", "")
                else:
                    origin_display = ""
                    dest_display = ""
                    departure_time = ""
                    arrival_time = ""

                legs_out.append(LegResult(
                    leg_index=leg_idx,
                    origin=origin_display,
                    destination=dest_display,
                    departure=departure_time,
                    arrival=arrival_time,
                    duration=slice_duration,
                    stops=stops,
                    segments=segments_out,
                ))

            results.append(ConnectionResult(
                transport_method="airplane",
                total_price=offer.get("total_amount"),
                currency=offer.get("total_currency"),
                bookable_seats=None,  # Duffel doesn't expose this in search
                last_ticketing_date=None,
                validating_airline_code=validating_code,
                legs=legs_out,
            ))

        logger.info(f"Duffel returned {len(results)} flight offer(s)")
        return results
