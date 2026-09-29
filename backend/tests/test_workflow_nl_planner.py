"""Recipe authoring contracts for CLI and Workflows input sessions."""
# ruff: noqa: E402

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event

import pytest

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.services.workflow_input_service import DirectusWorkflowInputRepository, WorkflowInputService
from backend.core.api.app.services.workflow_nl_planner import WorkflowNLPlanner, _google_usage
from backend.core.api.app.services.workflow_runtime_values import resolve_workflow_runtime_values
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.tests.test_workflows_models import FakeDirectusClient, rain_graph
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


class TargetJev(StubJev):
    def __init__(self) -> None:
        super().__init__({"route": "update"})

    async def evaluate(self, *, state, questions):
        if "target" not in questions:
            return await super().evaluate(state=state, questions=questions)
        self.calls += 1
        target = next(key for key, description in questions["target"]["criteria"].items()
                      if "Berlin umbrella alert" in description)
        return DecisionResponse.model_validate({
            "model": "typesafe/jev-1.13", "usage": {"input_tokens": 300, "output_tokens": 0},
            "answers": {"target": {"type": "choice", "choice": target,
                                   "probabilities": {target: 0.9}, "confidence": 0.9}},
        })


class StubGemini:
    def __init__(self) -> None:
        self.models: list[str] = []

    async def __call__(self, model, payload, schema):
        del schema
        self.models.append(model)
        if "existing_queries" in payload:
            return {"queries": ["AI", "queer community"], "location": "", "online_only": False}, {"input_tokens": 140, "output_tokens": 25}
        if "criteria" in payload:
            return ({"route": "create", "recipe": "rain_alert", "delivery": "chat", "cadence": "weekdays",
                     "horizon": "tomorrow", "city": "berlin", "timezone": "browser"},
                    {"input_tokens": 600, "output_tokens": 45})
        if model == "gemini-3.8-flash":
            return {"city": "Dresden"}, {"input_tokens": 100, "output_tokens": 5}
        request = str(payload.get("request") or "").lower()
        topic = "Startups" if "startup" in request else "AI" if "event" in request else "Berlin news"
        return {"title": "Berlin umbrella alert", "description": "Weekday warning when tomorrow's Berlin forecast predicts rain.",
                "category": "science", "icon": "cloud-rain", "message": "Take an umbrella.",
                "search_query": topic, "ask_ai_prompt": "Summarize {{ $nodes.news.output.results }} in three bullets."}, {"input_tokens": 200, "output_tokens": 40}


def _input_service(jev=None, gemini=None):
    workflows = workflow_service()
    planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                jev_client=jev or StubJev(), structured_call=gemini or StubGemini())
    return WorkflowInputService(workflow_service=workflows, planner=planner), workflows


# contract-test: supporting surface=cli assertions=workflows.content.encrypted-retained
def test_authoring_events_persist_in_encrypted_batches_and_restore_after_reconnect():
    workflows = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=workflows.payload_cipher, token="test-token")
    fake_client = FakeDirectusClient()
    repository._client = fake_client
    planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                jev_client=StubJev(), structured_call=StubGemini())
    service = WorkflowInputService(workflow_service=workflows, planner=planner, repository=repository)

    result = service.start(user_id="alice", timezone="Europe/Berlin",
                           text="Every weekday at 7 Berlin time, check tomorrow's Berlin weather and send me a chat message if rain is expected")

    assert result.status == "executed", result.error
    assert result.workflow is not None
    assert result.authoring_metrics is not None
    assert result.authoring_metrics["service_seconds"] >= 0
    assert sum(method == "POST" and collection == "workflow_input_events" for method, collection in fake_client.requests) == 2
    service._sessions.clear()
    events = service.events(result.session_id, user_id="alice")
    assert [event.event_id for event in events] == list(range(1, result.event_cursor + 1))
    assert events[-1].type == "committed"
    assert events[-1].payload == {"mutation_type": "create_workflow", "workflow_id": result.workflow.id}


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained,workflows.execution.lifecycle-visible
def test_optimistic_create_replays_from_encrypted_session_and_commits_once():
    workflows = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=workflows.payload_cipher, token="test-token")
    fake_client = FakeDirectusClient()
    repository._client = fake_client
    planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                jev_client=StubJev(), structured_call=StubGemini())
    api_service = WorkflowInputService(workflow_service=workflows, planner=planner, repository=repository)
    queued = api_service.start(
        user_id="alice", timezone="Europe/Berlin", optimistic_save=True,
        text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if it rains",
    )
    assert queued.status == "queued"
    assert queued.workflow is None
    assert queued.preview_workflow is not None
    assert queued.preview_workflow.enabled is False
    assert queued.preview_workflow.graph.nodes
    assert not workflows.list_workflows("alice")
    assert repository.queued_session_ids() == [queued.session_id]
    assert sum(method == "POST" and collection == "workflow_input_sessions" for method, collection in fake_client.requests) == 1
    assert sum(method == "POST" and collection == "workflow_input_events" for method, collection in fake_client.requests) == 1

    api_service._sessions.clear()
    reloaded_preview = api_service.status(queued.session_id, "alice").preview_workflow
    assert reloaded_preview is not None and reloaded_preview.id == queued.preview_workflow.id
    assert reloaded_preview.graph == queued.preview_workflow.graph

    worker = WorkflowInputService(workflow_service=workflows, repository=repository)
    committed = worker.commit_queued(queued.session_id)
    assert committed is not None and committed.status == "executed"
    assert committed.workflow is not None
    assert committed.workflow.id == queued.preview_workflow.id
    assert committed.preview_workflow is None
    assert len(workflows.list_workflows("alice")) == 1
    assert repository.queued_session_ids() == []
    assert worker.commit_queued(queued.session_id) is None
    assert worker.status(queued.session_id, "alice").undo_available is True
    assert api_service.status(queued.session_id, "alice").status == "executed"


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained,workflows.execution.lifecycle-visible
def test_optimistic_create_retries_after_mutation_write_failure_without_duplicate(monkeypatch):
    workflows = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=workflows.payload_cipher, token="test-token")
    repository._client = FakeDirectusClient()
    planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                jev_client=StubJev(), structured_call=StubGemini())
    service = WorkflowInputService(workflow_service=workflows, planner=planner, repository=repository)
    queued = service.start(user_id="alice", optimistic_save=True,
                           text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if it rains")
    save_mutation = repository.save_mutation
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary Directus error")
        return save_mutation(*args, **kwargs)

    monkeypatch.setattr(repository, "save_mutation", fail_once)
    first = service.commit_queued(queued.session_id)
    assert first is not None and first.status == "queued"
    assert len(workflows.list_workflows("alice")) == 1
    second = service.commit_queued(queued.session_id)
    assert second is not None and second.status == "executed"
    assert len(workflows.list_workflows("alice")) == 1
    assert attempts == 2


# contract-test: supporting surface=rest_api assertions=workflows.schedule.edge-cases
def test_optimistic_create_retry_repairs_trigger_after_partial_workflow_save(monkeypatch):
    workflows = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=workflows.payload_cipher, token="test-token")
    repository._client = FakeDirectusClient()
    planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                jev_client=StubJev(), structured_call=StubGemini())
    service = WorkflowInputService(workflow_service=workflows, planner=planner, repository=repository)
    queued = service.start(user_id="alice", optimistic_save=True,
                           text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if it rains")
    save_trigger = workflows.repository.save_trigger
    attempts = 0

    def fail_once(record):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary trigger storage error")
        return save_trigger(record)

    monkeypatch.setattr(workflows.repository, "save_trigger", fail_once)
    first = service.commit_queued(queued.session_id)
    assert first is not None and first.status == "queued"
    workflow = workflows.list_workflows("alice")[0]
    assert workflows.repository.get_trigger_for_workflow(workflow.id, "alice") is None

    second = service.commit_queued(queued.session_id)
    assert second is not None and second.status == "executed"
    trigger = workflows.repository.get_trigger_for_workflow(workflow.id, "alice")
    assert trigger is not None and trigger["version_id"] == second.workflow.current_version_id
    assert len(workflows.list_workflows("alice")) == 1


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect
def test_optimistic_edit_rejects_newer_manual_change_before_commit():
    workflows = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=workflows.payload_cipher, token="test-token")
    repository._client = FakeDirectusClient()
    create_planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                       jev_client=StubJev(), structured_call=StubGemini())
    create_service = WorkflowInputService(workflow_service=workflows, planner=create_planner, repository=repository)
    created = create_service.start(user_id="alice", text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if it rains")
    assert created.workflow is not None
    edit_planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                     jev_client=StubJev({"route": "update"}), structured_call=StubGemini())
    edit_service = WorkflowInputService(workflow_service=workflows, planner=edit_planner, repository=repository)
    queued = edit_service.start(user_id="alice", selected_workflow_id=created.workflow.id,
                                text="Move this workflow to 8:30 Berlin time", optimistic_save=True)
    assert queued.status == "queued"
    assert queued.preview_workflow is not None
    assert queued.preview_workflow.id == created.workflow.id
    assert next(node for node in queued.preview_workflow.graph.nodes if node.id == "trigger").config["schedule"]["time"] == "08:30"
    assert next(node for node in workflows.get_workflow(created.workflow.id, "alice").graph.nodes if node.id == "trigger").config["schedule"]["time"] == "07:00"
    workflows.update_workflow(created.workflow.id, "alice", title="My later manual title")
    result = edit_service.commit_queued(queued.session_id)
    assert result is not None and result.status == "failed"
    assert workflows.get_workflow(created.workflow.id, "alice").title == "My later manual title"


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible
def test_stop_during_planning_persists_and_prevents_workflow_creation():
    ready = Event()
    release = Event()

    class BlockingPlanner:
        requires_workflow_overview = False

        def plan(self, *, text, context):
            del text, context
            ready.set()
            assert release.wait(5)
            return {"action": "create_workflow", "title": "Late rain alert", "graph": rain_graph()}

    workflows = workflow_service()
    repository = DirectusWorkflowInputRepository(payload_cipher=workflows.payload_cipher, token="test-token")
    fake_client = FakeDirectusClient()
    repository._client = fake_client
    service = WorkflowInputService(workflow_service=workflows, planner=BlockingPlanner(), repository=repository)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.start, user_id="alice", text="Create a rain alert")
        try:
            assert ready.wait(5)
            session_id = next(iter(service._sessions))
            stopped = service.stop(user_id="alice", session_id=session_id)
            assert stopped.status == "stopped"
            assert fake_client.collections["workflow_input_sessions"][session_id]["status"] == "stopped"
        finally:
            release.set()
        result = future.result(timeout=5)

    assert result.status == "stopped"
    assert not workflows.list_workflows("alice")
    service._sessions.clear()
    assert service.events(session_id, user_id="alice")[-1].type == "stopped"


# contract-test: supporting surface=cli assertions=workflows.content.encrypted-retained
def test_recipe_authoring_does_not_decrypt_unrelated_workflows(monkeypatch):
    service, workflows = _input_service()

    def unexpected_list(*args, **kwargs):
        raise AssertionError("Recipe authoring loaded unrelated workflows")

    monkeypatch.setattr(workflows, "list_workflows", unexpected_list)
    result = service.start(user_id="alice", timezone="Europe/Berlin",
                           text="Every weekday at 7 Berlin time, check tomorrow's Berlin weather and send me a chat message if rain is expected")
    assert result.status == "executed", result.error


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


# contract-test: supporting surface=cli assertions=workflows.activation.reachable-side-effect
def test_short_incomplete_request_saves_blank_titled_draft():
    # Even if Jev guesses a known city and recipe, no city may enter the graph
    # unless the user actually named it.
    service, _ = _input_service()
    result = service.start(user_id="alice", text="Rain alert")
    assert result.status == "draft", result.error
    assert result.workflow is not None
    assert result.workflow.title == "Rain alert"
    assert result.workflow.enabled is False
    assert result.workflow.graph.nodes == []
    assert result.undo_available is True


# contract-test: infrastructure
def test_incomplete_short_request_does_not_spend_a_metadata_call():
    gemini = StubGemini()
    service, _ = _input_service(gemini=gemini)
    result = service.start(user_id="alice", text="Weekly rain alert")
    assert result.status == "draft"
    assert result.workflow is not None and result.workflow.title == "Weekly rain alert"
    assert gemini.models == []


# contract-test: supporting surface=cli assertions=workflows.actions.skill-contract
def test_long_weather_request_cannot_use_a_city_guessed_by_jev():
    service, workflows = _input_service()
    result = service.start(user_id="alice", text=(
        "Every weekday at 7, check tomorrow's weather and send me a chat message "
        "reminding me to take an umbrella if rain is expected"))
    assert result.status == "needs_clarification"
    assert workflows.list_workflows("alice") == []


# contract-test: supporting surface=cli assertions=workflows.schedule.recurrence
def test_short_complete_weekly_events_request_uses_monday_nine_default():
    service, _ = _input_service(StubJev({"recipe": "events_digest", "cadence": "weekly", "horizon": "other"}))
    result = service.start(user_id="alice", timezone="Europe/Berlin", text="Weekly AI event search for Berlin")
    assert result.status == "executed", result.error
    assert result.workflow is not None
    nodes = {node.id: node for node in result.workflow.graph.nodes}
    assert nodes["trigger"].config["schedule"] == {
        "type": "weekly", "time": "09:00", "timezone": "Europe/Berlin", "weekdays": ["monday"],
    }
    assert nodes["events"].config["input"]["requests"][0]["query"] == "AI"
    assert len(result.assumptions) == 2


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract
def test_selected_events_edit_adds_two_topics_even_when_jev_calls_them_multiple_workflows():
    service, workflows = _input_service(StubJev({"recipe": "events_digest", "cadence": "weekly"}))
    created = service.start(user_id="alice", timezone="Europe/Berlin", text="Weekly startup event search for Berlin")
    assert created.status == "executed", created.error
    assert created.workflow is not None
    before = created.workflow
    edit_planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                     jev_client=StubJev({"route": "multiple"}), structured_call=StubGemini())
    edit_service = WorkflowInputService(workflow_service=workflows, planner=edit_planner)
    edited = edit_service.start(
        user_id="alice", selected_workflow_id=before.id, timezone="Europe/Berlin",
        text="Also search for AI meetups and some queer meetups I'm curious about",
    )
    assert edited.status == "executed", edited.error
    assert edited.workflow is not None
    assert edited.workflow.id == before.id
    assert edited.workflow.enabled is False
    before_nodes = {node.id: node for node in before.graph.nodes}
    after_nodes = {node.id: node for node in edited.workflow.graph.nodes}
    assert after_nodes["trigger"] == before_nodes["trigger"]
    assert after_nodes["send"] == before_nodes["send"]
    requests = after_nodes["events"].config["input"]["requests"]
    assert [item["query"] for item in requests] == ["Startups", "AI", "queer community"]
    assert all(item["location"] == "Berlin" for item in requests)
    assert edited.authoring_metrics["event_searches_added"] == 2


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract
def test_selected_events_edit_does_not_discard_a_second_creation_request():
    service, workflows = _input_service(StubJev({"recipe": "events_digest", "cadence": "weekly"}))
    created = service.start(user_id="alice", timezone="Europe/Berlin", text="Weekly startup event search for Berlin")
    assert created.workflow is not None
    edit_planner = WorkflowNLPlanner(secrets_manager=None, workflow_service=workflows,
                                     jev_client=StubJev({"route": "multiple"}), structured_call=StubGemini())
    edit_service = WorkflowInputService(workflow_service=workflows, planner=edit_planner)
    edited = edit_service.start(
        user_id="alice", selected_workflow_id=created.workflow.id, timezone="Europe/Berlin",
        text="Also search for AI meetups and create a weekly news digest",
    )
    assert edited.status == "needs_clarification"
    assert workflows.get_workflow(created.workflow.id, "alice").graph == created.workflow.graph


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract
def test_jev_outage_uses_flash_lite_for_same_recipe_contract():
    gemini = StubGemini()
    service, _ = _input_service(StubJev(unavailable=True), gemini)
    result = service.start(user_id="alice", timezone="Europe/Berlin",
                           text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if it rains")
    assert result.status == "executed", result.error
    assert gemini.models.count("gemini-3.5-flash-lite") == 2
    assert result.authoring_metrics["bounded_fallback"] == "gemini-3.5-flash-lite"


# contract-test: infrastructure
def test_clear_create_drafts_metadata_while_jev_decides():
    metadata_started = asyncio.Event()
    jev_started = asyncio.Event()

    class ConcurrentJev(StubJev):
        async def evaluate(self, *, state, questions):
            jev_started.set()
            await asyncio.wait_for(metadata_started.wait(), timeout=1)
            return await super().evaluate(state=state, questions=questions)

    class ConcurrentGemini(StubGemini):
        async def __call__(self, model, payload, schema):
            if "criteria" not in payload:
                metadata_started.set()
                await asyncio.wait_for(jev_started.wait(), timeout=1)
            return await super().__call__(model, payload, schema)

    service, _ = _input_service(ConcurrentJev(), ConcurrentGemini())
    result = service.start(user_id="alice", timezone="Europe/Berlin",
                           text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if rain is expected")
    assert result.status == "executed", result.error
    assert result.authoring_metrics["metadata_prefetched"] is True


# contract-test: supporting surface=cli assertions=workflows.actions.skill-contract
def test_invalid_flash_lite_bounded_fallback_escalates_to_flash_38():
    class InvalidLiteBoundedGemini(StubGemini):
        async def __call__(self, model, payload, schema):
            if model == "gemini-3.5-flash-lite" and "criteria" in payload:
                self.models.append(model)
                return {"route": "unknown"}, {"input_tokens": 100, "output_tokens": 5}
            return await super().__call__(model, payload, schema)

    gemini = InvalidLiteBoundedGemini()
    service, _ = _input_service(StubJev(unavailable=True), gemini)
    result = service.start(user_id="alice", timezone="Europe/Berlin",
                           text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if it rains")
    assert result.status == "executed", result.error
    assert "gemini-3.8-flash" in gemini.models
    assert result.authoring_metrics["bounded_fallback"] == "gemini-3.8-flash"


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract
def test_low_confidence_jev_retries_once_before_gemini_fallback():
    class UncertainOnceJev(StubJev):
        async def evaluate(self, *, state, questions):
            response = await super().evaluate(state=state, questions=questions)
            if self.calls == 1:
                response.answers["route"].confidence = 0.2
            return response

    gemini = StubGemini()
    jev = UncertainOnceJev()
    service, _ = _input_service(jev, gemini)
    result = service.start(user_id="alice", timezone="Europe/Berlin",
                           text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if it rains")

    assert result.status == "executed", result.error
    assert jev.calls == 2
    assert gemini.models == ["gemini-3.5-flash-lite"]
    assert result.authoring_metrics["jev_low_confidence_retries"] == 1
    assert result.authoring_metrics.get("bounded_fallback") is None


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


@pytest.mark.parametrize("instruction", [
    "Create two workflows: a rain alert and an AI news digest",
    "Create a weekday news digest and move my existing rain alert to 8",
])
# contract-test: supporting surface=cli assertions=workflows.activation.reachable-side-effect
def test_explicit_batch_is_never_partially_saved(instruction):
    service, workflows = _input_service()
    result = service.start(user_id="alice", text=instruction, optimistic_save=True)
    assert result.status == "needs_clarification"
    assert result.authoring_metrics["jev_calls"] == 0
    assert workflows.list_workflows("alice") == []


# contract-test: direct surface=cli assertions=workflows.schedule.edge-cases
def test_tomorrow_runtime_date_rolls_in_schedule_timezone():
    now = datetime.fromisoformat("2026-03-28T23:30:00+00:00")
    value = {"$date": "tomorrow", "format": "date"}
    assert resolve_workflow_runtime_values(value, now=now, timezone="Europe/Berlin") == "2026-03-30"
    assert resolve_workflow_runtime_values(value, now=now, timezone="America/New_York") == "2026-03-29"


# contract-test: direct surface=cli assertions=workflows.actions.skill-contract
def test_selected_workflow_schedule_edit_keeps_enabled_state(monkeypatch):
    service, workflows = _input_service()
    created = service.start(user_id="alice", text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if rain is expected")
    assert created.workflow is not None
    edit_service, _ = _input_service(StubJev({"route": "update"}))
    edit_service.workflow_service = workflows
    edit_service.planner.workflow_service = workflows
    original_get = workflows.get_workflow
    reads = []

    def tracked_get(*args, **kwargs):
        reads.append(args[0])
        return original_get(*args, **kwargs)

    monkeypatch.setattr(workflows, "get_workflow", tracked_get)
    updated = edit_service.start(user_id="alice", selected_workflow_id=created.workflow.id,
                                 text="Move this workflow to 8:30 Berlin time")
    assert updated.status == "executed", updated.error
    assert reads == [created.workflow.id]
    assert updated.workflow.enabled is False
    trigger = next(node for node in updated.workflow.graph.nodes if node.id == "trigger")
    assert trigger.config["schedule"]["time"] == "08:30"


# contract-test: direct surface=cli assertions=workflows.surface.semantic-parity
def test_landing_edit_selects_only_the_named_owner_workflow():
    creator, workflows = _input_service()
    created = creator.start(user_id="alice", text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if rain is expected")
    assert created.workflow is not None
    rain = workflows.update_workflow(created.workflow.id, "alice", title="Berlin umbrella alert")
    other = workflows.create_workflow("alice", "Berlin news digest", rain.graph, description="Summarize AI news", enabled=False)
    workflows.create_workflow("bob", "Berlin umbrella alert", rain.graph, enabled=False)
    selector = TargetJev()
    editor, _ = _input_service(selector)
    editor.workflow_service = workflows
    editor.planner.workflow_service = workflows

    edited = editor.start(user_id="alice", text="Move my Berlin umbrella alert to 8:30 Berlin time")

    assert edited.status == "executed", edited.error
    assert edited.workflow is not None and edited.workflow.id == rain.id
    assert selector.calls == 2
    assert edited.workflow.enabled is False
    assert next(node for node in edited.workflow.graph.nodes if node.id == "trigger").config["schedule"]["time"] == "08:30"
    assert next(node for node in workflows.get_workflow(other.id, "alice").graph.nodes if node.id == "trigger").config["schedule"]["time"] == "07:00"


# contract-test: direct surface=cli assertions=workflows.surface.semantic-parity
def test_landing_edit_without_matching_workflow_clarifies_without_mutation():
    creator, workflows = _input_service()
    created = creator.start(user_id="alice", text="Every weekday at 7, check tomorrow's weather in Berlin and send a chat umbrella reminder if rain is expected")
    assert created.workflow is not None
    editor, _ = _input_service(StubJev({"route": "update"}))
    editor.workflow_service = workflows
    editor.planner.workflow_service = workflows

    result = editor.start(user_id="alice", text="Move my purple rocket workflow to 8:30")

    assert result.status == "needs_clarification"
    assert workflows.get_workflow(created.workflow.id, "alice").version == created.workflow.version


# contract-test: direct surface=cli assertions=workflows.surface.semantic-parity
def test_landing_edit_does_not_select_a_workflow_from_timezone_city_alone():
    workflows = workflow_service()
    news = workflows.create_workflow("alice", "Berlin news digest", rain_graph(), enabled=False)
    city = workflows.create_workflow("alice", "San Francisco", rain_graph(), enabled=False)
    editor, _ = _input_service(StubJev({"route": "update"}))
    editor.workflow_service = workflows
    editor.planner.workflow_service = workflows

    result = editor.start(user_id="alice", text="Move my rain alert to 8:30 San Francisco time")

    assert result.status == "needs_clarification"
    assert workflows.get_workflow(news.id, "alice").version == news.version
    assert workflows.get_workflow(city.id, "alice").version == city.version


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


# contract-test: direct surface=cli assertions=workflows.ai-ask.execution
def test_gemini_cost_usage_includes_reasoning_tokens():
    assert _google_usage({"promptTokenCount": 80, "candidatesTokenCount": 20, "thoughtsTokenCount": 35}) == {
        "input_tokens": 80, "output_tokens": 55,
    }
