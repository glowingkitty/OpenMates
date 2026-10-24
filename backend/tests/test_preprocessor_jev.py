"""Focused mapping tests for Jev foreground preprocessing."""

# contract-test-file: infrastructure

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import jev_preprocessing
from backend.apps.ai.processing import preprocessor
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.processing.preprocessor import (
    PreprocessingResult, _latest_user_text_from_history, _selected_apps_with_skill_owners,
)
from backend.shared.providers.typesafe.models import DecisionResponse


def test_routing_catalogue_keeps_providers_from_every_skill_before_hint_truncation():
    skills = []
    for skill_id, provider in (("locations", "Venue Network"), ("trainers", "Trainer Network"),
                               ("search_classes", "Activity Network")):
        skill = SimpleNamespace(id=skill_id, preprocessor_hint="Find matching public activities. " + "x" * 500,
                                providers=[SimpleNamespace(name="internal", display_name=provider)])
        skills.append(preprocessor._skill_routing_candidate("fitness", skill))
    catalogue = jev_preprocessing._app_catalogue(["fitness"], skills)
    assert len(catalogue) == 1
    assert all(provider in catalogue[0] for provider in ("Venue Network", "Trainer Network", "Activity Network"))
    assert "search classes" in catalogue[0]
    assert len(catalogue[0]) <= 500
    assert "internal" not in catalogue[0]


def test_provider_correction_keeps_preceding_activity_and_provider_brand():
    history = [
        {"role": "user", "content": "Show me capoeira classes on OpenSports in Berlin."},
        {"role": "assistant", "content": "Here are some general web pages."},
        {"role": "user", "content": "activity network"},
        {"role": "assistant", "content": "A response being drafted must not influence routing."},
    ]
    assert jev_preprocessing._messages(history) == history[:3]
    candidate = preprocessor._skill_routing_candidate("fitness", SimpleNamespace(
        id="search_classes", preprocessor_hint="Find dated fitness classes.",
        providers=[SimpleNamespace(name="Activity Network", display_name=None)],
    ))
    assert "Activity Network" in candidate
    assert "Find dated fitness classes" in candidate
    assert "Activity Network" in jev_preprocessing._app_catalogue(["fitness"], [candidate])[0]


# contract-test: direct surface=rest_api assertions=ai-model-routing.tiers.conservative-three-way,ai-model-routing.defaults.google-tier-profiles
@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_model", [False, True])
@pytest.mark.parametrize("tier,model,level", [
    ("low", "inception/mercury-3", "MEDIUM"),
    ("medium", "google/gemini-3.8-flash", "MEDIUM"),
    ("high", "google/gemini-3.8-flash", "HIGH"),
    ("max", "google/gemini-4-argon", "HIGH"),
])
async def test_jev_stage_one_routes_real_selector_and_thinking_profile(monkeypatch, tier, model, level, explicit_model):
    import yaml
    providers = Path(__file__).resolve().parents[1] / "providers"
    catalog = {provider: yaml.safe_load((providers / f"{provider}.yml").read_text()) for provider in ("inception", "google")}
    def model_config(provider, model_id):
        return next((entry for entry in catalog[provider]["models"] if entry["id"] == model_id), None)
    monkeypatch.setattr(preprocessor, "config_manager", SimpleNamespace(
        get_provider_config=lambda provider: catalog.get(provider),
        get_model_pricing=model_config,
        get_model_display_name=lambda model, _: model,
    ))
    monkeypatch.setattr(preprocessor, "is_provider_healthy", AsyncMock(return_value=True))
    questions = jev_preprocessing._early_routing_questions(["general_misc: General"], False)
    questions.update(jev_preprocessing._public_decision_questions(False))
    assert set(questions["complexity"]["criteria"]) == {"low", "medium", "high", "max"}
    response = _routing_answer(questions)
    # Independent effort must not change tier selection or its profile provenance.
    response.answers["reasoning_level"].choice = "extra_high"
    response.answers["complexity"].choice = tier
    response.answers["complexity"].probabilities = {
        value: float(value == tier) for value in questions["complexity"]["criteria"]
    }
    decisions = jev_preprocessing._validated_early_decisions(
        response, ["general_misc: General"], False, False,
    )
    assert decisions is not None
    assert decisions["reasoning_level"] == "extra_high"
    leaderboard_tasks = ModuleType("backend.core.api.app.tasks.leaderboard_tasks")
    leaderboard_tasks.get_leaderboard_data = AsyncMock(return_value=None)
    monkeypatch.setitem(sys.modules, leaderboard_tasks.__name__, leaderboard_tasks)
    request = AskSkillRequest(
        chat_id="routing-test", message_id="routing-message", user_id="routing-user",
        user_id_hash="routing-user-hash", message_history=[
            {"role": "user", "content": "Help with this request", "created_at": 1},
        ], user_preferences={},
    )
    selected = await preprocessor._select_main_model(
        decisions, request, SimpleNamespace(enable_auto_model_selection=True),
        preprocessor.UserOverrides(model_id="google/gemini-4-argon") if explicit_model else None,
        "routing-test",
    )
    assert selected["complexity_val"] == tier
    assert selected["selected_llm_for_main_id"] == ("google/gemini-4-argon" if explicit_model else model)
    assert selected["selected_llm_thinking_level"] == (None if explicit_model else level)
    assert selected["model_override_applied"] is explicit_model
    assert ("User override" if explicit_model else "Selected configured") in selected["model_selection_reason"]


def test_current_app_catalogue_and_public_questions_fit_one_jev_batch():
    app_ids = [path.parent.name for path in (Path(__file__).resolve().parents[1] / "apps").glob("*/app.yml")]
    assert app_ids
    questions = jev_preprocessing._early_routing_questions(
        [f"topic_{index}: Topic {index}" for index in range(60)], False)
    questions.update(jev_preprocessing._public_decision_questions(True))
    jev_preprocessing._add_multi_select_questions(
        questions, "app", jev_preprocessing._app_catalogue(
            app_ids, [f"{app_id}-example: " + "x" * 500 for app_id in app_ids]), "Relevant app?",
    )
    state = {"messages": [{"role": "user", "content": "Help me."}]}
    batches = jev_preprocessing._question_batches(state, questions)
    assert len(batches) == 1
    assert len(batches[0]) <= 160
    assert len(json.dumps({"state": state, "questions": batches[0]}, ensure_ascii=False)) <= 120_000


# contract-test: supporting surface=rest_api assertions=ai-model-routing.reasoning.preprocessor-recommendation
@pytest.mark.asyncio
@pytest.mark.parametrize("detailed", [False, True])
@pytest.mark.parametrize("effort", ["low", "medium", "high", "extra_high", None, "invalid"])
async def test_optional_effort_survives_staged_routing_without_extra_calls(monkeypatch, detailed, effort):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            assert "reasoning_level" not in kwargs["questions"]
        response = _routing_answer(kwargs["questions"])
        if detailed:
            for key, answer in response.answers.items():
                if key.startswith("app_"):
                    answer.noul = .95
        if effort is None:
            response.answers.pop("reasoning_level", None)
        elif "reasoning_level" in response.answers:
            response.answers["reasoning_level"].choice = effort
        return response

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "Help me"}],
        topic_areas=["general_misc: General"], available_apps=["web"] if detailed else [],
        available_skills=["web-search: Search"] if detailed else [], available_focus_modes=[],
        available_settings_and_memories={}, recent_skill_activity=[], conversation_summary=None,
        previous_category=None, is_first_message=False, candidate_discovery_complete=True,
    )
    expected = None if effort in {None, "invalid"} else effort
    assert result["reasoning_level"] == expected
    assert result["complexity"] == "low"
    assert len(calls) == (2 if detailed else 1)
    assert await preprocessor._recover_jev_preprocessing(
        preprocessor.LLMPreprocessingCallResult(arguments=result), task_id="valid-optional-effort",
    ) is not None


# contract-test: supporting surface=rest_api assertions=ai-model-routing.reasoning.preprocessor-recommendation
@pytest.mark.parametrize("raw,expected", [
    ("low", "LOW"), ("medium", "MEDIUM"), ("high", "HIGH"), ("extra_high", "EXTRA_HIGH"),
    (None, None), ("max", None), ([], None), ({}, None), (42, None),
])
def test_recommendation_is_optional_canonical_and_survives_serialized_continuation(raw, expected):
    recommendation = preprocessor._canonical_requested_reasoning_level(raw)
    assert recommendation == expected
    result = PreprocessingResult(requested_reasoning_level=recommendation,
                                 selected_main_llm_thinking_level="MEDIUM")
    resumed = PreprocessingResult.model_validate_json(result.model_dump_json())
    assert resumed.requested_reasoning_level == expected
    assert resumed.selected_main_llm_thinking_level == "MEDIUM"


def test_generative_recovery_effort_schema_remains_optional():
    import yaml
    schema = yaml.safe_load((Path(__file__).resolve().parents[1] / "apps/ai/base_instructions.yml").read_text())
    parameters = schema["preprocess_request_tool"]["function"]["parameters"]
    assert parameters["properties"]["reasoning_level"]["enum"] == ["low", "medium", "high", "extra_high"]
    assert "reasoning_level" not in parameters["required"]


def _routing_answer(questions, *, missing=(), public_harm=.05):
    answers = {}
    for key, question in questions.items():
        if key in missing:
            continue
        if question["type"] == "noul":
            value = public_harm if key == "harmful" else (.75 if key == "misuse" else
                    .95 if key in {"enable_subchats", "model_llm"} else .05)
            answers[key] = {"type": "noul", "noul": value}
        else:
            choice = {"temperature": "creative", "language": "de", "preview": "document",
                      "icon": "code"}.get(key, next(iter(question["criteria"])))
            answers[key] = {"type": "choice", "choice": choice, "confidence": .99,
                            "probabilities": {candidate: float(candidate == choice)
                                              for candidate in question["criteria"]}}
    return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_complete_public_routing_skips_empty_detailed_provider_call(monkeypatch):
    calls = []
    discovery = {"complete": False}

    async def evaluate(**kwargs):
        calls.append(kwargs)
        return _routing_answer(kwargs["questions"], public_harm=.81)

    async def load_rules(app_ids):
        assert app_ids == [] and len(calls) == 1
        discovery["complete"] = True
        return []

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "Hallo"}],
        topic_areas=["general_misc: General"], available_apps=[], available_skills=[],
        available_focus_modes=[], available_settings_and_memories={},
        recent_skill_activity=[], conversation_summary=None, previous_category=None,
        is_first_message=True, available_rules_loader=load_rules,
        candidate_discovery_complete=lambda: discovery["complete"],
    )
    assert len(calls) == 1
    assert result["selected_app_ids"] == []
    assert result["relevant_app_skills"] == result["relevant_focus_modes"] == []
    assert result["relevant_rules"] == result["relevant_workflows"] == []
    assert result["harmful_or_illegal"] == 8.1
    assert result["misuse_risk"] == 8
    assert result["output_language"] == "de"
    assert result["llm_response_temp"] == .8
    assert result["enable_subchats"] is True
    assert result["ai_model_topics"] == ["llm"]
    assert result["relevant_embedded_previews"] == ["document"]
    assert result["icon_names"] == ["code"]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing,complete", [("harmful", True), (None, False)])
async def test_missing_public_answer_or_uncertain_discovery_asks_full_detail(monkeypatch, missing, complete):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        omitted = (missing,) if len(calls) == 1 and missing else ()
        return _routing_answer(kwargs["questions"], missing=omitted, public_harm=.81)

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "Hallo"}],
        topic_areas=["general_misc: General"], available_apps=[], available_skills=[],
        available_focus_modes=[], available_settings_and_memories={},
        recent_skill_activity=[], conversation_summary=None, previous_category=None,
        is_first_message=False, candidate_discovery_complete=complete,
    )
    assert len(calls) == 2
    assert set(jev_preprocessing._public_decision_questions(False)) <= set(calls[1]["questions"])
    assert result["harmful_or_illegal"] == 8.1


@pytest.mark.asyncio
async def test_malformed_cached_public_decision_does_not_skip_safety(monkeypatch):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        return _routing_answer(kwargs["questions"], public_harm=.91)

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "Hello"}],
        topic_areas=["general_misc: General"], available_apps=[], available_skills=[],
        available_focus_modes=[], available_settings_and_memories={},
        recent_skill_activity=[], conversation_summary=None, previous_category=None,
        is_first_message=False, selected_app_ids=[], candidate_discovery_complete=True,
        early_decisions={"complexity": "simple", "task_area": "general",
                         "user_unhappy": False, "china_model_sensitive": False,
                         "topic_area": "general_misc", "topic_shift": "same_topic",
                         "public_decisions": {"temperature": [], "harmful_or_illegal": 0}},
    )
    assert len(calls) == 1
    assert set(jev_preprocessing._public_decision_questions(False)) <= set(calls[0]["questions"])
    assert result["harmful_or_illegal"] == 9.1


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["low", "medium", "high", "max"])
async def test_detailed_decisions_reuse_stage_one_model_and_mate_routing(monkeypatch, tier):
    async def evaluate(**kwargs):
        questions = kwargs["questions"]
        assert {"complexity", "task_area", "user_unhappy", "china_sensitive",
                "topic_area", "topic_shift"}.isdisjoint(questions)
        answers = {}
        for key, question in questions.items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.0}
            else:
                choice = next(iter(question["criteria"]))
                answers[key] = {"type": "choice", "choice": choice, "confidence": 0.99,
                                "probabilities": {candidate: float(candidate == choice)
                                                  for candidate in question["criteria"]}}
        return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "Fix this code"}],
        topic_areas=["software_development: Code"], available_skills=[],
        available_focus_modes=[], available_settings_and_memories=None,
        recent_skill_activity=[], conversation_summary=None, previous_category=None,
        is_first_message=True, selected_app_ids=[],
        early_decisions={"complexity": tier, "task_area": "code",
                         "user_unhappy": True, "china_model_sensitive": True,
                         "topic_area": "software_development", "topic_shift": "noticeable_shift"},
    )
    assert (result["complexity"], result["task_area"], result["topic_area"]) == (
        tier, "code", "software_development",
    )
    assert result["user_unhappy"] and result["china_model_sensitive"]


def test_selected_apps_are_transient_and_fallback_has_no_shortlist():
    assert PreprocessingResult().selected_app_ids is None
    result = PreprocessingResult(selected_app_ids=["news", "web"])
    assert result.selected_app_ids == ["news", "web"]
    assert "selected_app_ids" not in result.model_dump()


def test_final_forced_skill_keeps_its_owning_app_without_erasing_fallback_sentinel():
    apps = ["news", "web", "images", "x", "x-y"]
    assert _selected_apps_with_skill_owners(None, ["images-view"], apps) is None
    assert _selected_apps_with_skill_owners([], ["images-view"], apps) == ["images"]
    assert _selected_apps_with_skill_owners(["news"], ["web-search", "x-y-tool"], apps) == [
        "news", "web", "x-y",
    ]


@pytest.mark.asyncio
async def test_maps_bounded_decisions_without_generating_title(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_state = {}

    async def fake_evaluate(**kwargs):
        captured_state.update(kwargs["state"])
        answers = {}
        for question_id, question in kwargs["questions"].items():
            if question["type"] == "noul":
                probability = 0.9 if question_id in {"app_0", "skill_0", "memory_0", "user_unhappy", "model_llm", "rule_0", "workflow_0"} else 0.05
                answers[question_id] = {"type": "noul", "noul": probability}
            elif question["type"] == "score":
                answers[question_id] = {
                    "type": "score", "score": 0.1,
                    "legend": {str(i): label for i, label in enumerate(question["criteria"])},
                    "probabilities": {str(i): 1.0 if i == 0 else 0.0 for i in range(len(question["criteria"]))},
                    "confidence": 0.99,
                }
            else:
                choices = list(question["criteria"])
                preferred = {
                    "complexity": "low", "task_area": "code", "temperature": "precise",
                    "topic_area": "software_development", "topic_shift": "noticeable_shift",
                    "language": "en", "preview": "code", "icon": "code",
                }.get(question_id, choices[0])
                answers[question_id] = {
                    "type": "choice", "choice": preferred,
                    "probabilities": {choice: 1.0 if choice == preferred else 0.0 for choice in choices},
                    "confidence": 0.99,
                }
        return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})

    monkeypatch.setattr(jev_preprocessing, "evaluate_jev_decisions", fake_evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="typesafe/jev-1.13",
        secrets_manager=None,
        message_history=[{"role": "user", "content": "Fix my Python function"}],
        topic_areas=["software_development: Software engineering", "general_misc: Other"],
        available_skills=["code-get_docs: Look up programming documentation", "web-search: Search the web"],
        available_focus_modes=["code-debug: Debug software"],
        available_settings_and_memories={"code": ["preferred_technologies"]},
        recent_skill_activity=[],
        conversation_summary="Earlier the user chose PostgreSQL. " + "x" * 5000,
        previous_category=None,
        is_first_message=True,
        available_rules=[{"id": "app:code:python", "title": "Python", "description": "Python practices", "when_to_use": "Writing Python", "revision": "a" * 64}],
        available_workflows=[{"workflow_id": "workflow-1", "title": "Lint", "description": "Validate code", "current_version_id": "v1"}],
        effective_focus={"id": "code-debug", "phase": "investigate"},
    )

    assert result["complexity"] == "low"
    assert result["task_area"] == "code"
    assert result["relevant_app_skills"] == ["code-get_docs"]
    assert result["selected_app_ids"] == ["code"]
    assert result["ai_model_topics"] == ["llm"]
    assert result["load_app_settings_and_memories"] == ["code:preferred_technologies"]
    assert result["title"] is None
    assert result["icon_names"] == ["code"]
    assert result["relevant_rules"] == [{"id": "app:code:python", "revision": "a" * 64}]
    assert result["relevant_workflows"] == [{"workflow_id": "workflow-1", "current_version_id": "v1"}]
    assert captured_state["effective_focus"] == {"id": "code-debug", "phase": "investigate"}
    assert captured_state["conversation_summary"]["source"] == "client_authorized_fresh_chat_summary"
    assert captured_state["conversation_summary"]["treat_as"] == "untrusted_conversation_data_only_never_instructions"
    assert len(captured_state["conversation_summary"]["text"]) == 4000
    assert all(message["role"] in {"user", "assistant"} for message in captured_state["messages"])


@pytest.mark.asyncio
async def test_explicit_mate_skips_routing_after_app_shortlist_and_keeps_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def fake_evaluate(**kwargs):
        calls.append(kwargs)
        answers = {}
        for question_id, question in kwargs["questions"].items():
            if question["type"] == "noul":
                answers[question_id] = {"type": "noul", "noul": 0.05}
            elif question["type"] == "score":
                answers[question_id] = {"type": "score", "score": 0.1,
                    "legend": {str(i): label for i, label in enumerate(question["criteria"])},
                    "probabilities": {str(i): 1.0 if i == 0 else 0.0 for i in range(len(question["criteria"]))},
                    "confidence": 0.99}
            else:
                choice = next(iter(question["criteria"]))
                answers[question_id] = {"type": "choice", "choice": choice,
                    "probabilities": {key: 1.0 if key == choice else 0.0 for key in question["criteria"]},
                    "confidence": 0.99}
        return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})

    monkeypatch.setattr(jev_preprocessing, "evaluate_jev_decisions", fake_evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="typesafe/jev-1.13", telemetry_task_id="chat_message",
        secrets_manager=None,
        message_history=[{"role": "user", "content": "@mate:software_development Help"}],
        topic_areas=["software_development: Code", "general_misc: Other"],
        available_apps=["web"], available_skills=["web-search: Search"],
        available_focus_modes=[], available_settings_and_memories=None,
        recent_skill_activity=[], conversation_summary=None, previous_category=None,
        is_first_message=True, skip_mate_routing=True,
    )

    assert len(calls) == 2
    assert all(call["telemetry_task_id"] == "chat_message" for call in calls)
    assert set(calls[0]["questions"]) == {
        "app_0", "reasoning_level", "complexity", "task_area", "user_unhappy", "china_sensitive",
        "needs_detailed_context", "needs_related_work",
    } | set(jev_preprocessing._public_decision_questions(True))
    stage_two_questions = set(calls[1]["questions"])
    assert {"topic_area", "topic_shift"}.isdisjoint(stage_two_questions)
    assert {"harmful", "misuse", "language", "icon"} <= stage_two_questions
    assert {"task_area", "complexity"}.isdisjoint(stage_two_questions)
    assert result["topic_area"] is None
    assert result["topic_shift"] is None


@pytest.mark.asyncio
async def test_app_shortlist_selects_multiple_apps_without_unrelated_stage_two_catalogues(monkeypatch):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        answers = {}
        for question_id, question in kwargs["questions"].items():
            if question["type"] == "noul":
                candidate = question.get("instructions", {}).get("candidate_id") if isinstance(question.get("instructions"), dict) else None
                selected = candidate in {"news", "web", "images", "news-search", "web-search", "images-search", "news-guide"}
                answers[question_id] = {"type": "noul", "noul": .95 if selected else .05}
            else:
                choices = list(question["criteria"])
                choice = choices[0]
                answers[question_id] = {"type": "choice", "choice": choice,
                    "probabilities": {value: 1.0 if value == choice else 0.0 for value in choices},
                    "confidence": .99}
        return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    loaded_rule_apps = []

    async def load_scoped_rules(app_ids):
        assert len(calls) == 1  # Stage one finished before optional Rule discovery.
        loaded_rule_apps.append(app_ids)
        return [
            {"id": "news-guide", "source": "app", "app_id": "news",
             "title": "News guide", "revision": "v1"},
            {"id": "travel-guide", "source": "app", "app_id": "travel",
             "title": "PRIVATE-UNRELATED-RULE", "revision": "v1"},
        ]

    skills = [
        "news-search: Search for latest news articles and announcements.",
        "web-search: Search the web for current source pages.",
        "images-search: Search for relevant images and photographs.",
        "travel-stays: Find hotels. PRIVATE-UNRELATED-SKILL " + "x" * 2500,
    ]
    kwargs = dict(model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "Find the latest OpenAI news with sources and photos"}],
        topic_areas=["general_misc: General"], available_apps=["news", "web", "images", "travel"],
        available_skills=skills,
        available_focus_modes=["news-understand: Analyze news", "travel-plan: PRIVATE-UNRELATED-FOCUS"],
        available_settings_and_memories={"news": ["topics"], "travel": ["PRIVATE-UNRELATED-MEMORY"]},
        recent_skill_activity=[], conversation_summary=None, previous_category=None,
        is_first_message=False,
        available_rules_loader=load_scoped_rules,
    )
    result = await jev_preprocessing.decide_preprocessing_with_jev(**kwargs)
    assert result["selected_app_ids"] == ["news", "web", "images"]
    assert loaded_rule_apps == [["news", "web", "images"]]
    assert result["relevant_rules"] == [{"id": "news-guide", "revision": "v1"}]
    assert result["relevant_app_skills"] == ["news-search", "web-search", "images-search"]
    assert set(calls[0]["questions"]) == {
        "app_0", "app_1", "app_2", "app_3", "reasoning_level", "complexity", "task_area",
        "user_unhappy", "china_sensitive", "topic_area", "topic_shift",
        "needs_detailed_context", "needs_related_work",
    } | set(jev_preprocessing._public_decision_questions(False))
    assert {"complexity", "task_area", "topic_area", "topic_shift"}.isdisjoint(calls[1]["questions"])
    stage_one = repr(calls[0])
    stage_two = repr(calls[1])
    assert "PRIVATE-UNRELATED" not in stage_one
    assert "PRIVATE-UNRELATED" not in stage_two
    assert "harmful" in calls[0]["questions"] and "language" in calls[0]["questions"]
    assert set(jev_preprocessing._public_decision_questions(False)).isdisjoint(calls[1]["questions"])
    assert len(repr(jev_preprocessing._app_catalogue(kwargs["available_apps"], skills))) < len(repr(skills))
    stage_two_skill_questions = [question for key, question in calls[1]["questions"].items()
                                 if key.startswith("skill_")]
    assert len(repr(stage_two_skill_questions)) < len(repr(skills))


@pytest.mark.asyncio
async def test_forced_app_and_authorized_project_context_are_scoped(monkeypatch):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        answers = {}
        for question_id, question in kwargs["questions"].items():
            if question["type"] == "noul":
                answers[question_id] = {"type": "noul", "noul": .05}
            else:
                choices = list(question["criteria"])
                answers[question_id] = {"type": "choice", "choice": choices[0],
                    "probabilities": {value: 1.0 if value == choices[0] else 0.0 for value in choices},
                    "confidence": .99}
        return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    kwargs = dict(model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "@skill:code:get_docs Check project"}],
        topic_areas=["general_misc: General"], available_apps=["code", "web", "project"],
        available_skills=["code-get_docs: Get docs", "web-search: Search web"],
        available_focus_modes=["project-focus:project-1:private: PRIVATE-SPECIALIST", "project-project-1: Public project candidate"],
        available_settings_and_memories={"code": ["preferences"]},
        recent_skill_activity=[], conversation_summary=None, previous_category=None,
        is_first_message=False,
        available_rules=[{"id": "private", "source": "project", "project_id": "project-1",
                          "title": "PRIVATE-RULE", "revision": "v1"}],
        forced_app_ids=["code", "project"],
    )
    result = await jev_preprocessing.decide_preprocessing_with_jev(**kwargs)
    assert result["selected_app_ids"] == ["code", "project"]
    assert "PRIVATE-" not in repr(calls[0]) + repr(calls[1])
    assert "project-project-1" in repr(calls[1])
    calls.clear()
    await jev_preprocessing.decide_preprocessing_with_jev(
        **{**kwargs, "selected_app_ids": result["selected_app_ids"],
           "authorized_project_id": "project-1"})
    assert len(calls) == 1  # Reuse the app shortlist, refresh stage-two decisions.
    assert "PRIVATE-SPECIALIST" in repr(calls[0])
    assert "PRIVATE-RULE" in repr(calls[0])


@pytest.mark.asyncio
async def test_projects_create_stays_available_with_independent_public_project_candidate(monkeypatch):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        answers = {}
        for question_id, question in kwargs["questions"].items():
            if question["type"] == "noul":
                candidate = question.get("instructions", {}).get("candidate_id") if isinstance(question.get("instructions"), dict) else None
                answers[question_id] = {"type": "noul", "noul": .95 if candidate in {
                    "projects", "projects-create", "project-p1",
                } else .05}
            else:
                choices = list(question["criteria"])
                answers[question_id] = {"type": "choice", "choice": choices[0],
                    "probabilities": {value: 1.0 if value == choices[0] else 0.0 for value in choices},
                    "confidence": .99}
        return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "Create a new project for my garden plans"}],
        topic_areas=["general_misc: General"], available_apps=["projects", "web"],
        available_skills=["projects-create: Request creation of a user-visible project.",
                          "web-search: Search source pages"],
        available_focus_modes=["project-p1: Existing Project candidate, cancellable Focus consent"],
        available_settings_and_memories={}, recent_skill_activity=[], conversation_summary=None,
        previous_category=None, is_first_message=False,
    )
    assert result["selected_app_ids"] == ["projects"]
    assert result["relevant_app_skills"] == ["projects-create"]
    assert result["relevant_focus_modes"] == ["project-p1"]
    assert "Existing Project candidate" not in repr(calls[0])
    assert "Existing Project candidate" in repr(calls[1])


@pytest.mark.asyncio
async def test_project_consent_refresh_keeps_readme_request_as_stage_two_intent(monkeypatch):
    calls = []
    history = [
        {"role": "user", "sender_name": "user", "content": "Read the README in my Project"},
        {"role": "assistant", "content": "Requesting Project Focus access."},
        *[{"role": "user", "sender_name": "async_tool_result",
           "content": f"Access granted for Project Focus result {index}"} for index in range(9)],
    ]
    assert _latest_user_text_from_history(history) == "Read the README in my Project"

    async def evaluate(**kwargs):
        calls.append(kwargs)
        answers = {}
        for question_id, question in kwargs["questions"].items():
            if question["type"] == "noul":
                candidate = question.get("instructions", {}).get("candidate_id") if isinstance(question.get("instructions"), dict) else None
                answers[question_id] = {"type": "noul", "noul": .95 if candidate in {
                    "project-focus:p1:readme", "project-readme-rule",
                } else .05}
            else:
                choices = list(question["criteria"])
                answers[question_id] = {"type": "choice", "choice": choices[0],
                    "probabilities": {value: 1.0 if value == choices[0] else 0.0 for value in choices},
                    "confidence": .99}
        return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})

    async def load_rules(selected):
        assert selected == ["projects"]
        return [{"id": "project-readme-rule", "source": "project", "project_id": "p1",
                 "title": "README reading guide", "revision": "v1"}]

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None, message_history=history,
        topic_areas=["general_misc: General"], available_apps=["projects"],
        selected_app_ids=["projects"], available_skills=["projects-create: Create project"],
        available_focus_modes=["project-focus:p1:readme: README specialist"],
        available_settings_and_memories={}, recent_skill_activity=[],
        conversation_summary=None, previous_category=None, is_first_message=False,
        authorized_project_id="p1", available_rules_loader=load_rules,
    )
    assert len(calls) == 1  # Reuse stage one after Focus consent.
    assert calls[0]["state"]["messages"][-1]["content"] == "Read the README in my Project"
    assert "Access granted" not in repr(calls[0]["state"])
    assert result["relevant_app_skills"] == []
    assert result["relevant_focus_modes"] == ["project-focus:p1:readme"]
    assert result["relevant_rules"] == [{"id": "project-readme-rule", "revision": "v1"}]


@pytest.mark.asyncio
async def test_large_catalog_batches_all_candidates_and_retains_required_decisions(monkeypatch):
    from backend.shared.providers.typesafe.client import JevDecisionClient, MAX_QUESTIONS
    calls = []
    async def evaluate(**kwargs):
        JevDecisionClient._validate_request(kwargs["state"], kwargs["questions"])
        calls.append(kwargs)
        return DecisionResponse(model="jev", answers={key: {"type": "noul", "noul": .9}
            for key in kwargs["questions"]}, usage={"input_tokens": 10, "output_tokens": 2})
    monkeypatch.setattr(jev_preprocessing, "evaluate_jev_decisions", evaluate)
    questions = {"safety": {"type": "noul", "instructions": "Required safety decision"}}
    questions.update({f"focus_{i}": {"type": "noul", "instructions": f"Project candidate {i}"}
                      for i in range(MAX_QUESTIONS * 2)})
    response = await jev_preprocessing._evaluate_preprocessing_questions(state={"request": "Work on my Project"},
        questions=questions, secrets_manager=None, model_id="jev")
    assert len(calls) == 3
    assert set(response.answers) == set(questions)
    assert "safety" in calls[0]["questions"]
    assert all(call["state"] == calls[0]["state"] for call in calls)
    assert response.usage.input_tokens == 30


def test_serialized_budget_batches_long_metadata_without_dropping_ids():
    import json
    from backend.shared.providers.typesafe.client import MAX_SERIALIZED_REQUEST_CHARS
    state = {"messages": [{"role": "user", "content": "x" * 60_000}]}
    questions = {f"rule_{i}": {"type": "noul", "instructions": "metadata " + "x" * 2_000}
                 for i in range(70)}
    batches = jev_preprocessing._question_batches(state, questions)
    assert len(batches) > 1
    assert [key for batch in batches for key in batch] == list(questions)
    assert all(len(json.dumps({"state": state, "questions": batch}, ensure_ascii=False,
        separators=(",", ":"))) <= MAX_SERIALIZED_REQUEST_CHARS for batch in batches)


@pytest.mark.asyncio
async def test_oversized_catalog_rejected_before_any_partial_provider_call(monkeypatch):
    from unittest.mock import AsyncMock
    from backend.shared.providers.typesafe.client import MAX_QUESTIONS, DecisionRequestTooLarge
    evaluate = AsyncMock()
    monkeypatch.setattr(jev_preprocessing, "evaluate_jev_decisions", evaluate)
    questions = {f"candidate_{i}": {"type": "noul", "instructions": "Discovery"}
        for i in range(MAX_QUESTIONS * jev_preprocessing.MAX_PREPROCESSING_DECISION_BATCHES + 1)}
    with pytest.raises(DecisionRequestTooLarge):
        await jev_preprocessing._evaluate_preprocessing_questions(state={"request": "Code"},
            questions=questions, secrets_manager=None, model_id="jev")
    evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_latest_request_suffix_preserved_while_optional_history_yields(monkeypatch):
    captured = []
    latest = "😀" * 12_000 + " FINAL USER INSTRUCTION"
    messages = jev_preprocessing._messages([
        {"role": "user", "content": "😀" * 8_000},
        {"role": "assistant", "content": "😀" * 8_000},
        {"role": "user", "content": latest},
    ])
    assert messages[-1]["content"] == latest

    async def evaluate(**kwargs):
        captured.append(kwargs["state"])
        return DecisionResponse(model="jev", answers={"ok": {"type": "noul", "noul": .9}})

    monkeypatch.setattr(jev_preprocessing, "evaluate_jev_decisions", evaluate)
    await jev_preprocessing._evaluate_preprocessing_questions(
        state={"messages": messages, "conversation_summary": {"text": "😀" * 4_000}},
        questions={"ok": {"type": "noul", "instructions": "route"}},
        secrets_manager=None, model_id="jev",
    )
    assert captured[0]["messages"] == [{"role": "user", "content": latest}]
    assert "conversation_summary" not in captured[0]


@pytest.mark.asyncio
async def test_essential_latest_request_too_large_never_sends_a_prefix(monkeypatch):
    from unittest.mock import AsyncMock
    from backend.shared.providers.typesafe.client import DecisionRequestTooLarge
    evaluate = AsyncMock()
    monkeypatch.setattr(jev_preprocessing, "evaluate_jev_decisions", evaluate)
    with pytest.raises(DecisionRequestTooLarge):
        await jev_preprocessing._evaluate_preprocessing_questions(
            state={"messages": jev_preprocessing._messages([
                {"role": "user", "content": "😀" * 16_000 + "important suffix"},
            ])}, questions={"ok": {"type": "noul", "instructions": "route"}},
            secrets_manager=None, model_id="jev",
        )
    evaluate.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_reserved_stage_one_stops_before_project_specialist_and_reuses_snapshot(monkeypatch):
    calls = []
    async def evaluate(**kwargs):
        calls.append("stage-one")
        response = _routing_answer(kwargs["questions"])
        response.answers["project_target"] = jev_preprocessing.ChoiceAnswer(
            type="choice", choice="project-p1", confidence=.99,
            probabilities={"none": .01, "project-p1": .99})
        return response
    async def specialist(**kwargs):
        calls.append("specialist")
        return None
    async def publish(result):
        calls.append("mate")
    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    monkeypatch.setattr(jev_preprocessing, "_select_project_specialist_with_jev", specialist)
    kwargs = dict(model_id="jev", secrets_manager=None, message_history=[],
        available_apps=["projects"], available_skills=[], available_focus_modes=[],
        project_candidates=[{"project_id": "p1", "name": "Project", "focuses": []}],
        topic_areas=["general_misc: General"], is_first_message=True,
        on_project_routing_resolved=publish)
    snapshot = await jev_preprocessing.decide_app_and_project_routing_with_jev(**kwargs, stage_one_only=True)
    assert calls == ["stage-one", "mate"]
    await jev_preprocessing.decide_app_and_project_routing_with_jev(**kwargs, precomputed_stage_one=snapshot)
    assert calls == ["stage-one", "mate", "mate", "specialist"]
    revoked = await jev_preprocessing.decide_app_and_project_routing_with_jev(
        **{**kwargs, "project_candidates": [{"project_id": "p2", "name": "Other"}]},
        precomputed_stage_one=snapshot)
    assert "pending_project_focus_id" not in revoked


@pytest.mark.asyncio
async def test_healthy_jev_result_skips_all_generative_recovery(monkeypatch):
    result = preprocessor.LLMPreprocessingCallResult(arguments={"complexity": "medium", "task_area": "general"})
    forbidden = AsyncMock(side_effect=AssertionError("Healthy Jev must not start inference"))
    monkeypatch.setattr(preprocessor, "call_preprocessing_llm", forbidden)
    assert await preprocessor._recover_jev_preprocessing(result, task_id="healthy-jev") is result
    forbidden.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mercury_failure", ["outage", "missing_tool", "timeout"])
async def test_jev_generative_recovery_uses_only_mercury_then_configured_lite(monkeypatch, mercury_failure):
    import asyncio
    from backend.apps.ai.utils import llm_utils
    from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, UnifiedOpenAIResponse
    calls = []
    class NoHealthCache:
        @property
        async def client(self):
            return None
    monkeypatch.setattr(llm_utils, "CacheService", NoHealthCache)
    monkeypatch.setattr(llm_utils, "PREPROCESSING_TIMEOUT_SECONDS", .025)
    monkeypatch.setattr(llm_utils, "PREPROCESSING_TOTAL_TIMEOUT_SECONDS", .1)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda model:
        ("inception", "inception/mercury-3") if model == "inception/mercury-3"
        else ("google_ai_studio", "google_ai_studio/gemini-3.5-flash-lite"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _: [])
    async def mercury(**arguments):
        calls.append(("inception", arguments))
        assert arguments["reasoning_effort"] == "low"
        assert arguments["tool_choice"] == "required"
        if mercury_failure == "timeout":
            await asyncio.sleep(1)
        return UnifiedOpenAIResponse(task_id="recovery", model_id="mercury-3",
            success=mercury_failure == "missing_tool",
            error_message="503 Service Unavailable" if mercury_failure == "outage" else None)
    async def lite(**arguments):
        calls.append(("google_ai_studio", arguments))
        assert "reasoning_effort" not in arguments
        return UnifiedOpenAIResponse(task_id="recovery", model_id="gemini-3.5-flash-lite", success=True,
            tool_calls_made=[ParsedOpenAIToolCall(tool_call_id="decision", function_name="analyze_request_properties",
                function_arguments_raw='{"complexity":"medium"}', function_arguments_parsed={"complexity": "medium"})])
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda prefix: {"inception": mercury, "google_ai_studio": lite}[prefix])
    # Registry membership must not make a logical Google fallback bypass its configured host.
    monkeypatch.setitem(llm_utils.PROVIDER_CLIENT_REGISTRY, "google", lite)
    result = await preprocessor._recover_jev_preprocessing(None, task_id="recovery",
        message_history=[{"role": "user", "content": "Classify this request"}],
        tool_definition={"type": "function", "function": {"name": "analyze_request_properties", "description": "Classify",
            "parameters": {"type": "object", "properties": {"complexity": {"type": "string"}}}}})
    assert result.arguments == {"complexity": "medium"} and result.error_message is None
    assert [provider for provider, _ in calls] == ["inception", "google_ai_studio"]
    assert [arguments["model_id"] for _, arguments in calls] == ["mercury-3", "gemini-3.5-flash-lite"]


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_retries", [True, False])
async def test_exhausted_jev_generative_recovery_never_fabricates_routing(monkeypatch, allow_retries):
    from backend.apps.ai.utils import llm_utils
    from backend.apps.ai.llm_providers.openai_shared import UnifiedOpenAIResponse
    calls = []
    class NoHealthCache:
        @property
        async def client(self):
            return None
    monkeypatch.setattr(llm_utils, "CacheService", NoHealthCache)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda model:
        ("inception", "inception/mercury-3") if model == "inception/mercury-3"
        else ("google_ai_studio", "google_ai_studio/gemini-3.5-flash-lite"))
    async def missing_tool(**arguments):
        calls.append(arguments["model_id"])
        return UnifiedOpenAIResponse(task_id="recovery", model_id=arguments["model_id"], success=True)
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: missing_tool)
    result = await preprocessor._recover_jev_preprocessing(None, task_id="recovery", allow_retries=allow_retries,
        message_history=[{"role": "user", "content": "Classify"}],
        tool_definition={"type": "function", "function": {"name": "analyze_request_properties", "description": "Classify", "parameters": {"type": "object", "properties": {}}}})
    assert calls == (["mercury-3", "gemini-3.5-flash-lite"] if allow_retries else ["mercury-3"])
    assert result.arguments is None and result.error_message
