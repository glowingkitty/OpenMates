# backend/core/api/app/routes/admin_client_logs.py
"""
Admin Client Console Log Forwarding Endpoint

Receives batched browser console logs from admin users and pushes them to Loki
for centralized storage and querying via Grafana. This gives admins a unified
view of client-side and server-side logs when debugging issues.

Privacy guarantees:
- Only accessible to authenticated admin users (double-checked via require_admin dependency)
- Regular users cannot access this endpoint (HTTP 403)
- Log messages are pre-sanitized on the client side (API keys, tokens, passwords redacted)
- User identification in Loki uses username only (no email addresses)

See docs/admin-console-log-forwarding.md for full architecture documentation.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.loki_push_service import loki_push_service
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/admin",
    tags=["Admin"]
)


# --- Dependency ---

def get_directus_service(request: Request) -> DirectusService:
    """Get DirectusService from app state."""
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


async def require_admin(
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service)
) -> User:
    """Dependency to ensure user has admin privileges."""
    is_admin = await directus_service.admin.is_user_admin(current_user.id)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


# --- Request Models ---

class ClientLogEntry(BaseModel):
    """A single client console log entry."""
    timestamp: int = Field(..., description="Log timestamp in milliseconds since epoch")
    level: str = Field(..., description="Log level: log, info, warn, error, debug")
    message: str = Field(..., max_length=2000, description="Sanitized log message (max 2000 chars)")

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
        """Truncate overly long messages as a server-side safety net."""
        return v[:2000] if len(v) > 2000 else v


class ClientLogMetadata(BaseModel):
    """Metadata about the client environment sending the logs."""
    userAgent: str = Field(default="", max_length=500, description="Browser user agent string")
    pageUrl: str = Field(default="", max_length=500, description="Current page URL path")
    tabId: str = Field(default="", max_length=50, description="Unique tab identifier for multi-tab disambiguation")


class ClientLogsRequest(BaseModel):
    """Request body for the client log forwarding endpoint."""
    logs: List[ClientLogEntry] = Field(..., max_length=50, description="Batch of log entries (max 50 per request)")
    metadata: Optional[ClientLogMetadata] = Field(default=None, description="Client environment metadata")

    @field_validator("logs")
    @classmethod
    def validate_logs_not_empty(cls, v: List[ClientLogEntry]) -> List[ClientLogEntry]:
        if not v:
            raise ValueError("logs must contain at least one entry")
        if len(v) > 50:
            raise ValueError("Maximum 50 log entries per batch")
        return v


# --- Endpoint ---

@router.post(
    "/client-logs",
    include_in_schema=False,
    summary="Forward client console logs to Loki (admin only)",
)
@limiter.limit("10/minute")
async def receive_client_logs(
    request: Request,
    body: ClientLogsRequest,
    admin_user: User = Depends(require_admin),
) -> dict:
    """
    Receive batched browser console logs from an admin user and push them to Loki.

    This endpoint is rate-limited to 10 requests per minute per user. With the client
    sending batches every 5 seconds (max 50 entries each), this allows up to ~500 log
    entries per minute, which is more than sufficient for normal debugging sessions.

    The logs are pushed to Loki with the following labels:
    - job: "client-console" (distinguishes from server-side logs)
    - level: log level (info, warn, error, debug)
    - user: admin username
    - server_env: development or production
    - source: "browser"

    Returns:
        {"success": true} if logs were accepted, {"success": false} on Loki push failure
    """
    metadata = body.metadata or ClientLogMetadata()

    # Convert entries to the format expected by the Loki push service
    entries = [
        {
            "timestamp": entry.timestamp,
            "level": entry.level,
            "message": entry.message,
        }
        for entry in body.logs
    ]

    # Push to Loki using the admin's username as the identifier
    # We use username instead of email because:
    # 1. Email is encrypted in the database and not available on the User model
    # 2. Username is unique, human-readable, and sufficient for identifying the admin
    success = await loki_push_service.push_client_logs(
        entries=entries,
        user_email=admin_user.username,  # Using username as the user identifier label
        metadata={
            "userAgent": metadata.userAgent,
            "pageUrl": metadata.pageUrl,
            "tabId": metadata.tabId,
        },
    )

    if not success:
        logger.warning(
            f"Failed to push {len(entries)} client log entries to Loki for admin user {admin_user.username}"
        )

    # Always return 200 to the client - log forwarding failures should not
    # cause client-side errors or retries. This is non-critical debug infrastructure.
    return {"success": success}
