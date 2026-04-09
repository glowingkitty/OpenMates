# backend/core/api/app/routes/client_logs_ephemeral.py
"""
Ephemeral Client Console Log Forwarding — Rolling Buffer with Error-Triggered Retention

Receives batched browser console logs from ALL authenticated users and pushes
them to a short-lived OpenObserve stream (client_console_ephemeral, 48h retention).
When an error-level log is received, a Redis flag is set so a periodic Celery
task can promote the full session context to a longer-retention stream (14d).

Privacy guarantees:
- No user_id or user_email is sent to OpenObserve — only a random per-session
  UUID (session_pseudonym) generated client-side in sessionStorage.
- Server-side defense-in-depth sanitization strips emails, base64 blobs,
  long quoted strings, and UUIDs in chat/message contexts.
- The session_pseudonym cannot be correlated to a user unless the user
  voluntarily includes it in an issue report.

Legal basis: Legitimate interest (GDPR Art. 6(1)(f)) — service reliability.
Users can opt out via Settings > Privacy > "Help improve stability".
See docs/architecture/ephemeral-log-forwarding.md for full architecture.
"""

import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field, field_validator

from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.openobserve_push_service import openobserve_push_service
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1",
    tags=["Client Logs"]
)

# ── Server-side PII sanitization (defense in depth) ──────────────────────────
# These patterns match the client-side sanitizeContent() in logCollector.ts.
# Both layers must agree — if client-side misses something, server catches it.

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
_BASE64_RE = re.compile(r'[A-Za-z0-9+/=]{50,}')
_LONG_DOUBLE_QUOTED_RE = re.compile(r'"[^"]{100,}"')
_LONG_SINGLE_QUOTED_RE = re.compile(r"'[^']{100,}'")
_CHAT_UUID_RE = re.compile(
    r'(chat[_-]?id|message[_-]?id|embed[_-]?id)[=:]\s*'
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)
_URL_PATH_UUID_RE = re.compile(
    r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
)
# Match standalone UUIDs that appear as values (after = or : or whitespace)
_UUID_VALUE_RE = re.compile(
    r'(?<=[=:\s])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


def sanitize_ephemeral_message(message: str) -> str:
    """
    Server-side defense-in-depth sanitization for ephemeral log messages.

    Strips PII patterns that should already be removed client-side but may
    slip through due to bugs, new log statements, or edge cases.
    """
    message = _EMAIL_RE.sub('[EMAIL-REDACTED]', message)
    message = _BASE64_RE.sub('[BASE64-REDACTED]', message)
    message = _LONG_DOUBLE_QUOTED_RE.sub('"[LONG-STRING-REDACTED]"', message)
    message = _LONG_SINGLE_QUOTED_RE.sub("'[LONG-STRING-REDACTED]'", message)
    message = _CHAT_UUID_RE.sub(r'\1=[UUID-REDACTED]', message)
    message = _URL_PATH_UUID_RE.sub('/[UUID-REDACTED]', message)
    return message


# ── Request Models ────────────────────────────────────────────────────────────

class EphemeralLogEntry(BaseModel):
    """A single client console log entry (same schema as admin endpoint)."""
    timestamp: int = Field(..., description="Log timestamp in milliseconds since epoch")
    level: str = Field(..., description="Log level: log, info, warn, error")
    message: str = Field(..., max_length=2000, description="Sanitized log message")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        # Ephemeral mode drops debug-level on the client, but validate anyway
        allowed = {"log", "info", "warn", "error", "debug"}
        if v not in allowed:
            raise ValueError(f"Invalid log level: {v}. Must be one of: {allowed}")
        return v

    @field_validator("message")
    @classmethod
    def truncate_message(cls, v: str) -> str:
        """Truncate overly long messages as a server-side safety net."""
        return v[:2000] if len(v) > 2000 else v


class EphemeralLogMetadata(BaseModel):
    """Client environment metadata (no user-identifying fields)."""
    userAgent: str = Field(default="", max_length=500)
    pageUrl: str = Field(default="", max_length=500)
    tabId: str = Field(default="", max_length=50)


class EphemeralClientLogsRequest(BaseModel):
    """Request body for ephemeral client log forwarding."""
    logs: List[EphemeralLogEntry] = Field(
        ..., max_length=50, description="Batch of log entries (max 50)"
    )
    metadata: Optional[EphemeralLogMetadata] = Field(default=None)
    session_pseudonym: str = Field(
        ..., min_length=36, max_length=36,
        description="Random UUIDv4 generated per page load, stored in sessionStorage"
    )

    @field_validator("logs")
    @classmethod
    def validate_logs_not_empty(cls, v: List[EphemeralLogEntry]) -> List[EphemeralLogEntry]:
        if not v:
            raise ValueError("logs must contain at least one entry")
        if len(v) > 50:
            raise ValueError("Maximum 50 log entries per batch")
        return v

    @field_validator("session_pseudonym")
    @classmethod
    def validate_uuid_format(cls, v: str) -> str:
        """Ensure session_pseudonym looks like a UUID (basic format check)."""
        import re as _re
        if not _re.match(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            v.lower(),
        ):
            raise ValueError("session_pseudonym must be a valid UUID")
        return v.lower()


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/client-logs",
    include_in_schema=False,
    summary="Forward anonymized client console logs (all authenticated users)",
)
@limiter.limit("600/minute")
async def receive_ephemeral_client_logs(
    request: Request,
    body: EphemeralClientLogsRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Receive batched browser console logs from any authenticated user.

    Logs are pushed to the 'client_console_ephemeral' OpenObserve stream (48h retention).
    When an error-level entry is present, a Redis flag is set so the periodic
    promotion task copies the full session context to the 14-day error-context stream.

    The current_user dependency is used ONLY for authentication and rate limiting.
    No user identity is forwarded to OpenObserve.
    """
    metadata = body.metadata or EphemeralLogMetadata()
    has_error = False

    # Apply server-side sanitization and convert to push format
    entries = []
    for entry in body.logs:
        sanitized_message = sanitize_ephemeral_message(entry.message)
        entries.append({
            "timestamp": entry.timestamp,
            "level": entry.level,
            "message": sanitized_message,
        })
        if entry.level == "error":
            has_error = True

    # Push to ephemeral stream (no user identity in labels)
    success = await openobserve_push_service.push_ephemeral_client_logs(
        entries=entries,
        session_pseudonym=body.session_pseudonym,
        metadata={
            "userAgent": metadata.userAgent,
            "pageUrl": metadata.pageUrl,
            "tabId": metadata.tabId,
        },
    )

    # Flag this session in Redis if any error occurred, so the promotion
    # task knows to copy the surrounding context to the long-retention stream.
    # NOTE: CacheService exposes the redis client via an async `client`
    # property — there is no `.redis` attribute. Using `.redis` silently
    # broke the error-session flag pipeline for an unknown period.
    if has_error and success:
        try:
            cache_service = request.app.state.cache_service
            redis_client = await cache_service.client
            if redis_client is None:
                raise RuntimeError("cache client not connected")
            flag_key = f"ephemeral-error:{body.session_pseudonym}"
            await redis_client.set(flag_key, "1", ex=172800)  # 48h TTL
        except Exception as e:
            logger.warning(f"Failed to set ephemeral error flag in Redis: {e}")

    if not success:
        logger.warning(
            f"Failed to push ephemeral client logs to OpenObserve "
            f"(session={body.session_pseudonym[:8]}...)"
        )

    # Always 200 — log forwarding failures must not break the client
    return {"success": success}
