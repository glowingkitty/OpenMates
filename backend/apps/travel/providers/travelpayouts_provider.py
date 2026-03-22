"""
Travelpayouts (Aviasales) provider for the travel app.

Implements the price calendar feature using the Travelpayouts Data API
month-matrix endpoint. This is a free affiliate API that returns cached
flight prices (up to 48h old) for every day of a month on a given route.

Ideal for a quick "when is it cheapest to fly?" heatmap overview.
Not intended for booking — users should use the Search Connections skill
for live pricing and booking links on specific dates.

API docs: https://support.travelpayouts.com/hc/en-us/articles/203956163
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from backend.apps.travel.providers.base_provider import PriceCalendarEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRAVELPAYOUTS_BASE = "https://api.travelpayouts.com/v2/prices/month-matrix"

# Map IATA departure airport to Travelpayouts 'market' code.
# The market determines which regional search cache is queried.
# Reuses country codes that are close to Travelpayouts market codes.
_IATA_TO_MARKET: Dict[str, str] = {
    # Germany
    "BER": "de", "MUC": "de", "FRA": "de", "HAM": "de", "DUS": "de",
    # UK
    "LHR": "uk", "LGW": "uk", "STN": "uk", "MAN": "uk", "EDI": "uk",
    # France
    "CDG": "fr", "ORY": "fr", "NCE": "fr", "LYS": "fr",
    # Netherlands / Belgium / Switzerland / Austria
    "AMS": "nl", "BRU": "be", "ZRH": "ch", "GVA": "ch", "VIE": "at",
    # Italy / Spain / Portugal
    "FCO": "it", "MXP": "it", "MAD": "es", "BCN": "es", "LIS": "pt",
    # Scandinavia
    "CPH": "dk", "ARN": "se", "OSL": "no", "HEL": "fi",
    # Eastern Europe
    "WAW": "pl", "PRG": "cz", "BUD": "hu",
    # US / Canada
    "JFK": "us", "LAX": "us", "SFO": "us", "ORD": "us", "MIA": "us",
    "ATL": "us", "YYZ": "ca", "YUL": "ca", "YVR": "ca",
    # Asia
    "NRT": "jp", "ICN": "kr", "SIN": "sg", "BKK": "th",
    "DEL": "in", "DXB": "ae", "HKG": "hk",
    # Oceania
    "SYD": "au", "AKL": "nz",
    # South America
    "GRU": "br", "EZE": "ar",
}


def _get_market_from_iata(iata_code: str) -> str:
    """Derive Travelpayouts 'market' from departure IATA code. Defaults to 'us'."""
    return _IATA_TO_MARKET.get(iata_code, "us")


def _get_travelpayouts_token() -> Optional[str]:
    """
    Retrieve the Travelpayouts API token from environment variables.

    Returns:
        The API token string if found, None otherwise.
    """
    token = os.getenv("SECRET__TRAVELPAYOUTS__API_KEY")
    if token and token.strip():
        logger.debug("Successfully retrieved Travelpayouts token from environment variables")
        return token.strip()

    logger.error(
        "Travelpayouts API token not found. Set SECRET__TRAVELPAYOUTS__API_KEY in .env. "
        "Get a token from: https://app.travelpayouts.com/profile/api-token"
    )
    return None


# ---------------------------------------------------------------------------
# TravelpayoutsProvider
# ---------------------------------------------------------------------------

class TravelpayoutsProvider:
    """
    Price calendar provider using the Travelpayouts month-matrix API.

    Returns the cheapest cached price for each day of a given month on a
    route. Data comes from Aviasales user search history (up to 48h old).

    This is NOT a BaseTransportProvider — it doesn't search for connections.
    It's a standalone provider used by the PriceCalendarSkill.
    """

    async def get_price_calendar(
        self,
        origin: str,
        destination: str,
        month: str,
        currency: str = "eur",
    ) -> List[PriceCalendarEntry]:
        """
        Fetch the monthly price calendar for a route.

        Args:
            origin: IATA airport/city code (e.g., 'MUC').
            destination: IATA airport/city code (e.g., 'LON').
            month: Month to query as 'YYYY-MM-DD' (first day of month)
                   or 'YYYY-MM' (will be normalized to first day).
            currency: Price currency code (e.g., 'eur', 'usd').

        Returns:
            List of PriceCalendarEntry objects, one per day that has data.
            Empty list if no data available or API error.
        """
        token = _get_travelpayouts_token()
        if not token:
            raise ValueError("Travelpayouts API token not available")

        # Normalize month to YYYY-MM-DD (API expects first day of month)
        if len(month) == 7:  # "YYYY-MM"
            month = f"{month}-01"

        market = _get_market_from_iata(origin)

        params: Dict[str, Any] = {
            "origin": origin,
            "destination": destination,
            "currency": currency.lower(),
            "month": month,
            "show_to_affiliates": "true",
            "limit": "31",
            "market": market,
            "token": token,
        }

        data = await self._api_get(params)
        if data is None:
            return []

        if not data.get("success"):
            logger.error(f"Travelpayouts API returned success=false: {data}")
            return []

        raw_entries = data.get("data", [])
        if not raw_entries:
            logger.info(
                f"No price calendar data for {origin}->{destination} in {month} "
                f"(market={market}). Route may have no cached searches."
            )
            return []

        # Parse entries into PriceCalendarEntry objects
        entries: List[PriceCalendarEntry] = []
        for raw in raw_entries:
            try:
                entries.append(PriceCalendarEntry(
                    date=raw["depart_date"],
                    price=float(raw["value"]),
                    transfers=raw.get("number_of_changes"),
                    duration_minutes=raw.get("duration"),
                    distance_km=raw.get("distance"),
                    actual=raw.get("actual", True),
                ))
            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"Skipping malformed price entry: {e}")
                continue

        # Sort by date for clean calendar rendering
        entries.sort(key=lambda e: e.date)

        logger.info(
            f"Travelpayouts price calendar: {origin}->{destination} {month}, "
            f"{len(entries)} day(s) with data, "
            f"price range {min(e.price for e in entries):.0f}-"
            f"{max(e.price for e in entries):.0f} {currency.upper()}"
        )
        return entries

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    async def _api_get(self, params: Dict[str, Any]) -> Optional[dict]:
        """Make an async GET request to the Travelpayouts API."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(TRAVELPAYOUTS_BASE, params=params)

            if response.status_code == 401:
                logger.error("Travelpayouts API: Unauthorized (401). Check API token.")
                return None

            if response.status_code == 429:
                logger.warning("Travelpayouts API: Rate limited (429). Try again later.")
                return None

            if response.status_code != 200:
                logger.error(
                    f"Travelpayouts API error ({response.status_code}): "
                    f"{response.text[:500]}"
                )
                return None

            return response.json()

        except httpx.TimeoutException:
            logger.error("Travelpayouts API request timed out (30s)")
            return None
        except Exception as e:
            logger.error(f"Travelpayouts API request error: {e}", exc_info=True)
            return None
