"""Fixture checks for the public values returned by Workflow app skills.

These fixtures represent skill response shapes. They do not dispatch a skill,
contact a provider, or start an asynchronous job.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator

from backend.core.api.app.services.workflow_app_skill_adapter import _normalize_skill_output
from backend.core.api.app.services.workflow_capability_registry import (
    WorkflowCapabilityRegistry,
    _FilesystemWorkflowMetadataRegistry,
)


_SKILL_FIXTURES: tuple[
    tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]], ...
] = (
    (
        "code.get_docs",
        {"library": "Svelte", "question": "How do actions work?"},
        {
            "library": {"id": "/sveltejs/svelte", "title": "Svelte"},
            "documentation": "Actions are functions called when an element is mounted.",
            "word_count": 9,
            "source": "context7",
        },
        {"result_count": 1},
    ),
    (
        "openmates.get-docs",
        {"url": "architecture/apps"},
        {
            "title": "Apps architecture",
            "slug": "architecture/apps",
            "content": "# Apps architecture\n\nSkills run within an app.",
            "word_count": 7,
            "url": "https://openmates.org/docs/architecture/apps",
        },
        {"result_count": 1},
    ),
    (
        "travel.get_flight",
        {"flight_number": "LH400", "departure_date": "2026-08-01"},
        {
            "success": True,
            "flight_number": "LH400",
            "fr24_id": "flight-400",
            "data_source": "flightradar24",
            "tracks": [
                {"timestamp": "2026-08-01T13:00:00Z", "lat": 50.0, "lon": 8.0, "alt": 10000},
                {"timestamp": "2026-08-01T13:05:00Z", "lat": 50.3, "lon": 8.4, "alt": 15000},
            ],
            "actual_takeoff": "2026-08-01T12:48:00Z",
            "actual_landing": "2026-08-01T20:13:00Z",
            "diverted": False,
        },
        {"result_count": 1, "provider": "flightradar24"},
    ),
    (
        "weather.rain_radar",
        {"location": "Berlin", "radius_km": 5},
        {
            "provider": "Bright Sky",
            "location": {"name": "Berlin"},
            "summary": {
                "rain_expected": True,
                "in_10_min": "Light rain is expected.",
                "next_2_hours": "Rain passes within an hour.",
                "peak_intensity": "light",
                "preview_frame_id": "frame-1",
            },
            "timeline": [
                {"frame_id": "frame-1", "timestamp": "2026-10-01T12:00:00Z", "rain_expected": True},
                {"frame_id": "frame-2", "timestamp": "2026-10-01T12:10:00Z", "rain_expected": False},
            ],
            "coverage": {"status": "available"},
            "rendering": {"mode": "frames", "frame_count": 2},
        },
        {"result_count": 2},
    ),
    (
        "math.calculate",
        {"expression": "2 + 2"},
        {
            "expression": "2 + 2",
            "result": "4",
            "result_numeric": 4.0,
            "mode": "auto",
        },
        {"result": "4", "result_count": 1},
    ),
    (
        "web.search",
        {"requests": [{"query": "OpenMates"}]},
        {
            "provider": "Brave",
            "results": [{
                "id": "request-1",
                "results": [{
                    "title": "OpenMates",
                    "url": "https://openmates.org/?utm_source=test",
                    "description": "Private AI assistant",
                    "page_age": "today",
                }],
            }],
        },
        {"result_count": 1, "provider": "Brave"},
    ),
    (
        "web.read",
        {"requests": [{"url": "https://example.org/one"}, {"url": "https://example.org/two"}]},
        {
            "provider": "Firecrawl",
            "results": [
                {"id": "request-1", "results": [{"url": "https://example.org/one", "title": "First", "markdown": "First page text."}]},
                {"id": "request-2", "results": [{"url": "https://example.org/two", "title": "Second", "markdown": "Second page text."}]},
            ],
        },
        {"result_count": 2, "source_url": "", "read_status": "usable"},
    ),
    (
        "events.search",
        {"requests": [{"query": "concerts", "location": "Berlin"}]},
        {
            "provider": "auto",
            "warnings": ["One provider was unavailable"],
            "results": [{
                "id": "request-1",
                "results": [{
                    "id": "event-1",
                    "title": "Concert",
                    "url": "https://example.org/concert",
                    "date_start": "2026-10-03T19:00:00+02:00",
                    "location": "Berlin",
                }],
            }],
        },
        {"result_count": 1, "warnings": ["One provider was unavailable"], "partial": True},
    ),
    (
        "weather.forecast",
        {"location": "Berlin", "days": 1},
        {
            "provider": "Open-Meteo",
            "location": {"name": "Berlin"},
            "days_requested": 1,
            "start_date": "2026-10-01",
            "end_date": "2026-10-01",
            "results": [{
                "date": "2026-10-01",
                "title": "Thursday",
                "temperature_min_c": 8.0,
                "temperature_max_c": 16.0,
                "precipitation_probability_max_pct": 60.0,
                "hourly": [{
                    "timestamp": "2026-10-01T12:00:00+02:00",
                    "precipitation_probability_pct": 60.0,
                    "precipitation_mm": 0.5,
                }],
            }],
        },
        {"result_count": 1, "rain_probability": 60.0, "max_temperature_c": 16.0},
    ),
    (
        "finance.check_accounts",
        {"start_date": "2026-09-01", "end_date": "2026-09-30"},
        {
            "account_count": 2,
            "transaction_count": 14,
            "overview": {"summaries": {"income_total": 1200.0, "expense_total": 300.0}},
        },
        {"account_count": 2, "transaction_count": 14},
    ),
    (
        "openmates.share-usecase",
        {"title": "Private planning"},
        {"success": True, "message": "Use case shared"},
        {"success": True, "message": "Use case shared"},
    ),
)


def _declared_schema(capability_id: str) -> dict[str, Any]:
    capability = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry()).get_capability(capability_id)
    if capability_id == "openmates.share-usecase":
        # The approval:always skill has no per-run approval path in the runtime.
        # Its response contract remains useful to check while it is excluded.
        assert not capability.enabled
        assert capability.reason == "WORKFLOW_RUNTIME_UNSUPPORTED"
    else:
        assert capability.enabled, f"Fixture skill {capability_id} must be enabled"
    schema = capability.metadata.get("output_schema")
    assert isinstance(schema, dict)
    return schema


@pytest.mark.parametrize(
    ("capability_id", "skill_request", "raw", "expected"),
    _SKILL_FIXTURES,
    ids=[fixture[0] for fixture in _SKILL_FIXTURES],
)
# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_skill_output_values_match_declared_schema_and_preserve_useful_data(
    capability_id: str,
    skill_request: dict[str, Any],
    raw: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    app_id, skill_id = capability_id.split(".", 1)
    output = _normalize_skill_output(app_id, skill_id, skill_request, raw)

    for field, value in expected.items():
        assert field in output, f"{capability_id} dropped useful {field}"
        assert output[field] == value

    if capability_id == "code.get_docs":
        assert output["results"][0]["documentation"] == raw["documentation"]
        assert output["results"][0]["library"] == raw["library"]
    elif capability_id == "openmates.get-docs":
        assert all(output["results"][0][field] == value for field, value in raw.items())
    elif capability_id == "travel.get_flight":
        assert all(output["results"][0][field] == value for field, value in raw.items())
        assert output["results"][0]["tracks"] == raw["tracks"]
    elif capability_id == "weather.rain_radar":
        assert isinstance(output["summary"], str) and output["summary"]
        assert output["results"] == raw["timeline"]
    elif capability_id == "web.search":
        assert output["results"][0]["title"] == "OpenMates"
        assert output["results"][0]["canonical_url"] == "https://openmates.org/"
    elif capability_id == "web.read":
        assert "Source: https://example.org/one" in output["text"]
        assert "Source: https://example.org/two" in output["text"]
        assert "First page text." in output["text"]
        assert "Second page text." in output["text"]
        assert [page["markdown"] for page in output["results"]] == ["First page text.", "Second page text."]
    elif capability_id == "events.search":
        assert output["events"] == output["results"]
        assert output["results"][0]["source_id"] == "event-1"
    elif capability_id == "weather.forecast":
        assert output["forecast_day"] == raw["results"][0]
        assert output["forecast_days"] == raw["results"]
    elif capability_id == "finance.check_accounts":
        assert output["overview"] == raw["overview"]

    schema = _declared_schema(capability_id)
    errors = sorted(Draft202012Validator(schema).iter_errors(output), key=lambda error: list(map(str, error.path)))
    assert not errors, f"{capability_id} output violates declared schema: " + "; ".join(
        f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors
    )


@pytest.mark.parametrize(
    ("capability_id", "raw", "expected_task_ids", "expected_embed_ids"),
    (
        ("images.generate", {"status": "processing", "task_id": "image-task", "embed_id": "image-placeholder"}, ["image-task"], ["image-placeholder"]),
        ("music.generate", {"status": "processing", "task_ids": ["music-task-1", "music-task-2"], "embed_ids": ["music-placeholder-1", "music-placeholder-2"]}, ["music-task-1", "music-task-2"], ["music-placeholder-1", "music-placeholder-2"]),
        ("videos.create", {"status": "rendering", "task_id": "render-task", "embed_id": "video-placeholder", "render_id": "render-1"}, ["render-task"], ["video-placeholder"]),
    ),
)
# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_processing_generation_output_retains_job_and_placeholder_identities_without_claiming_completion(
    capability_id: str,
    raw: dict[str, Any],
    expected_task_ids: list[str],
    expected_embed_ids: list[str],
) -> None:
    app_id, skill_id = capability_id.split(".", 1)
    output = _normalize_skill_output(app_id, skill_id, {}, raw)

    assert output["task_ids"] == expected_task_ids
    assert output["artifact_ids"] == expected_embed_ids
    assert output["raw"]["status"] in {"processing", "rendering"}
    assert "completed" not in output["summary"].lower()
