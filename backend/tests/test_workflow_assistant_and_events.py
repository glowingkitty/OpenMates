# backend/tests/test_workflow_assistant_and_events.py
#
# Contract tests for assistant-created workflows, pending execution gates, and
# deterministic event trigger matching. These tests keep chat workflow creation
# safe before the assistant UI and app-skill wrappers are wired in.
#
# Spec: docs/specs/workflows-v1/spec.yml

import pytest

from backend.apps.workflows.skills.cancel_pending_skill import CancelPendingSkill
from backend.apps.workflows.skills.keep_temporary_skill import KeepTemporarySkill
from backend.apps.workflows.skills.run_skill import RunSkill
from backend.apps.workflows.skills.schedule_once_skill import ScheduleOnceSkill
from backend.apps.workflows.skills.schedule_recurring_skill import ScheduleRecurringSkill
from backend.apps.workflows.skills.search_skill import SearchSkill
from backend.core.api.app.services.workflow_assistant_service import WorkflowAssistantService
from backend.core.api.app.services.workflow_event_service import WorkflowEventService
from backend.core.api.app.services.workflow_models import WorkflowLifecycle, WorkflowMissingInputError
from backend.core.api.app.services.workflow_service import WORKFLOW_TEMPORARY_TTL_SECONDS, WorkflowService


def one_time_weather_graph() -> dict:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "once", "at": "2026-06-25T09:00:00+02:00"}}},
            {"id": "weather", "type": "app_skill_action", "config": {"app_id": "weather", "skill_id": "forecast", "input": {"location": "Berlin", "days": 7}}},
            {"id": "report", "type": "create_chat_report", "config": {"summary": "Weather for the coming week"}},
        ],
        "edges": [
            {"from": "trigger", "to": "weather"},
            {"from": "weather", "to": "report"},
        ],
    }


def recurring_news_graph() -> dict:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "weekly", "weekdays": ["monday"], "time": "09:00"}}},
            {"id": "news", "type": "app_skill_action", "config": {"app_id": "news", "skill_id": "search", "input": {"requests": [{"query": "AI news"}]}}},
        ],
        "edges": [{"from": "trigger", "to": "news"}],
    }


def manual_input_graph() -> dict:
    graph = one_time_weather_graph()
    graph["nodes"][0] = {
        "id": "trigger",
        "type": "manual_trigger",
        "config": {
            "required_start_input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            }
        },
    }
    return graph


def workflow_skill(skill_class, skill_id: str):
    return skill_class(
        app=None,
        app_id="workflows",
        skill_id=skill_id,
        skill_name=skill_id,
        skill_description=f"Workflow {skill_id}",
    )


def test_schedule_once_creates_temporary_workflow_with_seven_day_expiry() -> None:
    service = WorkflowService()
    assistant = WorkflowAssistantService(service)

    workflow = assistant.schedule_once("alice", "Tomorrow weather", one_time_weather_graph(), source_chat_id="chat-1")

    assert workflow.lifecycle == WorkflowLifecycle.TEMPORARY
    assert workflow.source == "chat"
    assert workflow.source_chat_id == "chat-1"
    assert workflow.created_by_assistant is True
    assert workflow.auto_delete_at is not None
    assert workflow.auto_delete_at - workflow.created_at >= WORKFLOW_TEMPORARY_TTL_SECONDS
    assert service.list_workflows("alice") == []
    assert service.list_temporary_workflows("alice")[0].id == workflow.id


def test_schedule_recurring_creates_persisted_workflow() -> None:
    service = WorkflowService()
    assistant = WorkflowAssistantService(service)

    workflow = assistant.schedule_recurring("alice", "Weekly AI news", recurring_news_graph(), source_chat_id="chat-1")

    assert workflow.lifecycle == WorkflowLifecycle.PERSISTED
    assert workflow.auto_delete_at is None
    assert service.list_workflows("alice")[0].id == workflow.id


def test_assistant_search_returns_owner_scoped_persisted_workflows() -> None:
    service = WorkflowService()
    assistant = WorkflowAssistantService(service)
    persisted = assistant.schedule_recurring("alice", "Weekly AI news", recurring_news_graph())
    assistant.schedule_once("alice", "Temporary weather", one_time_weather_graph())
    assistant.schedule_recurring("bob", "Bob AI news", recurring_news_graph())

    results = assistant.search("alice", "AI news")

    assert [item["workflow_id"] for item in results] == [persisted.id]


def test_pending_workflow_run_can_be_cancelled_and_requires_input() -> None:
    service = WorkflowService()
    assistant = WorkflowAssistantService(service)
    workflow = service.create_workflow("alice", "Manual city workflow", manual_input_graph())

    with pytest.raises(WorkflowMissingInputError):
        assistant.create_pending_run("alice", workflow.id, input_payload={})

    pending = assistant.create_pending_run("alice", workflow.id, input_payload={"city": "Berlin"})

    assert pending["status"] == "countdown"
    assert assistant.cancel_pending("bob", pending["pending_id"]) is False
    assert assistant.cancel_pending("alice", pending["pending_id"]) is True
    assert assistant.pending_runs[pending["pending_id"]]["status"] == "cancelled"


def test_high_risk_pending_workflow_requires_approval() -> None:
    service = WorkflowService()
    assistant = WorkflowAssistantService(service)
    workflow = assistant.schedule_recurring("alice", "Weekly AI news", recurring_news_graph())

    pending = assistant.create_pending_run("alice", workflow.id, high_risk=True)

    assert pending["status"] == "approval_required"
    assert pending["requires_approval"] is True


def test_assistant_schedule_skills_enforce_once_vs_recurring_graphs() -> None:
    assistant = WorkflowAssistantService(WorkflowService())

    with pytest.raises(ValueError, match="schedule_once requires"):
        assistant.schedule_once("alice", "Wrong once", recurring_news_graph())

    with pytest.raises(ValueError, match="schedule_recurring requires"):
        assistant.schedule_recurring("alice", "Wrong recurring", one_time_weather_graph())


def test_keep_temporary_converts_workflow_to_persisted() -> None:
    service = WorkflowService()
    assistant = WorkflowAssistantService(service)
    workflow = assistant.schedule_once("alice", "Temporary weather", one_time_weather_graph())

    kept = assistant.keep_temporary("alice", workflow.id)

    assert kept.lifecycle == WorkflowLifecycle.PERSISTED
    assert kept.auto_delete_at is None
    assert service.list_workflows("alice")[0].id == workflow.id


def test_event_trigger_matching_uses_scope_filters_and_rate_limits() -> None:
    event_service = WorkflowEventService()
    trigger = {
        "id": "trigger-1",
        "event_type": "assistant.skill.completed",
        "scope": {"user_id": "alice", "chat_id": "chat-1"},
        "filters": [{"field": "skill_id", "op": "eq", "value": "forecast"}],
        "rate_limit_seconds": 60,
    }
    event = {
        "type": "assistant.skill.completed",
        "scope": {"user_id": "alice", "chat_id": "chat-1"},
        "payload": {"skill_id": "forecast"},
    }

    assert event_service.matches(trigger, event, now=100) is True
    assert event_service.matches(trigger, event, now=120) is False
    assert event_service.matches(trigger, event, now=161) is True


def test_event_trigger_phrase_filters_are_deterministic() -> None:
    event_service = WorkflowEventService()
    trigger = {
        "event_type": "chat.message.created",
        "scope": {"user_id": "alice"},
        "filters": [{"field": "text", "op": "contains", "value": "urgent"}],
    }

    assert event_service.matches(trigger, {"type": "chat.message.created", "scope": {"user_id": "alice"}, "payload": {"text": "urgent: check this"}}) is True
    assert event_service.matches(trigger, {"type": "chat.message.created", "scope": {"user_id": "alice"}, "payload": {"text": "later"}}) is False


@pytest.mark.asyncio
async def test_workflow_app_skills_delegate_to_assistant_service() -> None:
    service = WorkflowService()
    assistant = WorkflowAssistantService(service)

    schedule_once = await workflow_skill(ScheduleOnceSkill, "schedule-once").execute(
        title="Temporary weather",
        graph=one_time_weather_graph(),
        user_id="alice",
        chat_id="chat-1",
        workflow_assistant_service=assistant,
    )
    assert schedule_once.success is True
    assert schedule_once.workflow is not None
    temporary_id = schedule_once.workflow["id"]
    assert schedule_once.workflow["lifecycle"] == "temporary"

    search_temporary = await workflow_skill(SearchSkill, "search").execute(
        query="weather",
        include_temporary=True,
        user_id="alice",
        workflow_assistant_service=assistant,
    )
    assert [item["workflow_id"] for item in search_temporary.workflows] == [temporary_id]

    kept = await workflow_skill(KeepTemporarySkill, "keep-temporary").execute(
        workflow_id=temporary_id,
        user_id="alice",
        workflow_assistant_service=assistant,
    )
    assert kept.success is True
    assert kept.workflow is not None
    assert kept.workflow["lifecycle"] == "persisted"

    pending = await workflow_skill(RunSkill, "run").execute(
        workflow_id=temporary_id,
        input={},
        high_risk=True,
        user_id="alice",
        workflow_assistant_service=assistant,
    )
    assert pending.success is True
    assert pending.pending_run is not None
    assert pending.pending_run["status"] == "approval_required"

    cancelled = await workflow_skill(CancelPendingSkill, "cancel-pending").execute(
        pending_id=pending.pending_run["pending_id"],
        user_id="alice",
        workflow_assistant_service=assistant,
    )
    assert cancelled.success is True
    assert cancelled.cancelled is True

    recurring = await workflow_skill(ScheduleRecurringSkill, "schedule-recurring").execute(
        title="Weekly AI news",
        graph=recurring_news_graph(),
        user_id="alice",
        workflow_assistant_service=assistant,
    )
    assert recurring.success is True
    assert recurring.workflow is not None
    assert recurring.workflow["lifecycle"] == "persisted"


def test_workflow_tasks_cleanup_and_event_dispatch(monkeypatch) -> None:
    pytest.importorskip("celery")
    from backend.core.api.app.tasks import workflow_tasks

    service = WorkflowService()
    monkeypatch.setattr(workflow_tasks, "_WORKFLOW_SERVICE", service)
    monkeypatch.setattr(workflow_tasks, "_WORKFLOW_EVENT_SERVICE", WorkflowEventService())

    temporary = service.create_workflow("alice", "Temporary weather", one_time_weather_graph(), lifecycle="temporary")
    assert temporary.auto_delete_at is not None
    cleanup = workflow_tasks.cleanup_expired_temporary_workflows(user_id="alice", now=temporary.auto_delete_at + 1)
    assert cleanup == {"deleted": 1}

    event_graph = one_time_weather_graph()
    event_graph["nodes"][0] = {
        "id": "trigger",
        "type": "event_trigger",
        "config": {
            "event": {
                "source": "chat_message",
                "scope": {"chat_id": "chat-1"},
                "filters": {"phrase": "rain"},
                "rate_limit": {"max_per_hour": 1},
            }
        },
    }
    workflow = service.create_workflow("alice", "Rain event", event_graph, enabled=True)
    dispatched = workflow_tasks.dispatch_workflow_event(
        "alice",
        {"source": "chat_message", "scope": {"chat_id": "chat-1"}, "payload": {"text": "rain later"}, "occurred_at": 1},
    )
    assert dispatched == {"matched_workflow_ids": [workflow.id], "matched_count": 1}
    rate_limited = workflow_tasks.dispatch_workflow_event(
        "alice",
        {"source": "chat_message", "scope": {"chat_id": "chat-1"}, "payload": {"text": "rain again"}, "occurred_at": 2},
    )
    assert rate_limited == {"matched_workflow_ids": [], "matched_count": 0}
