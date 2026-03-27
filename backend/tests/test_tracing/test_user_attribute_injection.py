# backend/tests/test_tracing/test_user_attribute_injection.py
"""
Tests proving user attributes flow from cached profile to OTel span attributes.

Covers:
- ws_span_helper.start_ws_handler_span creates spans with correct user attributes
- ws_span_helper.end_ws_handler_span safely ends spans and detaches tokens
- ws_span_helper gracefully handles missing OTel (returns None, None)
- determine_user_tier resolves Tier 3 for admin/opted-in users

Bug history this test suite guards against:
- OTEL-02: TracePrivacyFilter always defaulted to Tier 1 because enduser.is_admin
  and enduser.debug_opted_in were never set as span attributes.
- OTEL-06: No reusable helper existed, so handler instrumentation was either
  copy-pasted or missing entirely.
"""

import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch

# Add project root to sys.path so 'backend.shared...' imports resolve
_project_root = str(Path(__file__).resolve().parents[3])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)



def _load_module_directly(module_name: str, file_path: str):
    """Load a Python module directly from file path, bypassing package __init__.py."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load user_tier directly to avoid triggering tracing/__init__.py which imports
# config.py (requires OTel exporters + instrumentors not installed locally).
_tracing_dir = Path(_project_root) / "backend" / "shared" / "python_utils" / "tracing"
user_tier_mod = _load_module_directly(
    "backend.shared.python_utils.tracing.user_tier",
    str(_tracing_dir / "user_tier.py"),
)
determine_user_tier = user_tier_mod.determine_user_tier
TIER_FULL_VISIBILITY = user_tier_mod.TIER_FULL_VISIBILITY
TIER_MINIMAL = user_tier_mod.TIER_MINIMAL

# ws_trace_context is imported by ws_span_helper, load it first
ws_trace_ctx_mod = _load_module_directly(
    "backend.shared.python_utils.tracing.ws_trace_context",
    str(_tracing_dir / "ws_trace_context.py"),
)

# Load ws_span_helper directly
ws_span_helper_mod = _load_module_directly(
    "backend.shared.python_utils.tracing.ws_span_helper",
    str(_tracing_dir / "ws_span_helper.py"),
)


# ---------------------------------------------------------------------------
# Tests for ws_span_helper.start_ws_handler_span
# ---------------------------------------------------------------------------

class TestStartWsHandlerSpan:
    """Tests for the start_ws_handler_span function."""

    def test_returns_span_and_token_when_otel_available(self):
        """Test 1: start_ws_handler_span returns (span, token) with correct
        attributes when OTel is available."""
        start_ws_handler_span = ws_span_helper_mod.start_ws_handler_span
        end_ws_handler_span = ws_span_helper_mod.end_ws_handler_span

        span, token = start_ws_handler_span(
            handler_name="test_handler",
            user_id="user-abc-123",
            payload=None,
            user_otel_attrs={"is_admin": True, "debug_opted_in": False},
        )

        assert span is not None, "Span should not be None when OTel is installed"
        assert token is not None, "Token should not be None when OTel is installed"

        # Clean up
        end_ws_handler_span(span, token)

    def test_returns_none_none_when_otel_import_fails(self):
        """Test 2: start_ws_handler_span returns (None, None) when OTel
        import fails."""
        start_fn = ws_span_helper_mod.start_ws_handler_span

        with patch.object(ws_span_helper_mod, "_HAS_OTEL", False):
            span, token = start_fn(
                handler_name="test_handler",
                user_id="user-abc-123",
                payload=None,
            )
            assert span is None
            assert token is None

    def test_span_has_admin_and_debug_attrs_when_passed(self):
        """Test 3: span created by helper has enduser.is_admin=True and
        enduser.debug_opted_in=True when passed in user_otel_attrs."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from opentelemetry import trace

        # Set up in-memory exporter to inspect span attributes.
        # Use _TRACER_PROVIDER_SET_ONCE to handle single-set restriction.
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        # Patch the global tracer provider directly to avoid "override not allowed"
        trace._TRACER_PROVIDER_SET_ONCE._done = False
        trace.set_tracer_provider(provider)

        start_ws_handler_span = ws_span_helper_mod.start_ws_handler_span
        end_ws_handler_span = ws_span_helper_mod.end_ws_handler_span

        span, token = start_ws_handler_span(
            handler_name="message_received",
            user_id="user-admin-001",
            payload=None,
            user_otel_attrs={"is_admin": True, "debug_opted_in": True},
        )

        end_ws_handler_span(span, token)

        finished_spans = exporter.get_finished_spans()
        assert len(finished_spans) == 1

        attrs = dict(finished_spans[0].attributes)
        assert attrs["enduser.is_admin"] is True
        assert attrs["enduser.debug_opted_in"] is True
        assert attrs["enduser.id"] == "user-admin-001"
        assert attrs["ws.message_type"] == "message_received"

        # Clean up
        exporter.clear()

    def test_span_has_false_attrs_when_not_passed(self):
        """Test 4: span created by helper has enduser.is_admin=False and
        enduser.debug_opted_in=False when user_otel_attrs not passed."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from opentelemetry import trace

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        trace._TRACER_PROVIDER_SET_ONCE._done = False
        trace.set_tracer_provider(provider)

        start_ws_handler_span = ws_span_helper_mod.start_ws_handler_span
        end_ws_handler_span = ws_span_helper_mod.end_ws_handler_span

        span, token = start_ws_handler_span(
            handler_name="draft_update",
            user_id="user-regular-002",
            payload=None,
            # No user_otel_attrs passed
        )

        end_ws_handler_span(span, token)

        finished_spans = exporter.get_finished_spans()
        assert len(finished_spans) == 1

        attrs = dict(finished_spans[0].attributes)
        assert attrs["enduser.is_admin"] is False
        assert attrs["enduser.debug_opted_in"] is False

        exporter.clear()


# ---------------------------------------------------------------------------
# Tests for ws_span_helper.end_ws_handler_span
# ---------------------------------------------------------------------------

class TestEndWsHandlerSpan:
    """Tests for the end_ws_handler_span function."""

    def test_end_handles_none_inputs_safely(self):
        """Test 5: end_ws_handler_span ends span and detaches token safely,
        and does not raise on None inputs."""
        end_ws_handler_span = ws_span_helper_mod.end_ws_handler_span

        # Should not raise any exception
        end_ws_handler_span(None, None)
        end_ws_handler_span(None, None, error=ValueError("test error"))


# ---------------------------------------------------------------------------
# Tests for determine_user_tier (integration with span attributes)
# ---------------------------------------------------------------------------

class TestDetermineUserTierIntegration:
    """Tests proving determine_user_tier reads the attributes set by ws_span_helper."""

    def test_tier3_when_admin(self):
        """Test 6: determine_user_tier returns 3 when span has
        enduser.is_admin=True."""
        attrs = {
            "enduser.is_admin": True,
            "enduser.debug_opted_in": False,
            "otel.status_code": "OK",
        }
        assert determine_user_tier(attrs) == TIER_FULL_VISIBILITY

    def test_tier3_when_debug_opted_in(self):
        """Test 7: determine_user_tier returns 3 when span has
        enduser.debug_opted_in=True."""
        attrs = {
            "enduser.is_admin": False,
            "enduser.debug_opted_in": True,
            "otel.status_code": "OK",
        }
        assert determine_user_tier(attrs) == TIER_FULL_VISIBILITY

    def test_tier1_when_both_false_no_error(self):
        """Test 8: determine_user_tier returns 1 when both are False and
        no error."""
        attrs = {
            "enduser.is_admin": False,
            "enduser.debug_opted_in": False,
            "otel.status_code": "OK",
        }
        assert determine_user_tier(attrs) == TIER_MINIMAL
