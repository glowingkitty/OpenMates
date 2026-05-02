"""
Deutsche Bahn transport provider for the travel app.

Implements BaseTransportProvider to search for train connections via
the DB Navigator API. Returns real-time prices for German domestic and
select cross-border routes (Austria, Switzerland, Netherlands, etc.).

No API key required. Uses the unofficial Vendo/Movas Navigator API
(same API used by the DB Navigator mobile app).

Research: docs/architecture/apps/travel-train-api-research.md
Provider wrapper: backend/shared/providers/deutsche_bahn.py
"""

import logging
import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
    LayoverResult,
    LegResult,
    SegmentResult,
)
from backend.shared.providers.deutsche_bahn import (
    resolve_location_id,
    search_journeys,
)

logger = logging.getLogger(__name__)

# Travel class mapping: OpenMates → DB API
_CLASS_MAP = {
    "economy": "KLASSE_2",
    "second": "KLASSE_2",
    "2": "KLASSE_2",
    "first": "KLASSE_1",
    "business": "KLASSE_1",
    "1": "KLASSE_1",
}

# Traveller type mapping by age bracket
_TRAVELLER_TYPES = {
    "adult": "ERWACHSENER",
    "senior": "SENIOR",
    "youth": "JUGENDLICHER",
    "child": "KIND",
    "infant": "KLEINKIND",
}


def _extract_eva_number(location_id: str) -> str:
    """Extract EVA number from HAFAS locationId (e.g., 'L=8011160' → '8011160')."""
    match = re.search(r"L=(\d+)", location_id)
    return match.group(1) if match else ""


def _build_booking_url(
    from_lid: str,
    to_lid: str,
    departure_time: str,
    klasse: str,
) -> str:
    """
    Build a bahn.de deep link that opens the booking flow pre-filled with
    the origin, destination, date/time, and class.

    URL format reverse-engineered from BetterBahn and bahn.de SPA routing.
    See: https://github.com/l2xu/betterbahn/blob/main/utils/createUrl.ts
    """
    # Extract station names from locationId ("A=1@O=Berlin Hbf@X=..." → "Berlin Hbf")
    from_match = re.search(r"O=([^@]+)", from_lid)
    to_match = re.search(r"O=([^@]+)", to_lid)
    from_name = from_match.group(1) if from_match else "?"
    to_name = to_match.group(1) if to_match else "?"

    from_eva = _extract_eva_number(from_lid)
    to_eva = _extract_eva_number(to_lid)

    # Class: "KLASSE_2" → "2", "KLASSE_1" → "1"
    kl = "1" if klasse == "KLASSE_1" else "2"

    # Traveller param: "13:16:KLASSENLOS:1" = adult, no discount, 1 person
    r_param = "13:16:KLASSENLOS:1"

    # Parse departure time → "YYYY-MM-DDTHH:MM:SS"
    # Input is ISO like "2026-05-15T08:29:00+02:00"
    hd = departure_time[:19] if len(departure_time) >= 19 else departure_time

    # Build hash fragment
    params = (
        f"sts=true"
        f"&so={quote(from_name)}"
        f"&zo={quote(to_name)}"
        f"&kl={kl}"
        f"&r={r_param}"
        f"&soid={quote(from_lid)}"
        f"&zoid={quote(to_lid)}"
        f"&sot=ST&zot=ST"
        f"&soei={from_eva}"
        f"&zoei={to_eva}"
        f"&hd={quote(hd)}"
        f"&hza=D&ar=false&s=true&d=false"
        f"&fm=false&bp=false"
    )

    return f"https://www.bahn.de/buchung/fahrplan/suche#{params}"


def _format_duration(seconds: int) -> str:
    """Convert duration in seconds to 'Xh Ym' format."""
    h, remainder = divmod(seconds, 3600)
    m = remainder // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _is_daytime(iso_time: str, latitude: Optional[float], longitude: Optional[float]) -> Optional[bool]:
    """
    Determine if a time is between sunrise and sunset at a location.

    Uses the NOAA solar position algorithm (same approach as serpapi_provider).
    Parses timezone offset from the ISO 8601 string directly — no IANA tz needed.

    Returns True (daytime), False (night), or None if calculation not possible.
    """
    if not iso_time or latitude is None or longitude is None:
        return None

    try:
        # Parse ISO 8601 with offset (e.g., "2026-05-15T08:29:00+02:00")
        dt_local = datetime.fromisoformat(iso_time)
        dt_utc = dt_local.utctimetuple()
        day_of_year = dt_utc.tm_yday

        # Solar declination (simplified, accurate to ~0.5°)
        declination = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
        decl_rad = math.radians(declination)
        lat_rad = math.radians(latitude)

        # Hour angle at sunrise/sunset
        cos_ha = -math.tan(lat_rad) * math.tan(decl_rad)
        if cos_ha < -1:
            return True   # Midnight sun
        if cos_ha > 1:
            return False  # Polar night

        hour_angle = math.degrees(math.acos(cos_ha))

        # Solar noon in UTC hours (approximate using longitude)
        solar_noon_utc = 12.0 - (longitude / 15.0)
        sunrise_utc = (solar_noon_utc - hour_angle / 15.0) % 24
        sunset_utc = (solar_noon_utc + hour_angle / 15.0) % 24

        # Current time in UTC fractional hours
        current_utc_hours = dt_utc.tm_hour + dt_utc.tm_min / 60.0

        if sunrise_utc < sunset_utc:
            return sunrise_utc <= current_utc_hours <= sunset_utc
        else:
            return current_utc_hours >= sunrise_utc or current_utc_hours <= sunset_utc
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_connection(
    conn: Dict[str, Any],
    from_lid: str,
    to_lid: str,
    klasse: str,
) -> Optional[ConnectionResult]:
    """
    Map a single DB API verbindung+angebote dict to a ConnectionResult.

    Returns None if the connection has no usable segments.
    """
    verbindung = conn.get("verbindung", {})
    angebote = conn.get("angebote", {})

    segments_raw = verbindung.get("verbindungsAbschnitte", [])
    if not segments_raw:
        return None

    # Build segments (skip walking segments for the segment list,
    # but count them for accurate change counting)
    segments: List[SegmentResult] = []
    for seg in segments_raw:
        if seg.get("typ") != "FAHRZEUG":
            continue

        dep_ort = seg.get("abgangsOrt", {})
        arr_ort = seg.get("ankunftsOrt", {})
        dep_pos = dep_ort.get("position", {})
        arr_pos = arr_ort.get("position", {})

        dep_time = seg.get("abgangsDatum", "")
        arr_time = seg.get("ankunftsDatum", "")
        dep_lat = dep_pos.get("latitude")
        dep_lng = dep_pos.get("longitude")
        arr_lat = arr_pos.get("latitude")
        arr_lng = arr_pos.get("longitude")

        segments.append(SegmentResult(
            carrier=seg.get("produktGattung", seg.get("kurztext", "Train")),
            carrier_code=None,
            number=seg.get("mitteltext", seg.get("kurztext")),
            departure_station=dep_ort.get("name", "?"),
            departure_time=dep_time,
            departure_latitude=dep_lat,
            departure_longitude=dep_lng,
            arrival_station=arr_ort.get("name", "?"),
            arrival_time=arr_time,
            arrival_latitude=arr_lat,
            arrival_longitude=arr_lng,
            duration=_format_duration(seg.get("abschnittsDauer", 0)),
            departure_is_daytime=_is_daytime(dep_time, dep_lat, dep_lng),
            arrival_is_daytime=_is_daytime(arr_time, arr_lat, arr_lng),
        ))

    if not segments:
        return None

    # Build layover details between consecutive segments
    layovers: List[LayoverResult] = []
    for i in range(len(segments) - 1):
        prev_seg = segments[i]
        next_seg = segments[i + 1]
        # Layover station is where previous segment arrives / next departs
        layover_station = prev_seg.arrival_station

        # Calculate layover duration from arrival→departure times
        layover_duration: Optional[str] = None
        layover_minutes: Optional[int] = None
        overnight = False
        try:
            arr_dt = datetime.fromisoformat(prev_seg.arrival_time)
            dep_dt = datetime.fromisoformat(next_seg.departure_time)
            diff = dep_dt - arr_dt
            total_min = int(diff.total_seconds() / 60)
            if total_min > 0:
                layover_minutes = total_min
                layover_duration = _format_duration(total_min * 60)
                # Overnight if layover spans past midnight
                overnight = arr_dt.date() != dep_dt.date()
        except (ValueError, TypeError):
            pass

        layovers.append(LayoverResult(
            airport=layover_station,
            duration=layover_duration,
            duration_minutes=layover_minutes,
            overnight=overnight,
        ))

    # Extract price
    preise = angebote.get("preise", {})
    gesamt = preise.get("gesamt", {})
    ab_price = gesamt.get("ab", {})
    price_amount = ab_price.get("betrag")
    price_currency = ab_price.get("waehrung", "EUR")

    # Build leg (DB returns one-way results per call, so always 1 leg)
    first_seg = segments[0]
    last_seg = segments[-1]

    leg = LegResult(
        leg_index=0,
        origin=first_seg.departure_station,
        destination=last_seg.arrival_station,
        departure=first_seg.departure_time,
        arrival=last_seg.arrival_time,
        duration=_format_duration(verbindung.get("reiseDauer", 0)),
        stops=verbindung.get("umstiegeAnzahl", 0),
        segments=segments,
        layovers=layovers if layovers else None,
    )

    # Build booking URL for this specific connection's departure time
    booking_url = _build_booking_url(
        from_lid=from_lid,
        to_lid=to_lid,
        departure_time=first_seg.departure_time,
        klasse=klasse,
    )

    return ConnectionResult(
        transport_method="train",
        total_price=f"{price_amount:.2f}" if price_amount is not None else None,
        currency=price_currency,
        booking_url=booking_url,
        booking_provider="Deutsche Bahn",
        legs=[leg],
    )


class DeutscheBahnProvider(BaseTransportProvider):
    """
    Train connection provider using the Deutsche Bahn Navigator API.

    Supports the "train" transport method. Returns real-time connections
    with Sparpreis/Flexpreis pricing for German and select European routes.

    Limitations:
    - Germany-focused (some cross-border routes to AT, CH, NL, CZ, etc.)
    - Unofficial API — DB can change or block at any time
    - One-way per API call (round trips require two calls)
    """

    SUPPORTED_METHODS = {"train"}

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
    ) -> List[ConnectionResult]:
        """
        Search for train connections via the DB Navigator API.

        Resolves city names to HAFAS location IDs, then queries the
        journey search endpoint for each leg. Maps results to the
        unified ConnectionResult format.
        """
        klasse = _CLASS_MAP.get(travel_class.lower(), "KLASSE_2")

        # Build traveller list
        travellers: List[Dict[str, Any]] = []
        for _ in range(max(passengers, 1)):
            travellers.append({
                "ermaessigungen": ["KEINE_ERMAESSIGUNG KLASSENLOS"],
                "reisendenTyp": "ERWACHSENER",
            })
        for _ in range(children):
            travellers.append({
                "ermaessigungen": ["KEINE_ERMAESSIGUNG KLASSENLOS"],
                "reisendenTyp": "KIND",
            })

        # Determine max transfers
        max_changes = None
        if non_stop_only:
            max_changes = 0
        elif max_stops is not None:
            max_changes = max_stops

        all_connections: List[ConnectionResult] = []

        for leg in legs:
            origin = leg.get("origin", "")
            destination = leg.get("destination", "")
            date = leg.get("date", "")

            if not origin or not destination or not date:
                logger.warning("DB provider: skipping leg with missing fields: %s", leg)
                continue

            # Resolve station IDs
            from_lid = await resolve_location_id(origin)
            if not from_lid:
                logger.warning("DB provider: could not resolve origin '%s'", origin)
                continue

            to_lid = await resolve_location_id(destination)
            if not to_lid:
                logger.warning("DB provider: could not resolve destination '%s'", destination)
                continue

            # Search journeys
            try:
                result = await search_journeys(
                    from_location_id=from_lid,
                    to_location_id=to_lid,
                    date=date,
                    klasse=klasse,
                    travellers=travellers,
                    max_changes=max_changes,
                )
            except Exception as e:
                logger.error("DB journey search failed (%s → %s): %s", origin, destination, e)
                continue

            # Parse connections
            verbindungen = result.get("verbindungen", [])
            for conn in verbindungen[:max_results]:
                parsed = _parse_connection(conn, from_lid, to_lid, klasse)
                if parsed:
                    all_connections.append(parsed)

        return all_connections
