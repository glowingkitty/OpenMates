# backend/core/api/app/utils/request_context.py
"""
Provides a contextvars-based request_id that threads through FastAPI middleware,
log records, and Celery task headers — enabling end-to-end request tracing.

Architecture context: See docs/architecture/logging-and-monitoring.md
Tests: None yet — verified via docker logs grep for request_id field.
"""

import logging
import uuid
from contextvars import ContextVar

# ---------------------------------------------------------------------------
# Context variable — stores the current request_id for the active context
# (async task or thread). Defaults to "no-request-id" when not set.
# ---------------------------------------------------------------------------
REQUEST_ID_CTX_KEY = "request_id"
_request_id_var: ContextVar[str] = ContextVar(REQUEST_ID_CTX_KEY, default="no-request-id")

# ---------------------------------------------------------------------------
# Debugging ID — set from the X-Debug-Session header when a user has an
# active debug log sharing session. Injected into log records so backend
# logs can be correlated with frontend console logs by the same ID.
# ---------------------------------------------------------------------------
DEBUGGING_ID_CTX_KEY = "debugging_id"
_debugging_id_var: ContextVar[str] = ContextVar(DEBUGGING_ID_CTX_KEY, default="")


def get_request_id() -> str:
    """Return the current request_id from contextvars."""
    return _request_id_var.get()


def set_request_id(request_id: str) -> None:
    """Set the current request_id in contextvars."""
    _request_id_var.set(request_id)


def generate_request_id() -> str:
    """Generate a new UUID4 request_id and store it in contextvars."""
    rid = str(uuid.uuid4())
    _request_id_var.set(rid)
    return rid


def get_debugging_id() -> str:
    """Return the current debugging_id from contextvars (empty string if not set)."""
    return _debugging_id_var.get()


def set_debugging_id(debugging_id: str) -> None:
    """Set the current debugging_id in contextvars."""
    _debugging_id_var.set(debugging_id)


# ---------------------------------------------------------------------------
# Log filter — automatically injects request_id and debugging_id into every
# log record so JSON logs always contain these fields for queries.
# ---------------------------------------------------------------------------
class RequestIdLogFilter(logging.Filter):
    """Injects the current request_id and debugging_id from contextvars into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()  # type: ignore[attr-defined]
        debugging_id = _debugging_id_var.get()
        if debugging_id:
            record.debugging_id = debugging_id  # type: ignore[attr-defined]
        return True
