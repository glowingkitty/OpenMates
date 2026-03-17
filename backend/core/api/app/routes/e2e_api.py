# backend/core/api/app/routes/e2e_api.py
"""
E2E Test Client Log Forwarding Endpoint

Receives batched browser console logs from Playwright E2E test runs and pushes
them to OpenObserve. This enables post-mortem debugging of test failures by
correlating client-side logs with backend logs in a single timeline.

Security:
- Uses a scoped HMAC token derived from INTERNAL_API_SHARED_TOKEN, NOT the
  token itself. The scoped token only grants access to this single endpoint.
- The INTERNAL_API_SHARED_TOKEN is never exposed to the browser.
- Token derivation: HMAC-SHA256(INTERNAL_API_SHARED_TOKEN, "e2e-client-logs")

Privacy guarantees:
- This endpoint is only hit by Playwright Docker containers during E2E runs.
- Regular users never encounter this endpoint (no UI triggers it).
- The #e2e-debug= hash param is only injected by the test runner.

See docs/architecture/admin-console-log-forwarding.md for the broader log
forwarding architecture.
"""

import hashlib
import hmac
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.openobserve_push_service import openobserve_push_service

logger = logging.getLogger(__name__)

# Derive the scoped token at module load time.
# This token is a HMAC of the shared internal token with the scope "e2e-client-logs".
# It is NOT the INTERNAL_API_SHARED_TOKEN itself — it can only authenticate to this
# one endpoint, preventing lateral movement if it were ever leaked.
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN", "")
E2E_SCOPED_TOKEN: str = hmac.new(
    INTERNAL_API_SHARED_TOKEN.encode(),
    b"e2e-client-logs",
    hashlib.sha256,
).hexdigest() if INTERNAL_API_SHARED_TOKEN else ""

router = APIRouter(
    prefix="/e2e",
    tags=["E2E Testing"],
)


# --- Request Models ---

class E2ELogEntry(BaseModel):
    """A single client console log entry from an E2E test browser."""
    timestamp: int = Field(..., description="Log timestamp in milliseconds since epoch")
    level: str = Field(..., description="Log level: log, info, warn, error, debug")
    message: str = Field(..., max_length=2000, description="Sanitized log message")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = {"log", "info", "warn", "error", "debug"}
        if v not in allowed:
            raise ValueError(f"Invalid log level: {v}. Must be one of: {allowed}")
        return v

    @field_validator("message")
    @classmethod
    def truncate_message(cls, v: str) -> str:
        return v[:2000] if len(v) > 2000 else v


class E2ELogMetadata(BaseModel):
    """Metadata about the E2E test browser environment."""
    userAgent: str = Field(default="", max_length=500)
    pageUrl: str = Field(default="", max_length=500)
    tabId: str = Field(default="", max_length=50)


class E2EClientLogsRequest(BaseModel):
    """Request body for the E2E client log forwarding endpoint."""
    run_id: str = Field(..., min_length=1, max_length=200, description="E2E test run correlation ID")
    logs: List[E2ELogEntry] = Field(..., max_length=50, description="Batch of log entries (max 50)")
    metadata: Optional[E2ELogMetadata] = Field(default=None)

    @field_validator("logs")
    @classmethod
    def validate_logs_not_empty(cls, v: List[E2ELogEntry]) -> List[E2ELogEntry]:
        if not v:
            raise ValueError("logs must contain at least one entry")
        if len(v) > 50:
            raise ValueError("Maximum 50 log entries per batch")
        return v


# --- Auth dependency ---

def verify_e2e_token(request: Request) -> bool:
    """
    Verify the scoped E2E debug token from the X-E2E-Debug-Token header.

    This is NOT the INTERNAL_API_SHARED_TOKEN. It is an HMAC derivation that
    only authenticates against this specific endpoint.
    """
    if not E2E_SCOPED_TOKEN:
        logger.error("E2E client-logs endpoint called but INTERNAL_API_SHARED_TOKEN is not configured.")
        raise HTTPException(status_code=500, detail="E2E debug token not configured on server.")

    token = request.headers.get("X-E2E-Debug-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing E2E debug token.")

    if not hmac.compare_digest(token, E2E_SCOPED_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid E2E debug token.")

    return True


# --- Endpoint ---

@router.post(
    "/client-logs",
    include_in_schema=False,
    summary="Forward E2E test browser console logs to OpenObserve",
)
@limiter.limit("1200/minute")
async def receive_e2e_client_logs(
    request: Request,
    body: E2EClientLogsRequest,
) -> Dict[str, Any]:
    """
    Receive batched browser console logs from an E2E test run and push them
    to OpenObserve, tagged with the run_id for post-mortem querying via
    `debug.py logs --debug-id {run_id}`.

    Authentication: X-E2E-Debug-Token header (scoped HMAC, not the internal token).
    """
    verify_e2e_token(request)

    metadata = body.metadata or E2ELogMetadata()

    entries = [
        {
            "timestamp": entry.timestamp,
            "level": entry.level,
            "message": entry.message,
        }
        for entry in body.logs
    ]

    success = await openobserve_push_service.push_debug_session_logs(
        entries=entries,
        debugging_id=body.run_id,
        user_id="e2e-test",
        metadata={
            "userAgent": metadata.userAgent,
            "pageUrl": metadata.pageUrl,
            "tabId": metadata.tabId,
        },
    )

    if not success:
        logger.warning(f"Failed to push E2E client logs to OpenObserve for run_id={body.run_id}")

    # Always return 200 — log forwarding failures should not break E2E tests.
    return {"success": success}
