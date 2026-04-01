# backend/tests/test_tracing/test_ws_trace_context.py
#
# Unit tests for WebSocket trace context propagation utilities.
# These functions extract and inject W3C traceparent headers from/into
# WebSocket message payloads, enabling distributed tracing across the
# frontend-to-backend WebSocket boundary.
#
# Bug history this test suite guards against:
#   - Trace context must be popped from payload so handlers don't see _traceparent
#   - Missing _traceparent must not raise errors (graceful degradation)

import pytest
from opentelemetry import trace, context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

from backend.shared.python_utils.tracing.ws_trace_context import (
    extract_ws_trace_context,
    inject_ws_trace_context,
)


@pytest.fixture(autouse=True)
def setup_tracer():
    """Set up a tracer provider for testing."""
    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    yield provider
    provider.shutdown()


class TestExtractWsTraceContext:
    """Tests for extract_ws_trace_context()."""

    def test_valid_traceparent_returns_context_with_trace_info(self):
        """extract_ws_trace_context with valid _traceparent returns a context with trace info."""
        valid_traceparent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        payload = {
            "_traceparent": valid_traceparent,
            "chat_id": "test-chat",
            "message": {"content": "hello"},
        }

        ctx = extract_ws_trace_context(payload)

        # The returned context should contain a valid span context
        span_ctx = trace.get_current_span(ctx).get_span_context()
        assert span_ctx.trace_id != 0, "Expected non-zero trace_id from valid traceparent"
        assert span_ctx.span_id != 0, "Expected non-zero span_id from valid traceparent"

    def test_missing_traceparent_returns_current_context(self):
        """extract_ws_trace_context with missing _traceparent returns current context (no error)."""
        payload = {
            "chat_id": "test-chat",
            "message": {"content": "hello"},
        }

        ctx = extract_ws_trace_context(payload)

        # Should return a valid context without raising
        assert ctx is not None
        span_ctx = trace.get_current_span(ctx).get_span_context()
        # Invalid span context has trace_id == 0
        assert span_ctx.trace_id == 0, "Expected zero trace_id when no traceparent provided"

    def test_removes_traceparent_from_payload(self):
        """extract_ws_trace_context removes _traceparent from payload dict (side effect)."""
        valid_traceparent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        payload = {
            "_traceparent": valid_traceparent,
            "chat_id": "test-chat",
        }

        extract_ws_trace_context(payload)

        assert "_traceparent" not in payload, "_traceparent should be removed from payload"
        assert "chat_id" in payload, "Other payload fields should remain untouched"

    def test_invalid_traceparent_returns_current_context(self):
        """extract_ws_trace_context with invalid _traceparent returns current context gracefully."""
        payload = {
            "_traceparent": "invalid-traceparent-value",
            "chat_id": "test-chat",
        }

        ctx = extract_ws_trace_context(payload)

        # Should return a valid context without raising
        assert ctx is not None
        # _traceparent should still be popped from payload
        assert "_traceparent" not in payload


class TestInjectWsTraceContext:
    """Tests for inject_ws_trace_context()."""

    def test_adds_traceparent_to_payload(self):
        """inject_ws_trace_context adds _traceparent string to payload dict."""
        tracer = trace.get_tracer("test")

        payload = {"chat_id": "test-chat", "message": {"content": "hello"}}

        # Start a span to have an active context with trace info
        with tracer.start_as_current_span("test-span"):
            inject_ws_trace_context(payload)

        assert "_traceparent" in payload, "Expected _traceparent to be added to payload"
        traceparent = payload["_traceparent"]
        assert isinstance(traceparent, str)
        # W3C traceparent format: version-trace_id-span_id-flags
        parts = traceparent.split("-")
        assert len(parts) == 4, f"Expected 4 parts in traceparent, got {len(parts)}: {traceparent}"
        assert parts[0] == "00", "Expected version 00"

    def test_no_active_span_no_traceparent(self):
        """inject_ws_trace_context without active span does not add invalid _traceparent."""
        payload = {"chat_id": "test-chat"}

        inject_ws_trace_context(payload)

        # Without an active span, _traceparent should not be present
        # or should be empty/not added
        if "_traceparent" in payload:
            # If present, it should be empty
            assert payload["_traceparent"] == "", "Without active span, traceparent should be empty"
