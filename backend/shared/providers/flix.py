# backend/shared/providers/flix.py
#
# Pure HTTP client for FlixBus / FlixTrain search endpoints.
# The public developer portal exists but is SSO-gated, so these functions use
# the same web/mobile JSON endpoints currently used by Flix search surfaces.
# Keep app-specific result mapping in backend/apps/travel/providers/flix_provider.py.

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

AUTOCOMPLETE_URL = "https://global.api.flixbus.com/search/autocomplete/cities"
TRIP_SEARCH_URL = "https://global.api.flixbus.com/mobile/v1/trip/search.json"

DEFAULT_LOCALE = "en"
DEFAULT_COUNTRY = "DE"
DEFAULT_USER_COUNTRY = "de"
DEFAULT_TIMEOUT = 15.0
MAX_429_RETRIES = 3
DEFAULT_429_RETRY_DELAY = 1.0

# Reverse-engineered mobile API headers. The auth token is the public mobile
# client token observed in Flix's own traffic and historical public clients.
MOBILE_API_AUTHENTICATION = "k8LKgcuFoHnN5x/NdDYD6QSvjB4="
MOBILE_USER_AGENT = "FlixBus/7.55.0 (iPhone; iOS 16.5; Scale/2.00)"


class FlixApiError(RuntimeError):
    """Raised when Flix returns a transport-level or payload-level error."""


def _country_from_locale(locale: str) -> str:
    parts = locale.replace("-", "_").split("_")
    if len(parts) > 1 and len(parts[1]) == 2:
        return parts[1].upper()
    return DEFAULT_COUNTRY


def _format_locale_for_header(locale: str) -> str:
    if "-" in locale or "_" in locale:
        return locale.replace("_", "-")
    return f"{locale}-{DEFAULT_COUNTRY}"


async def _get_with_429_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> httpx.Response:
    for attempt in range(1, MAX_429_RETRIES + 1):
        response = await client.get(url, params=params, headers=headers)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        if attempt >= MAX_429_RETRIES:
            response.raise_for_status()
        retry_after = response.headers.get("Retry-After")
        try:
            wait_seconds = max(float(retry_after), 0.1) if retry_after else DEFAULT_429_RETRY_DELAY
        except (TypeError, ValueError):
            wait_seconds = DEFAULT_429_RETRY_DELAY
        logger.info("Flix API rate limited; retrying in %.1fs", wait_seconds)
        await asyncio.sleep(wait_seconds)
    raise FlixApiError("Flix API rate limit retries exhausted")


async def autocomplete_locations(
    query: str,
    *,
    locale: str = DEFAULT_LOCALE,
    country: Optional[str] = None,
    train_only: bool = False,
    departure_city_id: Optional[str] = None,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """Search Flix cities/stations by name and return raw autocomplete items."""
    query = query.strip()
    if not query:
        return []

    resolved_country = country or _country_from_locale(locale)
    params: Dict[str, Any] = {
        "q": query,
        "lang": locale.split("_")[0].split("-")[0],
        "country": resolved_country.upper(),
        "flixbus_cities_only": "true",
        "is_train_only": "true" if train_only else "false",
        "stations": "true",
        "popular_stations": "true",
        "popular_stations_count": "null",
        "disabled_countries": "",
    }
    if departure_city_id:
        params["departure_city"] = departure_city_id

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await _get_with_429_retry(client, AUTOCOMPLETE_URL, params=params)
        payload = response.json()

    if isinstance(payload, dict) and payload.get("code"):
        raise FlixApiError(f"Flix autocomplete failed: {payload}")
    if not isinstance(payload, list):
        raise FlixApiError("Flix autocomplete returned an unexpected payload")
    return payload[:max_results]


async def search_trips(
    from_id: int,
    to_id: int,
    *,
    departure_date: str,
    search_by: str = "cities",
    currency: str = "EUR",
    adults: int = 1,
    children: int = 0,
    bikes: int = 0,
    user_country: str = DEFAULT_USER_COUNTRY,
    locale: str = DEFAULT_LOCALE,
) -> Dict[str, Any]:
    """Search Flix trips by numeric legacy city/station IDs."""
    params = {
        "from": str(from_id),
        "to": str(to_id),
        "departure_date": departure_date,
        "return_date": "",
        "back": "0",
        "search_by": search_by,
        "currency": currency.upper(),
        "adult": str(max(adults, 1)),
        "children": str(max(children, 0)),
        "bikes": str(max(bikes, 0)),
    }
    headers = {
        "X-API-Authentication": MOBILE_API_AUTHENTICATION,
        "User-Agent": MOBILE_USER_AGENT,
        "X-User-Country": user_country.lower(),
        "Accept-Language": _format_locale_for_header(locale),
    }

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await _get_with_429_retry(client, TRIP_SEARCH_URL, params=params, headers=headers)
        payload = response.json()

    if not isinstance(payload, dict):
        raise FlixApiError("Flix trip search returned an unexpected payload")
    errors = payload.get("errors")
    if errors:
        raise FlixApiError(f"Flix trip search failed: {errors}")
    return payload
