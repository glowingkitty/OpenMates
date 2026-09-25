"""Offline contracts for the three deterministic workflow demos."""
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from backend.core.api.app.services.workflow_app_skill_adapter import _normalize_skill_output
from backend.core.api.app.services.workflow_runtime_values import resolve_workflow_runtime_values
from backend.core.api.app.services.workflow_scheduler_service import WorkflowSchedulerService


def stamp(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
@pytest.mark.parametrize("now,expected", [
    ("2026-09-14T09:12:00+02:00", "2026-09-14T10:00:00+02:00"),
    ("2026-03-29T01:59:00+01:00", "2026-03-29T03:00:00+02:00"),
    ("2026-10-25T02:01:00+02:00", "2026-10-25T02:00:00+01:00"),
])
def test_hourly_schedule_uses_real_occurrences_across_dst(now: str, expected: str) -> None:
    assert WorkflowSchedulerService.next_run_at_from_schedule(
        {"type": "hourly", "minute": 0, "timezone": "Europe/Berlin"}, now=stamp(now)
    ) == stamp(expected)


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
def test_calendar_schedule_and_relative_week_use_local_timezone() -> None:
    assert WorkflowSchedulerService.next_run_at_from_schedule(
        {"type": "daily", "time": "02:30", "timezone": "Europe/Berlin"},
        now=stamp("2026-03-29T00:00:00+01:00"),
    ) == stamp("2026-03-29T03:30:00+02:00")
    assert WorkflowSchedulerService.initial_next_run_at_from_schedule(
        {"type": "once", "at": "2026-09-14T09:00:00", "timezone": "Europe/Berlin"}
    ) == stamp("2026-09-14T09:00:00+02:00")
    result = resolve_workflow_runtime_values(
        {"requests": [{"start_date": {"$date": "next_week_start"}, "end_date": {"$date": "next_week_end"}}]},
        now=stamp("2026-03-22T09:00:00+01:00"), timezone="Europe/Berlin",
    )["requests"][0]
    assert result == {"start_date": "2026-03-23T00:00:00+01:00", "end_date": "2026-03-29T23:59:59+02:00"}


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_today_date_value_resolves_again_for_each_run_and_test() -> None:
    value = {"start_date": {"$date": "today", "format": "date"}}
    first = resolve_workflow_runtime_values(
        value, now=stamp("2026-09-14T23:30:00+02:00"), timezone="Europe/Berlin"
    )
    second = resolve_workflow_runtime_values(
        value, now=stamp("2026-09-15T00:30:00+02:00"), timezone="Europe/Berlin"
    )
    assert first == {"start_date": "2026-09-14"}
    assert second == {"start_date": "2026-09-15"}


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_today_end_datetime_uses_local_timezone_and_inclusive_boundary() -> None:
    assert resolve_workflow_runtime_values(
        {"$date": "today_end", "format": "datetime"},
        now=stamp("2026-09-14T23:30:00+02:00"),
        timezone="Europe/Berlin",
    ) == "2026-09-14T23:59:59+02:00"


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
@pytest.mark.parametrize("app,alias", [("news", "articles"), ("events", "events"), ("home", "listings")])
def test_search_results_are_flat_and_identity_ignores_tracking(app: str, alias: str) -> None:
    raw = {"provider": "Provider", "results": [{"id": "request-1", "results": [
        {"title": "First", "url": "https://example.com/item?id=123&utm_source=email#top"},
        {"id": "listing-2", "title": "Second", "url": "https://example.com/two"},
    ]}, {"id": "request-2", "results": []}]}
    result = _normalize_skill_output(app, "search", {}, raw)
    assert result["result_count"] == 2
    assert result[alias] == result["results"]
    assert result["results"][0]["source_id"] == "https://example.com/item?id=123"
    assert result["results"][1]["source_id"] == "listing-2"
    assert _normalize_skill_output(app, "search", {"requests": [{"query": "Berlin"}]}, {"results": []})["result_count"] == 0


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
def test_weather_reports_real_rain_windows_and_preserves_unknown_data() -> None:
    hours = [
        {"timestamp": "2026-09-14T12:00:00+02:00", "precipitation_probability_pct": 80},
        {"timestamp": "2026-09-14T13:00:00+02:00", "precipitation_mm": 1.2},
        {"timestamp": "2026-09-14T14:00:00+02:00", "precipitation_mm": 0, "precipitation_probability_pct": 10},
    ]
    result = _normalize_skill_output("weather", "forecast", {}, {
        "start_date": "2026-09-14", "end_date": "2026-09-14",
        "results": [{"date": "2026-09-14", "label": "today", "hourly": hours, "timezone": "Europe/Berlin"}],
    })
    assert result["rain_expected"] is True
    assert [(item["start_time"], item["end_time"]) for item in result["rain_periods"]] == [("12:00", "14:00")]
    assert "12:00–14:00" in result["rain_summary"]
    assert result["start_date"] == "2026-09-14"
    assert result["end_date"] == "2026-09-14"
    future = _normalize_skill_output("weather", "forecast", {}, {
        "results": [{"date": "2026-09-17", "hourly": hours, "timezone": "Europe/Berlin"}],
    })
    assert "forecast 2026-09-17" in future["rain_summary"]
    unknown = _normalize_skill_output("weather", "forecast", {}, {"results": [{"hourly": [{"timestamp": "2026-09-14T12:00:00"}]}]})
    assert unknown["rain_expected"] is None
    assert "unavailable" in unknown["rain_summary"]


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
def test_demo_metadata_exposes_actual_list_outputs_and_news_test() -> None:
    root = Path(__file__).resolve().parents[1] / "apps"
    for app in ("news", "events", "home"):
        skill = next(item for item in yaml.safe_load((root / app / "app.yml").read_text())["skills"] if item["id"] == "search")
        assert skill["workflow"]["test_allowed"] is True
        assert skill["workflow"]["output_schema"]["properties"]["results"]["items"]["properties"]["source_id"]["type"] == "string"


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_weather_demo_uses_today_range_instead_of_legacy_days() -> None:
    root = Path(__file__).resolve().parents[2] / "examples" / "workflows"
    document = yaml.safe_load((root / "morning-weather-news.yml").read_text())
    weather_input = document["steps"][0]["input"]
    today = {"$date": "today", "format": "date"}
    assert weather_input["start_date"] == today
    assert weather_input["end_date"] == today
    assert "days" not in weather_input


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
@pytest.mark.parametrize("filename", ["morning-weather-news.yml", "weekly-ai-events.yml", "hourly-apartments.yml"])
def test_editable_video_examples_compile_against_skill_metadata(filename: str) -> None:
    from backend.core.api.app.services.workflow_yaml_compiler import validate_workflow_yaml
    source = Path(__file__).resolve().parents[2] / "examples" / "workflows" / filename
    result = validate_workflow_yaml(source.read_text())
    assert result.draft_valid and result.enable_ready, result.diagnostics
    # Runtime preflight enforces the public input enums beyond YAML structure.
    from backend.core.api.app.services.workflow_models import validate_workflow_readiness
    validate_workflow_readiness(result.graph)
