# backend/apps/workflows/skills/create_or_modify_skill.py
#
# Assistant-facing workflow authoring. Natural-language requests use the same
# durable, owner-scoped input service as the Workflow UI; explicit graph calls
# remain compatible with the existing proposal interface.

from __future__ import annotations

import logging
import asyncio
from typing import Any
from types import SimpleNamespace

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.workflows.skills._services import (
    dump_model, get_assistant_service, get_workflow_input_service_for_skill, require_user_id,
)

logger = logging.getLogger(__name__)


class CreateOrModifyWorkflowResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "workflows"
    skill_id: str = "create-or-modify"
    status: str = "finished"
    workflow: dict[str, Any] | None = None
    run: dict[str, Any] | None = None
    workflows: list[dict[str, Any]] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int = 0
    message: str | None = None
    error: str | None = None


class CreateOrModifySkill(BaseSkill):
    """Author workflows from natural language or a legacy explicit graph."""

    async def execute(
        self,
        instruction: str | None = None,
        title: str | None = None,
        graph: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        execution_mode: str = "saved",
        input: dict[str, Any] | None = None,
        message_destination_overrides: dict[str, str] | None = None,
        return_outputs: dict[str, dict[str, str]] | None = None,
        workflows: list[dict[str, Any]] | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        timezone: str | None = None,
        user_vault_key_id: str | None = None,
        secrets_manager: Any = None,
        workflow_input_service: Any = None,
        workflow_assistant_service: Any = None,
        workflow_service: Any = None,
        directus_service: Any = None,
        workflow_runtime_service: Any = None,
        **kwargs: Any,
    ) -> CreateOrModifyWorkflowResponse:
        try:
            owner = require_user_id(user_id)
            if execution_mode not in {"saved", "run_once"}:
                raise ValueError("execution_mode must be saved or run_once")
            if team_id and execution_mode == "run_once":
                raise ValueError("Team workflow execution is not supported")
            if execution_mode == "run_once" and (not chat_id or not message_id or workflow_id):
                raise ValueError("One-time chat execution requires the current chat and message, with no selected workflow")
            if instruction is not None:
                if graph is not None or workflows is not None:
                    raise ValueError("Natural-language workflow authoring cannot include assistant-authored graphs")
                if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 16_000:
                    raise ValueError("Workflow instruction must contain 1 to 16000 characters")
                service = workflow_input_service or get_workflow_input_service_for_skill(
                    secrets_manager=secrets_manager, workflow_service=workflow_service,
                )
                result = await asyncio.to_thread(
                    service.start, user_id=owner, text=instruction.strip(),
                    selected_workflow_id=workflow_id, timezone=timezone or "UTC",
                    vault_key_id=user_vault_key_id, source_chat_id=chat_id,
                    optimistic_save=False,
                    idempotency_key=f"chat:{chat_id}:{message_id}:{execution_mode}" if chat_id and message_id else None,
                    execution_mode=execution_mode,
                    return_outputs=return_outputs,
                    **({"team_id": team_id} if team_id else {}),
                )
                if result.status == "needs_clarification":
                    return CreateOrModifyWorkflowResponse(
                        success=True, status="needs_clarification", message=result.message,
                    )
                if result.status == "queued":
                    return CreateOrModifyWorkflowResponse(
                        success=True, status="queued", message=result.message or "Workflow save is pending.",
                    )
                if result.status == "draft" and not result.workflow and not getattr(result, "workflows", None):
                    return CreateOrModifyWorkflowResponse(
                        success=True, status="draft", message=result.message or "Workflow draft needs more detail.",
                    )
                if result.status not in {"executed", "draft"}:
                    return CreateOrModifyWorkflowResponse(
                        success=False, status=result.status, error=result.error or "Workflow was not saved.",
                    )
                saved = getattr(result, "workflows", None) or ([result.workflow] if result.workflow else [])
                workflow_dicts = [dump_model(item) for item in saved]
                if not workflow_dicts:
                    return CreateOrModifyWorkflowResponse(
                        success=False, status="error", error="Workflow input completed without a saved workflow.",
                    )
                accepted_run = None
                if execution_mode == "run_once":
                    if len(workflow_dicts) != 1 or workflow_dicts[0].get("lifecycle") != "chat_embed":
                        raise ValueError("One-time authoring did not create one chat-owned workflow")
                    from backend.core.api.app.routes.workflows import WorkflowRunRequest, _accept_workflow_run
                    from backend.core.api.app.services.workflow_runtime_service import WorkflowRuntimeService
                    from backend.core.api.app.services.directus.directus import DirectusService
                    workflow_model = saved[0]
                    owned_directus = directus_service is None
                    directus = directus_service or DirectusService()
                    try:
                        run_body = WorkflowRunRequest(
                            input=input or {}, source_chat_id=chat_id,
                            message_destination_overrides=message_destination_overrides or {},
                            return_outputs=return_outputs or {},
                        )
                        request = SimpleNamespace(
                            state=SimpleNamespace(auth_source="session"),
                            headers={"Idempotency-Key": f"chat:{chat_id}:{message_id}:run_once"},
                        )
                        accepted_run = await _accept_workflow_run(
                            workflow_model.id, run_body, request,
                            SimpleNamespace(id=owner, vault_key_id=user_vault_key_id),
                            service.workflow_service,
                            workflow_runtime_service or WorkflowRuntimeService(directus),
                            directus, workflow_model,
                        )
                    finally:
                        if owned_directus:
                            await directus.close()
                return CreateOrModifyWorkflowResponse(
                    success=True, status="finished" if result.status == "executed" else "draft",
                    workflow=workflow_dicts[0],
                    run=accepted_run,
                    workflows=workflow_dicts,
                    results=[_workflow_embed_result(item, accepted_run) for item in workflow_dicts],
                    result_count=len(workflow_dicts),
                    message=result.message or getattr(result, "partial_warning", None),
                )
            if workflows is not None:
                raise ValueError("Workflow create-or-modify accepts exactly one workflow per skill call")
            if execution_mode == "run_once":
                raise ValueError("One-time chat execution requires a natural-language instruction")
            if team_id:
                raise ValueError("Team workflow graph proposals are not supported; use a natural-language instruction")
            workflow_title = str(title or "").strip()
            if not workflow_title:
                raise ValueError("Workflow create-or-modify requires a title")
            assistant = get_assistant_service(workflow_assistant_service, workflow_service)
            workflow = assistant.create_or_modify(
                owner,
                title=workflow_title,
                graph=graph,
                workflow_id=workflow_id,
                source_chat_id=chat_id,
            )
            workflow_dict = dump_model(workflow)
            result = _workflow_embed_result(workflow_dict)
            return CreateOrModifyWorkflowResponse(
                success=True,
                workflow=workflow_dict,
                results=[result],
                result_count=1,
            )
        except Exception as exc:
            logger.error("Workflow create-or-modify skill failed: %s", exc, exc_info=True)
            return CreateOrModifyWorkflowResponse(success=False, error=str(exc))


def _workflow_embed_result(workflow: dict[str, Any], run: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "workflow",
        "parent_app_skill_type": "app_skill_use",
        "workflow_id": workflow.get("workflow_id") or workflow.get("id"),
        "title": workflow.get("title") or "",
        "status": workflow.get("status") or "draft",
        "source_chat_id": workflow.get("source_chat_id"),
        "lifecycle": workflow.get("lifecycle", "persisted"),
        "graph": workflow.get("graph"),
        "run_id": run.get("id") if run else None,
        "run": run,
    }
