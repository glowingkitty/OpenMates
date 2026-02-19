# backend/core/api/app/routes/geocode.py
#
# Server-side proxy for Nominatim reverse and forward geocoding requests.
#
# Architecture / Why this exists:
# ---------------------------------
# Nominatim (nominatim.openstreetmap.org) does not reliably include the
# Access-Control-Allow-Origin response header on every request.  When the
# browser calls it directly it occasionally gets a CORS block — especially
# on the very first request after page load where TLS 1.3 0-RTT ("Too Early"
# / HTTP 425) causes the CDN edge to reject the request before any headers
# are set.
#
# By routing through this proxy:
# - CORS is eliminated completely (server-to-server has no CORS restrictions).
# - Retries with exponential back-off are centralised here instead of being
#   duplicated across frontend components.
# - Future rate-limit compliance and in-memory caching can be added in one
#   place.
#
# Endpoints:
#   GET /v1/geocode/reverse  — lat/lon → address (reverse geocode)
#   GET /v1/geocode/search   — text query → coordinates list (forward geocode)
#
# Authentication: session cookie OR API key (via get_current_user_or_api_key).
# Rate limit: 60 geocode requests per minute per user.

import logging
import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_current_user_or_api_key,
)
from backend.core.api.app.models.user import User
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/geocode", tags=["Geocode"])

# Nominatim base URL — centralised so it's easy to swap for a self-hosted
# instance via an environment variable in the future.
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"

# Timeout (seconds) for each individual Nominatim request
NOMINATIM_TIMEOUT = 10.0

# Retry settings: up to 3 attempts with exponential back-off
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.5  # seconds; doubled on each retry

# Standard headers sent to Nominatim.
# User-Agent is required by Nominatim's usage policy so they can contact
# operators if a client causes problems.  We do NOT send Accept-Language here
# — the frontend passes it as a query param instead (avoids CORS preflight).
NOMINATIM_HEADERS = {
    "User-Agent": "OpenMates/1.0 (https://openmates.org)",
    "Accept": "application/json",
}


async def _nominatim_get(url: str, params: dict) -> dict:
    """
    Make a GET request to Nominatim with automatic retries.

    Retries on:
    - HTTP 425 (Too Early — TLS 1.3 0-RTT rejection)
    - HTTP 429 (Too Many Requests — back off and retry)
    - HTTP 5xx (server-side errors)
    - Network / timeout errors

    Raises HTTPException on permanent failure.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=NOMINATIM_TIMEOUT) as client:
                response = await client.get(url, params=params, headers=NOMINATIM_HEADERS)

            if response.status_code == 200:
                return response.json()

            # Retriable status codes
            if response.status_code in (425, 429, 500, 502, 503, 504):
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Nominatim returned %d on attempt %d/%d, retrying in %.1fs",
                    response.status_code,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                    continue

                # Exhausted retries
                raise HTTPException(
                    status_code=502,
                    detail=f"Geocoding service returned {response.status_code} after {MAX_RETRIES} attempts",
                )

            # Non-retriable HTTP error (e.g. 400 Bad Request)
            logger.error("Nominatim non-retriable error: %d", response.status_code)
            raise HTTPException(
                status_code=502,
                detail=f"Geocoding service error: {response.status_code}",
            )

        except httpx.TimeoutException as exc:
            last_error = exc
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Nominatim timeout on attempt %d/%d, retrying in %.1fs",
                attempt + 1,
                MAX_RETRIES,
                delay,
            )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(delay)

        except httpx.RequestError as exc:
            last_error = exc
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Nominatim network error on attempt %d/%d (%s), retrying in %.1fs",
                attempt + 1,
                MAX_RETRIES,
                exc,
                delay,
            )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(delay)

    logger.error("All %d Nominatim attempts failed: %s", MAX_RETRIES, last_error)
    raise HTTPException(
        status_code=502,
        detail="Geocoding service unreachable",
    )


@router.get("/reverse")
@limiter.limit("60/minute")
async def reverse_geocode(
    request: Request,
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    zoom: int = Query(18, description="Zoom level (detail level)"),
    addressdetails: int = Query(1, description="Include address breakdown"),
    accept_language: str = Query("en", alias="accept-language", description="Language for results"),
    current_user: User = Depends(get_current_user_or_api_key),
) -> JSONResponse:
    """
    Reverse geocode lat/lon to a human-readable address via Nominatim.

    Proxies the request server-side to avoid CORS restrictions and TLS 0-RTT
    failures that affect direct browser→Nominatim calls.  Retries automatically
    on transient errors (425 Too Early, 429, 5xx, timeouts).
    """
    params = {
        "format": "json",
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
        "addressdetails": addressdetails,
        "accept-language": accept_language,
    }
    data = await _nominatim_get(f"{NOMINATIM_BASE}/reverse", params)
    return JSONResponse(content=data)


@router.get("/search")
@limiter.limit("60/minute")
async def forward_geocode(
    request: Request,
    q: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Maximum number of results"),
    addressdetails: int = Query(1, description="Include address breakdown"),
    extratags: int = Query(1, description="Include extra tags"),
    namedetails: int = Query(1, description="Include name details"),
    accept_language: str = Query("en", alias="accept-language", description="Language for results"),
    current_user: User = Depends(get_current_user_or_api_key),
) -> JSONResponse:
    """
    Forward geocode a text query to coordinates via Nominatim.

    Proxies the request server-side to avoid CORS restrictions and TLS 0-RTT
    failures that affect direct browser→Nominatim calls.  Retries automatically
    on transient errors (425 Too Early, 429, 5xx, timeouts).
    """
    params = {
        "format": "json",
        "q": q,
        "limit": limit,
        "addressdetails": addressdetails,
        "extratags": extratags,
        "namedetails": namedetails,
        "accept-language": accept_language,
    }
    data = await _nominatim_get(f"{NOMINATIM_BASE}/search", params)
    return JSONResponse(content=data)
