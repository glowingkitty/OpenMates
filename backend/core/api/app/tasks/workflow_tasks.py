# backend/core/api/app/tasks/workflow_tasks.py
#
# Celery task entry points for Workflows V1.
# These wrappers keep scheduled cleanup, queued execution, and event dispatch on
# the same WorkflowService/WorkflowRunner contracts used by the API and SDKs.
# Directus-backed persistence can replace the service repository without changing
# the Celery task contract.

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.core.api.app.services.workflow_event_service import WorkflowEventService
from backend.core.api.app.services.workflow_models import WorkflowNodeType
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

_WORKFLOW_SERVICE = WorkflowService(repository=DirectusWorkflowRepository())
_WORKFLOW_EVENT_SERVICE = WorkflowEventService()


def get_workflow_service() -> WorkflowService:
    return _WORKFLOW_SERVICE


def cleanup_expired_temporary_workflows(user_id: str | None = None, now: int | None = None) -> dict[str, Any]:
    deleted = get_workflow_service().cleanup_expired_temporary_workflows(user_id=user_id, now=now)
    return {"deleted": deleted}


async def run_workflow_now(
    workflow_id: str,
    user_id: str,
    trigger_type: str = "schedule",
    input_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    service = get_workflow_service()
    workflow = service.get_workflow(workflow_id, user_id)
    run = await WorkflowRunner(service).run_workflow(
        workflow,
        user_id,
        trigger_type=trigger_type,
        input_payload=input_payload or {},
    )
    return run.model_dump(mode="json")


def dispatch_workflow_event(user_id: str, event: dict[str, Any]) -> dict[str, Any]:
    service = get_workflow_service()
    matcher = _WORKFLOW_EVENT_SERVICE
    normalized_event = _normalize_event(user_id, event)
    matched_workflow_ids: list[str] = []
    for workflow in service.list_workflows(user_id):
        if not workflow.enabled:
            continue
        detail = service.get_workflow(workflow.id, user_id)
        trigger = next((node for node in detail.graph.nodes if node.id == detail.graph.trigger_node_id), None)
        if trigger is None or trigger.type != WorkflowNodeType.EVENT_TRIGGER:
            continue
        if matcher.matches(_normalize_trigger_config(trigger.config), normalized_event):
            matched_workflow_ids.append(workflow.id)
    return {"matched_workflow_ids": matched_workflow_ids, "matched_count": len(matched_workflow_ids)}


def _normalize_event(user_id: str, event: dict[str, Any]) -> dict[str, Any]:
    scope = dict(event.get("scope") or {})
    scope.setdefault("user_id", user_id)
    return {
        "type": event.get("type") or event.get("source"),
        "scope": scope,
        "payload": event.get("payload") or {},
    }


def _normalize_trigger_config(config: dict[str, Any]) -> dict[str, Any]:
    event_config = config.get("event") if isinstance(config.get("event"), dict) else config
    filters = event_config.get("filters") or []
    if isinstance(filters, dict) and filters.get("phrase"):
        filters = [{"field": "text", "op": "contains", "value": filters["phrase"]}]
    elif not isinstance(filters, list):
        filters = []
    rate_limit = event_config.get("rate_limit") or {}
    rate_limit_seconds = event_config.get("rate_limit_seconds") or 0
    if isinstance(rate_limit, dict) and rate_limit.get("max_per_hour"):
        rate_limit_seconds = max(1, int(3600 / int(rate_limit["max_per_hour"])))
    return {
        "event_type": event_config.get("event_type") or event_config.get("source"),
        "scope": event_config.get("scope") or {},
        "filters": filters,
        "rate_limit_seconds": rate_limit_seconds,
    }


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
    trigger_type: str = "schedule",
    input_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return asyncio.run(run_workflow_now(workflow_id, user_id, trigger_type=trigger_type, input_payload=input_payload))
    except Exception as exc:
        logger.error("Workflow run task failed: %s", exc, exc_info=True)
        raise


@app.task(name="workflows.dispatch_event", base=BaseServiceTask, bind=True)
def dispatch_workflow_event_task(self: BaseServiceTask, user_id: str, event: dict[str, Any]) -> dict[str, Any]:
    try:
        return dispatch_workflow_event(user_id, event)
    except Exception as exc:
        logger.error("Workflow event dispatch task failed: %s", exc, exc_info=True)
        raise
