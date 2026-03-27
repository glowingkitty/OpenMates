# backend/tests/test_tracing/test_integration.py
"""
Integration tests for the full OTel tracing pipeline.

Tests the complete flow: setup_tracing() → create spans → privacy filter
→ export to InMemoryExporter. Validates that the 3-tier model, WS trace
context propagation, and debug timeline formatting all work together.

Bug history this test suite guards against:
- Phase 06 initial implementation (2026-03-27)
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_project_root = str(Path(__file__).resolve().parents[3])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.trace import StatusCode, set_tracer_provider, get_tracer

from backend.shared.python_utils.tracing.privacy_filter import (
    TracePrivacyFilter,
    _pseudonymize_user_id,
    ALWAYS_STRIP_ATTRS,
    TIER_3_ONLY_ATTRS,
    TIER_2_ONLY_ATTRS,
)
from backend.shared.python_utils.tracing.ws_trace_context import (
    extract_ws_trace_context,
    inject_ws_trace_context,
)
from backend.scripts.debug_trace import format_trace_timeline, short_trace_id


class TestFullTracingPipeline:
    """End-to-end test: TracerProvider → spans → PrivacyFilter → exported spans."""

    def _create_pipeline(self, server_env: str = "production"):
        """Create a complete tracing pipeline with InMemory capture."""
        inner_exporter = InMemorySpanExporter()
        privacy_filter = TracePrivacyFilter(inner_exporter)

        resource = Resource.create({
            ResourceAttributes.SERVICE_NAME: "integration-test"
        })
        provider = TracerProvider(resource=resource)
        processor = SimpleSpanProcessor(privacy_filter)
        provider.add_span_processor(processor)

        return provider, inner_exporter, privacy_filter

    @patch.dict(os.environ, {"SERVER_ENVIRONMENT": "production"})
    def test_regular_user_request_tier1_filtering(self):
        """A regular user's OK request should have PII stripped (Tier 1)."""
        provider, exporter, _ = self._create_pipeline()
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("POST /v1/chat") as span:
            span.set_attribute("http.method", "POST")
            span.set_attribute("http.route", "/v1/chat")
            span.set_attribute("http.status_code", 200)
            span.set_attribute("enduser.id", "user-abc123")
            span.set_attribute("enduser.is_admin", False)
            span.set_attribute("enduser.debug_opted_in", False)
            span.set_attribute("otel.status_code", "OK")
            # Sensitive attrs that should be stripped at Tier 1
            span.set_attribute("http.request.header.authorization", "Bearer secret")
            span.set_attribute("db.statement", "SELECT * FROM users")
            span.set_attribute("exception.stacktrace", "Traceback...")
            span.set_attribute("cache.key", "user:abc:chats")
            span.set_attribute("llm.token_count", 500)

        provider.force_flush()
        exported = exporter.get_finished_spans()
        assert len(exported) == 1

        attrs = exported[0].attributes
        # Tier 1: safe operational attrs kept
        assert attrs["http.method"] == "POST"
        assert attrs["http.route"] == "/v1/chat"
        assert attrs["http.status_code"] == 200
        # Tier 1: user_id pseudonymized (not the original)
        assert attrs["enduser.id"] != "user-abc123"
        assert len(attrs["enduser.id"]) == 12  # pseudonym length
        # Tier 1: sensitive attrs stripped
        assert "http.request.header.authorization" not in attrs
        assert "db.statement" not in attrs
        assert "exception.stacktrace" not in attrs
        assert "cache.key" not in attrs
        assert "llm.token_count" not in attrs

        provider.shutdown()

    @patch.dict(os.environ, {"SERVER_ENVIRONMENT": "production"})
    def test_error_span_auto_escalates_to_tier2(self):
        """An error span from a regular user should auto-escalate to Tier 2."""
        provider, exporter, _ = self._create_pipeline()
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("POST /v1/auth/login") as span:
            span.set_attribute("http.method", "POST")
            span.set_attribute("http.status_code", 500)
            span.set_attribute("enduser.id", "user-xyz789")
            span.set_attribute("enduser.is_admin", False)
            span.set_attribute("enduser.debug_opted_in", False)
            span.set_attribute("otel.status_code", "ERROR")
            # Tier 2 attrs — should be kept on error
            span.set_attribute("exception.stacktrace", "Traceback: line 42...")
            span.set_attribute("celery.task_id", "task-uuid-456")
            span.set_attribute("celery.queue", "ai-queue")
            span.set_attribute("cache.hit", False)
            # Tier 3 attrs — should still be stripped
            span.set_attribute("cache.key", "user:xyz:session")
            span.set_attribute("llm.token_count", 300)
            # Always-strip
            span.set_attribute("http.request.header.authorization", "Bearer token")

        provider.force_flush()
        exported = exporter.get_finished_spans()
        attrs = exported[0].attributes

        # Tier 2: real user_id (not pseudonymized) for error investigation
        assert attrs["enduser.id"] == "user-xyz789"
        # Tier 2: debugging attrs kept
        assert "exception.stacktrace" in attrs
        assert "celery.task_id" in attrs
        assert attrs["cache.hit"] is False
        # Tier 3 only: still stripped
        assert "cache.key" not in attrs
        assert "llm.token_count" not in attrs
        # Always-strip: always gone
        assert "http.request.header.authorization" not in attrs

        provider.shutdown()

    @patch.dict(os.environ, {"SERVER_ENVIRONMENT": "production"})
    def test_admin_user_gets_tier3_full_visibility(self):
        """Admin users get full Tier 3 visibility on all spans."""
        provider, exporter, _ = self._create_pipeline()
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("GET /v1/admin/debug") as span:
            span.set_attribute("enduser.id", "admin-001")
            span.set_attribute("enduser.is_admin", True)
            span.set_attribute("enduser.debug_opted_in", False)
            span.set_attribute("otel.status_code", "OK")
            span.set_attribute("cache.key", "admin:debug:errors")
            span.set_attribute("llm.token_count", 1000)
            span.set_attribute("db.statement", "SELECT * FROM issues")
            span.set_attribute("http.request.header.authorization", "Bearer admin-token")

        provider.force_flush()
        exported = exporter.get_finished_spans()
        attrs = exported[0].attributes

        # Tier 3: real user_id
        assert attrs["enduser.id"] == "admin-001"
        # Tier 3: all debugging attrs visible
        assert attrs["cache.key"] == "admin:debug:errors"
        assert attrs["llm.token_count"] == 1000
        assert attrs["db.statement"] == "SELECT * FROM issues"
        # Always-strip: STILL gone even for admins
        assert "http.request.header.authorization" not in attrs

        provider.shutdown()

    @patch.dict(os.environ, {"SERVER_ENVIRONMENT": "dev"})
    def test_dev_server_bypasses_all_filtering(self):
        """Dev server should pass all attributes through unfiltered."""
        provider, exporter, _ = self._create_pipeline("dev")
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("POST /v1/chat") as span:
            span.set_attribute("enduser.id", "test-user")
            span.set_attribute("enduser.is_admin", False)
            span.set_attribute("enduser.debug_opted_in", False)
            span.set_attribute("otel.status_code", "OK")
            span.set_attribute("db.statement", "SELECT * FROM chats")
            span.set_attribute("cache.key", "chat:123:messages")
            span.set_attribute("http.request.header.authorization", "Bearer dev-token")

        provider.force_flush()
        exported = exporter.get_finished_spans()
        attrs = dict(exported[0].attributes)

        # Dev server: EVERYTHING passes through, including always-strip attrs
        assert attrs["enduser.id"] == "test-user"
        assert attrs["db.statement"] == "SELECT * FROM chats"
        assert attrs["cache.key"] == "chat:123:messages"
        assert attrs["http.request.header.authorization"] == "Bearer dev-token"

        provider.shutdown()


class TestWebSocketTraceContextPropagation:
    """Test that trace context propagates correctly through WS messages."""

    def test_inject_then_extract_roundtrip(self):
        """Trace context injected into WS payload should be extractable."""
        # Create a provider and start a span to get a valid context
        provider = TracerProvider(
            resource=Resource.create({ResourceAttributes.SERVICE_NAME: "test"})
        )
        set_tracer_provider(provider)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("ws.send.chat_message") as span:
            original_trace_id = format(span.get_span_context().trace_id, "032x")
            original_span_id = format(span.get_span_context().span_id, "016x")

            # Simulate frontend: inject trace context into WS payload
            payload = {"type": "message_received", "data": {"text": "hello"}}
            inject_ws_trace_context(payload)

            # Verify traceparent was injected
            assert "_traceparent" in payload
            traceparent = payload["_traceparent"]
            assert traceparent.startswith("00-")
            assert original_trace_id in traceparent

        # Simulate backend: extract trace context from received WS payload
        received_payload = dict(payload)
        ctx = extract_ws_trace_context(received_payload)

        # _traceparent should be removed from payload after extraction
        assert "_traceparent" not in received_payload
        # The context should be valid (not None/empty)
        assert ctx is not None

        provider.shutdown()

    def test_missing_traceparent_returns_current_context(self):
        """Payload without _traceparent should return current context gracefully."""
        payload = {"type": "message_received", "data": {}}
        ctx = extract_ws_trace_context(payload)
        # Should return a valid context (current/empty), not raise
        assert ctx is not None


class TestDebugTraceTimeline:
    """Test that debug.py trace produces readable timeline output."""

    def test_format_trace_timeline_renders_hierarchy(self):
        """Span hierarchy should render as indented text timeline."""
        # Timestamps in microseconds (as returned by OpenObserve trace queries)
        base_us = 1711543800000000  # arbitrary base timestamp in microseconds
        mock_spans = [
            {
                "trace_id": "abc123def456789012345678",
                "span_id": "span001",
                "parent_span_id": "",
                "operation_name": "POST /v1/auth/login",
                "service_name": "api",
                "start_time": base_us,
                "end_time": base_us + 120000,  # 120ms
                "duration": 120000,
                "span_status": "OK",
            },
            {
                "trace_id": "abc123def456789012345678",
                "span_id": "span002",
                "parent_span_id": "span001",
                "operation_name": "directus.get_user",
                "service_name": "api",
                "start_time": base_us + 8000,  # 8ms offset
                "end_time": base_us + 50000,   # 50ms offset
                "duration": 42000,
                "span_status": "OK",
            },
        ]
        output = format_trace_timeline(mock_spans)
        # Should contain operation names
        assert "POST /v1/auth/login" in output
        assert "directus.get_user" in output
        # Should contain timing info
        assert "120ms" in output or "120" in output
        assert "42ms" in output or "42" in output

    def test_short_trace_id_truncates(self):
        """Trace IDs should be truncated to 12 chars for readability."""
        assert short_trace_id("abc123def456789012345678") == "abc123def456"
        assert short_trace_id("short") == "short"


class TestPseudonymizationConsistency:
    """Test that pseudonymization is consistent within a day but different across days."""

    def test_same_user_same_day_same_pseudonym(self):
        """Same user on same day should get the same pseudonym."""
        p1 = _pseudonymize_user_id("user-abc123")
        p2 = _pseudonymize_user_id("user-abc123")
        assert p1 == p2
        assert len(p1) == 12

    def test_different_users_different_pseudonyms(self):
        """Different users should get different pseudonyms."""
        p1 = _pseudonymize_user_id("user-abc123")
        p2 = _pseudonymize_user_id("user-xyz789")
        assert p1 != p2

    def test_pseudonym_is_hex_string(self):
        """Pseudonym should be a valid hex string."""
        p = _pseudonymize_user_id("user-test")
        assert all(c in "0123456789abcdef" for c in p)
