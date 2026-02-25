# backend/core/api/app/routes/analytics_beacon.py
#
# Privacy-preserving analytics beacon endpoint.
#
# Receives lightweight POST requests from the client-side analytics snippet
# embedded in the frontend layout. Two event types are accepted:
#
#   "pv" (page view) — fired on page load:
#     { "t": "pv", "p": "/path", "sc": "lg" }
#
#   "sd" (session duration) — fired on pagehide:
#     { "t": "sd", "d": "2m-5m" }
#   OR with raw seconds (for WebSocket-based duration fallback):
#     { "t": "sd", "ds": 145.3 }
#
# Rate limiting: 10 requests/minute per IP (well above any legitimate use case).
# No authentication required — beacon is public, data is anonymous.
#
# Privacy guarantees:
# - IP address is used only for GeoIP lookup and HyperLogLog seeding; never stored
# - User-Agent is parsed to metadata only; raw string never stored
# - All data lands as aggregate Redis counters, flushed to Directus every 10 min
#
# See docs/analytics.md for the full design and privacy guarantees.

import logging
from typing import Optional, Literal
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/analytics",
    tags=["Analytics"]
)

# Valid screen classes from client beacon (matches CSS breakpoints)
VALID_SCREEN_CLASSES = {"sm", "md", "lg", "xl"}

# Valid pre-bucketed duration labels (client sends string bucket for pagehide events)
VALID_DURATION_BUCKETS = {"<30s", "30s-2m", "2m-5m", "5m-15m", "15m-30m", "30m-1h", "1h+"}


class BeaconPayload(BaseModel):
    """
    Payload for the analytics beacon endpoint.

    Two event types:
    - "pv" (page view): fires on page load with optional path and screen class
    - "sd" (session duration): fires on pagehide with either a pre-bucketed label
      or raw duration in seconds (when fired from WebSocket disconnect)
    """
    t: Literal["pv", "sd"] = Field(..., description="Event type: 'pv' (page view) or 'sd' (session duration)")

    # Page view fields
    p: Optional[str] = Field(None, max_length=256, description="Page path (page view only)")
    sc: Optional[str] = Field(None, max_length=4, description="Screen class: sm/md/lg/xl (page view only)")

    # Session duration fields
    d: Optional[str] = Field(None, max_length=10, description="Pre-bucketed duration label (pagehide)")
    ds: Optional[float] = Field(None, ge=0, le=86400, description="Raw duration in seconds (WebSocket fallback)")


def _get_client_ip(request: Request) -> str:
    """
    Extract the real client IP from the request.

    Checks X-Forwarded-For first (set by reverse proxy), falls back to
    the direct connection IP.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        # X-Forwarded-For can be a comma-separated list; the first entry is the client IP
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/beacon")
@limiter.limit("10/minute")
async def analytics_beacon(
    request: Request,
    payload: BeaconPayload,
) -> Response:
    """
    Receive an analytics beacon event from the client.

    Processes the event asynchronously — all analytics work happens in the
    background without blocking the HTTP response. Returns 204 No Content
    regardless of processing success to minimize client-side latency.

    Rate limited to 10 requests/minute per IP.
    No authentication required.
    """
    # Get web_analytics_service from app state (initialized in main.py lifespan)
    web_analytics_service = getattr(request.app.state, "web_analytics_service", None)
    if web_analytics_service is None:
        # Service not initialized — return 204 silently rather than surfacing errors
        logger.warning("analytics_beacon: web_analytics_service not in app.state, dropping event")
        return Response(status_code=204)

    try:
        if payload.t == "pv":
            # Page view event
            client_ip = _get_client_ip(request)
            ua_string = request.headers.get("User-Agent", "")
            referer = request.headers.get("Referer", "")

            # Validate screen class
            sc = payload.sc if payload.sc in VALID_SCREEN_CLASSES else None

            await web_analytics_service.record_page_view(
                client_ip=client_ip,
                ua_string=ua_string,
                referer_header=referer,
                screen_class=sc,
                path=payload.p,
            )

        elif payload.t == "sd":
            # Session duration event — either pre-bucketed string or raw seconds
            if payload.d and payload.d in VALID_DURATION_BUCKETS:
                # Client sent a pre-bucketed label — record it directly
                await web_analytics_service.record_session_duration_bucket(payload.d)
            elif payload.ds is not None:
                # Raw seconds — let the service bucket it
                await web_analytics_service.record_session_duration(payload.ds)

    except Exception as e:
        # Never surface analytics errors to the client
        logger.error(f"analytics_beacon: Error processing {payload.t} event: {e}", exc_info=True)

    # Always return 204 — analytics failures must not affect the user experience
    return Response(status_code=204)
