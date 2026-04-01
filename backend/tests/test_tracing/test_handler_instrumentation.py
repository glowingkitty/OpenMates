# backend/tests/test_tracing/test_handler_instrumentation.py
"""
Audit test: Verify all WebSocket handler files have OTel instrumentation.

This is a "living audit" -- if someone adds a new WS handler without OTel
instrumentation via ws_span_helper, this test fails immediately in CI.

Tests verify:
1. Every handler file imports/uses start_ws_handler_span
2. Every handler file imports/uses end_ws_handler_span
3. Every handler file accepts user_otel_attrs parameter
4. No handler still uses the old inline OTel pattern (opentelemetry import)

Bug history this test suite guards against:
- OTEL-05: Only 2 of 37 WS handlers had OTel instrumentation (fixed in 09-02)
"""

import pathlib

import pytest

# Path to the websocket handlers directory (relative to repo root)
_HANDLERS_DIR = pathlib.Path(__file__).resolve().parents[2] / (
    "core/api/app/routes/handlers/websocket_handlers"
)

# Discover all handler .py files, excluding __init__.py
_HANDLER_FILES = sorted(
    f for f in _HANDLERS_DIR.glob("*.py")
    if f.name != "__init__.py"
)


def _handler_ids():
    """Generate pytest IDs from handler filenames for readable output."""
    return [f.stem for f in _HANDLER_FILES]


class TestHandlerInstrumentationCoverage:
    """Ensure every WS handler file has OTel instrumentation via ws_span_helper."""

    def test_handler_files_discovered(self):
        """Sanity check: we discover at least 35 handler files (not hardcoded)."""
        assert len(_HANDLER_FILES) >= 35, (
            f"Expected at least 35 handler files, found {len(_HANDLER_FILES)}. "
            f"Directory: {_HANDLERS_DIR}"
        )

    @pytest.mark.parametrize("handler_file", _HANDLER_FILES, ids=_handler_ids())
    def test_has_start_ws_handler_span(self, handler_file: pathlib.Path):
        """Every handler file must use start_ws_handler_span for span creation."""
        content = handler_file.read_text()
        assert "start_ws_handler_span" in content, (
            f"{handler_file.name} is missing start_ws_handler_span. "
            f"All WS handlers must be instrumented via ws_span_helper."
        )

    @pytest.mark.parametrize("handler_file", _HANDLER_FILES, ids=_handler_ids())
    def test_has_end_ws_handler_span(self, handler_file: pathlib.Path):
        """Every handler file must use end_ws_handler_span for span cleanup."""
        content = handler_file.read_text()
        assert "end_ws_handler_span" in content, (
            f"{handler_file.name} is missing end_ws_handler_span. "
            f"All WS handler spans must be properly ended in a finally block."
        )

    @pytest.mark.parametrize("handler_file", _HANDLER_FILES, ids=_handler_ids())
    def test_has_user_otel_attrs_param(self, handler_file: pathlib.Path):
        """Every handler file must accept user_otel_attrs for privacy tier resolution."""
        content = handler_file.read_text()
        assert "user_otel_attrs" in content, (
            f"{handler_file.name} is missing user_otel_attrs parameter. "
            f"All WS handlers must accept user_otel_attrs for OTel privacy attributes."
        )

    @pytest.mark.parametrize("handler_file", _HANDLER_FILES, ids=_handler_ids())
    def test_no_legacy_inline_otel(self, handler_file: pathlib.Path):
        """No handler should still use the old inline OTel pattern."""
        content = handler_file.read_text()
        assert "from opentelemetry import trace as _trace" not in content, (
            f"{handler_file.name} still has legacy inline OTel imports. "
            f"Migrate to ws_span_helper (start_ws_handler_span/end_ws_handler_span)."
        )
