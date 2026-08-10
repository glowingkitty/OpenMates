# contract-test-file: infrastructure
# backend/apps/ai/tests/test_timeout_utils.py
#
# Regression tests for preprocessing LLM timeout configuration.
# Provider fallback calls are non-streaming tool calls, so the timeout must leave
# enough room for healthy-but-slow providers while still bounding failed calls.
#
# Run: python -m pytest backend/apps/ai/tests/test_timeout_utils.py -q

import importlib

from backend.apps.ai.utils import timeout_utils


def test_preprocessing_timeout_default_allows_slow_tool_fallback(monkeypatch):
    monkeypatch.delenv("AI_PREPROCESSING_TIMEOUT_SECONDS", raising=False)

    reloaded = importlib.reload(timeout_utils)
    try:
        assert reloaded.PREPROCESSING_TIMEOUT_SECONDS >= 20.0
    finally:
        importlib.reload(timeout_utils)


def test_preprocessing_timeout_supports_env_override(monkeypatch):
    monkeypatch.setenv("AI_PREPROCESSING_TIMEOUT_SECONDS", "17.5")

    reloaded = importlib.reload(timeout_utils)
    try:
        assert reloaded.PREPROCESSING_TIMEOUT_SECONDS == 17.5
    finally:
        monkeypatch.delenv("AI_PREPROCESSING_TIMEOUT_SECONDS", raising=False)
        importlib.reload(timeout_utils)
