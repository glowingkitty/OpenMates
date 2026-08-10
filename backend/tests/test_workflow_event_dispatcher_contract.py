# backend/tests/test_workflow_event_dispatcher_contract.py
#
# Durable event-dispatch contract: owner/project scope and dedupe stay at the
# transaction boundary, while event payloads remain transient to this adapter.
#
# Spec: docs/specs/workflows-v1/spec.yml (TASK-4, T-PYTEST-007)

import pytest

from backend.core.api.app.services.workflow_event_dispatcher import WorkflowEventDispatcher


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, operation: str, data: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation, data))
        return {"accepted": True, "run_id": "run-1", "version_id": "version-1"}


@pytest.mark.asyncio
async def test_dispatches_matching_owner_project_event_without_payload_persistence() -> None:
    runtime = FakeRuntime()
    trigger = {
        "trigger_id": "trigger-1", "hashed_user_id": "owner-1", "hashed_project_id": "project-1",
        "source": "assistant", "event_type": "skill.completed", "enabled": True,
    }
    event = {
        "event_id": "event-1", "hashed_user_id": "owner-1", "hashed_project_id": "project-1",
        "source": "assistant", "event_type": "skill.completed", "payload": {"skill_id": "forecast"},
    }

    result = await WorkflowEventDispatcher(runtime).dispatch(trigger, event, lambda payload: payload["skill_id"] == "forecast")

    assert result == {"accepted": True, "run_id": "run-1", "version_id": "version-1"}
    assert runtime.calls == [(
        "accept_event_trigger",
        {"trigger_id": "trigger-1", "event_id": "event-1", "hashed_user_id": "owner-1", "hashed_project_id": "project-1", "source": "assistant", "event_type": "skill.completed"},
    )]


@pytest.mark.asyncio
async def test_rejects_cross_project_event_before_receipt_or_run_creation() -> None:
    runtime = FakeRuntime()
    trigger = {"trigger_id": "trigger-1", "hashed_user_id": "owner-1", "hashed_project_id": "project-1", "source": "assistant", "event_type": "skill.completed", "enabled": True}
    event = {"event_id": "event-1", "hashed_user_id": "owner-1", "hashed_project_id": "project-2", "source": "assistant", "event_type": "skill.completed", "payload": {}}

    result = await WorkflowEventDispatcher(runtime).dispatch(trigger, event, lambda _payload: True)

    assert result == {"accepted": False, "reason": "event_trigger_mismatch"}
    assert runtime.calls == []
