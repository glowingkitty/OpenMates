# backend/tests/test_workflow_runner.py
#
# Contract tests for Workflows V1 server-side execution and node-run history.
#
# Spec: docs/specs/workflows-v1/spec.yml

import json

import pytest

from backend.core.api.app.services.workflow_models import WorkflowRunContentStorage
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository, WorkflowService


class FakeAppSkillAdapter:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, app_id, skill_id, request):
        self.calls.append({"app_id": app_id, "skill_id": skill_id, "request": request})
        if app_id == "weather":
            return {
                "app_id": app_id,
                "skill_id": skill_id,
                "summary": f"Weather forecast for {request.get('location')}",
                "rain_probability": request.get("mock_rain_probability", 70),
            }
        return {
            "app_id": app_id,
            "skill_id": skill_id,
            "summary": "News search completed",
            "queries": [item["query"] for item in request.get("requests", [])],
            "result_count": len(request.get("requests", [])),
        }


class FakeActionAdapter:
    def __init__(self) -> None:
        self.calls = []

    async def create_chat_report(self, config, context):
        self.calls.append({"type": "create_chat_report", "config": config})
        return {"report_id": "report-1", "summary": config.get("summary") or "Workflow report created"}

    async def start_new_chat(self, config, context):
        self.calls.append({"type": "start_new_chat", "config": config})
        return {"chat_id": "chat-1", "title": config.get("title")}

    async def send_notification(self, config, channel):
        self.calls.append({"type": channel, "config": config})
        return {"queued": True, "channel": channel, "title": config.get("title"), "body": config.get("body")}


def rain_graph(rain_probability: int = 70) -> dict:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {
                "id": "trigger",
                "type": "schedule_trigger",
                "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "Europe/Berlin"}},
            },
            {
                "id": "weather",
                "type": "app_skill_action",
                "config": {
                    "app_id": "weather",
                    "skill_id": "forecast",
                    "input": {"location": "Berlin", "days": 1, "mock_rain_probability": rain_probability},
                },
            },
            {
                "id": "decision",
                "type": "decision",
                "config": {"predicate": {"left": "$nodes.weather.output.rain_probability", "op": "gte", "right": 60}},
            },
            {"id": "notify", "type": "send_notification", "config": {"title": "Rain today", "body": "Take an umbrella."}},
            {"id": "email", "type": "send_email_notification", "config": {"title": "Rain today", "body": "Take an umbrella."}},
        ],
        "edges": [
            {"from": "trigger", "to": "weather"},
            {"from": "weather", "to": "decision"},
            {"from": "decision", "to": "notify", "branch": "yes"},
            {"from": "notify", "to": "email"},
        ],
    }


def news_graph() -> dict:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {
                "id": "trigger",
                "type": "schedule_trigger",
                "config": {"schedule": {"type": "weekly", "weekdays": ["monday", "thursday"], "time": "09:00"}},
            },
            {
                "id": "news",
                "type": "app_skill_action",
                "config": {
                    "app_id": "news",
                    "skill_id": "search",
                    "input": {
                        "requests": [
                            {"query": "OpenAI news"},
                            {"query": "Anthropic news"},
                            {"query": "Google Gemini news"},
                        ]
                    },
                },
            },
            {"id": "report", "type": "create_chat_report", "config": {"summary": "AI news brief report"}},
            {"id": "notify", "type": "send_notification", "config": {"title": "AI news brief", "body": "Your AI news brief is ready."}},
            {"id": "email", "type": "send_email_notification", "config": {"title": "AI news brief", "body": "Your AI news brief is ready."}},
        ],
        "edges": [
            {"from": "trigger", "to": "news"},
            {"from": "news", "to": "report"},
            {"from": "report", "to": "notify"},
            {"from": "notify", "to": "email"},
        ],
    }


@pytest.mark.asyncio
async def test_rain_workflow_runs_server_side_and_records_node_history() -> None:
    service = WorkflowService()
    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph(), enabled=True)
    app_adapter = FakeAppSkillAdapter()
    action_adapter = FakeActionAdapter()

    run = await WorkflowRunner(service, app_skill_adapter=app_adapter, action_adapter=action_adapter).run_workflow(workflow, "alice", trigger_type="schedule")

    assert run.status == "completed"
    assert [node.node_id for node in run.node_runs] == ["trigger", "weather", "decision", "notify", "email"]
    assert run.node_runs[1].output_summary["rain_probability"] == 70
    assert run.node_runs[2].output_summary == {"matched": True, "branch": "yes"}
    assert run.node_runs[3].output_summary["queued"] is True
    assert app_adapter.calls[0]["app_id"] == "weather"
    assert [call["type"] for call in action_adapter.calls] == ["send_notification", "send_email_notification"]
    assert service.get_run(workflow.id, run.id, "alice").id == run.id


@pytest.mark.asyncio
async def test_decision_node_records_unmatched_branch_without_silent_failure() -> None:
    service = WorkflowService()
    workflow = service.create_workflow("alice", "Dry day", rain_graph(rain_probability=10), enabled=True)

    run = await WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=FakeActionAdapter()).run_workflow(workflow, "alice", trigger_type="manual")

    decision = next(node for node in run.node_runs if node.node_id == "decision")
    assert [node.node_id for node in run.node_runs] == ["trigger", "weather", "decision"]
    assert decision.output_summary == {"matched": False, "branch": "no"}


@pytest.mark.asyncio
async def test_ai_news_brief_runs_news_action_report_and_notifications() -> None:
    service = WorkflowService()
    workflow = service.create_workflow("alice", "AI news brief", news_graph(), enabled=True)
    app_adapter = FakeAppSkillAdapter()
    action_adapter = FakeActionAdapter()

    run = await WorkflowRunner(service, app_skill_adapter=app_adapter, action_adapter=action_adapter).run_workflow(workflow, "alice", trigger_type="schedule")

    assert run.status == "completed"
    news = next(node for node in run.node_runs if node.node_id == "news")
    report = next(node for node in run.node_runs if node.node_id == "report")
    assert news.output_summary["queries"] == ["OpenAI news", "Anthropic news", "Google Gemini news"]
    assert report.output_summary["summary"] == "AI news brief report"
    assert app_adapter.calls[0]["skill_id"] == "search"
    assert [call["type"] for call in action_adapter.calls] == ["create_chat_report", "send_notification", "send_email_notification"]
    assert service.list_runs(workflow.id, "alice")[0].id == run.id


@pytest.mark.asyncio
async def test_run_content_rows_store_node_outputs_as_encrypted_blob_refs() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository=repository)
    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph(), enabled=True)

    run = await WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=FakeActionAdapter()).run_workflow(workflow, "alice", trigger_type="schedule")
    raw_run_rows = json.dumps(repository.runs, sort_keys=True)
    raw_blob_rows = json.dumps(repository.encrypted_blobs, sort_keys=True)

    assert service.get_run(workflow.id, run.id, "alice").node_runs[1].output_summary["summary"] == "Weather forecast for Berlin"
    assert run.content_available is True
    assert run.content_storage == WorkflowRunContentStorage.DURABLE
    assert "Weather forecast for Berlin" not in raw_run_rows
    assert "rain_probability" not in raw_run_rows
    assert "Weather forecast for Berlin" not in raw_blob_rows
    assert "rain_probability" not in raw_blob_rows


@pytest.mark.asyncio
async def test_default_run_content_retention_keeps_latest_five_durable_blobs() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository=repository)
    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph(), enabled=True)

    runner = WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=FakeActionAdapter())
    runs = [await runner.run_workflow(workflow, "alice", trigger_type="schedule") for _ in range(6)]
    persisted_runs = service.list_runs(workflow.id, "alice")
    available_runs = [run for run in persisted_runs if run.content_available]
    deleted_runs = [run for run in persisted_runs if not run.content_available]

    assert len(available_runs) == 5
    assert len(deleted_runs) == 1
    assert deleted_runs[0].id == runs[0].id
    assert deleted_runs[0].content_storage == WorkflowRunContentStorage.DELETED
    assert len([blob for blob in repository.encrypted_blobs.values() if blob["kind"] == "workflow_run_content"]) == 5


@pytest.mark.asyncio
async def test_none_retention_keeps_only_latest_ephemeral_run_content() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository=repository)
    workflow = service.create_workflow(
        "alice",
        "Daily rain alert",
        rain_graph(),
        enabled=True,
        run_content_retention="none",
    )

    runner = WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=FakeActionAdapter())
    first_run = await runner.run_workflow(workflow, "alice", trigger_type="schedule")
    second_run = await runner.run_workflow(workflow, "alice", trigger_type="schedule")
    persisted_first = service.get_run(workflow.id, first_run.id, "alice")
    persisted_second = service.get_run(workflow.id, second_run.id, "alice")

    assert persisted_first.content_available is False
    assert persisted_first.content_storage == WorkflowRunContentStorage.DELETED
    assert persisted_first.node_runs == []
    assert persisted_second.content_available is True
    assert persisted_second.content_storage == WorkflowRunContentStorage.EPHEMERAL
    assert persisted_second.content_expires_at is not None
    assert persisted_second.content_expires_at - (persisted_second.finished_at or 0) <= 7 * 24 * 60 * 60
    assert len([blob for blob in repository.encrypted_blobs.values() if blob["kind"] == "workflow_run_content_ephemeral"]) == 1


@pytest.mark.asyncio
async def test_temporary_workflow_remains_after_run_until_cleanup() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository=repository)
    workflow = service.create_workflow("alice", "Temporary rain", rain_graph(), lifecycle="temporary", enabled=True)
    assert workflow.auto_delete_at is not None

    await WorkflowRunner(service, app_skill_adapter=FakeAppSkillAdapter(), action_adapter=FakeActionAdapter()).run_workflow(workflow, "alice")

    assert service.get_workflow(workflow.id, "alice").id == workflow.id
    assert service.cleanup_expired_temporary_workflows("alice", now=workflow.auto_delete_at + 1) == 1
    with pytest.raises(KeyError):
        service.get_workflow(workflow.id, "alice")
