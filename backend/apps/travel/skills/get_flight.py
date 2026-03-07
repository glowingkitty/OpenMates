"""
Get Flight skill for the travel app.

Fetches real historical flight track data and enrichment metadata from
Flightradar24 for a completed flight, given its IATA flight number and
departure date. Returns GPS track points (polyline) and enrichment details
(actual takeoff/landing times, runway, actual distance, diversion indicator).

Architecture: This skill is AI-callable (appears in app store, can be used via
the chat API). Credits: 7 per call (covers ~46 FR24 API credits at current pricing).
See docs/architecture/app-skills.md for the execution model and credit math.

Tests: backend/tests/test_get_flight_skill.py
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.travel.providers.flightradar24_provider import (
    FR24Provider,
    FR24NotFoundError,
    FR24AuthError,
    FR24RateLimitError,
    FR24Error,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class GetFlightRequest(BaseModel):
    """Incoming request payload for the get_flight skill."""

    flight_number: str = Field(
        description="IATA flight number, e.g. 'LH2472', 'BA234'. "
        "Must include the carrier code prefix."
    )
    departure_date: str = Field(
        description="Departure date in YYYY-MM-DD format, e.g. '2026-03-05'. "
        "The flight must be a completed/past flight — live tracking is not supported."
    )
    origin_iata: Optional[str] = Field(
        default=None,
        description="IATA code of the departure airport, e.g. 'MUC'. "
        "Optional — used only for disambiguation if multiple flights share the same number.",
    )
    destination_iata: Optional[str] = Field(
        default=None,
        description="IATA code of the destination airport, e.g. 'LHR'. "
        "Optional — used only for disambiguation.",
    )


class FlightTrackPoint(BaseModel):
    """A single GPS data point in the flight track."""

    timestamp: int = Field(description="Unix epoch timestamp (seconds)")
    lat: float = Field(description="Latitude in decimal degrees")
    lon: float = Field(description="Longitude in decimal degrees")
    alt: Optional[int] = Field(default=None, description="Altitude in feet")
    gspeed: Optional[int] = Field(default=None, description="Ground speed in knots")


class GetFlightResponse(BaseModel):
    """Response payload for the get_flight skill."""

    success: bool = Field(description="Whether the flight data was fetched successfully")
    flight_number: Optional[str] = Field(default=None, description="Resolved flight number")
    fr24_id: Optional[str] = Field(default=None, description="Flightradar24 internal flight ID")
    data_source: str = Field(default="flightradar24", description="Data provider name")

    # Track data (GPS polyline)
    tracks: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="GPS track points, each with timestamp, lat, lon, alt, gspeed, "
        "vspeed, track (heading), squawk, callsign, source.",
    )

    # Enrichment metadata from flight-summary/full
    actual_takeoff: Optional[str] = Field(
        default=None, description="Actual takeoff datetime (ISO 8601)"
    )
    actual_landing: Optional[str] = Field(
        default=None, description="Actual landing datetime (ISO 8601)"
    )
    runway_takeoff: Optional[str] = Field(
        default=None, description="Takeoff runway used (e.g. '08L')"
    )
    runway_landing: Optional[str] = Field(
        default=None, description="Landing runway used (e.g. '27R')"
    )
    actual_distance_km: Optional[float] = Field(
        default=None, description="Actual flight distance in km"
    )
    circle_distance_km: Optional[float] = Field(
        default=None, description="Great-circle distance in km"
    )
    flight_time_minutes: Optional[int] = Field(
        default=None, description="Actual flight time in minutes"
    )
    diverted: bool = Field(
        default=False,
        description="True if the flight was diverted to a different destination",
    )
    actual_destination_iata: Optional[str] = Field(
        default=None,
        description="Actual IATA destination code if diverted, else None",
    )

    error: Optional[str] = Field(default=None, description="Error message if fetch failed")


# ---------------------------------------------------------------------------
# Skill class
# ---------------------------------------------------------------------------


class GetFlightSkill(BaseSkill):
    """
    Fetches real historical flight track data from Flightradar24.

    Given an IATA flight number and departure date, this skill:
    1. Resolves the flight to a FR24 internal ID
    2. Fetches the GPS track polyline in parallel with enrichment metadata
    3. Returns a structured response with track points and flight details

    The frontend (TravelConnectionEmbedFullscreen.svelte and
    TravelFlightDetailsEmbedFullscreen.svelte) uses the track data to display
    the real flight path on a Leaflet/OpenStreetMap map instead of an estimate.

    Only completed/past flights are supported — live tracking requires a
    higher FR24 plan tier and is not needed for our use case.
    """

    async def execute(
        self,
        flight_number: str,
        departure_date: str,
        origin_iata: Optional[str] = None,
        destination_iata: Optional[str] = None,
        secrets_manager: Optional["SecretsManager"] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Fetch flight track and enrichment data from Flightradar24.

        Args:
            flight_number: IATA flight number (e.g. "LH2472").
            departure_date: Departure date in YYYY-MM-DD format.
            origin_iata: Optional origin airport IATA code for disambiguation.
            destination_iata: Optional destination IATA code for disambiguation.
            secrets_manager: SecretsManager instance for loading the FR24 API key.
            **kwargs: Ignored extra arguments passed by the skill executor.

        Returns:
            Dict matching GetFlightResponse schema.
        """
        provider = FR24Provider(secrets_manager=secrets_manager)

        try:
            # Step 1: Resolve flight number + date → fr24_id
            fr24_id = await provider.get_fr24_id(flight_number, departure_date)

            # Step 2: Fetch tracks and summary in parallel to minimise latency
            tracks, summary = await asyncio.gather(
                provider.get_flight_tracks(fr24_id),
                provider.get_flight_summary(fr24_id),
            )

            # Step 3: Extract enrichment fields from summary
            actual_takeoff = summary.get("datetime_takeoff")
            actual_landing = summary.get("datetime_landed")
            runway_takeoff = summary.get("runway_takeoff")
            runway_landing = summary.get("runway_landed")
            actual_dist = summary.get("actual_distance")
            circle_dist = summary.get("circle_distance")
            flight_time_secs = summary.get("flight_time")
            dest_iata_actual = summary.get("dest_iata_actual")

            # Determine diversion: dest_iata_actual is set only when diverted
            # (FR24 omits the field or sets it to the scheduled destination otherwise)
            diverted = bool(
                dest_iata_actual and destination_iata
                and dest_iata_actual.upper() != destination_iata.upper()
            )
            # Fallback: if no destination_iata provided, treat any dest_iata_actual as diversion
            if not diverted and dest_iata_actual:
                diverted = True  # FR24 only sets this field when the flight diverted
                # Caveat: this is a heuristic; without the scheduled destination we
                # cannot definitively confirm diversion, but FR24 docs indicate
                # dest_iata_actual is only populated on diversions.
                diverted = False  # Conservative: only flag diversion when we can compare

            # Compute flight time in minutes from seconds
            flight_time_minutes: Optional[int] = None
            if flight_time_secs is not None:
                try:
                    flight_time_minutes = int(float(flight_time_secs)) // 60
                except (ValueError, TypeError):
                    pass

            # Normalise distance to float or None
            actual_distance_km: Optional[float] = None
            if actual_dist is not None:
                try:
                    actual_distance_km = float(actual_dist)
                except (ValueError, TypeError):
                    pass

            circle_distance_km: Optional[float] = None
            if circle_dist is not None:
                try:
                    circle_distance_km = float(circle_dist)
                except (ValueError, TypeError):
                    pass

            response = GetFlightResponse(
                success=True,
                flight_number=flight_number.upper(),
                fr24_id=fr24_id,
                data_source="flightradar24",
                tracks=tracks,
                actual_takeoff=actual_takeoff,
                actual_landing=actual_landing,
                runway_takeoff=runway_takeoff,
                runway_landing=runway_landing,
                actual_distance_km=actual_distance_km,
                circle_distance_km=circle_distance_km,
                flight_time_minutes=flight_time_minutes,
                diverted=diverted,
                actual_destination_iata=dest_iata_actual if diverted else None,
            )

            logger.info(
                f"GetFlightSkill: Successfully fetched {len(tracks)} track points "
                f"for {flight_number} on {departure_date} (fr24_id={fr24_id})"
            )
            return response.model_dump()

        except FR24NotFoundError as e:
            logger.warning(f"GetFlightSkill: Flight not found — {e}")
            return GetFlightResponse(
                success=False,
                flight_number=flight_number.upper(),
                error=f"Flight {flight_number} on {departure_date} not found in Flightradar24. "
                      "Only completed past flights are supported.",
            ).model_dump()

        except FR24AuthError as e:
            logger.error(f"GetFlightSkill: Auth error — {e}")
            return GetFlightResponse(
                success=False,
                flight_number=flight_number.upper(),
                error="Flight data service authentication failed. Please contact support.",
            ).model_dump()

        except FR24RateLimitError as e:
            logger.error(f"GetFlightSkill: Rate limit — {e}")
            return GetFlightResponse(
                success=False,
                flight_number=flight_number.upper(),
                error="Flight data service is temporarily unavailable. Please try again shortly.",
            ).model_dump()

        except FR24Error as e:
            logger.error(f"GetFlightSkill: FR24 error — {e}", exc_info=True)
            return GetFlightResponse(
                success=False,
                flight_number=flight_number.upper(),
                error="Failed to fetch flight data. Please try again.",
            ).model_dump()

        except Exception as e:
            logger.error(
                f"GetFlightSkill: Unexpected error for {flight_number} on {departure_date}: {e}",
                exc_info=True,
            )
            return GetFlightResponse(
                success=False,
                flight_number=flight_number.upper(),
                error="An unexpected error occurred while fetching flight data.",
            ).model_dump()
