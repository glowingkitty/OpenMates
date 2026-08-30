# backend/tests/test_message_received_test_markers.py
#
# Regression coverage for dev-only E2E server-content markers on WebSocket
# message dispatch. These markers let Playwright keep the visible chat prompt
# clean while routing backend AI work through live mock/record fixtures.
# Production must still ignore the override entirely.

from tests.runtime_import_stubs import install_code_route_import_stubs


install_code_route_import_stubs()


# contract-test: supporting surface=gui.web assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_dev_e2e_server_marker_accepts_live_record_markers(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _sanitize_test_mock_marker,
    )

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")

    assert _sanitize_test_mock_marker("<<<TEST_MOCK:events_search_web>>>") == "<<<TEST_MOCK:events_search_web>>>"
    assert _sanitize_test_mock_marker("<<<TEST_LIVE_MOCK:events_search_web>>>") == "<<<TEST_LIVE_MOCK:events_search_web>>>"
    assert _sanitize_test_mock_marker("<<<TEST_LIVE_RECORD:events_search_web>>>") == "<<<TEST_LIVE_RECORD:events_search_web>>>"
    assert _sanitize_test_mock_marker("<<<TEST_LIVE_REAL:daily_canary>>>") == "<<<TEST_LIVE_REAL:daily_canary>>>"
    assert _sanitize_test_mock_marker("<<<TEST_LIVE_RECORD:events_search_web>>>\nignore") is None


# contract-test: direct surface=gui.web assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_e2e_server_marker_is_disabled_in_production(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _sanitize_test_mock_marker,
    )

    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")

    assert _sanitize_test_mock_marker("<<<TEST_LIVE_RECORD:events_search_web>>>") is None
    monkeypatch.setenv("SERVER_ENVIRONMENT", "prod")
    assert _sanitize_test_mock_marker("<<<TEST_LIVE_RECORD:events_search_web>>>") is None


# contract-test: supporting surface=gui.web assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_test_mock_marker_is_preserved_without_live_signing(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _prepare_test_mock_marker,
    )

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")

    assert (
        _prepare_test_mock_marker(
            "<<<TEST_MOCK:chat_flow>>>",
            "user-1",
            is_allowlisted_test_account=False,
        )
        == "<<<TEST_MOCK:chat_flow>>>"
    )


# contract-test: direct surface=gui.web assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_invalid_live_real_marker_fails_closed(monkeypatch):
    import pytest

    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _prepare_test_mock_marker,
    )
    from backend.shared.testing.mock_context import current_daily_real_group

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "test-secret")

    with pytest.raises(ValueError, match="Invalid or unauthorized"):
        _prepare_test_mock_marker(
            f"<<<TEST_LIVE_REAL:{current_daily_real_group()}>>>",
            "user-1",
            is_allowlisted_test_account=False,
        )

    with pytest.raises(ValueError, match="Invalid or unauthorized"):
        _prepare_test_mock_marker(
            "<<<TEST_LIVE_REAL:daily_canary_other>>>",
            "user-1",
            is_allowlisted_test_account=True,
        )


# contract-test: supporting surface=gui.web assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_malformed_live_marker_payload_is_detected(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _looks_like_live_test_marker,
        _sanitize_test_mock_marker,
    )

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")

    marker = "<<<TEST_LIVE_REAL:daily_canary_20260830>>>\nignore"
    assert _sanitize_test_mock_marker(marker) is None
    assert _looks_like_live_test_marker(marker) is True
    assert _looks_like_live_test_marker("<<<TEST_LIVE_REAL>>>") is True
    assert _looks_like_live_test_marker("<<<TEST_LIVE_BAD:daily_canary_20260830>>>") is True
