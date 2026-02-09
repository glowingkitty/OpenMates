"""
Base transport provider abstraction for the travel app.

Defines unified data models (ConnectionResult, LegResult, SegmentResult) and
the abstract BaseTransportProvider class that all transport providers must implement.
This enables a clean separation between the skill layer and individual provider APIs
(Duffel for flights, Transitous for trains/buses, etc.).
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unified data models
# ---------------------------------------------------------------------------

class SegmentResult(BaseModel):
    """A single segment within a leg (e.g., one flight in a connecting itinerary)."""

    carrier: str = Field(description="Carrier/operator name (e.g., 'Lufthansa', 'Deutsche Bahn')")
    carrier_code: Optional[str] = Field(default=None, description="IATA carrier code (e.g., 'LH')")
    number: Optional[str] = Field(default=None, description="Flight/train number (e.g., 'LH2472', 'ICE 1234')")
    departure_station: str = Field(description="Departure airport code or station name")
    departure_time: str = Field(description="Departure time in ISO 8601 format")
    departure_latitude: Optional[float] = Field(default=None, description="Departure location latitude")
    departure_longitude: Optional[float] = Field(default=None, description="Departure location longitude")
    arrival_station: str = Field(description="Arrival airport code or station name")
    arrival_time: str = Field(description="Arrival time in ISO 8601 format")
    arrival_latitude: Optional[float] = Field(default=None, description="Arrival location latitude")
    arrival_longitude: Optional[float] = Field(default=None, description="Arrival location longitude")
    duration: str = Field(description="Segment duration (e.g., '2h 30m')")


class LegResult(BaseModel):
    """One leg of a trip (e.g., outbound, return, or a multi-stop segment)."""

    leg_index: int = Field(description="Zero-based index of this leg within the trip")
    origin: str = Field(description="Origin location with code (e.g., 'Munich (MUC)')")
    destination: str = Field(description="Destination location with code (e.g., 'London Heathrow (LHR)')")
    departure: str = Field(description="Departure time in ISO 8601 format")
    arrival: str = Field(description="Arrival time in ISO 8601 format")
    duration: str = Field(description="Total leg duration (e.g., '2h 30m')")
    stops: int = Field(description="Number of intermediate stops/transfers")
    segments: List[SegmentResult] = Field(default_factory=list, description="Ordered list of segments")


class ConnectionResult(BaseModel):
    """A single connection option returned by a transport provider."""

    transport_method: str = Field(description="Transport type: 'airplane', 'train', 'bus', 'boat'")
    total_price: Optional[str] = Field(default=None, description="Total price as string (e.g., '245.50')")
    currency: Optional[str] = Field(default=None, description="Price currency code (e.g., 'EUR')")
    bookable_seats: Optional[int] = Field(default=None, description="Number of remaining bookable seats")
    last_ticketing_date: Optional[str] = Field(default=None, description="Last date to purchase (YYYY-MM-DD)")
    booking_url: Optional[str] = Field(default=None, description="Direct airline booking URL")
    booking_provider: Optional[str] = Field(default=None, description="Name of the booking provider (e.g., 'Lufthansa')")
    validating_airline_code: Optional[str] = Field(
        default=None, description="IATA code of the validating/ticketing airline (e.g., 'LH')"
    )
    legs: List[LegResult] = Field(default_factory=list, description="Ordered list of trip legs")


# ---------------------------------------------------------------------------
# Abstract provider base class
# ---------------------------------------------------------------------------

class BaseTransportProvider(ABC):
    """
    Abstract base class for transport connection providers.

    Each provider implements search_connections() to query their upstream API
    and return results in the unified ConnectionResult format.
    """

    @abstractmethod
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
        Search for transport connections matching the given criteria.

        Args:
            legs: List of leg dicts, each with 'origin' (city name), 'destination' (city name),
                  and 'date' (YYYY-MM-DD).
            passengers: Number of adult passengers.
            travel_class: Cabin/travel class (e.g., 'economy', 'business').
            max_results: Maximum number of connection options to return.
            non_stop_only: If True, only return direct/non-stop connections.
            currency: Preferred currency for prices (ISO 4217 code).

        Returns:
            List of ConnectionResult objects in the unified format.
        """
        ...

    @abstractmethod
    def supports_transport_method(self, method: str) -> bool:
        """Check whether this provider supports a given transport method."""
        ...
