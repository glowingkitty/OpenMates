# backend/tests/test_wikipedia_language.py
#
# Regression coverage for locale-aware Wikipedia inline link handling.
# Assistant responses use wiki:Title refs, which must be validated against the
# user's UI-language Wikipedia site instead of silently defaulting to English.

from types import SimpleNamespace

import pytest

from backend.shared.providers.wikipedia.wikipedia_api import normalize_wikipedia_language

try:
    from backend.apps.ai.tasks.stream_consumer import _resolve_wikipedia_validation_language
except ImportError as _exc:
    _resolve_wikipedia_validation_language = None
    _STREAM_CONSUMER_IMPORT_ERROR = _exc
else:
    _STREAM_CONSUMER_IMPORT_ERROR = None


def test_normalize_wikipedia_language_uses_ui_language() -> None:
    assert normalize_wikipedia_language("de") == "de"


def test_normalize_wikipedia_language_accepts_regional_locale() -> None:
    assert normalize_wikipedia_language("de-DE") == "de"
    assert normalize_wikipedia_language("pt_BR") == "pt"


def test_normalize_wikipedia_language_falls_back_safely() -> None:
    assert normalize_wikipedia_language("../../evil", fallback="de") == "de"
    assert normalize_wikipedia_language(None, fallback="invalid") == "en"


def test_stream_consumer_resolves_user_interface_language() -> None:
    if _resolve_wikipedia_validation_language is None:
        pytest.skip(f"Backend task dependencies not installed: {_STREAM_CONSUMER_IMPORT_ERROR}")

    request_data = SimpleNamespace(user_preferences={"language": "de"})
    preprocessing_result = SimpleNamespace(output_language="en")

    assert _resolve_wikipedia_validation_language(request_data, preprocessing_result) == "de"
