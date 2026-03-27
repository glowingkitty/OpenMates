# backend/core/api/app/routes/telemetry.py
#
# OTLP proxy endpoint for frontend browser traces.
#
# The browser OTel SDK cannot send traces directly to OpenObserve because:
# 1. OpenObserve requires Basic auth credentials (not safe in browser)
# 2. CORS restrictions prevent direct cross-origin OTLP exports
#
# This endpoint accepts OTLP/HTTP trace payloads from authenticated users
# and forwards them to OpenObserve with server-side credentials.
#
# Architecture: docs/architecture/opentelemetry.md

import logging
import os
from base64 import b64encode

import httpx
from fastapi import APIRouter, Request, Depends

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/telemetry", tags=["Telemetry"])

# OpenObserve OTLP traces ingestion endpoint
OPENOBSERVE_TRACES_URL = "http://openobserve:5080/api/default/v1/traces"

# Rate limit: 60 requests per minute per user (prevent abuse)
TELEMETRY_RATE_LIMIT = "60/minute"


def _get_openobserve_auth_header() -> str:
    """
    Build HTTP Basic auth header from OpenObserve env vars.

    Returns:
        Base64-encoded Basic auth string, or empty string if credentials missing.
    """
    email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
    password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")
    if not email or not password:
        return ""
    credentials = b64encode(f"{email}:{password}".encode()).decode()
    return f"Basic {credentials}"


@router.post("/traces")
@limiter.limit(TELEMETRY_RATE_LIMIT)
async def proxy_traces(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Forward OTLP trace payloads from the browser SDK to OpenObserve.

    Requires JWT authentication. The request body is forwarded as-is
    to OpenObserve's OTLP/HTTP ingestion endpoint with server-side
    Basic auth credentials.

    Args:
        request: The incoming FastAPI request containing OTLP payload.
        current_user: Authenticated user (JWT dependency).

    Returns:
        200 on success, 502 if OpenObserve is unreachable.
    """
    auth_header = _get_openobserve_auth_header()
    if not auth_header:
        logger.error("[Telemetry] OpenObserve credentials not configured (OPENOBSERVE_ROOT_EMAIL/PASSWORD)")
        return {"status": "error", "detail": "Telemetry backend not configured"}, 503

    body = await request.body()
    content_type = request.headers.get("content-type", "application/x-protobuf")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                OPENOBSERVE_TRACES_URL,
                content=body,
                headers={
                    "Content-Type": content_type,
                    "Authorization": auth_header,
                },
            )

        if response.status_code >= 400:
            logger.warning(
                "[Telemetry] OpenObserve returned %d: %s",
                response.status_code,
                response.text[:200],
            )
            return {"status": "error", "detail": "Upstream telemetry error"}, 502

        return {"status": "ok"}

    except httpx.ConnectError:
        logger.warning("[Telemetry] Cannot reach OpenObserve at %s", OPENOBSERVE_TRACES_URL)
        return {"status": "error", "detail": "Telemetry backend unreachable"}, 502
    except Exception as exc:
        logger.error("[Telemetry] Unexpected error forwarding traces: %s", exc, exc_info=True)
        return {"status": "error", "detail": "Internal telemetry error"}, 502
