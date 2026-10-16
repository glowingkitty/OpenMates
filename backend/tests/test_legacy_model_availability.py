# contract-test-file: infrastructure
"""Legacy chat availability is date-bound without erasing historic tariffs."""

from datetime import date

import pytest

from backend.core.api.app.utils import config_manager as config_module
from backend.core.api.app.utils.config_manager import ConfigManager
from backend.shared.python_utils.model_availability import is_model_available


@pytest.mark.parametrize("release,retirement,expected", [
    ("2025-10-08", None, True),  # Twelve calendar months is inclusive.
    ("2025-10-07", None, False),
    ("2026-10-08", None, True),
    ("2026-10-09", None, False),
    ("2026-01-01", "2026-10-09", True),
    ("2026-01-01", "2026-10-08", False),
    ("2026-01-01", "2026-10-07", False),
    ("invalid", None, False),
    (None, None, False),
    ("2026-01-01", "invalid", False),
])
def test_legacy_chat_window_uses_release_and_actual_retirement_dates(
    release: str | None, retirement: str | None, expected: bool,
) -> None:
    model = {"for_app_skill": "ai.ask", "legacy_model": True, "release_date": release}
    if retirement is not None:
        model["api_retirement_date"] = retirement
    assert is_model_available(model, today=date(2026, 10, 8)) is expected


def test_curated_models_are_date_unrestricted_and_leap_cutoff_is_calendar_based() -> None:
    assert is_model_available(
        {"for_app_skill": "ai.ask", "release_date": "2020-01-01",
         "api_retirement_date": "2020-02-01"}, today=date(2026, 10, 8),
    )
    assert is_model_available(
        {"for_app_skill": "images.generate", "legacy_model": True,
         "release_date": "2020-01-01"}, today=date(2026, 10, 8),
    )
    legacy = {"for_app_skill": "ai.ask", "legacy_model": True, "release_date": "2027-02-28"}
    assert is_model_available(legacy, today=date(2028, 2, 29))
    legacy["release_date"] = "2027-02-27"
    assert not is_model_available(legacy, today=date(2028, 2, 29))


def test_catalogue_queries_expire_legacy_models_but_keep_raw_billing_tariffs(monkeypatch) -> None:
    manager = object.__new__(ConfigManager)
    legacy = {"id": "old", "name": "Old", "for_app_skill": "ai.ask", "legacy_model": True,
              "release_date": "2025-10-08", "pricing": {"tokens": {"input": {"per_credit_unit": 10}}}}
    curated = {"id": "curated", "for_app_skill": "ai.ask", "release_date": "2020-01-01"}
    raw = {"provider_id": "openai", "models": [legacy, curated]}
    manager._provider_configs = {"openai": raw}

    monkeypatch.setattr(config_module, "utc_today", lambda: date(2026, 10, 8))
    assert [model["id"] for model in manager.get_provider_config("openai")["models"]] == ["old", "curated"]
    assert manager.find_provider_for_model("old") == "openai"

    monkeypatch.setattr(config_module, "utc_today", lambda: date(2026, 10, 9))
    assert [model["id"] for model in manager.get_provider_configs()["openai"]["models"]] == ["curated"]
    assert [model["id"] for model in manager.get_provider_config("openai")["models"]] == ["curated"]
    assert manager.find_provider_for_model("old") is None
    assert manager.get_model_pricing("openai", "old") is legacy
    assert manager.get_model_display_name("old", "openai") == "Old"
    assert raw["models"] == [legacy, curated]
