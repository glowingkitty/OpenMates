"""
Deutsche Bahn Navigator API client.

Pure HTTP wrapper for the DB Vendo/Movas Navigator API used by the
DB Navigator mobile app. Provides station search and journey search
with real-time prices. No API key required.

Endpoints documented at:
  https://github.com/public-transport/db-vendo-client/blob/main/docs/db-apis.md
Research: docs/architecture/apps/travel-train-api-research.md
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

BASE_URL = "https://app.vendo.noncd.db.de/mob"

CT_JOURNEY = "application/x.db.vendo.mob.verbindungssuche.v9+json"
CT_LOCATION = "application/x.db.vendo.mob.location.v3+json"

USER_AGENT = "DBNavigator/Android/25.18.2"
REQUEST_TIMEOUT = 15.0

# ---------------------------------------------------------------------------
# Top German stations — avoids a location search API call for common cities.
# Format: city name (lowercase) → HAFAS locationId string.
# ---------------------------------------------------------------------------

_TOP_STATIONS: Dict[str, str] = {
    "berlin": "A=1@O=Berlin Hbf@X=13369549@Y=52525589@U=80@L=8011160@B=1@p=1@",
    "münchen": "A=1@O=München Hbf@X=11558339@Y=48140229@U=80@L=8000261@B=1@p=1@",
    "munich": "A=1@O=München Hbf@X=11558339@Y=48140229@U=80@L=8000261@B=1@p=1@",
    "frankfurt": "A=1@O=Frankfurt(Main)Hbf@X=8662833@Y=50106682@U=80@L=8000105@B=1@p=1@",
    "hamburg": "A=1@O=Hamburg Hbf@X=10006909@Y=53552733@U=80@L=8002549@B=1@p=1@",
    "köln": "A=1@O=Köln Hbf@X=6958730@Y=50943029@U=80@L=8000207@B=1@p=1@",
    "cologne": "A=1@O=Köln Hbf@X=6958730@Y=50943029@U=80@L=8000207@B=1@p=1@",
    "stuttgart": "A=1@O=Stuttgart Hbf@X=9181635@Y=48783902@U=80@L=8000096@B=1@p=1@",
    "düsseldorf": "A=1@O=Düsseldorf Hbf@X=6794219@Y=51219592@U=80@L=8000085@B=1@p=1@",
    "dusseldorf": "A=1@O=Düsseldorf Hbf@X=6794219@Y=51219592@U=80@L=8000085@B=1@p=1@",
    "dresden": "A=1@O=Dresden Hbf@X=13732039@Y=51040562@U=80@L=8010085@B=1@p=1@",
    "nürnberg": "A=1@O=Nürnberg Hbf@X=11082988@Y=49445615@U=80@L=8000284@B=1@p=1@",
    "nuremberg": "A=1@O=Nürnberg Hbf@X=11082988@Y=49445615@U=80@L=8000284@B=1@p=1@",
    "leipzig": "A=1@O=Leipzig Hbf@X=12382049@Y=51346546@U=80@L=8010205@B=1@p=1@",
    "hannover": "A=1@O=Hannover Hbf@X=9741017@Y=52376761@U=80@L=8000152@B=1@p=1@",
    "hanover": "A=1@O=Hannover Hbf@X=9741017@Y=52376761@U=80@L=8000152@B=1@p=1@",
    "dortmund": "A=1@O=Dortmund Hbf@X=7459294@Y=51517899@U=80@L=8000080@B=1@p=1@",
    "essen": "A=1@O=Essen Hbf@X=7014793@Y=51451355@U=80@L=8000098@B=1@p=1@",
    "bremen": "A=1@O=Bremen Hbf@X=8813833@Y=53083476@U=80@L=8000050@B=1@p=1@",
    "mannheim": "A=1@O=Mannheim Hbf@X=8469466@Y=49479258@U=80@L=8000244@B=1@p=1@",
    "augsburg": "A=1@O=Augsburg Hbf@X=10885590@Y=48365424@U=80@L=8000013@B=1@p=1@",
    "karlsruhe": "A=1@O=Karlsruhe Hbf@X=8402181@Y=48993512@U=80@L=8000191@B=1@p=1@",
    "bonn": "A=1@O=Bonn Hbf@X=7097200@Y=50732017@U=80@L=8000044@B=1@p=1@",
    "freiburg": "A=1@O=Freiburg(Breisgau) Hbf@X=7841256@Y=47997460@U=80@L=8000107@B=1@p=1@",
    "erfurt": "A=1@O=Erfurt Hbf@X=11038850@Y=50972550@U=80@L=8010101@B=1@p=1@",
    "mainz": "A=1@O=Mainz Hbf@X=8258723@Y=50001113@U=80@L=8000240@B=1@p=1@",
    "würzburg": "A=1@O=Würzburg Hbf@X=9935538@Y=49801499@U=80@L=8000260@B=1@p=1@",
    "regensburg": "A=1@O=Regensburg Hbf@X=12099754@Y=49011898@U=80@L=8000309@B=1@p=1@",
    "kassel": "A=1@O=Kassel-Wilhelmshöhe@X=9447321@Y=51313247@U=80@L=8003200@B=1@p=1@",
    "aachen": "A=1@O=Aachen Hbf@X=6091499@Y=50767803@U=80@L=8000001@B=1@p=1@",
    "kiel": "A=1@O=Kiel Hbf@X=10131976@Y=54314982@U=80@L=8000199@B=1@p=1@",
    "rostock": "A=1@O=Rostock Hbf@X=12130814@Y=54078345@U=80@L=8010304@B=1@p=1@",
    # Cross-border stations commonly reachable via DB
    "wien": "A=1@O=Wien Hbf@X=16375326@Y=48185187@U=80@L=8101003@B=1@p=1@",
    "vienna": "A=1@O=Wien Hbf@X=16375326@Y=48185187@U=80@L=8101003@B=1@p=1@",
    "zürich": "A=1@O=Zürich HB@X=8540192@Y=47378177@U=80@L=8503000@B=1@p=1@",
    "zurich": "A=1@O=Zürich HB@X=8540192@Y=47378177@U=80@L=8503000@B=1@p=1@",
    "amsterdam": "A=1@O=Amsterdam Centraal@X=4899431@Y=52378901@U=80@L=8400058@B=1@p=1@",
    "prague": "A=1@O=Praha hl.n.@X=14435337@Y=50083084@U=80@L=5400014@B=1@p=1@",
    "prag": "A=1@O=Praha hl.n.@X=14435337@Y=50083084@U=80@L=5400014@B=1@p=1@",
    "basel": "A=1@O=Basel SBB@X=7589064@Y=47547408@U=80@L=8500010@B=1@p=1@",
    "innsbruck": "A=1@O=Innsbruck Hbf@X=11400700@Y=47263100@U=80@L=8100108@B=1@p=1@",
    "salzburg": "A=1@O=Salzburg Hbf@X=13045910@Y=47812810@U=80@L=8100002@B=1@p=1@",
    "paris": "A=1@O=Paris Est@X=2359151@Y=48876416@U=80@L=8700011@B=1@p=1@",
    "bruxelles": "A=1@O=Bruxelles-Midi@X=4336531@Y=50835707@U=80@L=8800004@B=1@p=1@",
    "brussels": "A=1@O=Bruxelles-Midi@X=4336531@Y=50835707@U=80@L=8800004@B=1@p=1@",
    "copenhagen": "A=1@O=København H@X=12564854@Y=55672480@U=80@L=8600626@B=1@p=1@",
}

# In-memory cache for location search results (session-scoped)
_location_cache: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _correlation_id() -> str:
    return f"{uuid.uuid4()}_{uuid.uuid4()}"


def _base_headers(content_type: str) -> Dict[str, str]:
    return {
        "Content-Type": content_type,
        "Accept": content_type,
        "X-Correlation-ID": _correlation_id(),
        "Accept-Language": "en",
        "User-Agent": USER_AGENT,
    }


# ---------------------------------------------------------------------------
# Location search
# ---------------------------------------------------------------------------

async def search_locations(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search for stations/locations by name.

    Returns list of dicts with keys: locationId, name, evaNr, coordinates.
    """
    body = {
        "searchTerm": query,
        "locationTypes": ["ALL"],
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.post(
            f"{BASE_URL}/location/search",
            json=body,
            headers=_base_headers(CT_LOCATION),
        )
        resp.raise_for_status()
        results = resp.json()

    return [
        {
            "locationId": r["locationId"],
            "name": r.get("name", ""),
            "evaNr": r.get("evaNr", ""),
            "coordinates": r.get("coordinates", {}),
        }
        for r in results[:max_results]
    ]


async def resolve_location_id(city_name: str) -> Optional[str]:
    """
    Resolve a city/station name to a HAFAS locationId string.

    Checks the hardcoded top stations first, then the in-memory cache,
    then falls back to the location search API.
    """
    key = city_name.strip().lower()

    # 1. Hardcoded top stations
    if key in _TOP_STATIONS:
        return _TOP_STATIONS[key]

    # 2. Try common variations: "Berlin Hbf" → "berlin hbf" → try "berlin"
    base_key = key.replace(" hbf", "").replace(" hauptbahnhof", "").replace(" central", "")
    if base_key in _TOP_STATIONS:
        return _TOP_STATIONS[base_key]

    # 3. In-memory cache
    if key in _location_cache:
        return _location_cache[key]

    # 4. API fallback
    try:
        results = await search_locations(city_name, max_results=1)
        if results:
            lid = results[0]["locationId"]
            _location_cache[key] = lid
            logger.info("DB location resolved: %s → %s", city_name, results[0].get("name", "?"))
            return lid
    except Exception as e:
        logger.warning("DB location search failed for '%s': %s", city_name, e)

    return None


# ---------------------------------------------------------------------------
# Journey search
# ---------------------------------------------------------------------------

async def search_journeys(
    from_location_id: str,
    to_location_id: str,
    date: str,
    time: str = "08:00:00",
    klasse: str = "KLASSE_2",
    travellers: Optional[List[Dict[str, Any]]] = None,
    max_changes: Optional[int] = None,
    transport_filter: Optional[List[str]] = None,
    deutschland_ticket: bool = False,
) -> Dict[str, Any]:
    """
    Search for train connections with prices.

    Args:
        from_location_id: HAFAS locationId of the origin station.
        to_location_id: HAFAS locationId of the destination station.
        date: Travel date in YYYY-MM-DD format.
        time: Departure time in HH:MM:SS format (default 08:00:00).
        klasse: Travel class — KLASSE_1 or KLASSE_2.
        travellers: List of traveller dicts with reisendenTyp and ermaessigungen.
            Defaults to 1 adult with no discount.
        max_changes: Maximum number of transfers (None = no limit).
        transport_filter: Transport types to include (default: ["ALL"]).
        deutschland_ticket: Whether the traveller has a Deutschland-Ticket.

    Returns:
        Raw API response dict with 'verbindungen' array.
    """
    if travellers is None:
        travellers = [{
            "ermaessigungen": ["KEINE_ERMAESSIGUNG KLASSENLOS"],
            "reisendenTyp": "ERWACHSENER",
        }]

    if transport_filter is None:
        transport_filter = ["ALL"]

    wunsch: Dict[str, Any] = {
        "abgangsLocationId": from_location_id,
        "zielLocationId": to_location_id,
        "alternativeHalteBerechnung": True,
        "verkehrsmittel": transport_filter,
        "zeitWunsch": {
            "reiseDatum": f"{date}T{time}.000+02:00",
            "zeitPunktArt": "ABFAHRT",
        },
    }
    if max_changes is not None:
        wunsch["maxUmstiege"] = max_changes

    body = {
        "autonomeReservierung": False,
        "einstiegsTypList": ["STANDARD"],
        "fahrverguenstigungen": {
            "deutschlandTicketVorhanden": deutschland_ticket,
            "nurDeutschlandTicketVerbindungen": False,
        },
        "klasse": klasse,
        "reiseHin": {"wunsch": wunsch},
        "reisendenProfil": {"reisende": travellers},
        "reservierungsKontingenteVorhanden": False,
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.post(
            f"{BASE_URL}/angebote/fahrplan",
            json=body,
            headers=_base_headers(CT_JOURNEY),
        )
        resp.raise_for_status()
        return resp.json()
