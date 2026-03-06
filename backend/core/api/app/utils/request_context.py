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


# ---------------------------------------------------------------------------
# Log filter — automatically injects request_id into every log record
# so JSON logs always contain the field for Loki/Promtail queries.
# ---------------------------------------------------------------------------
class RequestIdLogFilter(logging.Filter):
    """Injects the current request_id from contextvars into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()  # type: ignore[attr-defined]
        return True
