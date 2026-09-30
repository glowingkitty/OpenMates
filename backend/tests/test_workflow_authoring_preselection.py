"""Engineering checks for registry selection and generic Jev graph assembly.

These checks exercise no product route and incur no inference charges. Live
quality measurements belong to the opt-in authoring benchmark, not CI fixtures.
"""
# contract-test-file: infrastructure

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.api.app.services.workflow_authoring_preselection import WorkflowAuthoringPreselector
from backend.core.api.app.services.workflow_models import WorkflowCapability, WorkflowValidationError
from backend.core.api.app.services.workflow_jev_constructor import WorkflowJevConstructor
from backend.shared.providers.typesafe.models import DecisionResponse


def capability(identifier="weather.forecast", *, enabled=True):
    return WorkflowCapability(type="app_skill", id=identifier, title=identifier, enabled=enabled, metadata={
        "description": "Forecast a single place's weather for a specified date range",
        "input_schema": {"type": "object", "required": ["location"], "properties": {
            "location": {"type": "string"}, "example": {"type": "string", "example": "omit-me"},
            "title": {"type": "string"},
        }},
        "output_schema": {"type": "object", "properties": {
            "rain_expected": {"type": "boolean"}, "rain_summary": {"type": "string"},
        }},
        "workflow": {"available": enabled, "effect": "read"},
    })


class Registry:
    def list_capabilities(self):
        return [capability(), capability("weather.rain_radar"), capability("private.secret", enabled=False)]


class Decisions:
    def __init__(self, *, malformed=False, cycle=False):
        self.requests = []
        self.malformed, self.cycle = malformed, cycle

    async def evaluate(self, *, state, questions):
        self.requests.append((state, questions))
        answers = {}
        for name, question in questions.items():
            if question["type"] == "noul":
                answers[name] = {"type": "noul", "noul": 0.9 if name in {"weather.forecast", "chat_delivery"} else 0.02}
                continue
            selection = {"operation": "create", "check_mode": "none", "workflow_count": "1", "request_clarity": "clear", "count:weather.forecast": "1",
                         "count:exact": "0", "count:ai": "0", "count:send": "1", "trigger": "schedule",
                         "trigger:next": "action1", "action1:next": "send1", "send1:next": "end"}.get(name)
            if self.cycle and name == "send1:next":
                selection = "action1"
            if selection is None:
                wanted = {"trigger:time": "09:00", "trigger:timezone": "Europe/Berlin", "trigger:cadence": "weekly",
                          "trigger:days": ["monday"], "action1:input:location": "Graz",
                          "send1:message": "Forecast", "send1:source1": "$nodes.action1.output.rain_summary"}.get(name)
                if wanted is not None:
                    selection = next(key for key, item in question["criteria"].items()
                                     if isinstance(item, dict) and item.get("value") == wanted)
                else:
                    selection = "omit"
            answers[name] = {"type": "choice", "choice": selection,
                             "probabilities": {selection: 1.0}, "confidence": 1.0}
        if self.malformed:
            answers.pop("weather.forecast", None)
        return DecisionResponse.model_validate({"model": "test", "answers": answers,
                                                "usage": {"input_tokens": 100, "output_tokens": 10}})


@pytest.mark.asyncio
async def test_selects_registered_skills_directly_and_retains_full_contract():
    jev = Decisions()
    result = await WorkflowAuthoringPreselector(jev_client=jev, registry=Registry()).select("Forecast Graz")
    assert [cap.id for cap in result.capabilities] == ["weather.forecast"]
    assert len(jev.requests) == 1
    state, questions = jev.requests[0]
    assert set(questions) == {"weather.forecast", "weather.rain_radar", "operation", "check_mode", "chat_delivery", "workflow_count", "request_clarity"}
    assert result.workflow_count == 1
    assert state["existing_graph"] is None
    assert "example" not in result.context()["capabilities"][0]["input_schema"]["properties"]["example"]
    assert "title" in result.context()["capabilities"][0]["input_schema"]["properties"]
    assert result.metrics["jev_calls"] == 1


@pytest.mark.asyncio
async def test_implicit_result_formatting_can_use_available_ask_ai_builtin():
    class BuiltinRegistry(Registry):
        def list_capabilities(self):
            return [*super().list_capabilities(), capability("ai.ask")]

    result = await WorkflowAuthoringPreselector(jev_client=Decisions(), registry=BuiltinRegistry()).select(
        "Weather in three cities with a missing-forecast explanation")
    assert result.scores["ai.ask"] < 0.35
    assert "ai.ask" in {cap.id for cap in result.capabilities}
    assert result.metrics["builtin_capabilities"] == ["ai.ask"]


@pytest.mark.asyncio
async def test_missing_relevance_answer_does_not_silently_drop_skill():
    with pytest.raises(ValueError, match="omitted skill relevance"):
        await WorkflowAuthoringPreselector(jev_client=Decisions(malformed=True), registry=Registry()).select("Forecast Graz")


@pytest.mark.asyncio
async def test_staged_selection_routes_apps_then_selects_skills_with_controls():
    class StagedDecisions(Decisions):
        async def evaluate(self, *, state, questions):
            self.requests.append((state, questions))
            answers = {}
            for name, question in questions.items():
                if question["type"] == "noul":
                    value = 0.9 if name in {"app:weather", "weather.forecast", "chat_delivery"} else 0.02
                    answers[name] = {"type": "noul", "noul": value}
                else:
                    choice = {"operation": "create", "check_mode": "none", "workflow_count": "1", "request_clarity": "clear"}[name]
                    answers[name] = {"type": "choice", "choice": choice,
                                     "probabilities": {choice: 1.0}, "confidence": 1.0}
            return DecisionResponse.model_validate({"model": "test", "answers": answers,
                                                    "usage": {"input_tokens": 100, "output_tokens": 10}})

    jev = StagedDecisions()
    result = await WorkflowAuthoringPreselector(jev_client=jev, registry=Registry(), mode="staged").select("Forecast Graz")
    assert [cap.id for cap in result.capabilities] == ["weather.forecast"]
    assert len(jev.requests) == 2
    assert "app:weather" in jev.requests[0][1]
    assert "changes a detail, not an existing workflow" in jev.requests[0][1]["operation"]["instructions"]
    assert set(jev.requests[1][1]) == {"weather.forecast", "weather.rain_radar"}
    assert result.metrics["jev_calls"] == 2
    assert result.metrics["input_tokens"] == 200
    assert result.metrics["app_scores"] == {"weather": 0.9}
    assert result.metrics["selected_capability_ids"] == ["weather.forecast"]
    assert result.workflow_count == 1


@pytest.mark.asyncio
async def test_staged_skill_outage_falls_back_to_direct_selection():
    class FailingStage(Decisions):
        async def evaluate(self, *, state, questions):
            if "app:weather" in questions:
                self.requests.append((state, questions))
                answers = {"app:weather": {"type": "noul", "noul": 0.9},
                           "operation": {"type": "choice", "choice": "create", "probabilities": {"create": 1.0}, "confidence": 1.0},
                           "check_mode": {"type": "choice", "choice": "none", "probabilities": {"none": 1.0}, "confidence": 1.0},
                           "workflow_count": {"type": "choice", "choice": "1", "probabilities": {"1": 1.0}, "confidence": 1.0},
                           "request_clarity": {"type": "choice", "choice": "clear", "probabilities": {"clear": 1.0}, "confidence": 1.0},
                           "chat_delivery": {"type": "noul", "noul": 0.9}}
                return DecisionResponse.model_validate({"model": "test", "answers": answers,
                                                        "usage": {"input_tokens": 100, "output_tokens": 10}})
            if set(questions) == {"weather.forecast", "weather.rain_radar"}:
                raise TimeoutError("stage unavailable")
            return await super().evaluate(state=state, questions=questions)

    result = await WorkflowAuthoringPreselector(jev_client=FailingStage(), registry=Registry(), mode="staged").select("Forecast Graz")
    assert [cap.id for cap in result.capabilities] == ["weather.forecast"]
    assert result.metrics["fallback"] == "direct"
    assert result.metrics["jev_calls"] == 2


@pytest.mark.asyncio
async def test_jev_unclear_count_is_confusing_unless_title_only():
    class ClarityDecisions(Decisions):
        def __init__(self, clarity):
            super().__init__()
            self.clarity = clarity

        async def evaluate(self, *, state, questions):
            result = await super().evaluate(state=state, questions=questions)
            answers = result.model_dump()["answers"]
            answers["workflow_count"] = {"type": "choice", "choice": "unclear",
                                         "probabilities": {"unclear": 1.0}, "confidence": 1.0}
            answers["request_clarity"] = {"type": "choice", "choice": self.clarity,
                                          "probabilities": {self.clarity: 1.0}, "confidence": 1.0}
            return DecisionResponse.model_validate({**result.model_dump(), "answers": answers})

    confusing = await WorkflowAuthoringPreselector(jev_client=ClarityDecisions("clear"), registry=Registry()).select("Maybe two workflows")
    draft = await WorkflowAuthoringPreselector(jev_client=ClarityDecisions("title_only"), registry=Registry()).select("My research")
    assert confusing.request_clarity == "confusing"
    assert draft.request_clarity == "title_only"
    assert draft.context()["request_clarity"] == "title_only"


@pytest.mark.asyncio
async def test_self_correction_routing_prompt_and_safe_metrics():
    spoken = ("Every Tuesday at 8 in Madrid—no, make that Thursday at 9 in Lisbon—"
              "find local tech meetups and send a chat summary. Name it CLI rollout spoken")
    jev = Decisions()
    result = await WorkflowAuthoringPreselector(jev_client=jev, registry=Registry()).select(spoken)
    state, questions = jev.requests[0]
    operation = questions["operation"]["instructions"]
    assert "changes a detail, not an existing workflow" in operation
    assert "existing named workflow or an open workflow" in operation
    assert "corrected details" in questions["operation"]["criteria"]["create"]
    assert "Replacing an earlier time, place" in questions["request_clarity"]["instructions"]
    assert state["open_workflow"] is False
    assert result.metrics["operation"] == "create"
    assert result.metrics["request_clarity"] == "clear"
    assert result.metrics["workflow_count"] == 1
    assert result.metrics["selected_capability_ids"] == ["weather.forecast"]
    assert spoken not in str(result.metrics)


@pytest.mark.asyncio
async def test_existing_open_workflow_remains_an_edit_target():
    class UpdateDecisions(Decisions):
        async def evaluate(self, *, state, questions):
            response = await super().evaluate(state=state, questions=questions)
            answers = response.model_dump()["answers"]
            answers["operation"] = {"type": "choice", "choice": "update",
                                    "probabilities": {"update": 1.0}, "confidence": 1.0}
            return DecisionResponse.model_validate({**response.model_dump(), "answers": answers})

    jev = UpdateDecisions()
    result = await WorkflowAuthoringPreselector(jev_client=jev, registry=Registry()).select(
        "Change this workflow's schedule to Thursday at 9", selected_workflow={"graph": {"nodes": []}})
    assert jev.requests[0][0]["open_workflow"] is True
    assert result.operation == "update"
    assert result.metrics["operation"] == "update"


@pytest.mark.asyncio
async def test_generic_constructor_copies_novel_city_and_validates(monkeypatch):
    # Availability/preflight is mocked only to isolate the generic compiler;
    # the live benchmark uses the full registry and readiness checks.
    from backend.core.api.app.services import workflow_jev_constructor as module
    monkeypatch.setattr(module, "validate_workflow_readiness", lambda graph: None)
    jev = Decisions()
    selection = await WorkflowAuthoringPreselector(jev_client=jev, registry=Registry()).select("Forecast Graz")
    graph, metrics = await WorkflowJevConstructor(jev_client=jev).construct(
        text='Forecast Graz and send "Forecast"', selection=selection, timezone="Europe/Berlin",
    )
    assert graph["nodes"][1]["config"]["input"] == {"location": "Graz"}
    assert graph["nodes"][0]["config"]["schedule"] == {
        "type": "weekly", "time": "09:00", "timezone": "Europe/Berlin", "weekdays": ["monday"],
    }
    assert metrics["jev_calls"] == 2
    assert len(jev.requests) == 3


@pytest.mark.asyncio
async def test_contradictory_edge_decisions_fail_validation_and_preserve_usage():
    jev = Decisions(cycle=True)
    selection = await WorkflowAuthoringPreselector(jev_client=jev, registry=Registry()).select("Forecast Graz")
    constructor = WorkflowJevConstructor(jev_client=jev)
    with pytest.raises((WorkflowValidationError, ValidationError), match="cycles|cyclic"):
        await constructor.construct(text='Forecast Graz and send "Forecast"', selection=selection, timezone="Europe/Berlin")
    assert constructor.candidate_graph is not None
    assert constructor.last_metrics["jev_calls"] == 2
    assert constructor.last_metrics["input_tokens"] == 200
