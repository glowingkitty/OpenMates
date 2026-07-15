# backend/apps/tasks/skills/create_skill.py
#
# Tasks app create skill. The skill can stage one or more task creations from a
# chat turn and returns embed-ready child task payloads for the shared app-skill
# parent embed flow. Durable task content still waits for client encryption.

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.ai.processing.task_runtime_tools import TASK_TOOL_CREATE
from backend.apps.ai.processing.task_tool_context import TaskToolContext
from backend.apps.ai.processing.task_tool_executor import execute_task_tool_call
from backend.apps.base_skill import BaseSkill
from backend.apps.tasks.skills.assignment import normalize_task_assignment, product_assignee_from_storage

logger = logging.getLogger(__name__)

TASK_CREATE_STATUS_VALUES = {"backlog", "todo", "in_progress", "blocked"}


class CreateTasksResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "tasks"
    skill_id: str = "create"
    status: str = "finished"
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int = 0
    error: str | None = None


class TaskStageService:
    """Stage task creation jobs for client-encrypted durable persistence."""

    def __init__(
        self,
        *,
        cache_service: Any | None = None,
        encryption_service: Any | None = None,
        user_vault_key_id: str | None = None,
    ) -> None:
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.utils.encryption import EncryptionService

        self.cache_service = cache_service or CacheService()
        self.encryption_service = encryption_service or EncryptionService()
        self.user_vault_key_id = user_vault_key_id

    async def stage_create(
        self,
        *,
        user_id: str,
        chat_id: str | None,
        message_id: str | None,
        title: str,
        description: str,
        assignee_type: str,
        status: str,
    ) -> dict[str, Any]:
        context = TaskToolContext(user_id=user_id, chat_id=chat_id or "")
        result = await execute_task_tool_call(
            tool_name=TASK_TOOL_CREATE,
            args={
                "title": title,
                "description": description,
                "assignee_type": assignee_type,
                "status": status,
            },
            context=context,
            cache_service=self.cache_service,
            directus_service=None,
            encryption_service=self.encryption_service,
            user_vault_key_id=self.user_vault_key_id,
            message_id=message_id or f"task-create-{int(time.time())}",
        )
        event = result.get("event") or {}
        job = result.get("job") or {}
        return {
            "task_id": event.get("task_id") or job.get("task_id"),
            "short_id": event.get("short_id"),
            "status": event.get("status") or status,
            "assignee_type": assignee_type,
            "task_update_job_id": job.get("job_id"),
        }


class CreateSkill(BaseSkill):
    """Create one or more tasks from assistant-provided task descriptions."""

    async def execute(
        self,
        tasks: list[dict[str, Any]] | None = None,
        title: str | None = None,
        description: str | None = None,
        assignee: str | None = None,
        status: str = "todo",
        user_id: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        task_stage_service: Any = None,
        cache_service: Any | None = None,
        encryption_service: Any | None = None,
        user_vault_key_id: str | None = None,
        **kwargs: Any,
    ) -> CreateTasksResponse:
        try:
            if not user_id:
                raise ValueError("Task create requires an authenticated user")
            task_inputs = _normalize_task_inputs(tasks, title=title, description=description, assignee=assignee, status=status)
            stage_service = task_stage_service or TaskStageService(
                cache_service=cache_service,
                encryption_service=encryption_service,
                user_vault_key_id=user_vault_key_id,
            )
            results: list[dict[str, Any]] = []
            for task_input in task_inputs:
                assignment = normalize_task_assignment(task_input.get("assignee"))
                task_status = _safe_create_status(task_input.get("status"))
                staged = await stage_service.stage_create(
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    title=task_input["title"],
                    description=str(task_input.get("description") or ""),
                    assignee_type=assignment.storage_assignee_type,
                    status=task_status,
                )
                results.append(_task_embed_result(task_input, staged, task_status))
            return CreateTasksResponse(success=True, results=results, result_count=len(results))
        except Exception as exc:
            logger.error("Task create skill failed: %s", exc, exc_info=True)
            return CreateTasksResponse(success=False, error=str(exc))


def _normalize_task_inputs(
    tasks: list[dict[str, Any]] | None,
    *,
    title: str | None,
    description: str | None,
    assignee: str | None,
    status: str,
) -> list[dict[str, Any]]:
    raw_tasks = tasks if tasks is not None else [{"title": title, "description": description, "assignee": assignee, "status": status}]
    normalized: list[dict[str, Any]] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            continue
        task_title = str(raw_task.get("title") or "").strip()
        if not task_title:
            continue
        normalized.append({**raw_task, "title": task_title})
    if not normalized:
        raise ValueError("Task create requires at least one task title")
    return normalized


def _safe_create_status(value: Any) -> str:
    status = str(value or "todo").strip()
    return status if status in TASK_CREATE_STATUS_VALUES else "todo"


def _task_embed_result(task_input: dict[str, Any], staged: dict[str, Any], status: str) -> dict[str, Any]:
    assignee_type = staged.get("assignee_type") or normalize_task_assignment(task_input.get("assignee")).storage_assignee_type
    return {
        "type": "task",
        "parent_app_skill_type": "app_skill_use",
        "task_id": staged.get("task_id"),
        "short_id": staged.get("short_id"),
        "title": task_input["title"],
        "description": str(task_input.get("description") or ""),
        "status": staged.get("status") or status,
        "assignee": product_assignee_from_storage(assignee_type),
        "assignee_type": assignee_type,
        "task_update_job_id": staged.get("task_update_job_id"),
        "pending_client_persistence": bool(staged.get("task_update_job_id")),
    }
