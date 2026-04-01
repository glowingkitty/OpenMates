# backend/core/api/app/utils/request_context.py
"""
Provides a contextvars-based request_id that threads through FastAPI middleware,
log records, and Celery task headers — enabling end-to-end request tracing.

When OpenTelemetry is active, request_id is derived from the OTel trace_id so
that log correlation and OTel distributed traces share a single identifier.
When OTel is not installed or no active span exists, falls back to UUID4.

Architecture context: See docs/architecture/logging-and-monitoring.md
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
    """Generate request_id: prefer OTel trace_id if tracing is active, else UUID4.

    When OpenTelemetry is installed and an active span exists, the request_id
    is set to the hex-encoded trace_id so that log records and OTel traces
    share the same correlation key. If OTel is unavailable or no span is
    active, falls back to a random UUID4.

    Returns:
        The generated (or OTel-derived) request_id string.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id != 0:
            # Use OTel trace_id as the request_id for unified correlation
            rid = format(ctx.trace_id, '032x')
            _request_id_var.set(rid)
            return rid
    except ImportError:
        pass
    # Fallback to UUID4 if OTel not available or no active span
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
    """Injects the current request_id and debugging_id from contextvars into every log record.

    This filter is supplementary to OTel's LoggingInstrumentor which injects
    otelTraceId and otelSpanId. RequestIdLogFilter continues injecting
    request_id for backwards compatibility with existing log queries and
    dashboards. When OTel is active, request_id == otelTraceId.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()  # type: ignore[attr-defined]
        debugging_id = _debugging_id_var.get()
        if debugging_id:
            record.debugging_id = debugging_id  # type: ignore[attr-defined]
        return True
