"""
Base transport provider abstraction for the travel app.

Defines unified data models (ConnectionResult, LegResult, SegmentResult,
PriceCalendarEntry) and the abstract BaseTransportProvider class that all
transport providers must implement. This enables a clean separation between
the skill layer and individual provider APIs (SerpAPI/Google Flights for
flights, Travelpayouts for price calendars, Transitous for trains/buses, etc.).
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

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
    mode: Optional[str] = Field(default=None, description="Transport mode for this segment, such as train, bus, tram, subway, ferry, walk, bike, or airplane")
    line: Optional[str] = Field(default=None, description="Public transport line, route short name, or train/flight number")
    operator: Optional[str] = Field(default=None, description="Operator name when available")
    source_provider: Optional[str] = Field(default=None, description="Provider that supplied this segment")
    fare_coverage: Optional[str] = Field(default=None, description="Fare coverage for this segment: paid, pass_covered, timetable_only, or unknown")
    departure_station: str = Field(description="Departure airport code or station name")
    departure_time: str = Field(description="Departure time in ISO 8601 format")
    scheduled_departure_time: Optional[str] = Field(default=None, description="Scheduled departure time in ISO 8601 format")
    actual_departure_time: Optional[str] = Field(default=None, description="Realtime/forecast departure time in ISO 8601 format")
    departure_delay_minutes: Optional[int] = Field(default=None, description="Departure delay in minutes; negative means early")
    departure_platform: Optional[str] = Field(default=None, description="Scheduled/current departure platform or track")
    departure_platform_changed: Optional[bool] = Field(default=None, description="True if the realtime departure platform differs from schedule")
    departure_latitude: Optional[float] = Field(default=None, description="Departure location latitude")
    departure_longitude: Optional[float] = Field(default=None, description="Departure location longitude")
    arrival_station: str = Field(description="Arrival airport code or station name")
    arrival_time: str = Field(description="Arrival time in ISO 8601 format")
    scheduled_arrival_time: Optional[str] = Field(default=None, description="Scheduled arrival time in ISO 8601 format")
    actual_arrival_time: Optional[str] = Field(default=None, description="Realtime/forecast arrival time in ISO 8601 format")
    arrival_delay_minutes: Optional[int] = Field(default=None, description="Arrival delay in minutes; negative means early")
    arrival_platform: Optional[str] = Field(default=None, description="Scheduled/current arrival platform or track")
    arrival_platform_changed: Optional[bool] = Field(default=None, description="True if the realtime arrival platform differs from schedule")
    arrival_latitude: Optional[float] = Field(default=None, description="Arrival location latitude")
    arrival_longitude: Optional[float] = Field(default=None, description="Arrival location longitude")
    duration: str = Field(description="Segment duration (e.g., '2h 30m')")
    cancelled: Optional[bool] = Field(default=None, description="True if the segment or a relevant stop is cancelled")
    realtime_notes: Optional[List[str]] = Field(default=None, description="Realtime disruption, cancellation, or status notes")
    # Country codes for flag emoji display (ISO 3166-1 alpha-2, e.g., 'DE', 'TH')
    departure_country_code: Optional[str] = Field(default=None, description="ISO 3166-1 alpha-2 country code of departure airport")
    arrival_country_code: Optional[str] = Field(default=None, description="ISO 3166-1 alpha-2 country code of arrival airport")
    # Daytime indicators for time badge color coding (sunrise/sunset-aware)
    departure_is_daytime: Optional[bool] = Field(default=None, description="True if departure is between sunrise and sunset at the airport")
    arrival_is_daytime: Optional[bool] = Field(default=None, description="True if arrival is between sunrise and sunset at the airport")
    # Rich metadata from Google Flights via SerpAPI
    airplane: Optional[str] = Field(default=None, description="Aircraft type (e.g., 'Airbus A321neo', 'Boeing 787')")
    airline_logo: Optional[str] = Field(default=None, description="URL to airline logo image")
    legroom: Optional[str] = Field(default=None, description="Legroom info (e.g., '29 in', '32 in')")
    travel_class: Optional[str] = Field(default=None, description="Actual cabin class (e.g., 'Economy', 'Business')")
    extensions: Optional[List[str]] = Field(default=None, description="Tags/features (e.g., 'Wi-Fi for a fee', 'In-seat USB outlet')")
    often_delayed: Optional[bool] = Field(default=None, description="True if flight is often delayed by >30 min")


class LayoverResult(BaseModel):
    """Layover between segments within a leg."""

    airport: str = Field(description="Layover airport name (e.g., 'Barcelona-El Prat Airport')")
    airport_code: Optional[str] = Field(default=None, description="IATA code of the layover airport (e.g., 'BCN')")
    duration: Optional[str] = Field(default=None, description="Layover duration (e.g., '2h 15m')")
    duration_minutes: Optional[int] = Field(default=None, description="Layover duration in minutes")
    overnight: Optional[bool] = Field(default=None, description="True if layover spans overnight")
    latitude: Optional[float] = Field(default=None, description="Transfer location latitude when known")
    longitude: Optional[float] = Field(default=None, description="Transfer location longitude when known")
    meets_min_transfer: Optional[bool] = Field(default=None, description="Whether this transfer meets the requested minimum transfer time")
    amenities: Optional[Dict[str, Any]] = Field(default=None, description="Source-labelled transfer amenity summary")


class LegResult(BaseModel):
    """One leg of a trip (e.g., outbound, return, or a multi-stop segment)."""

    leg_index: int = Field(description="Zero-based index of this leg within the trip")
    origin: str = Field(description="Origin location with code (e.g., 'Munich (MUC)')")
    destination: str = Field(description="Destination location with code (e.g., 'London Heathrow (LHR)')")
    departure: str = Field(description="Departure time in ISO 8601 format")
    scheduled_departure: Optional[str] = Field(default=None, description="Scheduled departure time in ISO 8601 format")
    actual_departure: Optional[str] = Field(default=None, description="Realtime/forecast departure time in ISO 8601 format")
    departure_delay_minutes: Optional[int] = Field(default=None, description="Departure delay in minutes; negative means early")
    arrival: str = Field(description="Arrival time in ISO 8601 format")
    scheduled_arrival: Optional[str] = Field(default=None, description="Scheduled arrival time in ISO 8601 format")
    actual_arrival: Optional[str] = Field(default=None, description="Realtime/forecast arrival time in ISO 8601 format")
    arrival_delay_minutes: Optional[int] = Field(default=None, description="Arrival delay in minutes; negative means early")
    duration: str = Field(description="Total leg duration (e.g., '2h 30m')")
    stops: int = Field(description="Number of intermediate stops/transfers")
    segments: List[SegmentResult] = Field(default_factory=list, description="Ordered list of segments")
    layovers: Optional[List[LayoverResult]] = Field(default=None, description="Layover details between segments")


class FareResult(BaseModel):
    """Structured fare metadata for a connection option."""

    amount: Optional[float] = Field(default=None, description="Confirmed fare amount, or null when pass-only, unknown, or timetable-only")
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code for amount")
    is_partial: bool = Field(default=False, description="True when amount covers only the paid portion of an itinerary")
    is_pass_only: bool = Field(default=False, description="True when the route is covered by owned passes with no additional fare returned")
    covered_by_passes: List[str] = Field(default_factory=list, description="Owned pass IDs considered or covering the fare")
    pricing_provider: Optional[str] = Field(default=None, description="Provider ID that confirmed the fare amount")
    confidence: str = Field(default="unknown", description="Fare confidence: confirmed, partial, pass_only, timetable_only, or unknown")
    summary: str = Field(default="", description="Short user-facing explanation of fare meaning")


class ConnectionResult(BaseModel):
    """A single connection option returned by a transport provider."""

    transport_method: str = Field(description="Transport type: 'airplane', 'train', 'bus', 'boat'")
    source_provider: Optional[str] = Field(default=None, description="Provider that returned this result (e.g., 'google_flights', 'deutsche_bahn')")
    total_price: Optional[str] = Field(default=None, description="Total price as string (e.g., '245.50')")
    currency: Optional[str] = Field(default=None, description="Price currency code (e.g., 'EUR')")
    bookable_seats: Optional[int] = Field(default=None, description="Number of remaining bookable seats")
    last_ticketing_date: Optional[str] = Field(default=None, description="Last date to purchase (YYYY-MM-DD)")
    booking_url: Optional[str] = Field(default=None, description="Direct airline booking URL")
    booking_provider: Optional[str] = Field(default=None, description="Name of the booking provider (e.g., 'Lufthansa')")
    booking_token: Optional[str] = Field(
        default=None,
        description="SerpAPI booking token for on-demand booking URL lookup via /v1/apps/travel/booking-link"
    )
    booking_context: Optional[Dict[str, str]] = Field(
        default=None,
        description="Original SerpAPI search parameters needed for booking_token lookup "
        "(departure_id, arrival_id, outbound_date, return_date, type, currency, gl, adults, travel_class)"
    )
    fare_is_partial: Optional[bool] = Field(
        default=None,
        description="True when the quoted fare only covers the paid portion of the itinerary, such as pass-covered regional legs",
    )
    fare_passes_applied: Optional[List[str]] = Field(
        default=None,
        description="Owned fare pass IDs considered by the provider for this quote, such as deutschland_ticket",
    )
    fare: Optional[FareResult] = Field(default=None, description="Structured fare metadata for this connection")
    validating_airline_code: Optional[str] = Field(
        default=None, description="IATA code of the validating/ticketing airline (e.g., 'LH')"
    )
    legs: List[LegResult] = Field(default_factory=list, description="Ordered list of trip legs")
    # Country codes for route header flag emojis (ISO 3166-1 alpha-2)
    origin_country_code: Optional[str] = Field(default=None, description="ISO 3166-1 alpha-2 country code of origin airport")
    destination_country_code: Optional[str] = Field(default=None, description="ISO 3166-1 alpha-2 country code of final destination airport")
    # Rich metadata from Google Flights via SerpAPI
    airline_logo: Optional[str] = Field(default=None, description="URL to primary airline logo image")
    co2_kg: Optional[int] = Field(default=None, description="CO2 emissions in kg for this connection")
    co2_typical_kg: Optional[int] = Field(default=None, description="Typical CO2 emissions in kg for this route")
    co2_difference_percent: Optional[int] = Field(default=None, description="CO2 difference vs typical (e.g., -7 = 7% less)")
    transfer_quality: Optional[Dict[str, Any]] = Field(default=None, description="Transfer buffer and enrichment metadata")
    optimization: Optional[Dict[str, Any]] = Field(default=None, description="OpenMates route optimization metadata")


# ---------------------------------------------------------------------------
# Price calendar data models
# ---------------------------------------------------------------------------

class PriceCalendarEntry(BaseModel):
    """One day in a price calendar — the cheapest price found for that date."""

    date: str = Field(description="Departure date (YYYY-MM-DD)")
    price: float = Field(description="Cheapest price found for this date")
    transfers: Optional[int] = Field(default=None, description="Number of stops/transfers for the cheapest option")
    duration_minutes: Optional[int] = Field(default=None, description="Flight duration in minutes")
    distance_km: Optional[int] = Field(default=None, description="Route distance in km")
    actual: bool = Field(default=True, description="Whether this price is still current (not expired)")


# ---------------------------------------------------------------------------
# Abstract provider base class
# ---------------------------------------------------------------------------

class BaseTransportProvider(ABC):
    """
    Abstract base class for transport connection providers.

    Each provider implements search_connections() to query their upstream API
    and return results in the unified ConnectionResult format.
    """

    provider_id: str = ""
    supported_countries: Optional[set[str]] = None

    @abstractmethod
    async def search_connections(
        self,
        legs: List[dict],
        passengers: int,
        travel_class: str,
        max_results: int,
        non_stop_only: bool,
        currency: str,
        children: int = 0,
        infants_in_seat: int = 0,
        infants_on_lap: int = 0,
        max_stops: Optional[int] = None,
        include_airlines: Optional[List[str]] = None,
        exclude_airlines: Optional[List[str]] = None,
        owned_passes: Optional[List[str]] = None,
        pass_only: bool = False,
        rail_products: Optional[List[str]] = None,
        min_transfer_minutes: Optional[int] = None,
        cache_service: Any = None,
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
            children: Number of child passengers (ages 2-11).
            infants_in_seat: Number of infants with own seat (under 2).
            infants_on_lap: Number of lap infants (under 2).
            max_stops: Maximum stops allowed (0/1/2). Overrides non_stop_only when set.
            include_airlines: Only show flights from these airlines (IATA codes).
            exclude_airlines: Exclude flights from these airlines (IATA codes).
            owned_passes: Fare/pass IDs the traveller already owns.
            pass_only: If True, return routes covered by owned passes when supported.
            rail_products: Stable OpenMates rail product filters for providers that support them.

        Returns:
            List of ConnectionResult objects in the unified format.
        """
        ...

    @abstractmethod
    def supports_transport_method(self, method: str) -> bool:
        """Check whether this provider supports a given transport method."""
        ...
