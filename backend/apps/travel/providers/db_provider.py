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
from typing import Any, Dict, List, Optional

from backend.apps.travel.providers.base_provider import (
    BaseTransportProvider,
    ConnectionResult,
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


def _format_duration(seconds: int) -> str:
    """Convert duration in seconds to 'Xh Ym' format."""
    h, remainder = divmod(seconds, 3600)
    m = remainder // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _parse_connection(conn: Dict[str, Any]) -> Optional[ConnectionResult]:
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

        segments.append(SegmentResult(
            carrier=seg.get("produktGattung", seg.get("kurztext", "Train")),
            carrier_code=None,
            number=seg.get("mitteltext", seg.get("kurztext")),
            departure_station=dep_ort.get("name", "?"),
            departure_time=seg.get("abgangsDatum", ""),
            departure_latitude=dep_pos.get("latitude"),
            departure_longitude=dep_pos.get("longitude"),
            arrival_station=arr_ort.get("name", "?"),
            arrival_time=seg.get("ankunftsDatum", ""),
            arrival_latitude=arr_pos.get("latitude"),
            arrival_longitude=arr_pos.get("longitude"),
            duration=_format_duration(seg.get("abschnittsDauer", 0)),
        ))

    if not segments:
        return None

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
    )

    return ConnectionResult(
        transport_method="train",
        total_price=f"{price_amount:.2f}" if price_amount is not None else None,
        currency=price_currency,
        legs=[leg],
    )


class DeutscheBahnProvider(BaseTransportProvider):
    """
    Train connection provider using the Deutsche Bahn Navigator API.

    Supports the "train" transport method. Returns real-time connections
    with Sparpreis/Flexpreis pricing for German and select European routes.

    Limitations:
    - Germany-focused (some cross-border routes to AT, CH, NL, CZ, etc.)
    - No booking deeplinks (user sees price but books on bahn.de manually)
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
                parsed = _parse_connection(conn)
                if parsed:
                    all_connections.append(parsed)

        return all_connections
