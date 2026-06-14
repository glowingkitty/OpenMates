# backend/tests/test_mock_replay.py
#
# Unit tests for E2E mock replay timing helpers.
#
# Mock replay publishes Redis events through the same channels as real AI
# streaming. These tests keep the default timing contract explicit so replay
# fixtures do not race ahead of the browser's active-chat subscription setup.

import pytest

try:
    from backend.apps.ai.testing.mock_replay import (
        DEFAULT_INITIAL_CHUNK_DELAY_MS,
        get_fixture_initial_delay_seconds,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


def test_fixture_initial_delay_defaults_to_readiness_delay() -> None:
    assert get_fixture_initial_delay_seconds({}) == DEFAULT_INITIAL_CHUNK_DELAY_MS / 1000.0


def test_fixture_initial_delay_can_be_overridden_to_zero() -> None:
    assert get_fixture_initial_delay_seconds({"initial_delay_ms": 0}) == 0.0


def test_fixture_initial_delay_uses_fixture_value() -> None:
    assert get_fixture_initial_delay_seconds({"initial_delay_ms": 750}) == 0.75
