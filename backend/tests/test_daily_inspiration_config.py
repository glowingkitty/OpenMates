"""Fixed background writer configuration for Daily Inspirations.

Model selection is local to the background writing stage. These checks ensure
old environment overrides and legacy fallback constants cannot silently restore
an alternate production model or alter normal account/chat model preferences.
"""
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
import pytest

from backend.apps.ai.daily_inspiration import config


@pytest.mark.parametrize('legacy_override', ['google/gemini-3.8-flash', 'google/gemini-3.5-flash-lite',
                                             'mistral/mistral-small-latest', 'unrecognized/model'])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_sole_writer_ignores_legacy_environment_selection(monkeypatch, legacy_override):
    monkeypatch.setenv('DAILY_INSPIRATION_WRITER_MODEL', legacy_override)
    assert config.WRITER_MODEL == config.writer_model() == 'inception/mercury-3'


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_runtime_writer_has_no_legacy_model_or_fallback_constants():
    for name in ('MERCURY_WRITER', 'MISTRAL_WRITER', 'FALLBACK_WRITER', 'DEFAULT_WRITER'):
        assert not hasattr(config, name)
