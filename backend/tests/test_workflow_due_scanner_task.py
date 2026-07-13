# backend/tests/test_workflow_due_scanner_task.py
#
# Celery scanner wiring contracts for Workflow schedules. The task lists only due
# trigger IDs through the Directus runtime transaction and delegates execution to
# the existing fenced scheduled-trigger task.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.tasks import workflow_tasks


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((operation, data))
        assert operation == "list_due_triggers"
        return {"trigger_ids": ["trigger-1", "trigger-2"]}


@pytest.mark.anyio
async def test_scan_due_workflow_triggers_dispatches_each_due_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = FakeRuntime()
    dispatched: list[str] = []
    monkeypatch.setattr(workflow_tasks.run_scheduled_workflow_trigger_task, "delay", dispatched.append)

    result = await workflow_tasks.scan_due_workflow_triggers_now(now=1_800_000_000, limit=25, runtime_service=runtime)

    assert runtime.calls == [("list_due_triggers", {"now": 1_800_000_000, "limit": 25})]
    assert dispatched == ["trigger-1", "trigger-2"]
    assert result == {"checked": 2, "dispatched": 2, "trigger_ids": ["trigger-1", "trigger-2"]}
