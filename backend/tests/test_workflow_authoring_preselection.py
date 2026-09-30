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
            selection = {"operation": "create", "check_mode": "none", "workflow_count": "1", "count:weather.forecast": "1",
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
    assert set(questions) == {"weather.forecast", "weather.rain_radar", "operation", "check_mode", "chat_delivery", "workflow_count"}
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
