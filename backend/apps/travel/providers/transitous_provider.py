"""
Transitous timetable provider for the travel app.

Implements timetable-only public transport routing with the current MOTIS API.
Transitous fare fields are not treated as prices in this slice because sampled
responses did not include usable amount/currency/booking data. Keep this
provider opt-in until production usage terms or self-hosting are settled.
"""

from __future__ import annotations

import logging
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
    FareResult,
    LayoverResult,
    LegResult,
    SegmentResult,
)

logger = logging.getLogger(__name__)

TRANSITOUS_BASE_URL = "https://api.transitous.org/api"
TRANSITOUS_USER_AGENT = "OpenMates/0.1 (https://openmates.org; travel.search_connections)"
REQUEST_TIMEOUT = 15.0
GEOCODE_MATCH_THRESHOLD = 0.72

MODE_MAP = {
    "AIRPLANE": "airplane",
    "BUS": "bus",
    "FERRY": "ferry",
    "RAIL": "train",
    "SUBWAY": "subway",
    "TRAM": "tram",
    "WALK": "walk",
    "BICYCLE": "bike",
}

STATION_QUERY_HINTS = {"bahnhof", "gare", "hbf", "hauptbahnhof", "station", "stop"}


class TransitousLocationResolutionError(ValueError):
    """Raised when Transitous geocoding cannot confidently resolve a place."""


def _normalize_name(value: str) -> str:
    normalized = value.lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "-": " ",
        "'": " ",
        "(": " ",
        ")": " ",
        ",": " ",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    words = [word for word in normalized.split() if word not in STATION_QUERY_HINTS]
    return " ".join(words)


def _format_duration(seconds_or_minutes: Any) -> str:
    try:
        value = int(float(seconds_or_minutes))
    except (TypeError, ValueError):
        return ""
    if value > 24 * 60:
        minutes = value // 60
    else:
        minutes = value
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if hours else f"{mins}m"


def _duration_minutes(start: str, end: str) -> Optional[int]:
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    return max(0, int((end_dt - start_dt).total_seconds() // 60))


def _format_plan_time(date: str, departure_time: str = "08:00", timezone_name: str = "UTC") -> str:
    """Convert an origin-local departure time to Transitous UTC format."""
    try:
        local_time = datetime.strptime(f"{date} {departure_time}", "%Y-%m-%d %H:%M")
        timezone_info = ZoneInfo(timezone_name)
        # Prefer the first occurrence during a fall-back fold and reject wall
        # times that do not exist during a spring-forward transition.
        localized_time = local_time.replace(tzinfo=timezone_info, fold=0)
        utc_time = localized_time.astimezone(ZoneInfo("UTC"))
        round_trip = utc_time.astimezone(timezone_info).replace(tzinfo=None)
        if round_trip != local_time:
            raise ValueError("departure_time does not exist in the origin timezone")
    except (ValueError, KeyError) as exc:
        raise ValueError("Transitous departure date, time, or timezone is invalid") from exc
    return utc_time.strftime("%Y-%m-%dT%H:%M:%SZ")


def _nested_string(value: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        current: Any = value
        for part in key.split("."):
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if isinstance(current, str) and current.strip():
            return current.strip()
    return None


def _coordinates(value: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    for lat_key, lon_key in (("lat", "lon"), ("lat", "lng"), ("latitude", "longitude")):
        lat = value.get(lat_key)
        lon = value.get(lon_key)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)

    place = value.get("place")
    if isinstance(place, dict):
        lat, lon = _coordinates(place)
        if lat is not None and lon is not None:
            return lat, lon

    point = value.get("point")
    if isinstance(point, dict):
        lat, lon = _coordinates(point)
        if lat is not None and lon is not None:
            return lat, lon

    geometry = value.get("geometry")
    if isinstance(geometry, dict):
        coords = geometry.get("coordinates")
        if isinstance(coords, list) and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                return float(lat), float(lon)

    return None, None


class TransitousProvider(BaseTransportProvider):
    """Timetable-only train/bus/ferry provider using Transitous MOTIS."""

    provider_id = "transitous"
    supported_countries = None
    SUPPORTED_METHODS = {"train", "bus", "boat"}

    def __init__(self, base_url: str = TRANSITOUS_BASE_URL, user_agent: str = TRANSITOUS_USER_AGENT) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent

    def supports_transport_method(self, method: str) -> bool:
        return method in self.SUPPORTED_METHODS

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
        """Search Transitous plans and return timetable-only connection results."""
        del passengers, travel_class, currency, children, infants_in_seat, infants_on_lap
        del include_airlines, exclude_airlines, owned_passes, pass_only, rail_products, min_transfer_minutes, cache_service

        all_connections: List[ConnectionResult] = []
        for leg in legs:
            origin = str(leg.get("origin") or "").strip()
            destination = str(leg.get("destination") or "").strip()
            date = str(leg.get("date") or "").strip()
            departure_time = str(leg.get("departure_time") or "08:00").strip()
            if not origin or not destination or not date:
                continue

            from_place = await self._geocode(origin, mode="RAIL")
            to_place = await self._geocode(destination, mode="RAIL")
            plan = await self._plan(
                from_place=from_place,
                to_place=to_place,
                date=date,
                departure_time=departure_time,
                timezone_name=str(from_place.get("timezone") or "UTC"),
                max_results=max_results,
                max_stops=0 if non_stop_only else max_stops,
            )
            for itinerary in plan.get("itineraries", [])[:max_results]:
                parsed = self._parse_itinerary(itinerary)
                if parsed:
                    all_connections.append(parsed)

        return all_connections[:max_results]

    async def _fetch_geocode_suggestions(self, query: str, *, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "text": query,
            "type": "STOP",
            "numResults": 5,
        }
        if mode:
            params["mode"] = mode
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers={"User-Agent": self.user_agent}) as client:
            response = await client.get(f"{self.base_url}/v1/geocode", params=params)
            response.raise_for_status()
            data = response.json()
        suggestions = data.get("suggestions") if isinstance(data, dict) else data
        return suggestions if isinstance(suggestions, list) else []

    async def _geocode(self, query: str, *, mode: Optional[str] = None) -> Dict[str, Any]:
        suggestions = await self._fetch_geocode_suggestions(query, mode=mode)
        selected = self._pick_geocode_suggestion(query, suggestions)
        if not selected:
            raise TransitousLocationResolutionError(f"Could not confidently resolve Transitous stop: {query}")
        return selected

    def _pick_geocode_suggestion(self, query: str, suggestions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        normalized_query = _normalize_name(query)
        station_requested = any(token in query.lower() for token in STATION_QUERY_HINTS)
        scored: List[tuple[float, Dict[str, Any]]] = []

        for suggestion in suggestions:
            name = _nested_string(suggestion, "name", "label", "displayName", "place.name")
            if not name:
                continue
            normalized_name = _normalize_name(name)
            if not normalized_name:
                continue
            suggestion_type = str(suggestion.get("type") or suggestion.get("placeType") or "").upper()
            if station_requested and suggestion_type and suggestion_type != "STOP":
                continue
            if normalized_query == normalized_name:
                score = 1.0
            elif normalized_query in normalized_name or normalized_name in normalized_query:
                score = 0.9
            else:
                score = SequenceMatcher(None, normalized_query, normalized_name).ratio()
            if suggestion_type == "STOP":
                score += 0.05
            lat, lon = _coordinates(suggestion)
            if lat is None or lon is None:
                continue
            scored.append((score, {
                "name": name,
                "lat": lat,
                "lon": lon,
                "type": suggestion_type or "STOP",
                "confidence": round(min(score, 1.0), 3),
                "timezone": str(suggestion.get("tz") or "UTC"),
                "raw": suggestion,
            }))

        if not scored:
            return None
        score, selected = max(scored, key=lambda item: item[0])
        if score < GEOCODE_MATCH_THRESHOLD:
            logger.info("Transitous geocode rejected: %s -> %s (score %.2f)", query, selected.get("name"), score)
            return None
        return selected

    async def _plan(
        self,
        *,
        from_place: Dict[str, Any],
        to_place: Dict[str, Any],
        date: str,
        departure_time: str,
        timezone_name: str,
        max_results: int,
        max_stops: Optional[int],
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "fromPlace": self._format_place(from_place),
            "toPlace": self._format_place(to_place),
            "time": _format_plan_time(date, departure_time, timezone_name),
            "numItineraries": max(1, min(max_results, 10)),
            "withFares": "true",
            "detailedLegs": "true",
            "joinInterlinedLegs": "true",
        }
        if max_stops is not None:
            params["maxTransfers"] = max_stops
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers={"User-Agent": self.user_agent}) as client:
            response = await client.get(f"{self.base_url}/v6/plan", params=params)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _format_place(place: Dict[str, Any]) -> str:
        return f"{place['lat']},{place['lon']}"

    def _parse_itinerary(self, itinerary: Dict[str, Any]) -> Optional[ConnectionResult]:
        raw_legs = itinerary.get("legs")
        if not isinstance(raw_legs, list) or not raw_legs:
            return None

        segments: List[SegmentResult] = []
        for raw_leg in raw_legs:
            if not isinstance(raw_leg, dict):
                continue
            segment = self._parse_segment(raw_leg)
            if segment:
                segments.append(segment)
        if not segments:
            return None

        layovers: List[LayoverResult] = []
        for previous, current in zip(segments, segments[1:]):
            minutes = _duration_minutes(previous.arrival_time, current.departure_time)
            layovers.append(LayoverResult(
                airport=previous.arrival_station,
                duration=_format_duration(minutes) if minutes is not None else None,
                duration_minutes=minutes,
                overnight=False,
            ))

        duration = _format_duration(itinerary.get("duration")) or _format_duration(
            _duration_minutes(segments[0].departure_time, segments[-1].arrival_time)
        )
        leg = LegResult(
            leg_index=0,
            origin=segments[0].departure_station,
            destination=segments[-1].arrival_station,
            departure=segments[0].departure_time,
            arrival=segments[-1].arrival_time,
            duration=duration,
            stops=int(itinerary.get("transfers") or max(0, len(segments) - 1)),
            segments=segments,
            layovers=layovers or None,
        )
        return ConnectionResult(
            transport_method=segments[0].mode or "train",
            source_provider="transitous",
            total_price=None,
            currency=None,
            booking_url=None,
            booking_provider=None,
            fare=FareResult(
                amount=None,
                currency=None,
                is_partial=False,
                is_pass_only=False,
                covered_by_passes=[],
                pricing_provider=None,
                confidence="timetable_only",
                summary="Timetable only; no fare available.",
            ),
            legs=[leg],
        )

    def _parse_segment(self, raw_leg: Dict[str, Any]) -> Optional[SegmentResult]:
        from_stop = raw_leg.get("from") if isinstance(raw_leg.get("from"), dict) else {}
        to_stop = raw_leg.get("to") if isinstance(raw_leg.get("to"), dict) else {}
        departure = str(raw_leg.get("startTime") or raw_leg.get("scheduledStartTime") or "")
        arrival = str(raw_leg.get("endTime") or raw_leg.get("scheduledEndTime") or "")
        if not departure or not arrival:
            return None

        mode = MODE_MAP.get(str(raw_leg.get("mode") or "").upper(), "unknown")
        line = _nested_string(raw_leg, "routeShortName", "route.shortName", "tripShortName", "headsign")
        operator = _nested_string(raw_leg, "agencyName", "agency.name", "operator", "operator.name")
        dep_lat, dep_lon = _coordinates(from_stop)
        arr_lat, arr_lon = _coordinates(to_stop)
        duration = _format_duration(raw_leg.get("duration")) or _format_duration(_duration_minutes(departure, arrival))
        return SegmentResult(
            carrier=operator or line or mode.title(),
            carrier_code=None,
            number=line,
            mode=mode,
            line=line,
            operator=operator,
            source_provider="transitous",
            fare_coverage="timetable_only",
            departure_station=_nested_string(from_stop, "name") or "?",
            departure_time=departure,
            scheduled_departure_time=str(raw_leg.get("scheduledStartTime") or departure),
            arrival_station=_nested_string(to_stop, "name") or "?",
            arrival_time=arrival,
            scheduled_arrival_time=str(raw_leg.get("scheduledEndTime") or arrival),
            departure_latitude=dep_lat,
            departure_longitude=dep_lon,
            arrival_latitude=arr_lat,
            arrival_longitude=arr_lon,
            duration=duration,
        )
