# backend/tests/test_message_received_test_markers.py
#
# Regression coverage for dev-only E2E server-content markers on WebSocket
# message dispatch. These markers let Playwright keep the visible chat prompt
# clean while routing backend AI work through live mock/record fixtures.
# Production must still ignore the override entirely.

from tests.runtime_import_stubs import install_code_route_import_stubs


install_code_route_import_stubs()


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,app-skills.surface.semantic-parity
def test_dev_e2e_server_marker_accepts_live_record_markers(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _sanitize_test_mock_marker,
    )

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")

    assert _sanitize_test_mock_marker("<<<TEST_MOCK:events_search_web>>>") == "<<<TEST_MOCK:events_search_web>>>"
    assert _sanitize_test_mock_marker("<<<TEST_LIVE_MOCK:events_search_web>>>") == "<<<TEST_LIVE_MOCK:events_search_web>>>"
    assert _sanitize_test_mock_marker("<<<TEST_LIVE_RECORD:events_search_web>>>") == "<<<TEST_LIVE_RECORD:events_search_web>>>"
    assert _sanitize_test_mock_marker("<<<TEST_LIVE_RECORD:events_search_web>>>\nignore") is None


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
def test_e2e_server_marker_is_disabled_in_production(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _sanitize_test_mock_marker,
    )

    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")

    assert _sanitize_test_mock_marker("<<<TEST_LIVE_RECORD:events_search_web>>>") is None
