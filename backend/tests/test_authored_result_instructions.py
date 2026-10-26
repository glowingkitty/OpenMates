"""Decision-mock proof of relevance and app-metadata authoring admission."""

# contract-test-file: infrastructure

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from backend.apps.ai.processing import jev_preprocessing as jev
from backend.apps.ai.utils.authored_result_fences import get_authoring_definitions
from backend.apps.ai.utils.authored_result_instructions import (
    admitted_authoring_definitions,
    build_authored_result_instructions,
    normalize_authoring_previews,
)
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.python_schemas.app_metadata_schemas import EmbedTypeDefinition


def _apps(*kinds):
    catalog = get_authoring_definitions()
    apps = {}
    for kind in kinds:
        row = catalog[kind]
        embed = EmbedTypeDefinition(
            id=row["backend_type"], category="direct", frontend_type=row["backend_type"],
            backend_type=row["backend_type"],
            authoring={"kind": kind, "schema_id": row["schema_id"]},
        )
        apps.setdefault(row["app_id"], SimpleNamespace(embed_types=[], skills=[])).embed_types.append(embed)
    return apps


def _answer(questions, primary, selected_apps, selected_kinds):
    answers = {}
    for key, question in questions.items():
        if question["type"] == "noul":
            candidate = question.get("instructions", {})
            candidate_id = candidate.get("candidate_id") if isinstance(candidate, dict) else None
            selected = (key.startswith("app_") and candidate_id in selected_apps
                        or key.startswith("authored_") and candidate_id in selected_kinds)
            answers[key] = {"type": "noul", "noul": .99 if selected else .01}
        else:
            choice = {"preview": primary, "language": "en", "temperature": "precise",
                      "topic_shift": "noticeable_shift"}.get(key, next(iter(question["criteria"])))
            answers[key] = {"type": "choice", "choice": choice, "confidence": .99,
                            "probabilities": {value: float(value == choice) for value in question["criteria"]}}
    return DecisionResponse.model_validate({"model": "decision-mock", "answers": answers, "usage": {}})


def test_metadata_retains_authoring_and_rejects_malformed_shape():
    embed = _apps("travel.stay")["travel"].embed_types[0]
    assert embed.model_dump()["authoring"] == {"kind": "travel.stay", "schema_id": "travel.stay"}
    for invalid in ({"kind": "stay"}, {"kind": "travel.stay", "schema_id": ""},
                    {"kind": "travel.stay", "schema_id": "travel.stay", "instruction": "trust me"}):
        with pytest.raises(ValidationError):
            EmbedTypeDefinition(**{**embed.model_dump(), "authoring": invalid})


def test_admission_requires_matching_app_schema_backend_and_explicit_metadata():
    apps = _apps("events.event", "travel.stay")
    assert set(admitted_authoring_definitions(apps)) == {"events.event", "travel.stay"}
    # No skill exists in these apps: admission must not depend on discovery.
    apps["calendar"] = apps.pop("events")
    assert set(admitted_authoring_definitions(apps)) == {"travel.stay"}
    apps["travel"].embed_types[0].authoring["schema_id"] = "events.event"
    assert admitted_authoring_definitions(apps) == {}
    apps = _apps("travel.stay")
    apps["travel"].embed_types[0].backend_type = "event"
    assert admitted_authoring_definitions(apps) == {}
    apps["travel"].embed_types[0].authoring = None
    assert admitted_authoring_definitions(apps) == {}


def test_all_25_registered_admissions_preserve_original_23_and_add_tv():
    apps = {}
    for path in (Path(__file__).resolve().parents[1] / "apps").glob("*/app.yml"):
        config = yaml.safe_load(path.read_text())
        apps[path.parent.name] = SimpleNamespace(
            embed_types=[EmbedTypeDefinition.model_validate(row) for row in config.get("embed_types", [])],
            skills=[],
        )
    admitted = set(admitted_authoring_definitions(apps))
    original = {
        "events.event", "home.listing", "health.appointment", "travel.connection", "travel.stay",
        "maps.place", "fitness.location", "fitness.class", "shopping.product", "jobs.job_result",
        "nutrition.recipe", "code.repo", "web.website", "news.website", "electronics.component",
        "business.company_financial_result", "weather.weather_day", "hosting.hosting_domain",
        "social_media.social_post", "design.icon_result", "images.image_result", "videos.video",
        "models3d.model_result",
    }
    assert len(original) == 23
    assert admitted == original | {"tv.movie", "tv.series"} == set(get_authoring_definitions())
    assert len(admitted) == 25


def test_selected_schema_exactness_aliases_and_legacy_artifact_separation():
    apps = _apps("travel.stay", "events.event", "maps.place", "news.website", "web.website")
    definitions = admitted_authoring_definitions(apps)
    assert normalize_authoring_previews(
        ["hotel", "events-event", "events.event", "calendar_event", "website", "document"], definitions,
    ) == ["travel.stay", "events.event"]
    prompt = build_authored_result_instructions(["hotel", "events.event"], apps)
    assert prompt is not None
    schema = json.loads(prompt.split("Selected result schema:\n", 1)[1])
    assert {row["properties"]["kind"]["const"] for row in schema["properties"]["items"]["items"]["oneOf"]} == {
        "travel.stay", "events.event",
    }
    assert "maps.place" not in prompt and "news.website" not in prompt
    assert prompt.count("Selected result schema:") == 1
    assert "Never invent embed refs" in prompt and "draft only" in prompt
    assert build_authored_result_instructions(["calendar_event", "document", "website"], apps) is None
    assert build_authored_result_instructions(["travel.stay"], apps, presentation_only=True) is None
    assert build_authored_result_instructions(["weather.weather_day"], apps) is None
    assert build_authored_result_instructions([], apps) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt,primary,selected_apps,selected_kinds", [
    ("Compare the supplied hotels and conference dates as cards.", "travel.stay", ["travel", "events"],
     ["travel.stay", "events.event"]),
    ("Turn my supplied itinerary and hotels into cards.", "travel.connection", ["travel"],
     ["travel.connection", "travel.stay"]),
    ("Create a calendar event and show the supplied hotel as a card.", "calendar_event", ["travel"],
     ["travel.stay"]),
    ("Hello, how are you?", "none", [], []),
    ("Explain this Python function.", "code", [], []),
])
async def test_public_and_detailed_decisions_gate_multiple_kinds_without_search_skills(
    monkeypatch, prompt, primary, selected_apps, selected_kinds,
):
    apps = _apps("travel.stay", "travel.connection", "events.event", "maps.place")
    definitions = admitted_authoring_definitions(apps)
    calls = []

    async def evaluate(**kwargs):
        assert kwargs["state"]["messages"][-1]["content"] == prompt
        calls.append(copy.deepcopy(kwargs))
        return _answer(kwargs["questions"], primary, selected_apps, selected_kinds)

    monkeypatch.setattr(jev, "_evaluate_preprocessing_questions", evaluate)
    result = await jev.decide_preprocessing_with_jev(
        model_id="decision-mock", secrets_manager=None,
        message_history=[{"role": "user", "content": prompt}],
        topic_areas=["general_misc: General"], available_apps=list(apps), available_skills=[],
        available_focus_modes=[], available_settings_and_memories={}, recent_skill_activity=[],
        conversation_summary=None, previous_category=None, is_first_message=False,
        authoring_definitions=definitions, candidate_discovery_complete=True,
    )
    expected = list(dict.fromkeys(([] if primary == "none" else [primary]) + selected_kinds))
    assert set(result["relevant_embedded_previews"]) == set(expected)
    assert result["relevant_app_skills"] == []
    assert "weather.weather_day" not in calls[0]["questions"]["preview"]["criteria"]
    app_hints = [question["instructions"]["candidate_description"]
                 for key, question in calls[0]["questions"].items() if key.startswith("app_")]
    assert any("travel.stay" in hint and "independent of search availability" in hint for hint in app_hints)
    detailed_authored = [key for call in calls[1:] for key in call["questions"] if key.startswith("authored_")]
    if selected_kinds:
        assert detailed_authored
        assert len(calls) == 2
    else:
        assert detailed_authored == []
        assert len(calls) == 1  # Complete public routing retains the zero-question fast path.


def test_public_criteria_and_catalogue_remain_compact_without_detail_schemas():
    definitions = get_authoring_definitions()
    questions = jev._public_decision_questions(False, definitions)
    assert all(kind in questions["preview"]["criteria"] for kind in definitions)
    assert len(json.dumps(questions)) < 12_000
    assert "details_schema" not in json.dumps(questions)
    assert not any("." in key for key in jev._public_decision_questions(False, {})["preview"]["criteria"])


def test_tv_metadata_admits_both_formats_without_any_discovery_skill():
    config = yaml.safe_load((Path(__file__).resolve().parents[1] / "apps/tv/app.yml").read_text())
    assert config.get("skills") == []
    apps = {"tv": SimpleNamespace(
        embed_types=[EmbedTypeDefinition.model_validate(row) for row in config["embed_types"]],
        skills=[],
    )}
    definitions = admitted_authoring_definitions(apps)
    assert set(definitions) == {"tv.movie", "tv.series"}
    assert normalize_authoring_previews(
        ["film", "films", "movies", "movie", "tv_show", "tv shows", "series"], definitions,
    ) == ["tv.movie", "tv.series"]
    assert normalize_authoring_previews(["film", "tv_shows"], {}) == []
    assert build_authored_result_instructions(["document", "code", "travel.stay"], apps) is None
    assert build_authored_result_instructions(["tv.movie"], apps, presentation_only=True) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt,primary,selected_kinds", [
    ("Show the movie facts I supplied as a card.", "tv.movie", ["tv.movie"]),
    ("Make a series card from the supplied season information.", "tv.series", ["tv.series"]),
    ("Compare my supplied films and TV shows as cards.", "tv.movie", ["tv.movie", "tv.series"]),
    ("Explain how a binary search works.", "none", []),
])
async def test_tv_relevance_selects_only_matching_movie_and_series_schemas_without_skills(
    monkeypatch, prompt, primary, selected_kinds,
):
    apps = _apps("tv.movie", "tv.series", "travel.stay")
    definitions = admitted_authoring_definitions(apps)
    calls = []

    async def evaluate(**kwargs):
        assert kwargs["state"]["messages"][-1]["content"] == prompt
        calls.append(copy.deepcopy(kwargs))
        return _answer(kwargs["questions"], primary, ["tv"] if selected_kinds else [], selected_kinds)

    monkeypatch.setattr(jev, "_evaluate_preprocessing_questions", evaluate)
    result = await jev.decide_preprocessing_with_jev(
        model_id="decision-mock", secrets_manager=None,
        message_history=[{"role": "user", "content": prompt}],
        topic_areas=["general_misc: General"], available_apps=list(apps), available_skills=[],
        available_focus_modes=[], available_settings_and_memories={}, recent_skill_activity=[],
        conversation_summary=None, previous_category=None, is_first_message=False,
        authoring_definitions=definitions, candidate_discovery_complete=True,
    )
    assert set(result["relevant_embedded_previews"]) == set(selected_kinds)
    assert result["relevant_app_skills"] == []
    criteria = calls[0]["questions"]["preview"]["criteria"]
    assert {"tv.movie", "tv.series"}.issubset(criteria)
    guidance = build_authored_result_instructions(result["relevant_embedded_previews"], apps)
    if selected_kinds:
        schema = json.loads(guidance.split("Selected result schema:\n", 1)[1])
        assert {variant["properties"]["kind"]["const"]
                for variant in schema["properties"]["items"]["items"]["oneOf"]} == set(selected_kinds)
        assert "travel.stay" not in guidance
        assert len(calls) == 2
        assert {question["instructions"]["candidate_id"] for key, question in calls[1]["questions"].items()
                if key.startswith("authored_")} == {"tv.movie", "tv.series"}
    else:
        assert guidance is None
        assert len(calls) == 1
