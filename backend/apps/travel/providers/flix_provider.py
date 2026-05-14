# backend/apps/travel/providers/flix_provider.py
#
# FlixBus / FlixTrain transport provider for the travel app.
# Resolves user locations through Flix autocomplete, queries Flix trip search,
# and maps results into the unified travel connection schema.
# API research: docs/architecture/apps/travel-flix-api-research.md

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
    LayoverResult,
    LegResult,
    SegmentResult,
)
from backend.shared.providers.flix import autocomplete_locations, search_trips

logger = logging.getLogger(__name__)

BOOKING_LINK_REL = "shop:search"
SOURCE_PROVIDER = "flix"
DEFAULT_LOCALE = "en"
FLIXTRAIN_SUPPORTED_COUNTRIES = {"AT", "CH", "DE", "NL"}


def _format_date_for_flix(date_value: str) -> str:
    """Convert YYYY-MM-DD skill input to Flix DD.MM.YYYY input."""
    try:
        parsed = datetime.strptime(date_value, "%Y-%m-%d")
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return date_value


def _format_duration(duration: Optional[Dict[str, Any]]) -> str:
    if not duration:
        return ""
    hours = int(duration.get("hour") or 0)
    minutes = int(duration.get("minutes") or 0)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _duration_minutes(duration: Optional[Dict[str, Any]]) -> Optional[int]:
    if not duration:
        return None
    return int(duration.get("hour") or 0) * 60 + int(duration.get("minutes") or 0)


def _format_flix_time(time_value: Dict[str, Any]) -> str:
    """Convert Flix timestamp + GMT offset into ISO 8601."""
    timestamp = int(time_value.get("timestamp"))
    tz_value = str(time_value.get("tz") or "GMT+00:00")
    match = re.match(r"GMT([+-])(\d{2}):(\d{2})", tz_value)
    if not match:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    sign = 1 if match.group(1) == "+" else -1
    offset = timezone(sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3))))
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(offset).isoformat()


def _booking_url(trip: Dict[str, Any]) -> Optional[str]:
    for link in trip.get("links", []) or []:
        if link.get("rel") == BOOKING_LINK_REL and link.get("href"):
            return str(link["href"])
    return None


def _country_code(location: Dict[str, Any]) -> Optional[str]:
    country = location.get("country")
    if isinstance(country, dict):
        code = country.get("code") or country.get("alpha2_code")
        return str(code).upper() if code else None
    if isinstance(country, str):
        return country.upper()
    return None


def _result_transport_method(item: Dict[str, Any]) -> str:
    transfer_key = str(item.get("transfer_type_key") or "")
    if "train" in transfer_key:
        return "train"
    return "bus"


def _operator_name(operators: List[Dict[str, Any]], index: int, fallback: str) -> str:
    if index < len(operators):
        label = operators[index].get("label")
        if label:
            return str(label)
    return fallback


def _operator_code(operators: List[Dict[str, Any]], index: int) -> Optional[str]:
    if index < len(operators):
        key = operators[index].get("key")
        return str(key) if key else None
    return None


def _bookable_seats(item: Dict[str, Any]) -> Optional[int]:
    available = item.get("available") or {}
    seats = available.get("seats")
    if isinstance(seats, int) and seats < 999:
        return seats
    info_message = str(item.get("info_message") or "")
    match = re.search(r"(\d+)\s+seat", info_message)
    if match:
        return int(match.group(1))
    return None


def _build_segments(
    trip: Dict[str, Any],
    item: Dict[str, Any],
    transport_method: str,
) -> List[SegmentResult]:
    operators = item.get("operated_by", []) or []
    transfers = item.get("interconnection_transfers", []) or []
    origin = trip.get("from", {}) or {}
    destination = trip.get("to", {}) or {}
    departure = item.get("departure", {}) or {}
    arrival = item.get("arrival", {}) or {}

    if not transfers:
        return [
            SegmentResult(
                carrier=_operator_name(operators, 0, "FlixTrain" if transport_method == "train" else "FlixBus"),
                carrier_code=_operator_code(operators, 0),
                departure_station=str(origin.get("name") or "?"),
                departure_time=_format_flix_time(departure),
                departure_latitude=(origin.get("location") or {}).get("latitude"),
                departure_longitude=(origin.get("location") or {}).get("longitude"),
                arrival_station=str(destination.get("name") or "?"),
                arrival_time=_format_flix_time(arrival),
                arrival_latitude=(destination.get("location") or {}).get("latitude"),
                arrival_longitude=(destination.get("location") or {}).get("longitude"),
                duration=_format_duration(item.get("duration")),
                extensions=[amenity.get("label") for amenity in (item.get("amenities") or [[]])[0] if amenity.get("label")]
                or None,
            )
        ]

    segments: List[SegmentResult] = []
    current_station = str(origin.get("name") or "?")
    current_time = departure
    current_lat = (origin.get("location") or {}).get("latitude")
    current_lng = (origin.get("location") or {}).get("longitude")

    for index, transfer in enumerate(transfers):
        transfer_name = str(transfer.get("station_name") or "?")
        transfer_arrival = transfer.get("arrival", {}) or {}
        segment_duration = None
        try:
            segment_duration = int(transfer_arrival.get("timestamp")) - int(current_time.get("timestamp"))
        except (TypeError, ValueError):
            pass
        segments.append(SegmentResult(
            carrier=_operator_name(operators, index, "Flix"),
            carrier_code=_operator_code(operators, index),
            departure_station=current_station,
            departure_time=_format_flix_time(current_time),
            departure_latitude=current_lat,
            departure_longitude=current_lng,
            arrival_station=transfer_name,
            arrival_time=_format_flix_time(transfer_arrival),
            duration=_format_duration({"hour": segment_duration // 3600, "minutes": (segment_duration % 3600) // 60})
            if segment_duration is not None else "",
        ))
        current_station = transfer_name
        current_time = transfer.get("departure", {}) or transfer_arrival
        current_lat = None
        current_lng = None

    final_duration = None
    try:
        final_duration = int(arrival.get("timestamp")) - int(current_time.get("timestamp"))
    except (TypeError, ValueError):
        pass
    segments.append(SegmentResult(
        carrier=_operator_name(operators, len(transfers), "Flix"),
        carrier_code=_operator_code(operators, len(transfers)),
        departure_station=current_station,
        departure_time=_format_flix_time(current_time),
        arrival_station=str(destination.get("name") or "?"),
        arrival_time=_format_flix_time(arrival),
        arrival_latitude=(destination.get("location") or {}).get("latitude"),
        arrival_longitude=(destination.get("location") or {}).get("longitude"),
        duration=_format_duration({"hour": final_duration // 3600, "minutes": (final_duration % 3600) // 60})
        if final_duration is not None else "",
    ))
    return segments


def _build_layovers(transfers: List[Dict[str, Any]]) -> Optional[List[LayoverResult]]:
    layovers: List[LayoverResult] = []
    for transfer in transfers:
        duration = transfer.get("duration")
        arrival = transfer.get("arrival") or {}
        departure = transfer.get("departure") or {}
        overnight = False
        try:
            overnight = _format_flix_time(arrival)[:10] != _format_flix_time(departure)[:10]
        except (TypeError, ValueError):
            pass
        layovers.append(LayoverResult(
            airport=str(transfer.get("station_name") or "?"),
            duration=_format_duration(duration),
            duration_minutes=_duration_minutes(duration),
            overnight=overnight,
        ))
    return layovers or None


def _parse_connection(trip: Dict[str, Any], item: Dict[str, Any]) -> Optional[ConnectionResult]:
    origin = trip.get("from", {}) or {}
    destination = trip.get("to", {}) or {}
    departure = item.get("departure") or {}
    arrival = item.get("arrival") or {}
    if not origin or not destination or not departure or not arrival:
        return None

    transport_method = _result_transport_method(item)
    segments = _build_segments(trip, item, transport_method)
    if not segments:
        return None

    leg = LegResult(
        leg_index=0,
        origin=str(origin.get("name") or segments[0].departure_station),
        destination=str(destination.get("name") or segments[-1].arrival_station),
        departure=_format_flix_time(departure),
        arrival=_format_flix_time(arrival),
        duration=_format_duration(item.get("duration")),
        stops=len(item.get("interconnection_transfers", []) or []),
        segments=segments,
        layovers=_build_layovers(item.get("interconnection_transfers", []) or []),
    )
    price = item.get("price_total_sum")
    return ConnectionResult(
        transport_method=transport_method,
        source_provider=SOURCE_PROVIDER,
        total_price=f"{float(price):.2f}" if price is not None else None,
        currency=None,
        bookable_seats=_bookable_seats(item),
        booking_url=_booking_url(trip),
        booking_provider="FlixBus / FlixTrain",
        legs=[leg],
        origin_country_code=_country_code(origin),
        destination_country_code=_country_code(destination),
    )


class FlixProvider(BaseTransportProvider):
    """FlixBus / FlixTrain provider backed by Flix web/mobile JSON endpoints."""

    def __init__(self, supported_methods: Optional[Set[str]] = None) -> None:
        self.supported_methods = supported_methods or {"bus", "train"}
        self.provider_id = SOURCE_PROVIDER
        self.supported_countries = FLIXTRAIN_SUPPORTED_COUNTRIES if self.supported_methods == {"train"} else None
        self._location_cache: Dict[tuple[str, bool], Dict[str, Any]] = {}

    def supports_transport_method(self, method: str) -> bool:
        return method in self.supported_methods

    async def _resolve_location(self, query: str, train_only: bool) -> Optional[Dict[str, Any]]:
        key = (query.strip().lower(), train_only)
        if key in self._location_cache:
            return self._location_cache[key]
        results = await autocomplete_locations(query, train_only=train_only)
        if not results:
            return None
        location = results[0]
        self._location_cache[key] = location
        return location

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
    ) -> List[ConnectionResult]:
        train_only = self.supported_methods == {"train"}
        wanted_methods = self.supported_methods
        all_connections: List[ConnectionResult] = []

        for leg in legs:
            origin = str(leg.get("origin") or "")
            destination = str(leg.get("destination") or "")
            date = str(leg.get("date") or "")
            if not origin or not destination or not date:
                logger.warning("Flix provider: skipping leg with missing fields: %s", leg)
                continue

            origin_location = await self._resolve_location(origin, train_only=train_only)
            destination_location = await self._resolve_location(destination, train_only=train_only)
            if not origin_location or not destination_location:
                logger.warning("Flix provider: could not resolve route %s -> %s", origin, destination)
                continue

            payload = await search_trips(
                int(origin_location["legacy_id"]),
                int(destination_location["legacy_id"]),
                departure_date=_format_date_for_flix(date),
                search_by="cities",
                currency=currency,
                adults=passengers,
                children=children,
                bikes=0,
            )
            for trip in payload.get("trips", []) or []:
                for item in trip.get("items", []) or []:
                    parsed = _parse_connection(trip, item)
                    if not parsed or parsed.transport_method not in wanted_methods:
                        continue
                    parsed.currency = currency.upper()
                    if non_stop_only and parsed.legs and parsed.legs[0].stops > 0:
                        continue
                    if max_stops is not None and parsed.legs and parsed.legs[0].stops > max_stops:
                        continue
                    all_connections.append(parsed)
                    if len(all_connections) >= max_results:
                        return all_connections

        return all_connections
