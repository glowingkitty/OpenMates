# backend/tests/test_workflow_due_scanner_task.py
#
# Celery scanner wiring contracts for Workflow schedules. The task lists only due
# trigger IDs through the Directus runtime transaction and delegates execution to
# the existing fenced scheduled-trigger task.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.core.api.app.tasks import workflow_tasks
from backend.core.api.app.tasks import base_task


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((operation, data))
        assert operation == "list_due_triggers"
        return {"trigger_ids": ["trigger-1", "trigger-2"]}


# contract-test: infrastructure
@pytest.mark.anyio
async def test_workflow_tasks_initialize_only_core_services(monkeypatch: pytest.MonkeyPatch) -> None:
    class ForbiddenService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("workflow task initialized a non-core service")

    for service_name in (
        "S3UploadService",
        "InvoiceTemplateService",
        "CreditNoteTemplateService",
        "EmailTemplateService",
        "TranslationService",
    ):
        monkeypatch.setattr(base_task, service_name, ForbiddenService)

    async def initialize_all_services(_task: base_task.BaseServiceTask) -> None:
        raise AssertionError("workflow task called the full service initializer")

    monkeypatch.setattr(base_task.BaseServiceTask, "initialize_services", initialize_all_services)

    task = workflow_tasks.WorkflowServiceTask()
    task.bind(workflow_tasks.app)
    task._service_loop = asyncio.get_running_loop()
    task._secrets_manager = object()
    task._cache_service = object()
    task._directus_service = object()
    task._encryption_service = object()

    task.push_request(id="workflow-service-test")
    try:
        await task.initialize_services()
    finally:
        task.pop_request()

    assert isinstance(workflow_tasks.run_workflow_task, workflow_tasks.WorkflowServiceTask)
    assert isinstance(workflow_tasks.cleanup_expired_temporary_workflows_task, workflow_tasks.WorkflowServiceTask)
    assert isinstance(workflow_tasks.run_scheduled_workflow_trigger_task, workflow_tasks.WorkflowServiceTask)
    assert isinstance(workflow_tasks.scan_due_workflow_triggers_task, workflow_tasks.WorkflowServiceTask)
    assert isinstance(workflow_tasks.dispatch_workflow_event_task, workflow_tasks.WorkflowServiceTask)


# contract-test: infrastructure
@pytest.mark.anyio
async def test_workflow_service_lifecycle_always_cleans_up() -> None:
    events: list[str] = []

    class FakeTask:
        async def initialize_services(self) -> None:
            events.append("initialize")

        async def cleanup_services(self) -> None:
            events.append("cleanup")

    async def fail() -> dict[str, Any]:
        events.append("operation")
        raise RuntimeError("workflow failed")

    with pytest.raises(RuntimeError, match="workflow failed"):
        await workflow_tasks._run_with_workflow_services(FakeTask(), fail)

    assert events == ["initialize", "operation", "cleanup"]

    events.clear()

    class InitializationFailureTask(FakeTask):
        async def initialize_services(self) -> None:
            events.append("initialize")
            raise RuntimeError("initialization failed")

    with pytest.raises(RuntimeError, match="initialization failed"):
        await workflow_tasks._run_with_workflow_services(InitializationFailureTask(), fail)

    assert events == ["initialize", "cleanup"]


# contract-test: infrastructure
@pytest.mark.anyio
async def test_scan_due_workflow_triggers_dispatches_each_due_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = FakeRuntime()
    dispatched: list[str] = []
    monkeypatch.setattr(workflow_tasks.run_scheduled_workflow_trigger_task, "delay", dispatched.append)
    monkeypatch.setattr(workflow_tasks, "acquire_celery_task_dedup_lock", lambda *_args, **_kwargs: True)

    result = await workflow_tasks.scan_due_workflow_triggers_now(now=1_800_000_000, limit=25, runtime_service=runtime)

    assert runtime.calls == [("list_due_triggers", {"now": 1_800_000_000, "limit": 25})]
    assert dispatched == ["trigger-1", "trigger-2"]
    assert result == {"checked": 2, "dispatched": 2, "trigger_ids": ["trigger-1", "trigger-2"]}


# contract-test: infrastructure
@pytest.mark.anyio
async def test_scan_due_workflow_triggers_suppresses_duplicate_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = FakeRuntime()
    dispatched: list[str] = []
    acquired: list[str] = []

    monkeypatch.setattr(workflow_tasks.run_scheduled_workflow_trigger_task, "delay", dispatched.append)
    monkeypatch.setattr(
        workflow_tasks,
        "acquire_celery_task_dedup_lock",
        lambda lock_id, **_kwargs: acquired.append(lock_id) or lock_id.endswith("trigger-1"),
    )

    result = await workflow_tasks.scan_due_workflow_triggers_now(
        now=1_800_000_000,
        limit=25,
        runtime_service=runtime,
    )

    assert acquired == [
        "workflow-scheduled-dispatch:trigger-1",
        "workflow-scheduled-dispatch:trigger-2",
    ]
    assert dispatched == ["trigger-1"]
    assert result == {"checked": 2, "dispatched": 1, "trigger_ids": ["trigger-1"]}


# contract-test: infrastructure
@pytest.mark.anyio
async def test_scan_due_workflow_triggers_releases_lock_when_publish_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = FakeRuntime()
    released: list[str] = []

    def fail_publish(_trigger_id: str) -> None:
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(workflow_tasks.run_scheduled_workflow_trigger_task, "delay", fail_publish)
    monkeypatch.setattr(workflow_tasks, "acquire_celery_task_dedup_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        workflow_tasks,
        "release_celery_task_dedup_lock",
        lambda lock_id, **_kwargs: released.append(lock_id) or True,
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await workflow_tasks.scan_due_workflow_triggers_now(
            now=1_800_000_000,
            limit=25,
            runtime_service=runtime,
        )

    assert released == ["workflow-scheduled-dispatch:trigger-1"]


# contract-test: infrastructure
def test_scheduled_trigger_execution_lock_deduplicates_legacy_queue_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    acquired: list[str] = []
    outcomes = iter([True, False])
    monkeypatch.setattr(
        workflow_tasks,
        "acquire_celery_task_dedup_lock",
        lambda lock_id, **_kwargs: acquired.append(lock_id) or next(outcomes),
    )

    assert workflow_tasks._acquire_scheduled_execution_lock("trigger-1") is True
    assert workflow_tasks._acquire_scheduled_execution_lock("trigger-1") is False
    assert acquired == [
        "workflow-scheduled-execution:trigger-1",
        "workflow-scheduled-execution:trigger-1",
    ]


# contract-test: infrastructure
def test_cancelled_scheduled_trigger_releases_execution_lock_before_requeue(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.api.app.routes import workflows

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        workflow_tasks,
        "_release_scheduled_execution_lock",
        lambda trigger_id: calls.append(("release", trigger_id)) or True,
    )
    monkeypatch.setattr(
        workflow_tasks.run_scheduled_workflow_trigger_task,
        "delay",
        lambda trigger_id: calls.append(("publish", trigger_id)),
    )

    workflows._dispatch_cancelled_scheduled_trigger("trigger-1")

    assert calls == [("release", "trigger-1"), ("publish", "trigger-1")]
