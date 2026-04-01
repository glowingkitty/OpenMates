# backend/core/api/app/routes/telemetry.py
#
# OTLP proxy endpoint for frontend browser traces.
#
# The browser OTel SDK cannot send traces directly to OpenObserve because:
# 1. OpenObserve requires Basic auth credentials (not safe in browser)
# 2. CORS restrictions prevent direct cross-origin OTLP exports
#
# This endpoint accepts OTLP/HTTP trace payloads and forwards them to
# OpenObserve with server-side credentials.
#
# Environment policy:
# - Development: public (no auth) — all visitors submit traces
# - Production:  auth required — admins always, regular users only if
#                they opted into extended debugging in settings
#
# Architecture: docs/architecture/opentelemetry.md

import logging
import os
from base64 import b64encode
from typing import Optional

import httpx
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_optional
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.server_mode import get_server_edition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/telemetry", tags=["Telemetry"])

# OpenObserve OTLP traces ingestion endpoint
OPENOBSERVE_TRACES_URL = "http://openobserve:5080/api/default/v1/traces"

# Rate limit: 60 requests per minute per IP (prevent abuse)
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


def _is_user_allowed_to_trace(user: Optional[User]) -> bool:
    """
    Check if a user is allowed to submit browser traces in production.

    Admins always submit traces. Regular users only if they have opted
    into extended debugging via their settings.

    Args:
        user: The authenticated user, or None if not logged in.

    Returns:
        True if the user may submit traces.
    """
    if user is None:
        return False
    if user.is_admin:
        return True
    # Check if user opted into extended debugging
    return getattr(user, "extended_debugging", False)


@router.post("/traces")
@limiter.limit(TELEMETRY_RATE_LIMIT)
async def proxy_traces(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Forward OTLP trace payloads from the browser SDK to OpenObserve.

    On development servers, all visitors can submit traces (no auth).
    On production, only admins and users with extended debugging enabled.
    Rate-limited to 60/min per IP regardless.

    Args:
        request: The incoming FastAPI request containing OTLP payload.
        current_user: Optionally authenticated user.

    Returns:
        200 on success, 403 if not authorized, 502 if OpenObserve is unreachable.
    """
    # Enforce auth policy based on environment
    edition = get_server_edition()
    if edition != "development":
        if not _is_user_allowed_to_trace(current_user):
            return JSONResponse(
                status_code=403,
                content={"status": "error", "detail": "Telemetry not enabled for this account"},
            )

    auth_header = _get_openobserve_auth_header()
    if not auth_header:
        logger.error("[Telemetry] OpenObserve credentials not configured (OPENOBSERVE_ROOT_EMAIL/PASSWORD)")
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": "Telemetry backend not configured"},
        )

    body = await request.body()
    content_type = request.headers.get("content-type", "application/x-protobuf")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                OPENOBSERVE_TRACES_URL,
                content=body,
                headers={
                    "Content-Type": content_type,
                    "Authorization": auth_header,
                },
            )

        if response.status_code == 503:
            # OpenObserve memory pressure — expected transient failure, don't alarm
            logger.debug("[Telemetry] OpenObserve returned 503 (memory pressure), dropping batch")
            return JSONResponse(
                status_code=202,
                content={"status": "dropped", "detail": "Telemetry backend temporarily unavailable"},
            )

        if response.status_code >= 400:
            logger.warning(
                "[Telemetry] OpenObserve returned %d: %s",
                response.status_code,
                response.text[:200],
            )
            return JSONResponse(
                status_code=502,
                content={"status": "error", "detail": "Upstream telemetry error"},
            )

        return {"status": "ok"}

    except (httpx.ConnectError, httpx.ReadTimeout):
        logger.debug("[Telemetry] OpenObserve unreachable/timeout — dropping batch")
        return JSONResponse(
            status_code=202,
            content={"status": "dropped", "detail": "Telemetry backend unreachable"},
        )
    except Exception as exc:
        logger.error("[Telemetry] Unexpected error forwarding traces: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=502,
            content={"status": "error", "detail": "Internal telemetry error"},
        )
