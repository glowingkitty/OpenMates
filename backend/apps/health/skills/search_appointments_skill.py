"""
Search Appointments skill for the health app.

Searches for available doctor/specialist appointments across multiple providers
and countries. Supports Doctolib Germany and Jameda (DocPlanner) with a simple
provider dispatch based on the `provider_platform` request field.

The skill uses the standard BaseSkill request/response pattern with the 'requests'
array convention. Each request can target a different speciality, city, and provider.

Architecture:
- Two providers in one file: Doctolib (reverse-engineered scraping) and Jameda
  (reverse-engineered DocPlanner API with anonymous token auth)
- Async + parallel: all requests processed concurrently via asyncio.gather
- Proxy-aware: Doctolib routes through Webshare rotating residential proxies;
  Jameda needs no proxy (token-based auth, no anti-bot)

API flow for Doctolib Germany:
  1. GET  /augenheilkunde/berlin  → HTML page with window.place location metadata
  2. POST /phs_proxy/raw?page=N   → Doctor listing (20 per page, paginated)
  3. GET  /search/availabilities.json  → Appointment slots per doctor (parallel)

API flow for Jameda (DocPlanner):
  1. GET  /token                                  → Anonymous access_token (24h TTL)
  2. GET  /allgemeinmediziner/berlin               → HTML search page, extract data-doctor-id
  3. GET  /api/v3/doctors/{id}/addresses            → Doctor addresses with has_slots flag
  4. GET  /api/v3/doctors/{id}/addresses/{id}/slots → Available slots with booking URLs
  5. GET  /api/v3/doctors/{id}/addresses/{id}/services → Service list with prices

URL types exposed in results:
  - practice_url: Doctolib practice page with live availability (always valid)
  - booking_url: Jameda direct slot booking URL (time-specific, but more durable)
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from urllib.parse import urlencode

import httpx

from backend.shared.testing.caching_http_transport import create_http_client

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.ai.processing.external_result_sanitizer import sanitize_long_text_fields_in_payload

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
    "allgemeinmediziner":           "allgemeinmedizin",
    "allgemeinarzt":                "allgemeinmedizin",
    "hausarzt":                     "allgemeinmedizin",
    "general_practitioner":         "allgemeinmedizin",
    "hautarzt":                     "hautarzt",
    "dermatologie":                 "hautarzt",
    "dermatologist":                "hautarzt",
    "frauenarzt":                   "frauenarzt",
    "gynäkologie":                  "frauenarzt",
    "gynaekologie":                 "frauenarzt",
    "gynakologie":                  "frauenarzt",
    "gynäkologe":                   "frauenarzt",
    "gynaekologe":                  "frauenarzt",
    "gynakologe":                   "frauenarzt",
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
    "radiologin":                   "radiologe",
    "radiologist":                  "radiologe",
    # LLMs commonly pass "radiologie" (the German field name, not the
    # profession) — Doctolib serves the URL under "radiologe", not "radiologie".
    "radiologie":                   "radiologe",
    "radiology":                    "radiologe",
    "diagnostische-radiologie":     "radiologe",
    "radiologische-diagnostik":     "radiologe",
    # MRT/MRI/CT/Röntgen/Ultraschall are imaging procedures performed by
    # radiologists — route them all to the radiologe speciality so the LLM
    # can pass the procedure name verbatim without us returning 404.
    "mrt":                          "radiologe",
    "mri":                          "radiologe",
    "magnetresonanztomographie":    "radiologe",
    "magnetresonanz":               "radiologe",
    "kernspintomographie":          "radiologe",
    "kernspin":                     "radiologe",
    "ct":                           "radiologe",
    "computertomographie":          "radiologe",
    "computertomografie":           "radiologe",
    "röntgen":                      "radiologe",
    "rontgen":                      "radiologe",
    "roentgen":                     "radiologe",
    "x-ray":                        "radiologe",
    "xray":                         "radiologe",
    "ultraschall":                  "radiologe",
    "ultrasound":                   "radiologe",
    "sonographie":                  "radiologe",
    "sonografie":                   "radiologe",
    "mammographie":                 "radiologe",
    "mammografie":                  "radiologe",
    "mammogram":                    "radiologe",
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

# Max total appointment slots to return per request (soonest first).
# Used as the per-provider cap BEFORE grouping by doctor.
DEFAULT_MAX_SLOTS = 60  # 6 doctors × ~10 slots each worst case

# Max doctors to return per request after grouping slots by doctor.
# Each returned doctor card shows one primary slot + up to 5 additional slots.
DEFAULT_MAX_DOCTORS_RETURNED = 6

# Max alternate slot datetimes to attach to each doctor card.
DEFAULT_MAX_ADDITIONAL_SLOTS = 5

# Max doctors to check per request when not specified
DEFAULT_MAX_DOCTORS = 10

# When visit_motive_category filtering is active, search a larger doctor pool
# then filter down, so we have enough relevant results after filtering.
FILTERED_SEARCH_MAX_DOCTORS = 30

# Retry configuration for transient Doctolib errors (403 from anti-bot, 429
# rate limits). Each retry uses a fresh proxy IP via Webshare's rotating pool.
DOCTOLIB_MAX_RETRIES = 5
DOCTOLIB_RETRY_DELAY_SECONDS = 2
# /search/availabilities.json enforces limit <= 7 days (2026-Q1 change).
DOCTOLIB_MAX_LIMIT_DAYS = 7

# ---------------------------------------------------------------------------
# Jameda (DocPlanner) constants
# ---------------------------------------------------------------------------

JAMEDA_BASE_URL = "https://www.jameda.de"

# Anonymous token cache — refreshed 1h before 24h expiry.
# Module-level dict so it persists across requests within the same process.
JAMEDA_TOKEN_TTL_SECONDS = 23 * 3600
_jameda_token_cache: Dict[str, Any] = {"token": None, "expires_at": 0.0}

# Jameda speciality aliases → URL slug (verified against jameda.de)
# URL pattern: jameda.de/<slug>/<city>
JAMEDA_SPECIALITY_SLUGS: Dict[str, str] = {
    "augenarzt":                    "augenarzt",
    "augenheilkunde":               "augenarzt",
    "ophthalmologist":              "augenarzt",
    "eye_doctor":                   "augenarzt",
    "allgemeinmedizin":             "allgemeinmediziner",
    "hausarzt":                     "hausarzt",
    "general_practitioner":         "allgemeinmediziner",
    "hautarzt":                     "hautarzt-dermatologe",
    "dermatologie":                 "hautarzt-dermatologe",
    "dermatologist":                "hautarzt-dermatologe",
    "skin_doctor":                  "hautarzt-dermatologe",
    "frauenarzt":                   "frauenarzt-gynaekologe",
    "gynäkologie":                  "frauenarzt-gynaekologe",
    "gynecologist":                 "frauenarzt-gynaekologe",
    "gynae":                        "frauenarzt-gynaekologe",
    "gynaecologist":                "frauenarzt-gynaekologe",
    "hno":                          "hals-nasen-ohren-arzt",
    "hno-arzt":                     "hals-nasen-ohren-arzt",
    "ent":                          "hals-nasen-ohren-arzt",
    "internist":                    "internist",
    "innere-medizin":               "internist",
    "kardiologie":                  "kardiologe",
    "kardiologe":                   "kardiologe",
    "cardiologist":                 "kardiologe",
    "kinderarzt":                   "kinder-und-jugendarzt",
    "kinderheilkunde":              "kinder-und-jugendarzt",
    "pediatrician":                 "kinder-und-jugendarzt",
    "neurologie":                   "neurologe",
    "neurologe":                    "neurologe",
    "neurologist":                  "neurologe",
    "orthopädie":                   "orthopaede",
    "orthopade":                    "orthopaede",
    "orthopedist":                  "orthopaede",
    "urologie":                     "urologe",
    "urologe":                      "urologe",
    "urologist":                    "urologe",
    "zahnarzt":                     "zahnarzt",
    "dentist":                      "zahnarzt",
    "zahnmedizin":                  "zahnarzt",
    "gastroenterologie":            "gastroenterologe",
    "gastroenterologist":           "gastroenterologe",
    "chirurg":                      "chirurg",
    "surgeon":                      "chirurg",
    "radiologe":                    "radiologe",
    "radiologin":                   "radiologe",
    "radiologist":                  "radiologe",
    "radiologie":                   "radiologe",
    "radiology":                    "radiologe",
    # MRT/CT/Röntgen/Ultraschall are procedures done by radiologists.
    "mrt":                          "radiologe",
    "mri":                          "radiologe",
    "magnetresonanztomographie":    "radiologe",
    "kernspintomographie":          "radiologe",
    "kernspin":                     "radiologe",
    "ct":                           "radiologe",
    "computertomographie":          "radiologe",
    "röntgen":                      "radiologe",
    "rontgen":                      "radiologe",
    "roentgen":                     "radiologe",
    "x-ray":                        "radiologe",
    "ultraschall":                  "radiologe",
    "ultrasound":                   "radiologe",
    "sonographie":                  "radiologe",
    "mammographie":                 "radiologe",
    "rheumatologie":                "rheumatologe",
    "rheumatologe":                 "rheumatologe",
    "rheumatologist":               "rheumatologe",
    "psychiatrie":                  "psychiater",
    "psychiatrist":                 "psychiater",
    "psychotherapie":               "psychotherapeut",
    "psychotherapist":              "psychotherapeut",
}

# Jameda city slugs — mostly plain lowercase city names.
# Where Jameda differs from Doctolib (which uses e.g. "frankfurt-am-main"),
# we override here. For cities not listed, we use the raw lowercase input
# (which is correct for most German cities on Jameda).
JAMEDA_CITY_SLUGS: Dict[str, str] = {
    "münchen":              "muenchen",
    "munich":               "muenchen",
    "muenchen":             "muenchen",
    "köln":                 "koeln",
    "cologne":              "koeln",
    "koeln":                "koeln",
    "düsseldorf":           "duesseldorf",
    "dusseldorf":           "duesseldorf",
    "duesseldorf":          "duesseldorf",
    "nürnberg":             "nuernberg",
    "nuremberg":            "nuernberg",
    "nuernberg":            "nuernberg",
    "münster":              "muenster",
    "munster":              "muenster",
    "muenster":             "muenster",
    "saarbrücken":          "saarbruecken",
    "saarbruecken":         "saarbruecken",
    "hanover":              "hannover",
    # Jameda uses plain "frankfurt", NOT "frankfurt-am-main"
    "frankfurt":            "frankfurt",
    "frankfurt am main":    "frankfurt",
    # Jameda uses plain "freiburg", NOT "freiburg-im-breisgau"
    "freiburg":             "freiburg",
    # Jameda uses plain "halle", NOT "halle-saale"
    "halle":                "halle",
}

# ---------------------------------------------------------------------------
# Visit motive category filtering
# ---------------------------------------------------------------------------
# Doctolib returns one "matchedVisitMotive" per doctor. The motive name is
# chosen by Doctolib's algorithm and often returns irrelevant types like
# "Impfung" or "DMP" when the user wants a general consultation.
#
# These patterns let us filter by category AFTER the search (no extra API
# calls needed). Each category maps to regex patterns (case-insensitive)
# that match against the German motive names returned by Doctolib.

VISIT_MOTIVE_CATEGORIES: Dict[str, List[str]] = {
    # General consultation / acute visit — the most common user intent
    "general": [
        r"erstuntersuchung",
        r"neupatient",
        r"akut",
        r"sprechstunde",
        r"allgemein",
        r"beratung",
        r"konsultation",
        r"consultation",
        r"(?:^|\s)termin(?:vereinbarung)?$",
        r"hausärztlich",
        r"hausarzt",
        r"schmerz",              # Schmerztermin (dentist pain appointment)
        r"beschwerden",          # Akute Beschwerden (already covered by akut, but explicit)
        r"notfall",              # Notfall / Notfallsprechstunde
        r"untersuchung",         # General examination
        r"behandlung(?!\s+bot)", # Behandlung but NOT "Behandlung Botox..."
    ],
    # Preventive checkups and screenings
    "checkup": [
        r"vorsorge",
        r"check[\s-]?up",
        r"gesundheitsuntersuchung",
        r"früherkennung",
        r"screening",
        r"j[12]\b",
        r"u\d+\b",
        r"krebsvorsorge",
        r"hautkrebsscreening",
        r"gesichtsfeld",          # Visual field test (ophthalmology screening)
    ],
    # Vaccinations
    "vaccination": [
        r"impf",
        r"vaccin",
    ],
    # Follow-up / existing patient
    "followup": [
        r"folge",
        r"kontroll",
        r"nachsorge",
        r"wiedervorstellung",
        r"bestandspatient",
        r"follow[\s-]?up",
    ],
}

# Motive names that are almost never what a general user wants.
# These are excluded when ANY category filter is active, unless the
# motive also matches the requested category patterns.
NOISE_MOTIVE_PATTERNS: List[str] = [
    r"renafan",
    r"disease\s+management",
    r"\bdmp\b",
    r"rettungsstelle",
    r"hausarztrettungsstelle",
    r"gutachten",
    r"attest",
    r"reisemedizin",
    r"tauchtauglichkeit",
    r"führerschein",
    r"sportmedizin",
    r"botox",
    r"hyaluron",
    r"filler",
    r"lasik",
    r"brillenfrei",
    r"ästhetik",
    r"kosmetisch",
    r"bleaching",
    r"professionelle\s+zahnreinigung",  # PZR — dental cleaning, not a medical visit
]


def _matches_motive_category(motive_name: str, category: str) -> bool:
    """Check if a visit motive name matches a given category.

    Returns True if the motive matches any pattern in the category,
    AND does not match a known noise pattern (unless the noise pattern
    also matches the category).
    """
    if not motive_name or category not in VISIT_MOTIVE_CATEGORIES:
        return False

    name_lower = motive_name.lower()

    # Check if it matches the requested category
    category_match = any(
        re.search(pattern, name_lower)
        for pattern in VISIT_MOTIVE_CATEGORIES[category]
    )
    if not category_match:
        return False

    # Even if it matched the category, reject known noise
    is_noise = any(
        re.search(pattern, name_lower)
        for pattern in NOISE_MOTIVE_PATTERNS
    )
    return not is_noise


def _is_noise_motive(motive_name: str) -> bool:
    """Check if a visit motive name is known noise (irrelevant for most users)."""
    if not motive_name:
        return False
    name_lower = motive_name.lower()
    return any(
        re.search(pattern, name_lower)
        for pattern in NOISE_MOTIVE_PATTERNS
    )

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class SearchAppointmentsRequestItem(BaseModel):
    """A single appointment search request."""

    speciality: str = Field(
        description="Doctor speciality or type (e.g. 'augenarzt', 'hautarzt', 'zahnarzt', "
        "'ophthalmologist', 'dermatologist', 'general_practitioner', 'dentist', 'cardiologist')."
    )
    city: str = Field(
        description="City where to search for appointments (e.g. 'Berlin', 'München', 'Munich', 'Hamburg')."
    )
    provider_platform: str = Field(
        default="both",
        description=(
            "Booking platform to search. 'both' (default) searches Doctolib and Jameda "
            "in parallel and merges results. 'doctolib_de' for Doctolib Germany only. "
            "'jameda' for Jameda Germany only (includes ratings, prices, direct booking URLs)."
        ),
    )
    insurance_sector: Optional[str] = Field(
        default=None,
        description="Insurance type filter: 'public' (GKV) or 'private' (PKV). Omit for all types.",
    )
    telehealth: bool = Field(
        default=False,
        description="If true, only return doctors offering telehealth (video consultation) appointments.",
    )
    language: Optional[str] = Field(
        default=None,
        description="Filter for doctors who speak a specific language (e.g. 'de', 'gb', 'ru', 'tr').",
    )
    days_ahead: Optional[int] = Field(
        default=None,
        description="Number of days ahead to look for availability.",
    )
    visit_motive_category: Optional[str] = Field(
        default=None,
        description=(
            "Filter results by appointment type category. Supported categories: "
            "'general' (consultation, acute visit, new patient), "
            "'checkup' (preventive screening, health check), "
            "'vaccination' (immunisation), "
            "'followup' (follow-up, existing patient). "
            "When set, increases the doctor search pool and filters by visit motive "
            "name to return only relevant appointment types."
        ),
    )


class SearchAppointmentsRequest(BaseModel):
    """Incoming request payload for the search_appointments skill."""

    requests: List[SearchAppointmentsRequestItem] = Field(
        description=(
            "Array of appointment search requests, each specifying the "
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
        # NOTE: Do NOT pass 'availabilitiesBefore' to /phs_proxy/raw.
        # Empirically, that filter causes Doctolib to return 0 results regardless
        # of actual availability. The days_ahead window is already applied per-doctor
        # via the 'limit' parameter in _fetch_availability() → /search/availabilities.json.
        # days_ahead is intentionally unused in this search phase.

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
    # Doctolib's /search/availabilities.json contract changed in 2026-Q1:
    #   • `start_date` (date-only) → `start_date_time` (ISO8601 with time zone)
    #   • `insurance_sector` must be lowercase "public" / "private" / "none"
    #   • `limit` is now capped at <= 7 days (400 "limit: must be less than
    #     or equal to 7" otherwise) — previously 14 was accepted.
    start_dt = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    agenda_str = "-".join(str(aid) for aid in agenda_ids)
    clamped_limit = min(max(1, days_ahead), DOCTOLIB_MAX_LIMIT_DAYS)
    params = urlencode({
        "telehealth": str(telehealth).lower(),
        "limit": clamped_limit,
        "start_date_time": start_dt,
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
        # Log at WARNING so contract drift (e.g. the 2026-Q1 start_date →
        # start_date_time rename) is visible without changing log levels.
        body_preview = ""
        try:
            body_preview = exc.response.text[:200]
        except Exception:
            pass
        logger.warning(
            "[health:search_appointments] Availability HTTP %d for practice %d: %s",
            exc.response.status_code,
            practice_id,
            body_preview,
        )
        return {"availabilities": [], "total": 0, "next_slot": None}
    except Exception as exc:
        logger.warning(
            "[health:search_appointments] Availability fetch error for practice %d: %s",
            practice_id,
            exc,
        )
        return {"availabilities": [], "total": 0, "next_slot": None}


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


def _extract_gps(loc: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Extract GPS coordinates from a Doctolib location dict.

    Returns {latitude, longitude} or None if coordinates are unavailable.
    The Doctolib API provides a gpsPoint string like "lat,lon".
    """
    gps_point = loc.get("gpsPoint", "")
    if not gps_point or "," not in str(gps_point):
        return None
    try:
        parts = str(gps_point).split(",")
        lat = float(parts[0].strip())
        lon = float(parts[1].strip())
        return {"latitude": lat, "longitude": lon}
    except (ValueError, IndexError):
        return None


def _result_hash(practice_id: int, visit_motive_id: int, slot_datetime: str = "") -> str:
    """Generate a stable short hash for a result item."""
    key = f"{practice_id}:{visit_motive_id}:{slot_datetime}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Post-processing helpers — past-slot filter, grouping, Google Places enrichment
# ---------------------------------------------------------------------------


def _filter_past_slots(slot_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop any slot whose datetime is already in the past.

    Some provider APIs (notably Jameda) occasionally return stale cached slots
    that have already been booked or passed. Filtering them up front prevents
    cards that point at expired appointments.
    """
    now = datetime.now(timezone.utc)
    fresh: List[Dict[str, Any]] = []
    for item in slot_items:
        raw_dt = item.get("slot_datetime", "")
        if not raw_dt:
            continue
        try:
            # Accept ISO 8601 with or without tz; assume UTC if naive.
            parsed = datetime.fromisoformat(str(raw_dt).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed >= now:
                fresh.append(item)
        except (ValueError, TypeError):
            # Keep items with unparseable timestamps — safer than dropping them
            fresh.append(item)
    return fresh


def _group_slots_by_doctor(
    slot_items: List[Dict[str, Any]],
    max_additional: int = DEFAULT_MAX_ADDITIONAL_SLOTS,
) -> List[Dict[str, Any]]:
    """Collapse per-slot results into one result per doctor.

    Each returned item keeps the earliest slot as `slot_datetime` and adds:
      - `additional_slot_datetimes`: list of up to `max_additional` next slot ISOs
      - `additional_slot_count`: total number of additional slots beyond the primary

    The doctor key combines `practice_id` and `visit_motive_id` so that a
    doctor with multiple motives still produces one card per motive (matching
    what the appointment search was actually for).

    Preserves input order for the primary slot assignment: the first slot seen
    for each doctor wins, so upstream sorting (earliest first) is honored.
    """
    seen_keys: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
    extras_by_key: Dict[Tuple[Any, Any], List[str]] = {}

    for item in slot_items:
        practice_id = item.get("practice_id")
        visit_motive_id = item.get("visit_motive_id")
        # Fall back to (name, address) when IDs are missing — defensive.
        key: Tuple[Any, Any] = (
            practice_id if practice_id is not None else item.get("name", ""),
            visit_motive_id if visit_motive_id is not None else item.get("address", ""),
        )

        if key not in seen_keys:
            seen_keys[key] = dict(item)  # Copy so we can mutate without affecting input
            extras_by_key[key] = []
        else:
            extras_by_key[key].append(item.get("slot_datetime", ""))

    grouped: List[Dict[str, Any]] = []
    for key, primary in seen_keys.items():
        extras = [dt for dt in extras_by_key[key] if dt]
        primary["additional_slot_datetimes"] = extras[:max_additional]
        primary["additional_slot_count"] = len(extras)
        grouped.append(primary)

    # Preserve earliest-slot ordering
    grouped.sort(key=lambda r: r.get("slot_datetime", ""))
    return grouped


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
        slots: [{datetime: ISO string}],   # datetimes only — no booking URLs (they expire)
        practice_url,                      # live availability page, always valid
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
    # Use "or" to handle None from Pydantic model_dump() — prevents int(None) TypeError
    days_ahead = int(request.get("days_ahead") or 7)
    max_doctors = int(request.get("max_doctors", DEFAULT_MAX_DOCTORS))
    visit_motive_category = request.get("visit_motive_category")

    # When a motive category is set, widen the search pool so that after
    # filtering we still have enough doctors to fill DEFAULT_MAX_SLOTS.
    if visit_motive_category:
        search_max_doctors = max(max_doctors, FILTERED_SEARCH_MAX_DOCTORS)
    else:
        search_max_doctors = max_doctors

    # Validate required fields
    if not speciality_raw:
        return request_id, [], "Missing required field: 'speciality'"
    if not city_raw:
        return request_id, [], "Missing required field: 'city'"
    if visit_motive_category and visit_motive_category not in VISIT_MOTIVE_CATEGORIES:
        return request_id, [], (
            f"Unknown visit_motive_category '{visit_motive_category}'. "
            f"Supported: {', '.join(sorted(VISIT_MOTIVE_CATEGORIES.keys()))}"
        )

    # Resolve speciality slug — warn loudly when the LLM passes an unknown
    # term so we can add the mapping. Without the warning, an unknown
    # speciality silently falls through and Doctolib returns 404 for every
    # request (seen in issue 0d5b2385 where "mrt" and "radiologie" both hit
    # the fallback path and produced zero results).
    speciality_slug = DOCTOLIB_SPECIALITY_SLUGS.get(speciality_raw)
    if speciality_slug is None:
        speciality_slug = speciality_raw
        logger.warning(
            "[health:search_appointments] Doctolib speciality '%s' not in "
            "DOCTOLIB_SPECIALITY_SLUGS map. Using raw value as slug — this "
            "will likely 404. Add a mapping in search_appointments_skill.py "
            "DOCTOLIB_SPECIALITY_SLUGS dict.",
            speciality_raw,
        )

    # Resolve city slug
    city_slug = DOCTOLIB_CITY_SLUGS.get(city_raw, city_raw.replace(" ", "-"))

    logger.info(
        "[health:search_appointments] Processing request %s: %s in %s "
        "(insurance=%s, telehealth=%s, language=%s, days=%d, max=%d, motive_category=%s)",
        request_id,
        speciality_slug,
        city_slug,
        insurance_sector,
        telehealth,
        language,
        days_ahead,
        max_doctors,
        visit_motive_category,
    )

    try:
        # Step 1: Resolve location (get window.place)
        place = await _resolve_location(client, city_slug, speciality_slug)

        # Step 2: Search doctors (paginated)
        # When filtering by motive category, search a larger pool (search_max_doctors)
        # so we have enough relevant results after filtering.
        providers = await _search_doctors(
            client=client,
            speciality_slug=speciality_slug,
            place=place,
            insurance_sector=insurance_sector,
            telehealth=telehealth,
            language=language,
            days_ahead=days_ahead,
            max_doctors=search_max_doctors,
        )

        if not providers:
            return request_id, [], None

        # Step 2b: Filter by visit motive category (if requested)
        # This is a client-side filter on the matchedVisitMotive.name returned
        # by Doctolib for each provider. No extra API calls needed.
        if visit_motive_category:
            pre_filter_count = len(providers)
            providers = [
                p for p in providers
                if _matches_motive_category(
                    p.get("matchedVisitMotive", {}).get("name", ""),
                    visit_motive_category,
                )
            ]
            logger.info(
                "[health:search_appointments] Motive filter '%s': %d/%d providers passed",
                visit_motive_category,
                len(providers),
                pre_filter_count,
            )
            if not providers:
                return request_id, [], None

        # Cap filtered providers at max_doctors for availability fetching
        providers = providers[:max_doctors]

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

        # Step 4: Collect all slots across all doctors, then flatten to per-slot results
        # Each result item = one appointment slot with duplicated doctor metadata.
        # Sorted by slot_datetime ascending (soonest first), capped at DEFAULT_MAX_SLOTS.
        all_slot_items: List[Dict[str, Any]] = []
        doctors_checked = 0
        doctors_with_slots = 0

        for provider, avail in zip(valid_providers, availabilities):
            if isinstance(avail, Exception):
                logger.warning(
                    "[health:search_appointments] Availability error for %s: %s",
                    _doctor_name(provider),
                    avail,
                )
                avail = {"availabilities": [], "total": 0, "next_slot": None}

            doctors_checked += 1
            visit_motive = provider.get("matchedVisitMotive", {})
            online_booking = provider.get("onlineBooking", {})
            references = provider.get("references", {})

            visit_motive_id = visit_motive.get("visitMotiveId")
            agenda_ids = online_booking.get("agendaIds", [])
            practice_id = references.get("practiceId")

            # Collect all available slots from availability response.
            # Doctolib returns two shapes depending on the visit motive:
            #   - plain ISO8601 strings for single-step motives
            #   - dicts {agenda_id, start_date, end_date, master_step, steps}
            #     for multi-step procedures (e.g. laser treatments at a
            #     Hautarzt). Normalise both to the start ISO string and drop
            #     anything we can't recognise.
            slot_datetimes: List[str] = []
            for day in avail.get("availabilities", []):
                for slot in day.get("slots", []):
                    if isinstance(slot, str):
                        slot_datetimes.append(slot)
                    elif isinstance(slot, dict):
                        start_iso = slot.get("start_date")
                        if isinstance(start_iso, str):
                            slot_datetimes.append(start_iso)

            if not slot_datetimes:
                continue

            doctors_with_slots += 1
            ins_sector_obj = visit_motive.get("insuranceSector") or {}
            primary_agenda_id = agenda_ids[0] if agenda_ids else None

            # Shared doctor metadata — duplicated into each slot item
            doctor_metadata = {
                "name": _doctor_name(provider),
                "title": provider.get("title", ""),
                "gender": provider.get("gender"),
                "doctor_type": provider.get("type"),  # PERSON | ORGANIZATION
                "address": _format_address(provider.get("location", {})),
                "gps_coordinates": _extract_gps(provider.get("location", {})),
                "speciality": provider.get("speciality", {}).get("name", ""),
                "languages": provider.get("languages", []),
                "telehealth": online_booking.get("telehealth", False),
                "visit_motive": visit_motive.get("name", ""),
                "insurance": ins_sector_obj.get("type", ""),
                "allows_new_patients": visit_motive.get("allowNewPatients", True),
                "practice_url": _practice_url(provider),
                "provider_platform": "Doctolib",
                "country": "DE",
                # Jameda-specific fields (null for Doctolib results)
                "booking_url": None,
                "rating": None,
                "rating_count": None,
                "price": None,
                "service_name": None,
                # Internal IDs (excluded from LLM)
                "visit_motive_id": visit_motive_id,
                "agenda_id": primary_agenda_id,
                "practice_id": practice_id,
            }

            # Create one result item per slot
            for slot_dt in slot_datetimes:
                slot_item: Dict[str, Any] = {
                    "type": "appointment",
                    "hash": _result_hash(practice_id, visit_motive_id, slot_dt),
                    "slot_datetime": slot_dt,
                    **doctor_metadata,
                }
                all_slot_items.append(slot_item)

        # Sort all slots by datetime ascending (soonest first), cap at DEFAULT_MAX_SLOTS
        all_slot_items.sort(key=lambda r: r["slot_datetime"])
        results: List[Dict[str, Any]] = all_slot_items[:DEFAULT_MAX_SLOTS]

        logger.info(
            "[health:search_appointments] Request %s: checked %d doctors, %d with slots, returning %d slot results",
            request_id,
            doctors_checked,
            doctors_with_slots,
            len(results),
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
# Jameda (DocPlanner) HTTP helpers
# ---------------------------------------------------------------------------


async def _get_jameda_token(client: httpx.AsyncClient) -> str:
    """Obtain an anonymous Jameda access_token via GET /token.

    Token is cached in-memory for ~23 hours (token valid 24h).
    No authentication required — any visitor can get a token.
    """
    now = time.time()
    if _jameda_token_cache["token"] and now < _jameda_token_cache["expires_at"]:
        return _jameda_token_cache["token"]

    resp = await client.get(
        f"{JAMEDA_BASE_URL}/token",
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    _jameda_token_cache["token"] = token
    _jameda_token_cache["expires_at"] = now + JAMEDA_TOKEN_TTL_SECONDS
    logger.debug("[health:jameda] Obtained anonymous token (cached %dh)", JAMEDA_TOKEN_TTL_SECONDS // 3600)
    return token


def _jameda_api_headers(token: str) -> Dict[str, str]:
    """Return headers for Jameda DocPlanner API calls."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Referer": f"{JAMEDA_BASE_URL}/",
    }


async def _jameda_search_doctors_algolia(
    client: httpx.AsyncClient,
    speciality_slug: str,
    city_slug: str,
    max_doctors: int,
) -> List[Dict[str, Any]]:
    """Search Jameda doctors via the DocPlanner Algolia index.

    Uses the public Algolia API (same key the Jameda frontend uses) to search
    the de_autocomplete_doctor index. Returns doctor IDs, ratings, and review
    counts — no HTML scraping needed.

    Returns list of dicts: {doctor_id, name, rating, rating_count, has_calendar}.
    Only returns doctors with calendar=True (online booking enabled).
    """
    # Algolia search query: "speciality_slug city_slug"
    # The index is full-text — searching "allgemeinmediziner berlin" matches
    # doctors whose URL or specialization contains those terms.
    query = f"{speciality_slug} {city_slug}"

    resp = await client.post(
        "https://docplanner-dsn.algolia.net/1/indexes/*/queries",
        json={
            "requests": [{
                "indexName": "de_autocomplete_doctor",
                "params": (
                    f"query={query}"
                    f"&hitsPerPage={max_doctors}"
                    "&attributesToRetrieve=objectID,fullname_formatted,specializations,"
                    "cities,calendar,stars,opinionCount"
                ),
            }],
        },
        headers={
            "x-algolia-api-key": "189da7b805744e97ef09dea8dbe7e35f",
            "x-algolia-application-id": "docplanner",
            "Content-Type": "application/json",
            "Referer": f"{JAMEDA_BASE_URL}/",
            "Origin": JAMEDA_BASE_URL,
        },
    )
    resp.raise_for_status()
    data = resp.json()

    hits = data.get("results", [{}])[0].get("hits", [])
    total = data.get("results", [{}])[0].get("nbHits", 0)

    results: List[Dict[str, Any]] = []
    for hit in hits:
        # objectID format: "doctor-12345"
        obj_id = hit.get("objectID", "")
        doctor_id = obj_id.replace("doctor-", "") if obj_id.startswith("doctor-") else ""
        if not doctor_id:
            continue

        # Only include doctors with online booking calendar
        if not hit.get("calendar"):
            continue

        results.append({
            "doctor_id": doctor_id,
            "name": hit.get("fullname_formatted", ""),
            "rating": hit.get("stars"),
            "rating_count": hit.get("opinionCount"),
            "specializations": hit.get("specializations", []),
        })

    logger.info(
        "[health:jameda] Algolia search '%s': %d total hits, %d with calendar (returning %d)",
        query, total, len(results), len(results),
    )
    return results


async def _jameda_fetch_addresses(
    client: httpx.AsyncClient,
    token: str,
    doctor_id: str,
) -> List[Dict[str, Any]]:
    """GET /api/v3/doctors/{id}/addresses — returns addresses with slot info.

    Filters to addresses where has_slots=True and calendar_active=True.
    """
    url = f"{JAMEDA_BASE_URL}/api/v3/doctors/{doctor_id}/addresses"
    resp = await client.get(url, headers=_jameda_api_headers(token))
    resp.raise_for_status()
    data = resp.json()

    addresses = [
        addr for addr in data.get("_items", [])
        if addr.get("has_slots") and addr.get("calendar_active", True)
    ]
    return addresses


async def _jameda_fetch_slots(
    client: httpx.AsyncClient,
    token: str,
    doctor_id: str,
    address_id: str,
    days_ahead: int,
) -> List[Dict[str, Any]]:
    """GET /api/v3/doctors/{id}/addresses/{id}/slots — available appointment slots.

    Returns list of slot dicts with 'start' (ISO datetime) and 'booking_url'.
    """
    start_dt = date.today()
    end_dt = start_dt + timedelta(days=days_ahead)
    start_iso = f"{start_dt.isoformat()}T00:00:00+01:00"
    end_iso = f"{end_dt.isoformat()}T23:59:59+01:00"

    url = (
        f"{JAMEDA_BASE_URL}/api/v3/doctors/{doctor_id}/addresses/{address_id}/slots"
        f"?start={start_iso}&end={end_iso}"
    )
    try:
        resp = await client.get(url, headers=_jameda_api_headers(token))
        resp.raise_for_status()
        data = resp.json()
        return data.get("_items", [])
    except Exception as exc:
        logger.warning(
            "[health:jameda] Slot fetch error for doctor %s address %s: %s",
            doctor_id, address_id, exc,
        )
        return []


async def _jameda_fetch_services(
    client: httpx.AsyncClient,
    token: str,
    doctor_id: str,
    address_id: str,
) -> List[Dict[str, Any]]:
    """GET /api/v3/doctors/{id}/addresses/{id}/services — service list with prices.

    Returns list of service dicts with 'id', 'name', 'price', 'is_default'.
    """
    url = f"{JAMEDA_BASE_URL}/api/v3/doctors/{doctor_id}/addresses/{address_id}/services"
    try:
        resp = await client.get(url, headers=_jameda_api_headers(token))
        resp.raise_for_status()
        data = resp.json()
        return data.get("_items", [])
    except Exception as exc:
        logger.warning(
            "[health:jameda] Service fetch error for doctor %s address %s: %s",
            doctor_id, address_id, exc,
        )
        return []


async def _process_single_jameda_request(
    client: httpx.AsyncClient,
    request: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    """Process a single search request against Jameda (DocPlanner API).

    Flow:
    1. Get anonymous token (cached 23h)
    2. Scrape search page for doctor IDs
    3. For each doctor: fetch addresses → filter has_slots → fetch slots + services
    4. Apply visit_motive_category filtering on service names
    5. Build unified result items, sort by slot_datetime, cap at DEFAULT_MAX_SLOTS

    Returns: (request_id, result_items, error_str_or_None)
    """
    request_id = str(request.get("id", "1"))
    speciality_raw = str(request.get("speciality", "")).lower().strip().replace(" ", "-")
    city_raw = str(request.get("city", "")).lower().strip()
    days_ahead = int(request.get("days_ahead") or 7)
    max_doctors = int(request.get("max_doctors", DEFAULT_MAX_DOCTORS))
    visit_motive_category = request.get("visit_motive_category")

    if not speciality_raw:
        return request_id, [], "Missing required field: 'speciality'"
    if not city_raw:
        return request_id, [], "Missing required field: 'city'"
    if visit_motive_category and visit_motive_category not in VISIT_MOTIVE_CATEGORIES:
        return request_id, [], (
            f"Unknown visit_motive_category '{visit_motive_category}'. "
            f"Supported: {', '.join(sorted(VISIT_MOTIVE_CATEGORIES.keys()))}"
        )

    # Resolve slugs
    speciality_slug = JAMEDA_SPECIALITY_SLUGS.get(speciality_raw, speciality_raw)
    # City: check Jameda-specific map first, then fall back to raw lowercase
    city_slug = JAMEDA_CITY_SLUGS.get(city_raw, city_raw.replace(" ", "-"))

    logger.info(
        "[health:jameda] Processing request %s: %s in %s (days=%d, max=%d, category=%s)",
        request_id, speciality_slug, city_slug, days_ahead, max_doctors, visit_motive_category,
    )

    try:
        # Step 1: Get token
        token = await _get_jameda_token(client)

        # Step 2: Search doctors via Algolia (no HTML scraping needed)
        search_max = max(max_doctors, FILTERED_SEARCH_MAX_DOCTORS) if visit_motive_category else max_doctors
        doctor_infos = await _jameda_search_doctors_algolia(client, speciality_slug, city_slug, search_max)
        if not doctor_infos:
            return request_id, [], None

        # Step 3: For each doctor, fetch addresses (filter has_slots)
        address_tasks = [
            _jameda_fetch_addresses(client, token, doc["doctor_id"])
            for doc in doctor_infos
        ]
        all_addresses = await asyncio.gather(*address_tasks, return_exceptions=True)

        # Build list of (doctor_info, address) pairs to fetch slots for.
        #
        # CITY FILTER: The Algolia index does a full-text search on
        # "{speciality_slug} {city_slug}" which returns the best text matches
        # globally — it does NOT restrict to the requested city. A doctor in
        # Leipzig whose name/specialization happens to match the query can
        # outrank Berlin doctors. We therefore filter addresses by city_name
        # here so the returned appointments are actually in the requested city.
        city_slug_lc = city_slug.lower().strip()
        doctor_address_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        dropped_wrong_city = 0
        for doc_info, addrs in zip(doctor_infos, all_addresses):
            if isinstance(addrs, Exception):
                logger.warning("[health:jameda] Address fetch error for doctor %s: %s", doc_info["doctor_id"], addrs)
                continue
            matched_addr: Optional[Dict[str, Any]] = None
            for addr in addrs:
                addr_city = str(addr.get("city_name", "")).lower().strip()
                if addr_city and addr_city == city_slug_lc:
                    matched_addr = addr
                    break
            if matched_addr is not None:
                doctor_address_pairs.append((doc_info, matched_addr))
            else:
                dropped_wrong_city += 1

        if dropped_wrong_city:
            logger.info(
                "[health:jameda] Dropped %d doctor(s) whose addresses were not in city '%s'",
                dropped_wrong_city, city_slug,
            )

        if not doctor_address_pairs:
            return request_id, [], None

        # Step 4: Fetch slots and services in parallel for all doctor-address pairs
        slot_tasks = []
        service_tasks = []
        for doc_info, addr in doctor_address_pairs:
            did = doc_info["doctor_id"]
            aid = str(addr.get("id", ""))
            slot_tasks.append(_jameda_fetch_slots(client, token, did, aid, days_ahead))
            service_tasks.append(_jameda_fetch_services(client, token, did, aid))

        all_slots, all_services = await asyncio.gather(
            asyncio.gather(*slot_tasks, return_exceptions=True),
            asyncio.gather(*service_tasks, return_exceptions=True),
        )

        # Step 5: Build result items
        all_slot_items: List[Dict[str, Any]] = []
        doctors_checked = 0
        doctors_with_slots = 0

        for (doc_info, addr), slots, services in zip(doctor_address_pairs, all_slots, all_services):
            if isinstance(slots, Exception):
                logger.warning("[health:jameda] Slot error for doctor %s: %s", doc_info["doctor_id"], slots)
                slots = []
            if isinstance(services, Exception):
                services = []

            doctors_checked += 1
            if not slots:
                continue

            # Pick default/first service for metadata
            default_service = None
            for svc in services:
                if svc.get("is_default"):
                    default_service = svc
                    break
            if not default_service and services:
                default_service = services[0]

            service_name = default_service.get("name", "") if default_service else ""
            service_price = default_service.get("price") if default_service else None

            # Apply visit_motive_category filtering on service names
            if visit_motive_category:
                # Check if ANY service matches the category
                has_matching_service = any(
                    _matches_motive_category(svc.get("name", ""), visit_motive_category)
                    for svc in services
                ) if services else False
                # Also check the default service name
                if not has_matching_service and service_name:
                    has_matching_service = _matches_motive_category(service_name, visit_motive_category)
                if not has_matching_service:
                    continue
                # Use the matching service for display
                for svc in services:
                    if _matches_motive_category(svc.get("name", ""), visit_motive_category):
                        service_name = svc.get("name", "")
                        service_price = svc.get("price")
                        break

            doctors_with_slots += 1
            did = doc_info["doctor_id"]
            aid = str(addr.get("id", ""))

            # Build address string
            street = addr.get("street", "")
            post_code = addr.get("post_code", "")
            city_name = addr.get("city_name", "")
            city_part = f"{post_code} {city_name}".strip()
            address_str = ", ".join(p for p in [street, city_part] if p)

            # GPS from address
            coord = addr.get("coordinate") or {}
            gps = None
            if coord.get("lat") and coord.get("lon"):
                gps = {"latitude": coord["lat"], "longitude": coord["lon"]}

            # Doctor metadata — prefer Algolia name (doctor name) over address name (practice name)
            doctor_name = doc_info.get("name") or addr.get("name", "")
            algolia_specs = doc_info.get("specializations", [])
            spec_display = algolia_specs[0] if algolia_specs else speciality_slug
            doctor_metadata = {
                "name": doctor_name,
                "title": "",
                "gender": None,
                "doctor_type": "PERSON",
                "address": address_str,
                "gps_coordinates": gps,
                "speciality": spec_display,
                "languages": [],
                "telehealth": False,
                "visit_motive": service_name,
                # Jameda's public API does not expose per-doctor insurance
                # sector info (neither addresses nor services endpoint return
                # it — verified by reverse-engineering the v3 API). We mark
                # the sector as "unknown" so the LLM (and UI) can warn the
                # user that Jameda results may include both public and
                # private practices. When the user requires a specific
                # insurance sector, the orchestrator skips Jameda entirely
                # and relies only on Doctolib, which has a real filter.
                "insurance": "unknown",
                "allows_new_patients": True,
                "practice_url": f"{JAMEDA_BASE_URL}/{speciality_slug}/{city_slug}",
                "provider_platform": "Jameda",
                "country": "DE",
                # Jameda-specific fields
                "booking_url": None,  # set per-slot below
                "rating": doc_info.get("rating"),
                "rating_count": doc_info.get("rating_count"),
                "price": service_price,
                "service_name": service_name,
                # Internal IDs (excluded from LLM)
                "visit_motive_id": None,
                "agenda_id": None,
                "practice_id": int(aid) if aid.isdigit() else None,
            }

            for slot in slots:
                slot_dt = slot.get("start", "")
                booking_url = slot.get("booking_url", "")
                slot_item: Dict[str, Any] = {
                    "type": "appointment",
                    "hash": _result_hash(int(aid) if aid.isdigit() else 0, 0, slot_dt),
                    "slot_datetime": slot_dt,
                    **doctor_metadata,
                    "booking_url": booking_url,
                }
                all_slot_items.append(slot_item)

        # Sort by datetime ascending, cap at DEFAULT_MAX_SLOTS
        all_slot_items.sort(key=lambda r: r["slot_datetime"])
        results: List[Dict[str, Any]] = all_slot_items[:DEFAULT_MAX_SLOTS]

        logger.info(
            "[health:jameda] Request %s: checked %d doctors, %d with slots, returning %d slot results",
            request_id, doctors_checked, doctors_with_slots, len(results),
        )
        return request_id, results, None

    except Exception as exc:
        logger.error(
            "[health:jameda] Error processing request %s: %s",
            request_id, exc, exc_info=True,
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
        # Lazily instantiate the SecretsManager when the dispatcher did not
        # inject one. Needed so the Google Places enrichment pass (and
        # Webshare proxy credentials) can actually read secrets from Vault.
        # Without this, base_app.dispatch_skill passes secrets_manager=None
        # and enrichment silently no-ops.
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="SearchAppointmentsSkill",
            error_response_factory=lambda msg: SearchAppointmentsResponse(error=msg),
            logger=logger,
        )
        if error_response:
            return error_response

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
                    # The "-rotate" suffix is required by Webshare's rotating proxy
                    # username/password auth mode; without it the proxy returns 407.
                    proxy_url = f"http://{ws_username}-rotate:{ws_password}@p.webshare.io:80/"
                    logger.debug(
                        "[health:search_appointments] Using Webshare rotating proxy"
                    )
            except Exception as exc:
                logger.warning(
                    "[health:search_appointments] Could not load proxy credentials: %s. "
                    "Proceeding without proxy.",
                    exc,
                )

        # Note on Jameda + insurance: Jameda's public API does not expose
        # per-doctor insurance info (verified by reverse-engineering the v3
        # API — neither /addresses nor /services returns an insurance
        # sector). We still include Jameda results when the user specifies
        # insurance_sector, but mark them with insurance="unknown" so the
        # UI can surface a badge telling the user to verify on Jameda
        # before booking. Doctolib results continue to honour the
        # insuranceSector filter via _fetch_availability.

        # Process all requests in parallel
        # Each request gets its own httpx.AsyncClient so different requests
        # can get different proxy IPs from Webshare's rotating pool.
        all_results = await self._process_requests_in_parallel(
            requests=validated,
            process_single_request_func=self._make_request_processor(
                proxy_url,
                secrets_manager,
                kwargs.get("cache_service"),
            ),
            logger=logger,
        )

        # Group results by request ID
        grouped, errors = self._group_results_by_request_id(
            all_results, validated, logger
        )

        # Derive provider label from the requests
        platforms_used = set(
            r.get("provider_platform", "both") for r in validated
        )
        if platforms_used == {"jameda"}:
            provider_label = "Jameda"
        elif platforms_used == {"doctolib_de"}:
            provider_label = "Doctolib"
        else:
            provider_label = "Doctolib, Jameda"

        return self._build_response_with_errors(
            response_class=SearchAppointmentsResponse,
            grouped_results=grouped,
            errors=errors,
            provider=provider_label,
            suggestions=self.FOLLOW_UP_SUGGESTIONS,
            logger=logger,
        )

    def _make_request_processor(
        self,
        proxy_url: Optional[str],
        secrets_manager: Optional["SecretsManager"],
        cache_service: Optional[Any],
    ):
        """
        Return an async function that processes a single request with its own
        httpx.AsyncClient. Wrapping in a closure lets us inject proxy_url without
        changing the signature expected by _process_requests_in_parallel.
        """
        async def _run_doctolib(req: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
            """Run Doctolib search with proxy + retry logic."""
            client_kwargs: Dict[str, Any] = {
                "timeout": httpx.Timeout(30.0, connect=10.0),
                "follow_redirects": True,
                "headers": _make_browser_headers(),
            }
            if proxy_url:
                client_kwargs["proxy"] = proxy_url

            request_id = str(req.get("id", "1"))
            last_error: Optional[str] = None

            for attempt in range(DOCTOLIB_MAX_RETRIES):
                async with create_http_client("doctolib", **client_kwargs) as client:
                    request_id, results, error = await _process_single_doctolib_request(client, req)

                if not error:
                    return request_id, results, None
                last_error = error

                is_retryable = any(code in error for code in ("403", "429"))
                if not is_retryable:
                    return request_id, results, error

                logger.info(
                    "[health:search_appointments] Retryable error on attempt %d/%d for request %s: %s",
                    attempt + 1, DOCTOLIB_MAX_RETRIES, request_id, error[:80],
                )
                await asyncio.sleep(DOCTOLIB_RETRY_DELAY_SECONDS)

            logger.warning(
                "[health:search_appointments] All %d retries failed for request %s",
                DOCTOLIB_MAX_RETRIES, request_id,
            )
            return request_id, [], last_error

        async def _run_jameda(req: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
            """Run Jameda search with anonymous token auth."""
            jameda_kwargs: Dict[str, Any] = {
                "timeout": httpx.Timeout(30.0, connect=10.0),
                "follow_redirects": True,
            }
            async with create_http_client("jameda", **jameda_kwargs) as client:
                return await _process_single_jameda_request(client, req)

        async def _process(req: Dict[str, Any], **kwargs) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
            # NOTE: signature uses 'req' to match the kwarg passed by
            # BaseSkill._process_requests_in_parallel (which calls req=req).
            provider_platform = req.get("provider_platform", "both")
            request_id = str(req.get("id", "1"))

            if provider_platform == "both":
                # Search both providers in parallel, merge results by slot_datetime
                doctolib_result, jameda_result = await asyncio.gather(
                    _run_doctolib(req),
                    _run_jameda(req),
                    return_exceptions=True,
                )

                merged: List[Dict[str, Any]] = []
                errors_list: List[str] = []

                for label, result in [("Doctolib", doctolib_result), ("Jameda", jameda_result)]:
                    if isinstance(result, Exception):
                        logger.warning("[health:both] %s failed: %s", label, result)
                        errors_list.append(f"{label}: {result}")
                        continue
                    _, items, err = result
                    if err:
                        logger.info("[health:both] %s returned error: %s", label, err[:80])
                        errors_list.append(f"{label}: {err}")
                    if items:
                        merged.extend(items)

                if not merged:
                    error_summary = "; ".join(errors_list) if errors_list else None
                    return request_id, [], error_summary

                # Sort combined results by slot_datetime (soonest first)
                merged.sort(key=lambda r: r.get("slot_datetime", ""))
                results = merged
                error = None

            elif provider_platform == "jameda":
                request_id, results, error = await _run_jameda(req)

            else:
                request_id, results, error = await _run_doctolib(req)

            if not error and results:
                # 1. Drop any slot whose datetime is already in the past (stale
                #    cached slots from provider APIs). Keeps the user-facing
                #    result set fresh.
                results = _filter_past_slots(results)

                # 2. Collapse per-slot rows into one card per doctor, with up to
                #    DEFAULT_MAX_ADDITIONAL_SLOTS alternate times attached. This
                #    replaces the old "10 slots from the same doctor" output
                #    with "6 different doctors, each with their soonest slot
                #    plus their next N alternate slots".
                results = _group_slots_by_doctor(results)

                # 3. Cap at DEFAULT_MAX_DOCTORS_RETURNED per request.
                results = results[:DEFAULT_MAX_DOCTORS_RETURNED]

            if error or not results:
                return request_id, results, error

            try:
                sanitized_results = await sanitize_long_text_fields_in_payload(
                    payload=results,
                    task_id=f"health_appointments_{request_id}",
                    secrets_manager=secrets_manager,
                    cache_service=cache_service,
                )
                return request_id, sanitized_results, None
            except Exception as sanitize_error:
                logger.error(
                    "Appointment content sanitization failed for request %s: %s",
                    request_id,
                    sanitize_error,
                    exc_info=True,
                )
                return request_id, [], "Content sanitization failed"

        return _process
