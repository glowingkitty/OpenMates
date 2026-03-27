# backend/shared/python_utils/tracing/ws_trace_context.py
#
# WebSocket trace context propagation utilities.
#
# HTTP auto-instrumentation handles traceparent headers automatically, but
# WebSocket frames don't have HTTP headers. This module provides functions
# to extract and inject W3C traceparent values from/into WebSocket message
# payloads using a reserved `_traceparent` field.
#
# Architecture: docs/architecture/opentelemetry.md

import logging
from typing import Dict, Any

from opentelemetry import context, trace
from opentelemetry.propagate import extract, inject

logger = logging.getLogger(__name__)

# Reserved payload field name for trace context propagation
TRACEPARENT_FIELD = "_traceparent"


def extract_ws_trace_context(payload: Dict[str, Any]) -> context.Context:
    """
    Extract W3C trace context from a WebSocket message payload.

    Pops the `_traceparent` field from the payload dict (so downstream handlers
    don't see it) and returns an OTel Context with the extracted trace info.
    If `_traceparent` is missing or invalid, returns the current context.

    Args:
        payload: The WebSocket message payload dict. Modified in-place --
                 `_traceparent` is removed if present.

    Returns:
        An opentelemetry.context.Context carrying the extracted trace parent,
        or the current context if no valid traceparent was found.
    """
    traceparent = payload.pop(TRACEPARENT_FIELD, None)

    if not traceparent:
        return context.get_current()

    try:
        carrier = {"traceparent": traceparent}
        ctx = extract(carrier=carrier)
        return ctx
    except Exception as exc:
        logger.debug("Failed to extract trace context from WS payload: %s", exc)
        return context.get_current()


def inject_ws_trace_context(payload: Dict[str, Any]) -> None:
    """
    Inject the current trace context into a WebSocket message payload.

    Reads the active span's trace context and sets `payload['_traceparent']`
    to the W3C traceparent string. If no active span exists, the field is
    not added.

    Args:
        payload: The WebSocket message payload dict. Modified in-place --
                 `_traceparent` is added if there is an active trace context.
    """
    carrier: Dict[str, str] = {}
    inject(carrier)

    traceparent = carrier.get("traceparent", "")
    if traceparent:
        payload[TRACEPARENT_FIELD] = traceparent
