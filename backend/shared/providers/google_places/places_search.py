# backend/shared/providers/google_places/places_search.py
#
# Google Places API (New) wrapper for Text Search with Enterprise field mask.
# Used by the Health app to enrich doctor appointment results with ratings,
# reviews, opening hours, phone, website, and editorial summaries.
#
# API docs: https://developers.google.com/maps/documentation/places/web-service/text-search
# Pricing:  https://developers.google.com/maps/billing-and-pricing/pricing
#
# The `rating` + `userRatingCount` fields trigger the Text Search Enterprise
# SKU ($35 per 1000 calls, 1000/month free). We request every useful Enterprise
# field in the same call because they are all included at the same SKU tier —
# no extra cost for additional fields within the Enterprise pricing bracket.

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

GOOGLE_PLACES_SECRET_PATH = "kv/data/providers/google_places"
GOOGLE_PLACES_API_KEY_NAME = "api_key"

PLACES_API_BASE_URL = "https://places.googleapis.com/v1"

# Enterprise-tier field mask. All these fields cost the same (single Enterprise
# call) — we request them all and drop what we don't need later.
ENTERPRISE_FIELD_MASK = ",".join([
    # Essentials (free)
    "places.id",
    "places.formattedAddress",
    "places.location",
    "places.types",
    # Pro (free in same call)
    "places.displayName",
    "places.primaryType",
    "places.primaryTypeDisplayName",
    "places.businessStatus",
    "places.googleMapsUri",
    "places.accessibilityOptions",
    # Enterprise (what we pay for)
    "places.rating",
    "places.userRatingCount",
    "places.reviews",
    "places.regularOpeningHours",
    "places.currentOpeningHours",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.editorialSummary",
])


@dataclass
class PlaceReview:
    """A single patient/customer review from Google Places."""
    author: Optional[str] = None
    rating: Optional[float] = None
    text: Optional[str] = None
    language: Optional[str] = None
    relative_time: Optional[str] = None  # e.g. "2 weeks ago"


@dataclass
class OpeningHoursDay:
    """One weekday's opening hours."""
    day: int  # 0=Sunday, 6=Saturday per Google's enum
    open_time: Optional[str] = None  # "HH:MM"
    close_time: Optional[str] = None  # "HH:MM"


@dataclass
class PlaceDetails:
    """Structured Google Places result for a single doctor/practice."""
    place_id: Optional[str] = None
    display_name: Optional[str] = None
    formatted_address: Optional[str] = None
    primary_type_display: Optional[str] = None
    business_status: Optional[str] = None  # OPERATIONAL, CLOSED_TEMPORARILY, CLOSED_PERMANENTLY
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    reviews: List[PlaceReview] = field(default_factory=list)
    opening_hours_weekday_text: List[str] = field(default_factory=list)
    opening_hours_by_day: List[OpeningHoursDay] = field(default_factory=list)
    phone_national: Optional[str] = None
    phone_international: Optional[str] = None
    website_uri: Optional[str] = None
    editorial_summary: Optional[str] = None
    google_maps_uri: Optional[str] = None
    wheelchair_accessible_entrance: Optional[bool] = None
    wheelchair_accessible_parking: Optional[bool] = None
    wheelchair_accessible_seating: Optional[bool] = None
    wheelchair_accessible_restroom: Optional[bool] = None


async def _get_google_places_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    """Retrieve the Google Places API key from Vault or env fallback."""
    try:
        api_key = await secrets_manager.get_secret(
            secret_path=GOOGLE_PLACES_SECRET_PATH,
            secret_key=GOOGLE_PLACES_API_KEY_NAME,
        )
        if api_key:
            cleaned = api_key.strip().strip('"').strip("'").strip()
            if cleaned:
                logger.debug(
                    "Retrieved Google Places API key from Vault (length=%d)",
                    len(cleaned),
                )
                return cleaned
    except Exception as exc:
        logger.warning(
            "Error retrieving Google Places API key from Vault: %s", exc,
        )

    env_key = os.getenv("SECRET__GOOGLE_PLACES__API_KEY", "").strip().strip('"').strip("'").strip()
    if env_key:
        masked = f"{env_key[:4]}****{env_key[-4:]}" if len(env_key) > 8 else "****"
        logger.info(
            "Retrieved Google Places API key from env var SECRET__GOOGLE_PLACES__API_KEY: %s",
            masked,
        )
        return env_key

    logger.error(
        "Google Places API key not found in Vault or environment. "
        "Set SECRET__GOOGLE_PLACES__API_KEY or configure kv/data/providers/google_places.",
    )
    return None


def _parse_reviews(raw_reviews: List[Dict[str, Any]]) -> List[PlaceReview]:
    """Convert the raw review array from the Places API into PlaceReview structs."""
    parsed: List[PlaceReview] = []
    for rev in raw_reviews[:5]:  # Cap at 5 reviews (the API returns max 5 anyway)
        try:
            author_attr = rev.get("authorAttribution", {}) or {}
            text_obj = rev.get("text", {}) or {}
            parsed.append(PlaceReview(
                author=author_attr.get("displayName"),
                rating=rev.get("rating"),
                text=text_obj.get("text"),
                language=text_obj.get("languageCode"),
                relative_time=rev.get("relativePublishTimeDescription"),
            ))
        except Exception as exc:
            logger.debug("Failed to parse a Places review: %s", exc)
    return parsed


def _parse_opening_hours(raw_hours: Optional[Dict[str, Any]]) -> tuple[List[str], List[OpeningHoursDay]]:
    """Parse opening hours, returning both the weekday_text and structured per-day times."""
    if not raw_hours:
        return [], []

    weekday_text = list(raw_hours.get("weekdayDescriptions", []) or [])

    by_day: List[OpeningHoursDay] = []
    for period in raw_hours.get("periods", []) or []:
        try:
            open_info = period.get("open") or {}
            close_info = period.get("close") or {}
            day = open_info.get("day", -1)
            open_time = None
            close_time = None
            if "hour" in open_info:
                open_time = f"{open_info.get('hour', 0):02d}:{open_info.get('minute', 0):02d}"
            if "hour" in close_info:
                close_time = f"{close_info.get('hour', 0):02d}:{close_info.get('minute', 0):02d}"
            by_day.append(OpeningHoursDay(day=day, open_time=open_time, close_time=close_time))
        except Exception as exc:
            logger.debug("Failed to parse an opening hours period: %s", exc)

    return weekday_text, by_day


def _parse_place(raw: Dict[str, Any]) -> PlaceDetails:
    """Convert a raw Places API result dict into our structured PlaceDetails."""
    display_name = None
    if isinstance(raw.get("displayName"), dict):
        display_name = raw["displayName"].get("text")

    primary_type_display = None
    if isinstance(raw.get("primaryTypeDisplayName"), dict):
        primary_type_display = raw["primaryTypeDisplayName"].get("text")

    editorial_summary = None
    if isinstance(raw.get("editorialSummary"), dict):
        editorial_summary = raw["editorialSummary"].get("text")

    # Prefer currentOpeningHours over regularOpeningHours — it includes holiday overrides
    raw_hours = raw.get("currentOpeningHours") or raw.get("regularOpeningHours")
    weekday_text, by_day = _parse_opening_hours(raw_hours)

    accessibility = raw.get("accessibilityOptions") or {}

    return PlaceDetails(
        place_id=raw.get("id"),
        display_name=display_name,
        formatted_address=raw.get("formattedAddress"),
        primary_type_display=primary_type_display,
        business_status=raw.get("businessStatus"),
        rating=raw.get("rating"),
        rating_count=raw.get("userRatingCount"),
        reviews=_parse_reviews(raw.get("reviews", []) or []),
        opening_hours_weekday_text=weekday_text,
        opening_hours_by_day=by_day,
        phone_national=raw.get("nationalPhoneNumber"),
        phone_international=raw.get("internationalPhoneNumber"),
        website_uri=raw.get("websiteUri"),
        editorial_summary=editorial_summary,
        google_maps_uri=raw.get("googleMapsUri"),
        wheelchair_accessible_entrance=accessibility.get("wheelchairAccessibleEntrance"),
        wheelchair_accessible_parking=accessibility.get("wheelchairAccessibleParking"),
        wheelchair_accessible_seating=accessibility.get("wheelchairAccessibleSeating"),
        wheelchair_accessible_restroom=accessibility.get("wheelchairAccessibleRestroom"),
    )


async def search_place_details(
    client: httpx.AsyncClient,
    secrets_manager: SecretsManager,
    query: str,
    region_code: str = "DE",
    language_code: str = "de",
) -> Optional[PlaceDetails]:
    """
    Search for a place by free-text query and return the first match as PlaceDetails.

    The query should combine doctor name + address (e.g. "Dr. Smith Kantstraße 10 Berlin").
    Returns None when no match is found or the API call fails.

    Cost: 1 Text Search Enterprise call per invocation ($35/1000, 1000/mo free).
    """
    api_key = await _get_google_places_api_key(secrets_manager)
    if not api_key:
        logger.warning("Google Places: skipping lookup, API key not configured")
        return None

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ENTERPRISE_FIELD_MASK,
    }

    payload: Dict[str, Any] = {
        "textQuery": query,
        "languageCode": language_code,
        "regionCode": region_code,
        "maxResultCount": 1,
    }

    try:
        resp = await client.post(
            f"{PLACES_API_BASE_URL}/places:searchText",
            headers=headers,
            json=payload,
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.warning(
                "Google Places: non-200 response for query (status=%d): %s",
                resp.status_code, resp.text[:200],
            )
            return None

        data = resp.json()
        places = data.get("places", [])
        if not places:
            logger.debug("Google Places: no results for query")
            return None

        return _parse_place(places[0])

    except httpx.TimeoutException:
        logger.warning("Google Places: timeout fetching place details")
        return None
    except Exception as exc:
        logger.warning(
            "Google Places: unexpected error during place lookup: %s", exc,
        )
        return None


async def check_google_places_health(
    secrets_manager: SecretsManager,
) -> tuple[bool, Optional[str]]:
    """Lightweight health check: verify the API key is configured (no billing)."""
    api_key = await _get_google_places_api_key(secrets_manager)
    if not api_key:
        return False, "API key not configured"
    return True, None
