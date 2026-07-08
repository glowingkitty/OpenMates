# backend/core/api/app/services/user_task_service.py
#
# Tasks V1 orchestration boundary. This service keeps product task semantics
# separate from Celery task polling and centralizes conflict checks before route,
# CLI, SDK, and future AI execution layers mutate task records.

import time
import uuid
from typing import Any, Awaitable, Callable

from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods, hash_id


TRANSIENT_AI_FIELDS = {
    "plaintext_title",
    "plaintext_description",
    "plaintext_latest_instruction",
    "plaintext_chat_title",
    "plaintext_project_context",
}

AiDispatcher = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]


class UserTaskConflictError(ValueError):
    """Raised when a task update is based on a stale client version."""


class UserTaskNotFoundError(ValueError):
    """Raised when a user task does not exist or belongs to another user."""


class UserTaskService:
    def __init__(
        self,
        task_methods: UserTaskMethods,
        *,
        cache_service: Any | None = None,
        ai_dispatcher: AiDispatcher | None = None,
    ):
        self.task_methods = task_methods
        self.cache_service = cache_service
        self.ai_dispatcher = ai_dispatcher

    async def list_tasks(self, user_id: str, **filters: Any) -> list[dict[str, Any]]:
        return await self.task_methods.list_tasks(user_id, **filters)

    async def create_task(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("status", "todo")
        payload.setdefault("assignee_type", "user")
        if payload.get("assignee_type") == "ai" and payload.get("due_at") is None:
            now = payload.get("updated_at") or payload.get("created_at")
            primary_chat_id = payload.get("primary_chat_id")
            active_tasks = []
            if primary_chat_id:
                active_tasks = await self.task_methods.list_active_ai_tasks_for_chat(user_id, primary_chat_id)
            if active_tasks:
                payload["status"] = "todo"
                payload.setdefault("ai_execution_state", "waiting_for_previous_task")
            else:
                payload["status"] = "in_progress"
                payload.setdefault("ai_execution_state", "queued")
                payload.setdefault("started_at", now)
        created = await self.task_methods.create_task(user_id, payload)
        if not created:
            raise ValueError("Failed to create task")
        return created

    async def update_task(self, task_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = await self.task_methods.get_task(task_id, user_id)
        if not existing:
            raise UserTaskNotFoundError("Task not found")
        expected_version = patch.get("version")
        if expected_version is not None and int(expected_version) != int(existing.get("version") or 1):
            raise UserTaskConflictError("Task was modified by another client")
        update = dict(patch)
        update.pop("version", None)
        updated = await self.task_methods.update_task(task_id, user_id, update)
        if not updated:
            raise ValueError("Failed to update task")
        return updated

    async def start_ai(self, task_id: str, user_id: str, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        existing = await self.task_methods.get_task(task_id, user_id)
        if not existing:
            raise UserTaskNotFoundError("Task not found")

        raw_patch = dict(patch or {})
        expected_version = raw_patch.get("version")
        if expected_version is not None and int(expected_version) != int(existing.get("version") or 1):
            raise UserTaskConflictError("Task was modified by another client")

        now = int(raw_patch.get("updated_at") or time.time())
        instruction = self._build_transient_ai_instruction(raw_patch)
        chat_id = raw_patch.get("primary_chat_id") or existing.get("primary_chat_id")
        if instruction and not chat_id:
            raise ValueError("primary_chat_id is required to start a task with AI")
        if chat_id:
            active_tasks = await self.task_methods.list_active_ai_tasks_for_chat(user_id, chat_id, exclude_task_id=task_id)
            active_tasks = [task for task in active_tasks if task.get("task_id") != task_id]
            if active_tasks:
                raise UserTaskConflictError("Another AI task is already active in this chat")

        update = {
            key: value
            for key, value in raw_patch.items()
            if key not in TRANSIENT_AI_FIELDS and key != "version"
        }
        update.update(
            {
                "status": "in_progress",
                "assignee_type": "ai",
                "ai_execution_state": "queued",
                "started_at": existing.get("started_at") or now,
                "updated_at": now,
            }
        )
        updated = await self.task_methods.update_task(task_id, user_id, update)
        if not updated:
            raise UserTaskNotFoundError("Task not found")

        if instruction and chat_id:
            try:
                ai_task_id = await self._dispatch_transient_ai_task(
                    task_id=task_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    instruction=instruction,
                    created_at=now,
                    current_chat_title=raw_patch.get("plaintext_chat_title"),
                )
                if ai_task_id and self.cache_service:
                    await self.cache_service.set_active_ai_task(chat_id, ai_task_id)
            except Exception:
                await self.task_methods.update_task(
                    task_id,
                    user_id,
                    {
                        "status": "blocked",
                        "ai_execution_state": "failed",
                        "blocked_reason_code": "ai_dispatch_failed",
                        "updated_at": int(time.time()),
                    },
                )
                raise

        return updated

    def _build_transient_ai_instruction(self, patch: dict[str, Any]) -> str:
        title = str(patch.get("plaintext_title") or "").strip()
        description = str(patch.get("plaintext_description") or "").strip()
        latest_instruction = str(patch.get("plaintext_latest_instruction") or "").strip()
        project_context = str(patch.get("plaintext_project_context") or "").strip()
        parts = ["You are executing an OpenMates user task."]
        if title:
            parts.append(f"Task: {title}")
        if description:
            parts.append(f"Details: {description}")
        if latest_instruction:
            parts.append(f"Latest instruction: {latest_instruction}")
        if project_context:
            parts.append(f"Project context: {project_context}")
        return "\n\n".join(parts) if len(parts) > 1 else ""

    async def _dispatch_transient_ai_task(
        self,
        *,
        task_id: str,
        user_id: str,
        chat_id: str,
        instruction: str,
        created_at: int,
        current_chat_title: str | None = None,
    ) -> str | None:
        dispatcher = self.ai_dispatcher
        if dispatcher is None:
            from backend.core.api.app.services.skill_registry import get_global_registry

            dispatcher = get_global_registry().dispatch_skill

        message_id = f"task-{task_id}-{uuid.uuid4()}"
        response = await dispatcher(
            "ai",
            "ask",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "user_id": user_id,
                "user_id_hash": hash_id(user_id),
                "message_history": [
                    AIHistoryMessage(
                        content=instruction,
                        role="user",
                        created_at=created_at,
                    ).model_dump()
                ],
                "current_user_content": instruction,
                "chat_has_title": True,
                "current_chat_title": current_chat_title,
                "user_preferences": {},
                "user_task_id": task_id,
            },
        )
        return response.get("task_id") if isinstance(response, dict) else None
