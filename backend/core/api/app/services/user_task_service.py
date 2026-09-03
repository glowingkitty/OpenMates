# backend/core/api/app/services/user_task_service.py
#
# Tasks V1 orchestration boundary. This service keeps product task semantics
# separate from Celery task polling and centralizes conflict checks before route,
# CLI, SDK, and future AI execution layers mutate task records.
# test-file: backend/tests/test_user_task_activity_api.py

import time
import uuid
from typing import Any, Awaitable, Callable

from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods, hash_id
from backend.core.api.app.services.user_task_admission_service import TaskAdmissionService
from backend.core.api.app.services.user_task_execution_service import UserTaskExecutionService


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
        admission_service: TaskAdmissionService | None = None,
        encryption_service: Any | None = None,
    ):
        self.task_methods = task_methods
        self.cache_service = cache_service
        self.ai_dispatcher = ai_dispatcher
        self.execution_service = (
            UserTaskExecutionService(
                task_methods,
                encryption_service=encryption_service,
                cache_service=cache_service,
                ai_dispatcher=ai_dispatcher,
            )
            if encryption_service is not None
            else None
        )
        self.admission_service = admission_service or TaskAdmissionService(
            task_methods,
            on_admitted=self.execution_service.dispatch_admitted if self.execution_service else None,
        )

    async def list_tasks(self, user_id: str, **filters: Any) -> list[dict[str, Any]]:
        return await self.task_methods.list_tasks(user_id, **filters)

    async def list_task_activity(self, task_id: str, user_id: str, **filters: Any) -> list[dict[str, Any]]:
        if not await self.task_methods.get_task(task_id, user_id, filters.get("team_id")):
            raise UserTaskNotFoundError("Task not found")
        return await self.task_methods.list_task_activity(user_id, task_id, **filters)

    async def create_task_activity(
        self,
        task_id: str,
        user_id: str,
        payload: dict[str, Any],
        **options: Any,
    ) -> dict[str, Any]:
        if not await self.task_methods.get_task(task_id, user_id, options.get("team_id")):
            raise UserTaskNotFoundError("Task not found")
        try:
            created = await self.task_methods.create_task_activity(user_id, task_id, payload, **options)
        except ValueError as exc:
            if "Task Activity entry id conflicts" in str(exc):
                raise UserTaskConflictError("TASK_ACTIVITY_ENTRY_CONFLICT") from exc
            raise
        if not created:
            raise ValueError("Failed to create Task Activity entry")
        return created

    async def delete_task_activity(
        self,
        task_id: str,
        entry_id: str,
        user_id: str,
        **options: Any,
    ) -> dict[str, Any]:
        if not await self.task_methods.get_task(task_id, user_id, options.get("team_id")):
            raise UserTaskNotFoundError("Task not found")
        try:
            return await self.task_methods.delete_task_activity(user_id, task_id, entry_id, **options)
        except ValueError as exc:
            if str(exc) == "TASK_ACTIVITY_ALREADY_DELETED":
                raise UserTaskConflictError("TASK_ACTIVITY_ALREADY_DELETED") from exc
            raise

    async def create_task(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        transient = {key: payload.pop(key) for key in TRANSIENT_AI_FIELDS if key in payload}
        payload.setdefault("status", "todo")
        payload.setdefault("assignee_type", "user")
        if payload.get("assignee_type") == "ai":
            payload["status"] = "todo"
            payload.setdefault("queue_state", "waiting")
            payload.setdefault("ai_execution_state", "waiting_for_capacity")
        created = await self.task_methods.create_task(user_id, payload)
        if not created:
            raise ValueError("Failed to create task")
        if payload.get("assignee_type") == "ai" and transient:
            now = int(payload.get("updated_at") or payload.get("created_at") or time.time())
            due_at = payload.get("due_at")
            start_patch = {
                **transient,
                "version": int(created.get("version") or payload.get("version") or 1),
                "primary_chat_id": payload.get("primary_chat_id"),
                "updated_at": now,
            }
            if due_at is None or int(due_at) <= now:
                return await self.start_ai(str(created.get("task_id") or payload.get("task_id")), user_id, start_patch)
            instruction = self._build_transient_ai_instruction(transient)
            chat_id = payload.get("primary_chat_id")
            if instruction and chat_id and self.execution_service:
                await self.execution_service.stage(
                    task_id=str(created.get("task_id") or payload.get("task_id")),
                    user_id=user_id,
                    chat_id=chat_id,
                    instruction=instruction,
                    current_chat_title=transient.get("plaintext_chat_title"),
                    created_at=now,
                )
        return created

    async def update_task(self, task_id: str, user_id: str, patch: dict[str, Any], *, team_id: str | None = None) -> dict[str, Any]:
        update = dict(patch)
        expected_version = update.get("version")
        if expected_version is None:
            raise ValueError("Task update requires expected version")
        updated = await self.task_methods.update_task_if_version(
            task_id,
            user_id,
            update,
            int(expected_version),
            team_id=team_id,
        )
        if not updated:
            current = await self.task_methods.get_task(task_id, user_id, team_id)
            if not current:
                raise UserTaskNotFoundError("Task not found")
            current_version = current.get("version")
            if current_version is None or int(current_version) != int(expected_version):
                raise UserTaskConflictError("Task was modified by another client")
            raise ValueError("Failed to update task")
        return updated

    async def start_ai(
        self,
        task_id: str,
        user_id: str,
        patch: dict[str, Any] | None = None,
        *,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        existing = await self.task_methods.get_task(task_id, user_id, team_id)
        if not existing:
            raise UserTaskNotFoundError("Task not found")

        raw_patch = dict(patch or {})
        expected_version = raw_patch.get("version")
        if expected_version is None:
            raise ValueError("Task update requires expected version")
        existing_version = existing.get("version")
        if existing_version is None:
            raise UserTaskConflictError("Task version is required before mutation")
        if int(expected_version) != int(existing_version):
            raise UserTaskConflictError("Task was modified by another client")

        now = int(raw_patch.get("updated_at") or time.time())
        instruction = self._build_transient_ai_instruction(raw_patch)
        chat_id = raw_patch.get("primary_chat_id") or existing.get("primary_chat_id")
        if instruction and not chat_id:
            raise ValueError("primary_chat_id is required to start a task with AI")
        update = {
            key: value
            for key, value in raw_patch.items()
            if key not in TRANSIENT_AI_FIELDS and key != "version"
        }
        requires_staging = bool(instruction and chat_id and self.execution_service)
        update.update(
            {
                "status": "todo",
                "assignee_type": "ai",
                "queue_state": "staging" if requires_staging else "waiting",
                "ai_execution_state": "preparing_execution_context" if requires_staging else "waiting_for_capacity",
                "updated_at": now,
            }
        )
        updated = await self.task_methods.update_task_if_version(
            task_id,
            user_id,
            update,
            int(existing_version),
            team_id=team_id,
        )
        if not updated:
            raise UserTaskConflictError("Task was modified by another client")

        if requires_staging and self.execution_service:
            try:
                await self.execution_service.stage(
                    task_id=task_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    instruction=instruction,
                    current_chat_title=raw_patch.get("plaintext_chat_title"),
                    created_at=now,
                    team_id=team_id,
                )
                prepared_version = updated.get("version")
                if prepared_version is None:
                    raise UserTaskConflictError("Task version is required after execution context staging")
                updated = await self.task_methods.update_task_if_version(
                    task_id,
                    user_id,
                    {
                        "status": "todo",
                        "assignee_type": "ai",
                        "queue_state": "waiting",
                        "ai_execution_state": "waiting_for_capacity",
                        "updated_at": now,
                    },
                    int(prepared_version),
                    team_id=team_id,
                )
                if not updated:
                    raise UserTaskConflictError("Task was modified while staging its execution context")
            except Exception:
                current = await self.task_methods.get_task(task_id, user_id, team_id)
                current_version = (current or {}).get("version")
                if (current or {}).get("queue_state") == "staging" and current_version is not None:
                    await self.task_methods.update_task_if_version(
                        task_id,
                        user_id,
                        {
                            "status": "blocked",
                            "queue_state": "waiting_for_user",
                            "ai_execution_state": "failed",
                            "blocked_reason_code": "execution_context_staging_failed",
                            "updated_at": int(time.time()),
                        },
                        int(current_version),
                        team_id=team_id,
                    )
                raise

        admission = await self.admission_service.admit_available(
            user_id,
            team_id=team_id,
            now=now,
            preferred_chat_id=chat_id,
        )
        admitted = next(
            (task for task in admission.get("admitted_tasks", []) if task.get("task_id") == task_id),
            None,
        )
        if not admitted:
            return updated
        updated = admitted

        if instruction and chat_id and self.execution_service is None:
            try:
                ai_task_id = await self._dispatch_transient_ai_task(
                    task_id=task_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    instruction=instruction,
                    created_at=now,
                    current_chat_title=raw_patch.get("plaintext_chat_title"),
                    team_id=team_id,
                )
                if ai_task_id and self.cache_service:
                    await self.cache_service.set_active_ai_task(chat_id, ai_task_id)
            except Exception:
                await self.task_methods.update_task_if_version(
                    task_id,
                    user_id,
                    {
                        "status": "blocked",
                        "ai_execution_state": "failed",
                        "blocked_reason_code": "ai_dispatch_failed",
                        "updated_at": int(time.time()),
                    },
                    int(updated["version"]),
                    team_id=team_id,
                )
                await self.admission_service.admit_available(
                    user_id,
                    team_id=team_id,
                    now=int(time.time()),
                    preferred_chat_id=chat_id,
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
        team_id: str | None = None,
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
                "team_id": team_id,
                "team_id_hash": hash_id(team_id) if team_id else None,
            },
        )
        return response.get("task_id") if isinstance(response, dict) else None
