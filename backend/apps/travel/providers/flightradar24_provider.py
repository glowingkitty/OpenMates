"""
Flightradar24 (FR24) API provider for the travel app.

Fetches real historical flight track data (polyline) and enrichment metadata
(actual departure/arrival times, runway used, actual distance, diversion info)
for a completed flight. Used by the get_flight skill.

Architecture: Direct async HTTP via httpx.AsyncClient, authenticated with a
Bearer token loaded from SecretsManager (SECRET__FLIGHTRADAR24__API_KEY).
See docs/architecture/app-skills.md for the skill execution model.

Tests: backend/tests/test_flightradar24_provider.py
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import httpx

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FR24_BASE_URL = "https://fr24api.flightradar24.com/api"
FR24_API_VERSION = "v1"

# Timeout in seconds for FR24 HTTP requests
FR24_REQUEST_TIMEOUT_SECONDS = 20.0

# Secret name for the FR24 API key in Vault / .env
FR24_SECRET_KEY_NAME = "SECRET__FLIGHTRADAR24__API_KEY"

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class FR24Error(Exception):
    """Base exception for all FR24 provider errors."""


class FR24NotFoundError(FR24Error):
    """Raised when no flight is found matching the given flight number and date."""


class FR24RateLimitError(FR24Error):
    """Raised when the FR24 API rate limit is exceeded (HTTP 429)."""


class FR24AuthError(FR24Error):
    """Raised when the FR24 API key is invalid or missing (HTTP 401/403)."""


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class FR24Provider:
    """
    Flightradar24 API client for fetching completed flight track data.

    Provides three main methods:
    1. get_fr24_id() — resolve flight number + date → fr24_id (internal FR24 flight ID)
    2. get_flight_tracks() — fetch per-point GPS track (polyline) for a flight
    3. get_flight_summary() — fetch enrichment: actual times, runway, distance, diversion

    Storage rule: Fetched track data must NOT be stored for more than 30 days
    (FR24 API ToS). The persist-to-embed mechanism in the frontend handles this
    by design since embed data follows the user's data retention settings.
    """

    def __init__(self, secrets_manager: Optional["SecretsManager"] = None) -> None:
        """
        Initialise the FR24 provider.

        Args:
            secrets_manager: Optional SecretsManager for loading the API key
                from Vault. If None, the key must be available as an env var.
        """
        self._secrets_manager = secrets_manager
        self._api_key: Optional[str] = None

    async def _get_api_key(self) -> str:
        """
        Load and cache the FR24 API key from SecretsManager (Vault / .env).

        Raises:
            ValueError: If the API key is not configured.
        """
        if self._api_key:
            return self._api_key

        if self._secrets_manager:
            key = await self._secrets_manager.get_secret(FR24_SECRET_KEY_NAME)
        else:
            import os
            key = os.environ.get(FR24_SECRET_KEY_NAME)

        if not key:
            raise ValueError(
                f"FR24 API key not configured. "
                f"Set {FR24_SECRET_KEY_NAME} in Vault or .env"
            )

        self._api_key = key
        return self._api_key

    def _build_headers(self, api_key: str) -> Dict[str, str]:
        """Return the required HTTP headers for FR24 API requests."""
        return {
            "Authorization": f"Bearer {api_key}",
            "Accept-Version": FR24_API_VERSION,
            "Accept": "application/json",
        }

    def _handle_response_status(self, response: httpx.Response, context: str) -> None:
        """
        Raise a typed exception based on the HTTP status code.

        Args:
            response: The httpx Response object.
            context: Human-readable context string for error messages.

        Raises:
            FR24AuthError: On 401/403.
            FR24RateLimitError: On 429.
            FR24NotFoundError: On 404.
            FR24Error: On any other non-2xx status.
        """
        if response.status_code == 401 or response.status_code == 403:
            raise FR24AuthError(
                f"FR24 authentication failed for {context} "
                f"(HTTP {response.status_code}). Check {FR24_SECRET_KEY_NAME}."
            )
        if response.status_code == 429:
            raise FR24RateLimitError(
                f"FR24 rate limit exceeded for {context}. "
                "Retry after some time or upgrade the FR24 plan."
            )
        if response.status_code == 404:
            raise FR24NotFoundError(
                f"FR24: Not found for {context} (HTTP 404)."
            )
        if response.status_code >= 400:
            raise FR24Error(
                f"FR24 API error for {context}: "
                f"HTTP {response.status_code} — {response.text[:200]}"
            )

    async def get_fr24_id(
        self,
        flight_number: str,
        departure_date: str,
    ) -> str:
        """
        Resolve an IATA flight number and departure date to a FR24 internal flight ID.

        Uses the flight-summary/light endpoint (~3 FR24 credits).

        Args:
            flight_number: IATA flight number, e.g. "LH2472".
            departure_date: Departure date in YYYY-MM-DD format, e.g. "2026-03-05".

        Returns:
            fr24_id string, e.g. "3b5c7a1d30a2".

        Raises:
            FR24NotFoundError: If no flight matches the query.
            FR24AuthError: On authentication failure.
            FR24RateLimitError: On rate limit.
            FR24Error: On other API errors.
        """
        api_key = await self._get_api_key()
        headers = self._build_headers(api_key)

        # Build the datetime range covering the full departure day
        datetime_from = f"{departure_date}T00:00:00"
        datetime_to = f"{departure_date}T23:59:59"

        params = {
            "flights": flight_number,
            "flight_datetime_from": datetime_from,
            "flight_datetime_to": datetime_to,
        }

        logger.info(
            f"FR24: Fetching fr24_id for flight {flight_number} on {departure_date}"
        )

        async with httpx.AsyncClient(timeout=FR24_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{FR24_BASE_URL}/flight-summary/light",
                headers=headers,
                params=params,
            )

        self._handle_response_status(
            response,
            context=f"flight-summary/light flight={flight_number} date={departure_date}",
        )

        data = response.json()

        # The response is {"data": [...]} where each item has "fr24_id"
        items: List[Dict[str, Any]] = data.get("data", [])
        if not items:
            raise FR24NotFoundError(
                f"FR24: No flight found for {flight_number} on {departure_date}"
            )

        # Take the first match (closest to the requested date)
        fr24_id: Optional[str] = items[0].get("fr24_id")
        if not fr24_id:
            raise FR24NotFoundError(
                f"FR24: Response for {flight_number} on {departure_date} "
                "has no fr24_id field"
            )

        logger.info(f"FR24: Resolved {flight_number} → fr24_id={fr24_id}")
        return fr24_id

    async def get_flight_tracks(self, fr24_id: str) -> List[Dict[str, Any]]:
        """
        Fetch the GPS track points for a completed flight.

        Uses the flight-tracks endpoint (~40 FR24 credits).

        Args:
            fr24_id: FR24 internal flight ID from get_fr24_id().

        Returns:
            List of track point dicts, each with keys:
                - timestamp: int (Unix epoch)
                - lat: float (degrees)
                - lon: float (degrees)
                - alt: int (feet)
                - gspeed: int (knots)
                - vspeed: int (feet/min)
                - track: int (heading degrees 0–359)
                - squawk: str
                - callsign: str
                - source: str

        Raises:
            FR24NotFoundError: If the flight has no track data.
            FR24AuthError: On authentication failure.
            FR24RateLimitError: On rate limit.
            FR24Error: On other API errors.
        """
        api_key = await self._get_api_key()
        headers = self._build_headers(api_key)

        logger.info(f"FR24: Fetching flight tracks for fr24_id={fr24_id}")

        async with httpx.AsyncClient(timeout=FR24_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{FR24_BASE_URL}/flight-tracks",
                headers=headers,
                params={"flight_id": fr24_id},
            )

        self._handle_response_status(
            response,
            context=f"flight-tracks fr24_id={fr24_id}",
        )

        data = response.json()

        # Response schema: {"data": {"tracks": [...]} }
        # or {"tracks": [...]} depending on the endpoint version
        tracks: List[Dict[str, Any]] = (
            data.get("data", {}).get("tracks")
            or data.get("tracks")
            or []
        )

        if not tracks:
            raise FR24NotFoundError(
                f"FR24: No track points found for fr24_id={fr24_id}"
            )

        logger.info(
            f"FR24: Got {len(tracks)} track points for fr24_id={fr24_id}"
        )
        return tracks

    async def get_flight_summary(self, fr24_id: str) -> Dict[str, Any]:
        """
        Fetch enrichment metadata for a completed flight.

        Uses the flight-summary/full endpoint (~3 FR24 credits).

        Args:
            fr24_id: FR24 internal flight ID from get_fr24_id().

        Returns:
            Dict with enrichment fields, including:
                - runway_takeoff: str (e.g. "08L")
                - runway_landed: str (e.g. "27R")
                - actual_distance: float (km)
                - circle_distance: float (km, great-circle)
                - flight_time: int (seconds)
                - datetime_takeoff: str (ISO 8601)
                - datetime_landed: str (ISO 8601)
                - dest_icao_actual: str (actual destination ICAO if diverted)
                - dest_iata_actual: str (actual destination IATA if diverted)
                - category: str (e.g. "A1", "B2")

        Raises:
            FR24NotFoundError: If no summary is found.
            FR24AuthError: On authentication failure.
            FR24RateLimitError: On rate limit.
            FR24Error: On other API errors.
        """
        api_key = await self._get_api_key()
        headers = self._build_headers(api_key)

        logger.info(f"FR24: Fetching flight summary (full) for fr24_id={fr24_id}")

        async with httpx.AsyncClient(timeout=FR24_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{FR24_BASE_URL}/flight-summary/full",
                headers=headers,
                params={"flight_ids": fr24_id},
            )

        self._handle_response_status(
            response,
            context=f"flight-summary/full fr24_id={fr24_id}",
        )

        data = response.json()

        # Response schema: {"data": [{...enrichment fields...}]}
        items: List[Dict[str, Any]] = data.get("data", [])
        if not items:
            raise FR24NotFoundError(
                f"FR24: No summary found for fr24_id={fr24_id}"
            )

        summary = items[0]
        logger.info(
            f"FR24: Got flight summary for fr24_id={fr24_id}: "
            f"takeoff={summary.get('datetime_takeoff')}, "
            f"landed={summary.get('datetime_landed')}"
        )
        return summary
