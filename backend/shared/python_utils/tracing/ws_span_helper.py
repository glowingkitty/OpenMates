# backend/shared/python_utils/tracing/ws_span_helper.py
"""
Reusable WebSocket handler span creation and teardown.

Provides start_ws_handler_span() and end_ws_handler_span() so that every
WS handler can be instrumented with user-level OTel attributes without
copy-pasting the try/ImportError/except boilerplate 37 times.

Key attributes set on every handler span:
- ws.message_type: The handler name (e.g., "message_received")
- enduser.id: The user ID string
- enduser.is_admin: Whether the user is an admin (from cached profile)
- enduser.debug_opted_in: Whether the user opted into debug logging

These attributes are read by TracePrivacyFilter (via determine_user_tier)
to resolve the correct privacy tier for span export.

Architecture context: docs/architecture/observability.md
"""

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Guard OTel imports so the module degrades gracefully if OTel is not installed.
_HAS_OTEL = False
_trace = None
_context = None
_StatusCode = None

try:
    from opentelemetry import trace as _trace_mod, context as _context_mod
    from opentelemetry.trace import StatusCode as _StatusCode_cls

    _trace = _trace_mod
    _context = _context_mod
    _StatusCode = _StatusCode_cls
    _HAS_OTEL = True
except ImportError:
    pass

# Import ws_trace_context for parent context extraction (also guarded)
_extract_ws_trace_context = None
try:
    from backend.shared.python_utils.tracing.ws_trace_context import extract_ws_trace_context as _extract_fn
    _extract_ws_trace_context = _extract_fn
except ImportError:
    pass


def start_ws_handler_span(
    handler_name: str,
    user_id: str,
    payload: Optional[Dict[str, Any]],
    user_otel_attrs: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Any]:
    """
    Create an OTel span for a WebSocket handler with user-level attributes.

    If OTel is not installed, returns (None, None) without raising.

    Args:
        handler_name: The handler name used as span suffix (e.g., "message_received").
            The span will be named "ws.{handler_name}".
        user_id: The user's ID string.
        payload: The WebSocket message payload dict. If not None and contains
            a _traceparent field, it is extracted for parent context propagation.
        user_otel_attrs: Optional dict with keys "is_admin" and "debug_opted_in"
            extracted from the cached user profile. Defaults to False for both
            if not provided.

    Returns:
        Tuple of (span, context_token). Both are None if OTel is unavailable.
        The caller MUST pass these to end_ws_handler_span() in a finally block.
    """
    if not _HAS_OTEL or _trace is None or _context is None:
        return None, None

    try:
        # Extract parent context from payload if available
        parent_ctx = None
        if payload is not None and _extract_ws_trace_context is not None:
            parent_ctx = _extract_ws_trace_context(payload)

        # Resolve user attributes with safe defaults
        is_admin = False
        debug_opted_in = False
        if user_otel_attrs:
            is_admin = user_otel_attrs.get("is_admin", False)
            debug_opted_in = user_otel_attrs.get("debug_opted_in", False)

        tracer = _trace.get_tracer(__name__)

        # Build span kwargs
        span_kwargs = {
            "name": f"ws.{handler_name}",
            "attributes": {
                "ws.message_type": handler_name,
                "enduser.id": str(user_id),
                "enduser.is_admin": bool(is_admin),
                "enduser.debug_opted_in": bool(debug_opted_in),
            },
        }
        if parent_ctx is not None:
            span_kwargs["context"] = parent_ctx

        span = tracer.start_span(**span_kwargs)
        token = _context.attach(_context.set_value("current-span", span))

        return span, token

    except Exception as exc:
        logger.debug("ws_span_helper: span creation failed (non-fatal): %s", exc)
        return None, None


def end_ws_handler_span(
    span: Any,
    token: Any,
    error: Optional[Exception] = None,
) -> None:
    """
    End an OTel span and detach its context token.

    Safe to call with None values -- does nothing in that case.
    Never raises exceptions.

    Args:
        span: The span returned by start_ws_handler_span (or None).
        token: The context token returned by start_ws_handler_span (or None).
        error: Optional exception to record as an error status on the span.
    """
    try:
        if error is not None and span is not None and _StatusCode is not None:
            span.set_status(_StatusCode.ERROR, str(error))
    except Exception:
        pass

    try:
        if span is not None:
            span.end()
    except Exception:
        pass

    try:
        if token is not None and _context is not None:
            _context.detach(token)
    except Exception:
        pass
