# backend/core/api/app/tasks/workflow_assistant_tasks.py
#
# Durable cleanup entry point for expired assistant workflow proposals. Pending
# approval records never execute automatically when they expire.

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.core.api.app.services.workflow_assistant_service import (
    DirectusWorkflowAssistantProposalRepository,
    WorkflowAssistantService,
)
from backend.core.api.app.services.workflow_runtime_service import WorkflowRuntimeService
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app


logger = logging.getLogger(__name__)


def expire_workflow_assistant_proposals(now: int | None = None) -> dict[str, Any]:
    service = WorkflowAssistantService(
        WorkflowService(repository=DirectusWorkflowRepository()),
        proposal_repository=DirectusWorkflowAssistantProposalRepository(),
    )
    return {"expired": service.expire_pending(now=now)}


async def execute_workflow_assistant_countdown(
    user_id: str,
    proposal_id: str,
    *,
    workflow_service: WorkflowService | None = None,
    proposal_repository: Any | None = None,
    runtime_service: WorkflowRuntimeService,
    enqueue_accepted_run: Any,
) -> dict[str, Any]:
    """Advance one durable assistant run proposal through the accepted-run handoff."""
    service = WorkflowAssistantService(
        workflow_service or WorkflowService(repository=DirectusWorkflowRepository()),
        proposal_repository=proposal_repository or DirectusWorkflowAssistantProposalRepository(),
    )
    return await service.execute_after_countdown(
        user_id,
        proposal_id,
        runtime_service=runtime_service,
        enqueue_accepted_run=enqueue_accepted_run,
    )


@app.task(name="workflows.expire_assistant_proposals", base=BaseServiceTask, bind=True)
def expire_workflow_assistant_proposals_task(self: BaseServiceTask, now: int | None = None) -> dict[str, Any]:
    try:
        return expire_workflow_assistant_proposals(now=now)
    except Exception as exc:
        logger.error("Workflow assistant proposal expiry failed: %s", exc, exc_info=True)
        raise


@app.task(name="workflows.execute_assistant_countdown", base=BaseServiceTask, bind=True)
def execute_workflow_assistant_countdown_task(
    self: BaseServiceTask,
    user_id: str,
    proposal_id: str,
) -> dict[str, Any]:
    try:
        async def run() -> dict[str, Any]:
            await self.initialize_services()

            def enqueue_accepted_run(
                workflow_id: str,
                owner_user_id: str,
                run_id: str,
                version_id: str,
                trigger_type: str,
                input_payload: dict[str, Any],
            ) -> None:
                from backend.core.api.app.tasks.workflow_tasks import run_workflow_task

                run_workflow_task.delay(workflow_id, owner_user_id, run_id, version_id, trigger_type, input_payload)

            return await execute_workflow_assistant_countdown(
                user_id,
                proposal_id,
                runtime_service=WorkflowRuntimeService(self.directus_service),
                enqueue_accepted_run=enqueue_accepted_run,
            )

        return asyncio.run(run())
    except Exception as exc:
        logger.error("Workflow assistant countdown execution failed: %s", exc, exc_info=True)
        raise
