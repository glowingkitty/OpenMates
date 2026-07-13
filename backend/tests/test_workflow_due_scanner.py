# backend/tests/test_workflow_due_scanner.py
#
# Due-trigger scanner contracts for Workflow scheduled execution. The scanner
# only reads indexed due trigger IDs; recurrence plaintext is decrypted later by
# the existing fenced claim executor.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

import pytest

from backend.core.api.app.services.workflow_scheduler_service import WorkflowSchedulerService


class FakeRuntime:
    def __init__(self, trigger_ids: list[object]) -> None:
        self.trigger_ids = trigger_ids
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, operation: str, data: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation, data))
        if operation == "list_due_triggers":
            return {"trigger_ids": self.trigger_ids}
        raise AssertionError(operation)


@pytest.mark.asyncio
async def test_due_scanner_dispatches_indexed_enabled_triggers_without_decrypting_recurrence() -> None:
    runtime = FakeRuntime(["trigger-1", "", "trigger-2"])
    dispatched: list[str] = []

    async def dispatch(trigger_id: str) -> None:
        dispatched.append(trigger_id)

    result = await WorkflowSchedulerService(runtime).scan_due_triggers(now=1_800_000_000, limit=25, dispatch_trigger=dispatch)

    assert runtime.calls == [("list_due_triggers", {"now": 1_800_000_000, "limit": 25})]
    assert dispatched == ["trigger-1", "trigger-2"]
    assert result == {"checked": 3, "dispatched": 2, "trigger_ids": ["trigger-1", "trigger-2"]}


@pytest.mark.asyncio
async def test_due_scanner_rejects_invalid_limits_before_touching_runtime() -> None:
    runtime = FakeRuntime([])

    with pytest.raises(ValueError, match="limit"):
        await WorkflowSchedulerService(runtime).scan_due_triggers(now=1, limit=0, dispatch_trigger=lambda _trigger_id: None)  # type: ignore[arg-type]

    assert runtime.calls == []
