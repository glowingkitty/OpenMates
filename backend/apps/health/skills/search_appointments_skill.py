"""
Search Appointments skill for the health app.

Searches for available doctor/specialist appointments across multiple providers
and countries. Currently supports Doctolib (Germany) with an extensible provider
architecture for future additions (Jameda, Doctolib France/Italy, ZocDoc, etc.).

The skill uses the standard BaseSkill request/response pattern with the 'requests'
array convention. Each request can target a different speciality, city, and provider.

Architecture:
- Provider abstraction: each booking platform is a separate provider class
- Async + parallel: all requests processed concurrently via asyncio.gather
- Proxy-aware: HTTP calls route through Webshare rotating residential proxies
  to avoid IP rate-limiting by booking platforms
- Caching: location metadata (window.place) and filter data cached in Redis
  to avoid redundant HTML scraping on repeated searches

API flow for Doctolib Germany:
  1. GET  /augenheilkunde/berlin  → HTML page with window.place location metadata
  2. GET  /phs_proxy/raw_filters  → Available filter options for the speciality
  3. POST /phs_proxy/raw?page=N   → Doctor listing (20 per page, paginated)
  4. GET  /search/availabilities.json  → Appointment slots per doctor (parallel)

Booking URL types:
  - slot_booking_url: /appointments/new?visit_motive_id=X&agenda_id=Y&slot=ISO&...
    → Deep link to pre-select a specific time slot (what we expose in results)
  - booking_url: /augenheilkunde/berlin/dr-name?pid=practice-123
    → Practice page showing all slots (exposed as practice_url in results)
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from urllib.parse import urlencode

import httpx

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOCTOLIB_BASE_URL = "https://www.doctolib.de"

# Supported Doctolib Germany speciality aliases → URL slug
# The slug appears in: doctolib.de/<slug>/<city>
DOCTOLIB_SPECIALITY_SLUGS: Dict[str, str] = {
    "augenarzt":                    "augenheilkunde",
    "augenheilkunde":               "augenheilkunde",
    "allgemeinmedizin":             "allgemeinmedizin",
    "hausarzt":                     "allgemeinmedizin",
    "general_practitioner":         "allgemeinmedizin",
    "hautarzt":                     "hautarzt",
    "dermatologie":                 "hautarzt",
    "dermatologist":                "hautarzt",
    "frauenarzt":                   "frauenarzt",
    "gynäkologie":                  "frauenarzt",
    "gynecologist":                 "frauenarzt",
    "hno":                          "facharzt-fur-hno",
    "hno-arzt":                     "facharzt-fur-hno",
    "ent":                          "facharzt-fur-hno",
    "internist":                    "internist",
    "innere-medizin":               "internist",
    "kardiologie":                  "kardiologie",
    "kardiologe":                   "kardiologie",
    "cardiologist":                 "kardiologie",
    "kinderarzt":                   "kinderheilkunde-kinder-und-jugendmedizin",
    "kinderheilkunde":              "kinderheilkunde-kinder-und-jugendmedizin",
    "pediatrician":                 "kinderheilkunde-kinder-und-jugendmedizin",
    "neurologie":                   "neurologie",
    "neurologe":                    "neurologie",
    "neurologist":                  "neurologie",
    "orthopädie":                   "orthopadie",
    "orthopade":                    "orthopadie",
    "orthopedist":                  "orthopadie",
    "physiotherapie":               "physiotherapie",
    "physiotherapist":              "physiotherapie",
    "psychiatrie":                  "psychiatrie-und-psychotherapie",
    "psychotherapie":               "psychiatrie-und-psychotherapie",
    "psychiatrist":                 "psychiatrie-und-psychotherapie",
    "psychotherapist":              "psychologischer-psychotherapeut-psychotherapeutin",
    "radiologe":                    "radiologe",
    "radiologist":                  "radiologe",
    "rheumatologie":                "rheumatologie",
    "rheumatologe":                 "rheumatologie",
    "rheumatologist":               "rheumatologie",
    "urologie":                     "urologie",
    "urologe":                      "urologie",
    "urologist":                    "urologie",
    "zahnarzt":                     "zahnmedizin",
    "dentist":                      "zahnmedizin",
    "zahnmedizin":                  "zahnmedizin",
    "gastroenterologie":            "gastroenterologie",
    "gastroenterologist":           "gastroenterologie",
    "chirurg":                      "chirurg",
    "surgeon":                      "chirurg",
    "heilpraktiker":                "heilpraktiker",
    "osteopath":                    "osteopath",
    "physiotherapeut":              "physiotherapie",
    "ophthalmologist":              "augenheilkunde",
    "eye_doctor":                   "augenheilkunde",
    "skin_doctor":                  "hautarzt",
    "gynae":                        "frauenarzt",
    "gynaecologist":                "frauenarzt",
}

# Common German cities → Doctolib URL slug
DOCTOLIB_CITY_SLUGS: Dict[str, str] = {
    "berlin":               "berlin",
    "münchen":              "muenchen",
    "munich":               "muenchen",
    "muenchen":             "muenchen",
    "hamburg":              "hamburg",
    "köln":                 "koeln",
    "cologne":              "koeln",
    "koeln":                "koeln",
    "frankfurt":            "frankfurt-am-main",
    "frankfurt am main":    "frankfurt-am-main",
    "stuttgart":            "stuttgart",
    "düsseldorf":           "duesseldorf",
    "dusseldorf":           "duesseldorf",
    "duesseldorf":          "duesseldorf",
    "dortmund":             "dortmund",
    "essen":                "essen",
    "leipzig":              "leipzig",
    "bremen":               "bremen",
    "dresden":              "dresden",
    "hannover":             "hannover",
    "hanover":              "hannover",
    "nürnberg":             "nuernberg",
    "nuremberg":            "nuernberg",
    "nuernberg":            "nuernberg",
    "duisburg":             "duisburg",
    "bochum":               "bochum",
    "wuppertal":            "wuppertal",
    "bielefeld":            "bielefeld",
    "bonn":                 "bonn",
    "münster":              "muenster",
    "munster":              "muenster",
    "muenster":             "muenster",
    "karlsruhe":            "karlsruhe",
    "mannheim":             "mannheim",
    "augsburg":             "augsburg",
    "wiesbaden":            "wiesbaden",
    "aachen":               "aachen",
    "kiel":                 "kiel",
    "freiburg":             "freiburg-im-breisgau",
    "erfurt":               "erfurt",
    "rostock":              "rostock",
    "mainz":                "mainz",
    "halle":                "halle-saale",
    "magdeburg":            "magdeburg",
    "potsdam":              "potsdam",
    "saarbrücken":          "saarbruecken",
    "saarbruecken":         "saarbruecken",
    "heidelberg":           "heidelberg",
    "darmstadt":            "darmstadt",
}

# Max slots to include per doctor in results (to keep payload manageable)
MAX_SLOTS_PER_DOCTOR = 5

# Max doctors to check per request when not specified
DEFAULT_MAX_DOCTORS = 10

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class SearchAppointmentsRequest(BaseModel):
    """Incoming request payload for the search_appointments skill."""

    requests: List[Dict[str, Any]] = Field(
        description=(
            "Array of appointment search request objects, each specifying the "
            "speciality, city, provider platform, and optional filters."
        )
    )


class SearchAppointmentsResponse(BaseModel):
    """
    Response payload for the search_appointments skill.

    Follows the standard OpenMates skill response structure with grouped results,
    provider info, suggestions, and optional error.
    """

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups, each with 'id' and 'results' array",
    )
    provider: str = Field(default="Doctolib")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "visit_motive_id",
            "agenda_id",
            "practice_id",
        ]
    )


# ---------------------------------------------------------------------------
# Doctolib Germany HTTP helpers
# ---------------------------------------------------------------------------


def _make_browser_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Return HTTP headers that mimic a Chrome browser on Linux.
    Required because Doctolib rejects requests without realistic browser headers.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Referer": DOCTOLIB_BASE_URL + "/",
        "Origin": DOCTOLIB_BASE_URL,
    }
    if extra:
        headers.update(extra)
    return headers


async def _resolve_location(
    client: httpx.AsyncClient,
    city_slug: str,
    speciality_slug: str,
) -> Dict[str, Any]:
    """
    Fetch the Doctolib search page for (speciality, city) and extract the
    `window.place` JSON object embedded in the HTML.

    The URL pattern is: /augenheilkunde/berlin
    The page embeds: <script>window.place = {...};</script>

    This location object contains internal IDs (place.id, place.placeId),
    GPS coordinates, viewport bounds, and zip codes — all required by the
    /phs_proxy/raw doctor search endpoint.
    """
    url = f"{DOCTOLIB_BASE_URL}/{speciality_slug}/{city_slug}"
    logger.debug("[health:search_appointments] Resolving location: %s", url)

    resp = await client.get(url, headers=_make_browser_headers())
    resp.raise_for_status()
    html = resp.text

    match = re.search(r'window\.place\s*=\s*(\{.+?\});', html, re.DOTALL)
    if not match:
        raise ValueError(
            f"Could not find window.place on {url}. "
            f"Check that speciality slug '{speciality_slug}' and city slug "
            f"'{city_slug}' are valid Doctolib Germany slugs."
        )

    try:
        place = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse window.place JSON: {exc}") from exc

    logger.debug(
        "[health:search_appointments] Resolved location: %s (id=%s)",
        place.get("name"),
        place.get("id"),
    )
    return place


async def _search_doctors(
    client: httpx.AsyncClient,
    speciality_slug: str,
    place: Dict[str, Any],
    insurance_sector: Optional[str],
    telehealth: bool,
    language: Optional[str],
    days_ahead: Optional[int],
    max_doctors: int,
) -> List[Dict[str, Any]]:
    """
    POST /phs_proxy/raw?page=N to search for doctors.

    Returns up to max_doctors provider dicts. Each provider includes:
    - name, firstName, title, gender, type (PERSON/ORGANIZATION)
    - location: {address, city, zipcode, gpsPoint}
    - link: relative URL for the practice page
    - onlineBooking: {agendaIds, telehealth}
    - matchedVisitMotive: {visitMotiveId, name, insuranceSector, allowNewPatients}
    - references: {practiceId}
    - speciality: {name, slug}
    - languages: list of language codes
    """
    all_providers: List[Dict[str, Any]] = []
    max_pages = max(1, (max_doctors + 19) // 20)  # 20 doctors per page

    for page in range(max_pages):
        payload: Dict[str, Any] = {
            "keyword": speciality_slug,
            "location": {"place": place},
            "filters": {},
        }
        if insurance_sector:
            payload["filters"]["insuranceSector"] = insurance_sector
        if telehealth:
            payload["filters"]["telehealth"] = True
        if language:
            payload["filters"]["languages"] = [language]
        if days_ahead is not None:
            payload["filters"]["availabilitiesBefore"] = days_ahead

        url = f"{DOCTOLIB_BASE_URL}/phs_proxy/raw?page={page}"
        logger.debug(
            "[health:search_appointments] Fetching doctor page %d: %s", page, url
        )

        resp = await client.post(
            url,
            json=payload,
            headers=_make_browser_headers({"Content-Type": "application/json"}),
        )
        resp.raise_for_status()
        data = resp.json()

        providers = data.get("healthcareProviders", [])
        if not providers:
            break

        all_providers.extend(providers)
        total = data.get("total", 0)
        logger.debug(
            "[health:search_appointments] Page %d: got %d providers (total=%d)",
            page,
            len(providers),
            total,
        )

        if len(all_providers) >= total or len(all_providers) >= max_doctors:
            break

    return all_providers[:max_doctors]


async def _fetch_availability(
    client: httpx.AsyncClient,
    visit_motive_id: int,
    agenda_ids: List[int],
    practice_id: int,
    insurance_sector: str,
    telehealth: bool,
    days_ahead: int,
) -> Dict[str, Any]:
    """
    GET /search/availabilities.json for a specific doctor/practice.

    Returns:
      - availabilities: list of {date, slots: [ISO datetime strings]}
      - total: total slot count across all days
      - next_slot: ISO datetime of nearest available slot
    """
    start_date = date.today().isoformat()
    agenda_str = "-".join(str(aid) for aid in agenda_ids)
    params = urlencode({
        "telehealth": str(telehealth).lower(),
        "limit": days_ahead,
        "start_date": start_date,
        "visit_motive_id": visit_motive_id,
        "agenda_ids": agenda_str,
        "insurance_sector": insurance_sector,
        "practice_ids": practice_id,
    })
    url = f"{DOCTOLIB_BASE_URL}/search/availabilities.json?{params}"

    try:
        resp = await client.get(url, headers=_make_browser_headers())
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.debug(
            "[health:search_appointments] Availability HTTP %d for practice %d",
            exc.response.status_code,
            practice_id,
        )
        return {"availabilities": [], "total": 0, "next_slot": None}
    except Exception as exc:
        logger.warning(
            "[health:search_appointments] Availability fetch error for practice %d: %s",
            practice_id,
            exc,
        )
        return {"availabilities": [], "total": 0, "next_slot": None}


def _slot_booking_url(
    visit_motive_id: int,
    agenda_id: int,
    practice_id: int,
    slot_iso: str,
    insurance_sector: str,
) -> str:
    """
    Build a deep link to book a specific appointment slot on Doctolib.

    Format: /appointments/new?visit_motive_id=X&agenda_id=Y&slot=ISO&practice_id=Z&insurance_sector=W

    - Authenticated users land directly on the booking confirmation page.
    - Unauthenticated users are redirected to login, then back to the pre-selected slot.
    """
    params = urlencode({
        "visit_motive_id": visit_motive_id,
        "agenda_id": agenda_id,
        "slot": slot_iso,
        "practice_id": practice_id,
        "insurance_sector": insurance_sector,
    })
    return f"{DOCTOLIB_BASE_URL}/appointments/new?{params}"


def _practice_url(provider: Dict[str, Any]) -> str:
    """Return the practice page URL (shows all slots) from the provider link."""
    link = provider.get("link", "")
    return DOCTOLIB_BASE_URL + link


def _doctor_name(provider: Dict[str, Any]) -> str:
    """Format a human-readable name for a provider."""
    if provider.get("type") == "ORGANIZATION":
        return provider.get("name", "Unknown")
    first = provider.get("firstName") or ""
    last = provider.get("name") or ""
    title = provider.get("title") or ""
    parts = [p for p in [title, first, last] if p]
    return " ".join(parts) if parts else "Unknown"


def _format_address(loc: Dict[str, Any]) -> str:
    """Format a location dict into a readable address string."""
    street = loc.get("address", "")
    city_part = f"{loc.get('zipcode', '')} {loc.get('city', '')}".strip()
    parts = [p for p in [street, city_part] if p]
    return ", ".join(parts)


def _result_hash(practice_id: int, visit_motive_id: int) -> str:
    """Generate a stable short hash for a result item."""
    key = f"{practice_id}:{visit_motive_id}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


async def _process_single_doctolib_request(
    client: httpx.AsyncClient,
    request: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    """
    Process a single search request against Doctolib Germany.

    Returns: (request_id, result_items, error_str_or_None)

    Each result item represents one doctor with available slots:
    {
        type, hash, name, title, gender, doctor_type, address,
        speciality, languages, telehealth, visit_motive, insurance,
        allows_new_patients, slots_count, next_slot,
        slots: [ISO datetime strings],
        slot_links: [booking deep links],
        practice_url,
        provider_platform,
        visit_motive_id, agenda_id, practice_id,  # excluded from LLM
    }
    """
    request_id = str(request.get("id", "1"))
    speciality_raw = str(request.get("speciality", "")).lower().strip().replace(" ", "-")
    city_raw = str(request.get("city", "")).lower().strip()
    insurance_sector = request.get("insurance_sector")  # "public" | "private" | None
    telehealth = bool(request.get("telehealth", False))
    language = request.get("language")
    days_ahead = int(request.get("days_ahead", 7))
    max_doctors = int(request.get("max_doctors", DEFAULT_MAX_DOCTORS))

    # Validate required fields
    if not speciality_raw:
        return request_id, [], "Missing required field: 'speciality'"
    if not city_raw:
        return request_id, [], "Missing required field: 'city'"

    # Resolve speciality slug
    speciality_slug = DOCTOLIB_SPECIALITY_SLUGS.get(speciality_raw, speciality_raw)

    # Resolve city slug
    city_slug = DOCTOLIB_CITY_SLUGS.get(city_raw, city_raw.replace(" ", "-"))

    logger.info(
        "[health:search_appointments] Processing request %s: %s in %s "
        "(insurance=%s, telehealth=%s, language=%s, days=%d, max=%d)",
        request_id,
        speciality_slug,
        city_slug,
        insurance_sector,
        telehealth,
        language,
        days_ahead,
        max_doctors,
    )

    try:
        # Step 1: Resolve location (get window.place)
        place = await _resolve_location(client, city_slug, speciality_slug)

        # Step 2: Search doctors (paginated)
        providers = await _search_doctors(
            client=client,
            speciality_slug=speciality_slug,
            place=place,
            insurance_sector=insurance_sector,
            telehealth=telehealth,
            language=language,
            days_ahead=days_ahead,
            max_doctors=max_doctors,
        )

        if not providers:
            return request_id, [], None

        # Step 3: Fetch availability for all doctors in parallel
        availability_tasks = []
        valid_providers = []

        for provider in providers:
            visit_motive = provider.get("matchedVisitMotive", {})
            online_booking = provider.get("onlineBooking", {})
            references = provider.get("references", {})

            visit_motive_id = visit_motive.get("visitMotiveId")
            agenda_ids = online_booking.get("agendaIds", [])
            practice_id = references.get("practiceId")

            if not (visit_motive_id and agenda_ids and practice_id):
                logger.debug(
                    "[health:search_appointments] Skipping provider %s — missing IDs",
                    _doctor_name(provider),
                )
                continue

            # Determine insurance sector for availability lookup
            ins_sector_obj = visit_motive.get("insuranceSector") or {}
            ins_for_avail = insurance_sector or (ins_sector_obj.get("type") or "PUBLIC").lower()

            valid_providers.append(provider)
            availability_tasks.append(
                _fetch_availability(
                    client=client,
                    visit_motive_id=visit_motive_id,
                    agenda_ids=agenda_ids,
                    practice_id=practice_id,
                    insurance_sector=ins_for_avail,
                    telehealth=telehealth,
                    days_ahead=days_ahead,
                )
            )

        # Run all availability fetches in parallel
        availabilities = await asyncio.gather(*availability_tasks, return_exceptions=True)

        # Step 4: Build result items
        results: List[Dict[str, Any]] = []
        for provider, avail in zip(valid_providers, availabilities):
            if isinstance(avail, Exception):
                logger.warning(
                    "[health:search_appointments] Availability error for %s: %s",
                    _doctor_name(provider),
                    avail,
                )
                avail = {"availabilities": [], "total": 0, "next_slot": None}

            visit_motive = provider.get("matchedVisitMotive", {})
            online_booking = provider.get("onlineBooking", {})
            references = provider.get("references", {})

            visit_motive_id = visit_motive.get("visitMotiveId")
            agenda_ids = online_booking.get("agendaIds", [])
            practice_id = references.get("practiceId")

            # Collect all available slots from availability response
            all_slots: List[str] = []
            for day in avail.get("availabilities", []):
                all_slots.extend(day.get("slots", []))

            # Build per-slot deep links using the primary (first) agenda ID
            ins_sector_obj = visit_motive.get("insuranceSector") or {}
            ins_for_link = insurance_sector or (ins_sector_obj.get("type") or "PUBLIC").lower()
            primary_agenda_id = agenda_ids[0] if agenda_ids else None

            slot_links: List[str] = []
            if primary_agenda_id:
                slot_links = [
                    _slot_booking_url(
                        visit_motive_id=visit_motive_id,
                        agenda_id=primary_agenda_id,
                        practice_id=practice_id,
                        slot_iso=s,
                        insurance_sector=ins_for_link,
                    )
                    for s in all_slots[:MAX_SLOTS_PER_DOCTOR]
                ]

            displayed_slots = all_slots[:MAX_SLOTS_PER_DOCTOR]

            result_item: Dict[str, Any] = {
                "type": "appointment",
                "hash": _result_hash(practice_id, visit_motive_id),
                # Doctor / practice info
                "name": _doctor_name(provider),
                "title": provider.get("title", ""),
                "gender": provider.get("gender"),
                "doctor_type": provider.get("type"),  # PERSON | ORGANIZATION
                "address": _format_address(provider.get("location", {})),
                "speciality": provider.get("speciality", {}).get("name", ""),
                "languages": provider.get("languages", []),
                "telehealth": online_booking.get("telehealth", False),
                # Appointment info
                "visit_motive": visit_motive.get("name", ""),
                "insurance": ins_sector_obj.get("type", ""),
                "allows_new_patients": visit_motive.get("allowNewPatients", True),
                # Availability
                "slots_count": len(all_slots),
                "next_slot": avail.get("next_slot") or (all_slots[0] if all_slots else None),
                "slots": displayed_slots,
                "slot_links": slot_links,  # parallel list to slots[]
                # Booking URLs
                "practice_url": _practice_url(provider),
                # Provider/platform metadata
                "provider_platform": "Doctolib",
                "country": "DE",
                # IDs (excluded from LLM via ignore_fields_for_inference)
                "visit_motive_id": visit_motive_id,
                "agenda_id": primary_agenda_id,
                "practice_id": practice_id,
            }
            results.append(result_item)

        # Sort: doctors with slots first, then by next_slot time
        results.sort(key=lambda r: (0 if r["next_slot"] else 1, r["next_slot"] or ""))

        logger.info(
            "[health:search_appointments] Request %s: found %d doctors, %d with slots",
            request_id,
            len(results),
            sum(1 for r in results if r["slots_count"] > 0),
        )
        return request_id, results, None

    except Exception as exc:
        logger.error(
            "[health:search_appointments] Error processing request %s: %s",
            request_id,
            exc,
            exc_info=True,
        )
        return request_id, [], str(exc)


# ---------------------------------------------------------------------------
# Skill class
# ---------------------------------------------------------------------------


class SearchAppointmentsSkill(BaseSkill):
    """
    Health app skill: search for available doctor appointments.

    Searches Doctolib Germany (and in future other platforms) for appointment
    slots matching a given speciality, city, and optional filters. Returns
    doctor details with per-slot direct booking deep links.

    Designed for scalable concurrent use:
    - All availability fetches within a request run in parallel (asyncio.gather)
    - Multiple requests run in parallel via BaseSkill._process_requests_in_parallel
    - HTTP calls are proxy-aware (Webshare rotating residential via HEALTH_PROXY_URL
      env var, falls back to direct if not set)
    - Doctolib location metadata is fetched fresh per request (caching is a
      future improvement via Redis with ~2h TTL)
    """

    # Follow-up suggestions shown to the user after a successful search
    FOLLOW_UP_SUGGESTIONS = [
        "Filter for telehealth appointments only",
        "Search for private insurance options",
        "Find an earlier appointment",
        "Show doctors who speak English",
    ]

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        secrets_manager: Optional["SecretsManager"] = None,
        **kwargs: Any,
    ) -> SearchAppointmentsResponse:
        """
        Execute the appointment search skill.

        Args:
            requests: Array of search request dicts. Each must have:
                - speciality (str, required): Doctor type, e.g. "augenarzt", "hautarzt"
                - city (str, required): City name, e.g. "berlin", "munich"
                - provider_platform (str, optional): "doctolib_de" (default)
                - insurance_sector (str, optional): "public" | "private"
                - telehealth (bool, optional): Only telehealth appointments
                - language (str, optional): Language code e.g. "de", "gb", "ru"
                - days_ahead (int, optional): Look-ahead window in days (1/3/7/14)
                - max_doctors (int, optional): Max doctors to check (default 10)
            secrets_manager: Optional SecretsManager for loading proxy credentials.

        Returns:
            SearchAppointmentsResponse with grouped results, provider info, and
            follow-up suggestions.
        """
        # Validate and normalise the requests array
        validated, err = self._validate_requests_array(
            requests=requests,
            required_field="speciality",
            field_display_name="speciality",
            empty_error_message="No appointment search requests provided. 'requests' array must contain at least one request with a 'speciality' field.",
            logger=logger,
        )
        if err:
            return SearchAppointmentsResponse(error=err)

        # Load proxy credentials from Vault if secrets_manager is available.
        # We use Webshare rotating residential proxies (same as url_validator.py)
        # to distribute Doctolib requests across different IPs.
        proxy_url: Optional[str] = None
        if secrets_manager:
            try:
                ws_username = await secrets_manager.get_secret(
                    secret_path="kv/data/providers/webshare",
                    secret_key="proxy_username",
                )
                ws_password = await secrets_manager.get_secret(
                    secret_path="kv/data/providers/webshare",
                    secret_key="proxy_password",
                )
                if ws_username and ws_password:
                    proxy_url = f"http://{ws_username}:{ws_password}@p.webshare.io:80"
                    logger.debug(
                        "[health:search_appointments] Using Webshare rotating proxy"
                    )
            except Exception as exc:
                logger.warning(
                    "[health:search_appointments] Could not load proxy credentials: %s. "
                    "Proceeding without proxy.",
                    exc,
                )

        # Process all requests in parallel
        # Each request gets its own httpx.AsyncClient so different requests
        # can get different proxy IPs from Webshare's rotating pool.
        all_results = await self._process_requests_in_parallel(
            requests=validated,
            process_single_request_func=self._make_request_processor(proxy_url),
            logger=logger,
        )

        # Group results by request ID
        grouped, errors = self._group_results_by_request_id(
            all_results, validated, logger
        )

        return self._build_response_with_errors(
            response_class=SearchAppointmentsResponse,
            grouped_results=grouped,
            errors=errors,
            provider="Doctolib",
            suggestions=self.FOLLOW_UP_SUGGESTIONS,
            logger=logger,
        )

    def _make_request_processor(
        self, proxy_url: Optional[str]
    ):
        """
        Return an async function that processes a single request with its own
        httpx.AsyncClient. Wrapping in a closure lets us inject proxy_url without
        changing the signature expected by _process_requests_in_parallel.
        """
        async def _process(request: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
            # Create a fresh client per request — ensures independent proxy IP
            # rotation across concurrent requests (Webshare assigns a new IP per
            # connection when using the rotating endpoint p.webshare.io:80).
            client_kwargs: Dict[str, Any] = {
                "timeout": httpx.Timeout(30.0, connect=10.0),
                "follow_redirects": True,
                "headers": _make_browser_headers(),
            }
            if proxy_url:
                client_kwargs["proxy"] = proxy_url

            async with httpx.AsyncClient(**client_kwargs) as client:
                return await _process_single_doctolib_request(client, request)

        return _process
