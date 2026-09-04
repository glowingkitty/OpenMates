# backend/tests/test_workflow_readiness.py
#
# Readiness contracts distinguish editable disabled workflows from activatable
# workflows that must have one trigger and a reachable qualifying effect.
# These service-boundary tests preserve the persisted workflow lifecycle.
#
# Spec: TASK-16

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository
from backend.tests.workflow_test_utils import workflow_service


USER_ID = "alice"
SCHEDULE_TRIGGER = {
    "id": "trigger",
    "type": "schedule_trigger",
    "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "Europe/Berlin"}},
}
QUALIFYING_EFFECTS = (
    "create_chat_report",
    "start_new_chat",
    "send_notification",
    "send_email_notification",
)


def _graph(nodes: list[dict[str, Any]], edges: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "trigger" if nodes else None,
        "nodes": nodes,
        "edges": edges or [],
    }


def _schedule_graph_with(node: dict[str, Any], *, reachable: bool = True) -> dict[str, Any]:
    edges = [{"from": "trigger", "to": node["id"]}] if reachable else []
    return _graph([SCHEDULE_TRIGGER, node], edges)


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect
def test_disabled_persisted_blank_workflow_accepts_zero_triggers_and_steps() -> None:
    workflow = workflow_service().create_workflow(
        USER_ID,
        "Blank draft",
        _graph([], []),
        enabled=False,
    )

    assert workflow.enabled is False
    assert workflow.graph.nodes == []


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect
def test_zero_triggers_cannot_enable() -> None:
    service = workflow_service()
    workflow = service.create_workflow(USER_ID, "Incomplete draft", _graph([], []), enabled=False)

    with pytest.raises(ValueError, match="exactly one trigger"):
        service.update_workflow(workflow.id, USER_ID, enabled=True)


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect
def test_multiple_triggers_cannot_persist_even_when_disabled() -> None:
    with pytest.raises(ValueError, match="exactly one trigger"):
        workflow_service().create_workflow(
            USER_ID,
            "Invalid draft",
            _graph([SCHEDULE_TRIGGER, {"id": "manual", "type": "manual_trigger", "config": {}}]),
            enabled=False,
        )


@pytest.mark.parametrize(
    "node",
    [
        {"id": "fetch", "type": "app_skill_action", "config": {"app_id": "web", "skill_id": "fetch"}},
        {"id": "decision", "type": "decision", "config": {"predicate": {"left": True, "op": "eq", "right": True}}},
        {"id": "repeat", "type": "repeat", "config": {"max_iterations": 1, "max_duration_seconds": 1, "max_credits": 1, "per_iteration_timeout_seconds": 1}},
        {"id": "ask", "type": "ask_user", "config": {"prompt": "Continue?"}},
        {"id": "wait", "type": "wait", "config": {"seconds": 1}},
        {"id": "end", "type": "end", "config": {}},
    ],
    ids=("app-skill-fetch", "decision", "repeat", "ask-user", "wait", "end"),
)
# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect
def test_schedule_workflow_without_a_qualifying_effect_cannot_enable(node: dict[str, Any]) -> None:
    service = workflow_service()
    workflow = service.create_workflow(USER_ID, "No visible effect", _schedule_graph_with(node), enabled=False)

    with pytest.raises(ValueError, match="reachable.*effect"):
        service.update_workflow(workflow.id, USER_ID, enabled=True)


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect
def test_unreachable_qualifying_effect_cannot_enable() -> None:
    service = workflow_service()
    workflow = service.create_workflow(
        USER_ID,
        "Unreachable notification",
        _graph(
            [
                SCHEDULE_TRIGGER,
                {"id": "end", "type": "end", "config": {}},
                {"id": "notify", "type": "send_notification", "config": {"title": "Heads up", "body": "Done"}},
            ],
            [{"from": "trigger", "to": "end"}],
        ),
        enabled=False,
    )

    with pytest.raises(ValueError, match="reachable.*effect"):
        service.update_workflow(workflow.id, USER_ID, enabled=True)


@pytest.mark.parametrize("effect_type", QUALIFYING_EFFECTS)
# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect
def test_schedule_workflow_with_reachable_qualifying_effect_can_enable(effect_type: str) -> None:
    effect = {"id": "effect", "type": effect_type, "config": {"title": "Ready", "body": "Visible result"}}

    workflow = workflow_service().create_workflow(
        USER_ID,
        "Visible scheduled workflow",
        _schedule_graph_with(effect),
        enabled=True,
    )

    assert workflow.enabled is True


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect,workflows.execution.lifecycle-visible
def test_failed_readiness_does_not_accept_a_run_or_execute_an_effect() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow(
        USER_ID,
        "No effect to run",
        _schedule_graph_with({"id": "end", "type": "end", "config": {}}),
        enabled=False,
    )

    with pytest.raises(ValueError, match="reachable.*effect"):
        service.update_workflow(workflow.id, USER_ID, enabled=True)

    assert repository.runs == {}
    assert repository.get_workflow(workflow.id, USER_ID)["enabled"] is False


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect
def test_disabling_and_clearing_an_enabled_workflow_in_one_update_is_allowed() -> None:
    service = workflow_service()
    workflow = service.create_workflow(
        USER_ID,
        "Ready then cleared",
        _schedule_graph_with({"id": "notify", "type": "send_notification", "config": {"title": "Ready", "body": "Ready"}}),
        enabled=True,
    )

    updated = service.update_workflow(
        workflow.id,
        USER_ID,
        enabled=False,
        graph=_graph([], []),
    )

    assert updated.enabled is False
    assert updated.graph.nodes == []
