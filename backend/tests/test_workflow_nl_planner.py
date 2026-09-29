"""Recipe authoring contracts for CLI and Workflows input sessions."""
# ruff: noqa: E402

from __future__ import annotations

from datetime import datetime

import pytest

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.services.workflow_input_service import WorkflowInputService
from backend.core.api.app.services.workflow_nl_planner import WorkflowNLPlanner
from backend.core.api.app.services.workflow_runtime_values import resolve_workflow_runtime_values
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.tests.workflow_test_utils import workflow_service


@pytest.fixture(autouse=True)
def filesystem_capabilities(monkeypatch):
    monkeypatch.setattr(WorkflowCapabilityRegistry, "_registry", lambda self: _FilesystemWorkflowMetadataRegistry())


class StubJev:
    def __init__(self, choices: dict[str, str] | None = None, *, unavailable: bool = False) -> None:
        self.choices = choices or {}
        self.unavailable = unavailable
        self.calls = 0

    async def evaluate(self, *, state, questions):
        del state
        self.calls += 1
        if self.unavailable:
            raise RuntimeError("Jev unavailable")
        defaults = {"route": "create", "recipe": "rain_alert", "delivery": "chat", "cadence": "weekdays",
                    "horizon": "tomorrow", "city": "berlin", "timezone": "browser"}
        choices = defaults | self.choices
        return DecisionResponse.model_validate({
            "model": "typesafe/jev-1.13", "usage": {"input_tokens": 800, "output_tokens": 0},
            "answers": {name: {"type": "choice", "choice": choices[name],
                               "probabilities": {choices[name]: 0.9}, "confidence": 0.9}
                        for name in questions},
        })


class StubGemini:
    def __init__(self) -> None:
        self.models: list[str] = []

    async def __call__(self, model, payload, schema):
        del schema
        self.models.append(model)
        if model == "gemini-3.8-flash" and "criteria" in payload:
            return ({"route": "create", "recipe": "rain_alert", "delivery": "chat", "cadence": "weekdays",
                     "horizon": "tomorrow", "city": "berlin", "timezone": "browser"},
                    {"input_tokens": 600, "output_tokens": 45})
        if model == "gemini-3.8-flash":
            return {"city": "Dresden"}, {"input_tokens": 100, "output_tokens": 5}
        return {"title": "Berlin umbrella alert", "description": "Weekday warning when tomorrow's Berlin forecast predicts rain.",
                "category": "science", "icon": "cloud-rain", "message": "Take an umbrella.",
                "search_query": "Berlin news", "ask_ai_prompt": "Summarize {{ $nodes.news.output.results }} in three bullets."}, {"input_tokens": 200, "output_tokens": 40}


def _input_service(jev=None, gemini=None):
    workflows = workflow_service()
    planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                jev_client=jev or StubJev(), structured_call=gemini or StubGemini())
    return WorkflowInputService(workflow_service=workflows, planner=planner), workflows


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract,workflows.schedule.edge-cases
def test_cli_input_creates_disabled_ready_tomorrow_rain_recipe_with_identity_and_metrics():
    service, workflows = _input_service()
    result = service.start(user_id="alice", timezone="America/New_York",
                           text="Every weekday at 7, check tomorrow's weather in Berlin. If rain is expected, send me a chat message reminding me to take an umbrella")

    assert result.status == "executed", result.error
    assert result.workflow is not None
    assert result.workflow.enabled is False
    assert result.workflow.description and "Berlin" in result.workflow.description
    assert result.workflow.icon == "cloud-rain"
    nodes = {node.id: node for node in result.workflow.graph.nodes}
    assert nodes["trigger"].config["schedule"] == {
        "type": "weekly", "time": "07:00", "timezone": "America/New_York",
        "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    }
    assert nodes["weather"].config["input"]["start_date"] == {"$date": "tomorrow", "format": "date"}
    assert any(edge.from_node == "rain_check" and edge.to_node == "send" and edge.branch == "yes"
               for edge in result.workflow.graph.edges)
    assert result.authoring_metrics["jev_calls"] == 1
    assert result.authoring_metrics["gemini_calls"] == 1
    assert result.authoring_metrics["estimated_cost_usd"] > 0
    assert len(workflows.list_workflows("alice")) == 1


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract
def test_jev_outage_uses_gemini_38_for_same_recipe_contract():
    gemini = StubGemini()
    service, _ = _input_service(StubJev(unavailable=True), gemini)
    result = service.start(user_id="alice", timezone="Europe/Berlin",
                           text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if it rains")
    assert result.status == "executed", result.error
    assert gemini.models == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert result.authoring_metrics["bounded_fallback"] == "gemini-3.8-flash"


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract
def test_unsupported_delivery_creates_nothing_and_requests_clarification():
    service, workflows = _input_service(StubJev({"delivery": "email"}))
    result = service.start(user_id="alice", text="Every weekday at 7 email tomorrow's Berlin rain forecast")
    assert result.status == "needs_clarification"
    assert not workflows.list_workflows("alice")


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract
def test_explicit_external_channel_cannot_be_silently_replaced_by_chat():
    service, workflows = _input_service(StubJev({"recipe": "news_ai_digest", "delivery": "chat"}))
    result = service.start(user_id="alice", text="Every day at 8 UTC, post an AI news digest to Slack")
    assert result.status == "needs_clarification"
    assert result.authoring_metrics["jev_calls"] == 0
    assert not workflows.list_workflows("alice")


# contract-test: direct surface=cli assertions=workflows.schedule.edge-cases
def test_tomorrow_runtime_date_rolls_in_schedule_timezone():
    now = datetime.fromisoformat("2026-03-28T23:30:00+00:00")
    value = {"$date": "tomorrow", "format": "date"}
    assert resolve_workflow_runtime_values(value, now=now, timezone="Europe/Berlin") == "2026-03-30"
    assert resolve_workflow_runtime_values(value, now=now, timezone="America/New_York") == "2026-03-29"


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract
def test_selected_workflow_schedule_edit_keeps_enabled_state():
    service, workflows = _input_service()
    created = service.start(user_id="alice", text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if rain is expected")
    assert created.workflow is not None
    edit_service, _ = _input_service(StubJev({"route": "update"}))
    edit_service.workflow_service = workflows
    edit_service.planner.workflow_service = workflows
    updated = edit_service.start(user_id="alice", selected_workflow_id=created.workflow.id,
                                 text="Move this workflow to 8:30 Berlin time")
    assert updated.status == "executed", updated.error
    assert updated.workflow.enabled is False
    trigger = next(node for node in updated.workflow.graph.nodes if node.id == "trigger")
    assert trigger.config["schedule"]["time"] == "08:30"


# contract-test: direct surface=cli assertions=workflows.surface.semantic-parity
def test_ai_undo_preserves_later_manual_edits():
    service, workflows = _input_service()
    result = service.start(user_id="alice", text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if rain is expected")
    assert result.workflow is not None
    changed = workflows.update_workflow(result.workflow.id, "alice", title="My manual title")

    undone = service.undo(user_id="alice", session_id=result.session_id)

    assert undone.error_code == "WORKFLOW_INPUT_UNDO_CONFLICT"
    assert workflows.get_workflow(changed.id, "alice").title == "My manual title"


# contract-test: direct surface=cli assertions=workflows.ai-ask.execution,workflows.composition.earlier-action-reference
def test_news_ai_recipe_uses_generated_grounded_instruction():
    service, _ = _input_service(StubJev({"recipe": "news_ai_digest", "city": "none", "horizon": "today"}))
    result = service.start(user_id="alice", text="Every day at 8, search Berlin news, ask AI for a short digest, and send it to chat")
    assert result.status == "executed", result.error
    nodes = {node.id: node for node in result.workflow.graph.nodes}
    assert nodes["ask"].config["input"]["prompt"] == "Summarize {{ $nodes.news.output.results }} in three bullets."
    assert nodes["send"].config["message"] == "{{ $nodes.ask.output.answer }}"
