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
    FareResult,
    LayoverResult,
    LegResult,
    SegmentResult,
)
from backend.shared.providers.deutsche_bahn import (
    get_train_run,
    resolve_location_id,
    search_journeys,
)

logger = logging.getLogger(__name__)

DB_SUPPORTED_COUNTRIES = {
    "AT",
    "BE",
    "CH",
    "CZ",
    "DE",
    "DK",
    "FR",
    "HR",
    "HU",
    "IT",
    "LU",
    "NL",
    "PL",
    "SE",
    "SI",
    "SK",
    "UA",
}

DEUTSCHLAND_TICKET_PASS_IDS = {
    "49_euro_ticket",
    "deutschland_ticket",
    "deutschlandticket",
    "d_ticket",
    "dticket",
}

RAIL_PRODUCT_FILTERS = {
    "high_speed": "HOCHGESCHWINDIGKEITSZUEGE",
    "intercity": "INTERCITYUNDEUROCITYZUEGE",
    "regional_express": "INTERREGIOUNDSCHNELLZUEGE",
    "regional": "NAHVERKEHRSONSTIGEZUEGE",
    "s_bahn": "SBAHNEN",
    "subway": "UBAHN",
    "tram": "STRASSENBAHN",
    "bus": "BUSSE",
    "ferry": "SCHIFFE",
}

PASS_COVERED_PRODUCT_HINTS = {
    "BUS",
    "Bus",
    "Busse",
    "IRE",
    "RB",
    "RE",
    "S",
    "SBAHN",
    "S-Bahn",
    "STR",
    "TRAM",
    "UBAHN",
}

REGIONAL_OPTIMIZATION_PRODUCTS = {
    "regional_express",
    "regional",
    "s_bahn",
    "subway",
    "tram",
    "bus",
    "ferry",
}

TRAIN_RUN_CACHE_TTL_SECONDS = 24 * 60 * 60

_train_run_cache: Dict[str, Dict[str, Any]] = {}

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


def _normalize_pass_id(value: str) -> str:
    """Normalize user/provider pass IDs for stable matching."""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _owns_deutschland_ticket(owned_passes: Optional[List[str]]) -> bool:
    """Return whether owned_passes includes a Deutschlandticket alias."""
    return any(
        _normalize_pass_id(str(pass_id)) in DEUTSCHLAND_TICKET_PASS_IDS
        for pass_id in owned_passes or []
    )


def _db_transport_filter(rail_products: Optional[List[str]]) -> Optional[List[str]]:
    """Map stable OpenMates rail products to current DB Navigator filter values."""
    if not rail_products:
        return None
    mapped: List[str] = []
    invalid: List[str] = []
    for product in rail_products:
        normalized = _normalize_pass_id(str(product))
        db_value = RAIL_PRODUCT_FILTERS.get(normalized)
        if not db_value:
            invalid.append(str(product))
            continue
        if db_value not in mapped:
            mapped.append(db_value)
    if invalid:
        raise ValueError(f"Unsupported rail_products values: {', '.join(invalid)}")
    return mapped or None


def _segment_mode(product: Optional[str]) -> str:
    """Map DB product hints to OpenMates segment modes."""
    value = str(product or "").upper()
    if "BUS" in value:
        return "bus"
    if "UBAHN" in value or value == "U":
        return "subway"
    if "STR" in value or "TRAM" in value:
        return "tram"
    if "SCHIFF" in value or "FERRY" in value:
        return "ferry"
    return "train"


def _segment_fare_coverage(product: Optional[str], *, has_pass: bool, is_partial: bool, is_pass_only: bool) -> str:
    """Infer segment-level fare coverage from DB product and pass context."""
    if is_pass_only:
        return "pass_covered"
    if not has_pass:
        return "paid"
    if not is_partial:
        return "paid"
    product_value = str(product or "")
    if product_value in PASS_COVERED_PRODUCT_HINTS or product_value.upper() in PASS_COVERED_PRODUCT_HINTS:
        return "pass_covered"
    return "paid"


def _build_fare_result(
    *,
    amount: Optional[float],
    currency: Optional[str],
    fare_is_partial: Optional[bool],
    fare_passes_applied: Optional[List[str]],
    pass_only: bool,
) -> FareResult:
    """Build user-facing fare metadata from DB price fields."""
    passes = fare_passes_applied or []
    if amount is not None:
        if fare_is_partial:
            summary = f"{currency or 'EUR'} {amount:.2f} paid portion after Deutschlandticket coverage."
            return FareResult(
                amount=float(amount),
                currency=currency or "EUR",
                is_partial=True,
                is_pass_only=False,
                covered_by_passes=passes,
                pricing_provider="deutsche_bahn",
                confidence="partial",
                summary=summary,
            )
        return FareResult(
            amount=float(amount),
            currency=currency or "EUR",
            is_partial=False,
            is_pass_only=False,
            covered_by_passes=passes,
            pricing_provider="deutsche_bahn",
            confidence="confirmed",
            summary=f"{currency or 'EUR'} {amount:.2f} confirmed by Deutsche Bahn.",
        )
    if pass_only:
        return FareResult(
            amount=None,
            currency=None,
            is_partial=False,
            is_pass_only=True,
            covered_by_passes=passes,
            pricing_provider="deutsche_bahn",
            confidence="pass_only",
            summary="Covered by Deutschlandticket; no additional DB fare returned.",
        )
    return FareResult(
        amount=None,
        currency=None,
        is_partial=False,
        is_pass_only=False,
        covered_by_passes=passes,
        pricing_provider="deutsche_bahn",
        confidence="unknown",
        summary="No DB fare returned for this connection.",
    )


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


def _regional_optimization_requested(
    *,
    owned_passes: Optional[List[str]],
    pass_only: bool,
    rail_products: Optional[List[str]],
) -> bool:
    """Return whether a search should try bounded regional transfer optimization."""

    if pass_only and _owns_deutschland_ticket(owned_passes):
        return True
    if not rail_products:
        return False
    return any(_normalize_pass_id(product) in REGIONAL_OPTIMIZATION_PRODUCTS for product in rail_products)


def _segment_train_run_id(segment: Dict[str, Any]) -> Optional[str]:
    """Extract DB train-run ID from known Vendo segment shapes."""

    for key in ("zuglaufId", "zuglaufID", "trainRunId", "train_run_id"):
        value = segment.get(key)
        if value:
            return str(value)
    for container_key in ("verkehrsmittel", "verkehrsmittelInfo", "zuglauf"):
        container = segment.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("zuglaufId", "zuglaufID", "id"):
            value = container.get(key)
            if value:
                return str(value)
    return None


def _normalize_stop_name(name: str) -> str:
    normalized = name.lower().strip()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "-": " ",
        "(": " ",
        ")": " ",
        ",": " ",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return re.sub(r"\s+", " ", normalized).strip()


def _stop_name(stop: Dict[str, Any]) -> str:
    for key in ("name", "haltName", "bahnhofsName"):
        value = stop.get(key)
        if value:
            return str(value)
    station = stop.get("ort") or stop.get("location") or stop.get("halt")
    if isinstance(station, dict):
        return str(station.get("name") or station.get("bezeichnung") or "")
    return ""


def _stop_time(stop: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = stop.get(key)
        if value:
            return str(value)
    return None


def _stop_coordinates(stop: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    position = stop.get("position") or stop.get("coordinates") or {}
    if not isinstance(position, dict):
        return None, None
    lat = position.get("latitude") or position.get("lat")
    lon = position.get("longitude") or position.get("lon") or position.get("lng")
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None


def _train_run_stops(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("halte", "halteListe", "stops"):
        stops = payload.get(key)
        if isinstance(stops, list):
            return [stop for stop in stops if isinstance(stop, dict)]
    nested = payload.get("zuglauf")
    if isinstance(nested, dict):
        return _train_run_stops(nested)
    return []


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def _cache_get(cache_service: Any, key: str) -> Any:
    if not cache_service:
        return None
    try:
        return await cache_service.get(key)
    except Exception as exc:
        logger.debug("DB train-run cache read failed for %s: %s", key, exc)
        return None


async def _cache_set(cache_service: Any, key: str, value: Dict[str, Any], ttl: int) -> None:
    if not cache_service:
        return
    try:
        await cache_service.set(key, value, ttl=ttl)
    except Exception as exc:
        logger.debug("DB train-run cache write failed for %s: %s", key, exc)


async def _get_train_run_cached(zuglauf_id: str, cache_service: Any = None) -> Dict[str, Any]:
    cache_key = f"travel:db_train_run:v1:{zuglauf_id}"
    cached = _train_run_cache.get(cache_key)
    if isinstance(cached, dict):
        return cached
    persistent_cached = await _cache_get(cache_service, cache_key)
    if isinstance(persistent_cached, dict):
        _train_run_cache[cache_key] = persistent_cached
        return persistent_cached
    payload = await get_train_run(zuglauf_id)
    _train_run_cache[cache_key] = payload
    await _cache_set(cache_service, cache_key, payload, TRAIN_RUN_CACHE_TTL_SECONDS)
    return payload


def _find_overlap_transfer(
    previous_run: Dict[str, Any],
    next_run: Dict[str, Any],
    *,
    min_transfer_minutes: int,
) -> Optional[Dict[str, Any]]:
    """Find the shortest feasible overlapping transfer stop between two train runs."""

    next_stops_by_name: Dict[str, List[Dict[str, Any]]] = {}
    for stop in _train_run_stops(next_run):
        name = _stop_name(stop)
        if not name:
            continue
        next_stops_by_name.setdefault(_normalize_stop_name(name), []).append(stop)

    best: Optional[Dict[str, Any]] = None
    for prev_stop in _train_run_stops(previous_run):
        name = _stop_name(prev_stop)
        if not name:
            continue
        arrival_time = _stop_time(prev_stop, "ankunftsDatum", "ezAnkunftsDatum", "arrival", "arrivalTime")
        arrival_dt = _parse_iso_datetime(arrival_time)
        if not arrival_dt:
            continue
        for next_stop in next_stops_by_name.get(_normalize_stop_name(name), []):
            departure_time = _stop_time(next_stop, "abgangsDatum", "ezAbgangsDatum", "departure", "departureTime")
            departure_dt = _parse_iso_datetime(departure_time)
            if not departure_dt:
                continue
            transfer_minutes = int((departure_dt - arrival_dt).total_seconds() / 60)
            if transfer_minutes < min_transfer_minutes:
                continue
            lat, lon = _stop_coordinates(prev_stop)
            if lat is None or lon is None:
                lat, lon = _stop_coordinates(next_stop)
            candidate = {
                "name": name,
                "arrival_time": arrival_time,
                "departure_time": departure_time,
                "transfer_minutes": transfer_minutes,
                "latitude": lat,
                "longitude": lon,
            }
            if best is None or transfer_minutes < best["transfer_minutes"]:
                best = candidate
    return best


async def _build_optimized_connection(
    raw_connection: Dict[str, Any],
    parsed: ConnectionResult,
    *,
    min_transfer_minutes: Optional[int],
    cache_service: Any = None,
) -> Optional[ConnectionResult]:
    """Create an OpenMates-optimized same-shape connection with a fixed transfer."""

    if min_transfer_minutes is None or not parsed.legs:
        return None
    leg = parsed.legs[0]
    if len(leg.segments) < 2:
        return None
    raw_segments = [
        segment
        for segment in (raw_connection.get("verbindung", {}).get("verbindungsAbschnitte", []) or [])
        if isinstance(segment, dict) and segment.get("typ") == "FAHRZEUG"
    ]
    if len(raw_segments) < len(leg.segments):
        return None

    for index in range(len(leg.segments) - 1):
        current_layover = leg.layovers[index] if leg.layovers and index < len(leg.layovers) else None
        original_station = current_layover.airport if current_layover else leg.segments[index].arrival_station
        first_run_id = _segment_train_run_id(raw_segments[index])
        second_run_id = _segment_train_run_id(raw_segments[index + 1])
        if not first_run_id or not second_run_id or first_run_id == second_run_id:
            continue
        try:
            first_run = await _get_train_run_cached(first_run_id, cache_service=cache_service)
            second_run = await _get_train_run_cached(second_run_id, cache_service=cache_service)
        except Exception as exc:
            logger.info("DB train-run lookup failed for optimized transfer candidate: %s", exc)
            continue
        overlap = _find_overlap_transfer(
            first_run,
            second_run,
            min_transfer_minutes=min_transfer_minutes,
        )
        if not overlap or _normalize_stop_name(overlap["name"]) == _normalize_stop_name(original_station):
            continue

        optimized = parsed.model_copy(deep=True)
        optimized_leg = optimized.legs[0]
        prev_segment = optimized_leg.segments[index]
        next_segment = optimized_leg.segments[index + 1]
        prev_segment.arrival_station = overlap["name"]
        prev_segment.arrival_time = overlap["arrival_time"]
        prev_segment.scheduled_arrival_time = overlap["arrival_time"]
        prev_segment.actual_arrival_time = overlap["arrival_time"]
        prev_segment.arrival_latitude = overlap.get("latitude")
        prev_segment.arrival_longitude = overlap.get("longitude")
        next_segment.departure_station = overlap["name"]
        next_segment.departure_time = overlap["departure_time"]
        next_segment.scheduled_departure_time = overlap["departure_time"]
        next_segment.actual_departure_time = overlap["departure_time"]
        next_segment.departure_latitude = overlap.get("latitude")
        next_segment.departure_longitude = overlap.get("longitude")

        replacement_layover = LayoverResult(
            airport=overlap["name"],
            duration=_format_duration(overlap["transfer_minutes"] * 60),
            duration_minutes=overlap["transfer_minutes"],
            overnight=False,
            latitude=overlap.get("latitude"),
            longitude=overlap.get("longitude"),
            meets_min_transfer=True,
        )
        layovers = list(optimized_leg.layovers or [])
        while len(layovers) <= index:
            layovers.append(replacement_layover)
        layovers[index] = replacement_layover
        optimized_leg.layovers = layovers
        optimized.optimization = {
            "optimized_by": "openmates",
            "badge": "Optimized by OpenMates",
            "original_transfer_station": original_station,
            "optimized_transfer_station": overlap["name"],
            "min_transfer_minutes": min_transfer_minutes,
            "transfer_minutes": overlap["transfer_minutes"],
            "confidence": "bounded_train_run_overlap",
        }
        optimized.transfer_quality = {
            "min_transfer_minutes": min_transfer_minutes,
            "has_transfers": True,
            "short_transfer_count": 0,
        }
        return optimized
    return None


def _format_duration(seconds: int) -> str:
    """Convert duration in seconds to 'Xh Ym' format."""
    h, remainder = divmod(seconds, 3600)
    m = remainder // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _delay_minutes(actual_time: Optional[str], scheduled_time: Optional[str]) -> Optional[int]:
    """Return realtime delay in minutes, where negative values mean early."""
    if not actual_time or not scheduled_time:
        return None
    try:
        actual_dt = datetime.fromisoformat(actual_time)
        scheduled_dt = datetime.fromisoformat(scheduled_time)
        return int((actual_dt - scheduled_dt).total_seconds() / 60)
    except (ValueError, TypeError):
        return None


def _stop_platform(stop: Dict[str, Any]) -> Optional[str]:
    """Extract the most useful platform/track value from a DB stop object."""
    return stop.get("gleis") or stop.get("plattform")


def _stop_is_cancelled(stop: Dict[str, Any]) -> bool:
    """Return whether DB marks this stop as cancelled."""
    replacement_note = stop.get("ersatzhaltNotiz") or {}
    if replacement_note.get("typ") == "GECANCELT":
        return True
    return any(
        "cancel" in str(note.get("text", "")).lower() or "entfällt" in str(note.get("text", "")).lower()
        for note in stop.get("echtzeitNotizen", [])
    )


def _stop_notes(stop: Dict[str, Any]) -> List[str]:
    """Collect human-readable realtime notes from a DB stop object."""
    notes: List[str] = []
    for key in ("echtzeitNotizen", "himNotizen", "attributNotizen"):
        for note in stop.get(key, []) or []:
            text = note.get("text")
            if text and text not in notes:
                notes.append(text)
    replacement_note = stop.get("ersatzhaltNotiz") or {}
    replacement_text = replacement_note.get("text")
    if replacement_text and replacement_text not in notes:
        notes.append(replacement_text)
    return notes


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
    fare_passes_applied: Optional[List[str]] = None,
    pass_only: bool = False,
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

        stops = seg.get("halte", []) or []
        dep_stop = stops[0] if stops else {}
        arr_stop = stops[-1] if stops else {}

        scheduled_dep_time = dep_stop.get("abgangsDatum") or seg.get("abgangsDatum", "")
        actual_dep_time = dep_stop.get("ezAbgangsDatum") or scheduled_dep_time
        scheduled_arr_time = arr_stop.get("ankunftsDatum") or seg.get("ankunftsDatum", "")
        actual_arr_time = arr_stop.get("ezAnkunftsDatum") or scheduled_arr_time

        dep_platform = _stop_platform(dep_stop)
        arr_platform = _stop_platform(arr_stop)
        cancelled = any(_stop_is_cancelled(stop) for stop in stops) or bool(seg.get("isAusfall"))
        realtime_notes = []
        for stop in stops:
            for note in _stop_notes(stop):
                if note not in realtime_notes:
                    realtime_notes.append(note)
        dep_lat = dep_pos.get("latitude")
        dep_lng = dep_pos.get("longitude")
        arr_lat = arr_pos.get("latitude")
        arr_lng = arr_pos.get("longitude")

        segments.append(SegmentResult(
            carrier=seg.get("produktGattung", seg.get("kurztext", "Train")),
            carrier_code=None,
            number=seg.get("mitteltext", seg.get("kurztext")),
            departure_station=dep_ort.get("name", "?"),
            departure_time=scheduled_dep_time,
            scheduled_departure_time=scheduled_dep_time,
            actual_departure_time=actual_dep_time,
            departure_delay_minutes=_delay_minutes(actual_dep_time, scheduled_dep_time),
            departure_platform=dep_platform,
            departure_platform_changed=None,
            departure_latitude=dep_lat,
            departure_longitude=dep_lng,
            arrival_station=arr_ort.get("name", "?"),
            arrival_time=scheduled_arr_time,
            scheduled_arrival_time=scheduled_arr_time,
            actual_arrival_time=actual_arr_time,
            arrival_delay_minutes=_delay_minutes(actual_arr_time, scheduled_arr_time),
            arrival_platform=arr_platform,
            arrival_platform_changed=None,
            arrival_latitude=arr_lat,
            arrival_longitude=arr_lng,
            duration=_format_duration(seg.get("abschnittsDauer", 0)),
            cancelled=cancelled if cancelled else None,
            realtime_notes=realtime_notes or None,
            departure_is_daytime=_is_daytime(actual_dep_time, dep_lat, dep_lng),
            arrival_is_daytime=_is_daytime(actual_arr_time, arr_lat, arr_lng),
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
            latitude=prev_seg.arrival_latitude or next_seg.departure_latitude,
            longitude=prev_seg.arrival_longitude or next_seg.departure_longitude,
        ))

    # Extract price
    preise = angebote.get("preise", {})
    gesamt = preise.get("gesamt", {})
    ab_price = gesamt.get("ab", {})
    price_amount = ab_price.get("betrag")
    price_currency = ab_price.get("waehrung", "EUR")
    fare_is_partial = preise.get("istTeilpreis")
    fare_is_partial_value = fare_is_partial if isinstance(fare_is_partial, bool) else None
    fare = _build_fare_result(
        amount=price_amount,
        currency=price_currency if price_amount is not None else None,
        fare_is_partial=fare_is_partial_value,
        fare_passes_applied=fare_passes_applied,
        pass_only=pass_only,
    )

    # Add fare coverage after fare metadata is known.
    for index, seg in enumerate(segments):
        raw_segment = [raw for raw in segments_raw if raw.get("typ") == "FAHRZEUG"][index]
        product = raw_segment.get("produktGattung") or raw_segment.get("kurztext")
        seg.mode = _segment_mode(product)
        seg.line = seg.number
        seg.operator = seg.carrier
        seg.source_provider = "deutsche_bahn"
        seg.fare_coverage = _segment_fare_coverage(
            product,
            has_pass=bool(fare_passes_applied),
            is_partial=fare.is_partial,
            is_pass_only=fare.is_pass_only,
        )

    # Build leg (DB returns one-way results per call, so always 1 leg)
    first_seg = segments[0]
    last_seg = segments[-1]

    leg = LegResult(
        leg_index=0,
        origin=first_seg.departure_station,
        destination=last_seg.arrival_station,
        departure=first_seg.departure_time,
        scheduled_departure=first_seg.scheduled_departure_time,
        actual_departure=first_seg.actual_departure_time,
        departure_delay_minutes=first_seg.departure_delay_minutes,
        arrival=last_seg.arrival_time,
        scheduled_arrival=last_seg.scheduled_arrival_time,
        actual_arrival=last_seg.actual_arrival_time,
        arrival_delay_minutes=last_seg.arrival_delay_minutes,
        duration=_format_duration(verbindung.get("reiseDauer", 0)),
        stops=verbindung.get("umstiegeAnzahl", 0),
        segments=segments,
        layovers=layovers if layovers else None,
    )

    # Build booking URL for this specific connection's departure time
    booking_url = None
    if not pass_only:
        booking_url = _build_booking_url(
            from_lid=from_lid,
            to_lid=to_lid,
            departure_time=first_seg.departure_time,
            klasse=klasse,
        )

    return ConnectionResult(
        transport_method="train",
        source_provider="deutsche_bahn",
        total_price=f"{price_amount:.2f}" if price_amount is not None else None,
        currency=price_currency if price_amount is not None else None,
        fare_is_partial=fare_is_partial_value,
        fare_passes_applied=fare_passes_applied if fare_is_partial_value else None,
        fare=fare,
        booking_url=booking_url,
        booking_provider="Deutsche Bahn" if booking_url else None,
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

    provider_id = "deutsche_bahn"
    supported_countries = DB_SUPPORTED_COUNTRIES
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
        owned_passes: Optional[List[str]] = None,
        pass_only: bool = False,
        rail_products: Optional[List[str]] = None,
        min_transfer_minutes: Optional[int] = None,
        cache_service: Any = None,
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

        has_deutschland_ticket = _owns_deutschland_ticket(owned_passes)
        fare_passes_applied = ["deutschland_ticket"] if has_deutschland_ticket else None
        deutschland_ticket_only = bool(pass_only and has_deutschland_ticket)
        transport_filter = _db_transport_filter(rail_products)

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
                    transport_filter=transport_filter,
                    deutschland_ticket=has_deutschland_ticket,
                    deutschland_ticket_only=deutschland_ticket_only,
                    min_transfer_minutes=min_transfer_minutes,
                )
            except Exception as e:
                logger.error("DB journey search failed (%s → %s): %s", origin, destination, e)
                continue

            # Parse connections
            verbindungen = result.get("verbindungen", [])
            for conn in verbindungen[:max_results]:
                parsed = _parse_connection(
                    conn,
                    from_lid,
                    to_lid,
                    klasse,
                    fare_passes_applied=fare_passes_applied,
                    pass_only=deutschland_ticket_only,
                )
                if parsed:
                    all_connections.append(parsed)
                    if _regional_optimization_requested(
                        owned_passes=owned_passes,
                        pass_only=pass_only,
                        rail_products=rail_products,
                    ):
                        optimized = await _build_optimized_connection(
                            conn,
                            parsed,
                            min_transfer_minutes=min_transfer_minutes,
                            cache_service=cache_service,
                        )
                        if optimized:
                            all_connections.append(optimized)

        return all_connections
