# backend/core/api/app/tasks/workflow_tasks.py
#
# Celery task entry points for Workflows V1.
# These wrappers keep scheduled cleanup, queued execution, and event dispatch on
# the same WorkflowService/WorkflowRunner contracts used by the API and SDKs.
# Directus-backed persistence can replace the service repository without changing
# the Celery task contract.

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.api.app.services.workflow_event_dispatcher import WorkflowEventDispatcher
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_runtime_service import WorkflowRuntimeService
from backend.core.api.app.services.workflow_scheduler_service import WorkflowSchedulerService
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

_WORKFLOW_SERVICE = WorkflowService(repository=DirectusWorkflowRepository())


def get_workflow_service() -> WorkflowService:
    return _WORKFLOW_SERVICE


def cleanup_expired_temporary_workflows(user_id: str | None = None, now: int | None = None) -> dict[str, Any]:
    deleted = get_workflow_service().cleanup_expired_temporary_workflows(user_id=user_id, now=now)
    return {"deleted": deleted}


async def run_workflow_now(
    workflow_id: str,
    user_id: str,
    run_id: str,
    version_id: str,
    trigger_type: str,
    input_payload: dict[str, Any],
    *,
    workflow_service: WorkflowService | None = None,
    runtime_service: WorkflowRuntimeService | None = None,
) -> dict[str, Any]:
    """Execute a run only after its API or scheduler acceptance pinned a version."""
    if trigger_type not in {"manual", "test"}:
        raise ValueError("Manual worker task only accepts manual or test runs")
    if runtime_service is None:
        raise RuntimeError("Workflow runtime service is required to claim accepted runs")
    service = workflow_service or get_workflow_service()
    started = await runtime_service.execute(
        "start_accepted_run",
        {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "hashed_user_id": service.repository.workflow_owner_hash(user_id),
        },
    )
    claimed_run_id = started.get("run_id")
    claimed_workflow_id = started.get("workflow_id")
    claimed_version_id = started.get("version_id")
    status = started.get("status")
    started_flag = started.get("started")
    if not all(isinstance(value, str) and value for value in (claimed_run_id, claimed_workflow_id, claimed_version_id, status)):
        raise RuntimeError("Workflow runtime start returned invalid run metadata")
    if not isinstance(started_flag, bool):
        raise RuntimeError("Workflow runtime start returned invalid started state")
    if (claimed_run_id, claimed_workflow_id, claimed_version_id) != (run_id, workflow_id, version_id):
        raise RuntimeError("Workflow runtime start did not match the accepted run")
    if not started_flag:
        return {"id": run_id, "workflow_id": workflow_id, "version_id": version_id, "status": status}
    vault_key_id = service.resolve_user_vault_key_id(user_id)
    workflow = await asyncio.to_thread(service.get_workflow_version, workflow_id, user_id, version_id, vault_key_id)
    run = await WorkflowRunner(service).run_workflow(
        workflow,
        user_id,
        vault_key_id=vault_key_id,
        trigger_type=trigger_type,
        input_payload=input_payload,
        run_id=run_id,
        version_id=version_id,
    )
    return run.model_dump(mode="json")


async def run_scheduled_workflow_trigger_now(
    trigger_id: str,
    *,
    runtime_service: WorkflowRuntimeService,
    decrypt_and_schedule: Callable[[str, str], Awaitable[int]] | None = None,
    workflow_service: WorkflowService | None = None,
) -> dict[str, Any]:
    """Execute a Directus-accepted schedule occurrence with its existing run id."""
    service = workflow_service or get_workflow_service()

    if decrypt_and_schedule is None:
        async def decrypt_and_schedule(owner_user_id: str, config_ref: str) -> int:
            vault_key_id = await asyncio.to_thread(service.resolve_user_vault_key_id, owner_user_id)
            config = await asyncio.to_thread(service.decrypt_schedule_config, owner_user_id, config_ref, vault_key_id)
            return WorkflowSchedulerService.next_run_at_from_schedule(config)

    async def execute_accepted_run(run_id: str, workflow_id: str, version_id: str, owner_user_id: str) -> None:
        vault_key_id = await asyncio.to_thread(service.resolve_user_vault_key_id, owner_user_id)
        workflow = await asyncio.to_thread(service.get_workflow_version, workflow_id, owner_user_id, version_id, vault_key_id)
        await WorkflowRunner(service).run_workflow(
            workflow,
            owner_user_id,
            vault_key_id=vault_key_id,
            trigger_type="schedule",
            run_id=run_id,
            version_id=version_id,
        )

    return await WorkflowSchedulerService(runtime_service).execute_due_trigger(
        trigger_id,
        decrypt_and_schedule,
        execute_accepted_run,
    )


async def scan_due_workflow_triggers_now(
    *,
    now: int | None = None,
    limit: int = 100,
    runtime_service: WorkflowRuntimeService,
) -> dict[str, Any]:
    async def dispatch_trigger(trigger_id: str) -> None:
        run_scheduled_workflow_trigger_task.delay(trigger_id)

    return await WorkflowSchedulerService(runtime_service).scan_due_triggers(
        now=now if now is not None else int(time.time()),
        limit=limit,
        dispatch_trigger=dispatch_trigger,
    )


def dispatch_workflow_event(
    user_id: str,
    event: dict[str, Any],
    *,
    runtime_service: WorkflowRuntimeService,
    workflow_service: WorkflowService | None = None,
) -> dict[str, Any]:
    return asyncio.run(_dispatch_workflow_event_async(user_id, event, runtime_service=runtime_service, workflow_service=workflow_service))


async def _dispatch_workflow_event_async(
    user_id: str,
    event: dict[str, Any],
    *,
    runtime_service: WorkflowRuntimeService,
    workflow_service: WorkflowService | None = None,
) -> dict[str, Any]:
    service = workflow_service or get_workflow_service()
    normalized_event = _normalize_event(service, user_id, event)
    if normalized_event is None:
        return {"accepted_run_ids": [], "accepted_count": 0, "rejected_reason": "invalid_event"}
    vault_key_id = service.resolve_user_vault_key_id(user_id)
    dispatcher = WorkflowEventDispatcher(runtime_service)
    accepted_run_ids: list[str] = []
    for trigger in service.repository.list_event_triggers(
        normalized_event["hashed_user_id"],
        normalized_event["hashed_project_id"],
        normalized_event["source"],
        normalized_event["event_type"],
    ):
        predicate_ref = trigger.get("encrypted_event_predicate_ref")
        if not isinstance(predicate_ref, str) or not predicate_ref:
            continue
        event_config = await asyncio.to_thread(service.decrypt_event_predicate, user_id, predicate_ref, vault_key_id)
        result = await dispatcher.dispatch(trigger, normalized_event, lambda payload, config=event_config: _event_filters_match(config, payload))
        if result.get("accepted") and isinstance(result.get("run_id"), str):
            accepted_run_ids.append(result["run_id"])
    return {"accepted_run_ids": accepted_run_ids, "accepted_count": len(accepted_run_ids)}


def _normalize_event(service: WorkflowService, user_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
    scope = dict(event.get("scope") or {})
    source = event.get("source")
    event_type = event.get("event_type") or event.get("type") or source
    event_id = event.get("event_id") or event.get("id")
    project_hash = scope.get("project_hash") or scope.get("hashed_project_id")
    project_id = scope.get("project_id")
    if project_hash is None and isinstance(project_id, str) and project_id:
        project_hash = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
    if not all(isinstance(value, str) and value for value in (source, event_type, event_id, project_hash)):
        return None
    return {
        "event_id": event_id,
        "hashed_user_id": service.repository.workflow_owner_hash(user_id),
        "hashed_project_id": project_hash,
        "source": source,
        "event_type": event_type,
        "payload": event.get("payload") or {},
    }


def _event_filters_match(config: dict[str, Any], payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    event_config = config.get("event") if isinstance(config.get("event"), dict) else config
    filters = event_config.get("filters") or []
    if isinstance(filters, dict) and filters.get("phrase"):
        filters = [{"field": "text", "op": "contains", "value": filters["phrase"]}]
    elif isinstance(filters, dict):
        filters = [
            {"field": field, "op": item.get("op"), "value": item.get("value")}
            for field, item in filters.items()
            if isinstance(item, dict)
        ]
    if not isinstance(filters, list) or not filters:
        return False
    for item in filters:
        if not isinstance(item, dict):
            return False
        actual = _value_at_path(payload, str(item.get("field") or ""))
        expected = item.get("value")
        op = item.get("op")
        if op == "eq" and actual != expected:
            return False
        if op == "contains" and expected not in str(actual or ""):
            return False
        if op == "starts_with" and not str(actual or "").startswith(str(expected)):
            return False
        if op == "exists" and actual is None:
            return False
        if op not in {"eq", "contains", "starts_with", "exists"}:
            return False
    return True


def _value_at_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not part:
            continue
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


@app.task(name="workflows.cleanup_expired_temporary", base=BaseServiceTask, bind=True)
def cleanup_expired_temporary_workflows_task(self: BaseServiceTask, user_id: str | None = None, now: int | None = None) -> dict[str, Any]:
    try:
        return cleanup_expired_temporary_workflows(user_id=user_id, now=now)
    except Exception as exc:
        logger.error("Workflow temporary cleanup task failed: %s", exc, exc_info=True)
        raise


@app.task(name="workflows.run", base=BaseServiceTask, bind=True)
def run_workflow_task(
    self: BaseServiceTask,
    workflow_id: str,
    user_id: str,
    run_id: str,
    version_id: str,
    trigger_type: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        async def run() -> dict[str, Any]:
            await self.initialize_services()
            return await run_workflow_now(
                workflow_id,
                user_id,
                run_id,
                version_id,
                trigger_type,
                input_payload,
                runtime_service=WorkflowRuntimeService(self.directus_service),
            )

        return asyncio.run(run())
    except Exception as exc:
        logger.error("Workflow run task failed: %s", exc, exc_info=True)
        raise


@app.task(name="workflows.run_scheduled_trigger", base=BaseServiceTask, bind=True)
def run_scheduled_workflow_trigger_task(self: BaseServiceTask, trigger_id: str) -> dict[str, Any]:
    try:
        async def run() -> dict[str, Any]:
            await self.initialize_services()
            return await run_scheduled_workflow_trigger_now(
                trigger_id,
                runtime_service=WorkflowRuntimeService(self.directus_service),
            )

        return asyncio.run(run())
    except Exception as exc:
        logger.error("Workflow scheduled trigger task failed: %s", exc, exc_info=True)
        raise


@app.task(name="workflows.scan_due_triggers", base=BaseServiceTask, bind=True)
def scan_due_workflow_triggers_task(self: BaseServiceTask, now: int | None = None, limit: int = 100) -> dict[str, Any]:
    try:
        async def run() -> dict[str, Any]:
            await self.initialize_services()
            return await scan_due_workflow_triggers_now(
                now=now,
                limit=limit,
                runtime_service=WorkflowRuntimeService(self.directus_service),
            )

        return asyncio.run(run())
    except Exception as exc:
        logger.error("Workflow due-trigger scanner task failed: %s", exc, exc_info=True)
        raise


@app.task(name="workflows.dispatch_event", base=BaseServiceTask, bind=True)
def dispatch_workflow_event_task(self: BaseServiceTask, user_id: str, event: dict[str, Any]) -> dict[str, Any]:
    try:
        async def run() -> dict[str, Any]:
            await self.initialize_services()
            return await _dispatch_workflow_event_async(
                user_id,
                event,
                runtime_service=WorkflowRuntimeService(self.directus_service),
            )

        return asyncio.run(run())
    except Exception as exc:
        logger.error("Workflow event dispatch task failed: %s", exc, exc_info=True)
        raise
