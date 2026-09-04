# backend/core/api/app/services/user_task_queue_service.py
#
# Queue transition logic for Tasks V1. This keeps explicit task actions such as
# complete, block, unblock, and skip deterministic and separate from FastAPI
# route parsing. Durable task content remains client-encrypted; this service only
# mutates safe metadata used for queue orchestration.

import time
from typing import Any

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods
from backend.core.api.app.services.user_task_admission_service import TaskAdmissionService
from backend.core.api.app.services.user_task_execution_service import UserTaskExecutionService
from backend.core.api.app.services.user_task_service import UserTaskConflictError, UserTaskNotFoundError


class UserTaskQueueService:
    def __init__(
        self,
        task_methods: UserTaskMethods,
        *,
        admission_service: TaskAdmissionService | None = None,
        inline_chat_id: str | None = None,
    ):
        self.task_methods = task_methods
        directus = getattr(task_methods, "directus_service", None)
        execution_service = (
            UserTaskExecutionService(
                task_methods,
                encryption_service=directus.encryption_service,
                cache_service=directus.cache,
            )
            if isinstance(task_methods, UserTaskMethods)
            and directus is not None
            and getattr(directus, "encryption_service", None) is not None
            else None
        )

        async def dispatch_or_continue_inline(task: dict[str, Any], now: int) -> bool:
            if inline_chat_id and task.get("primary_chat_id") == inline_chat_id:
                return True
            if execution_service is None:
                return True
            return await execution_service.dispatch_admitted(task, now)

        self.admission_service = admission_service or TaskAdmissionService(
            task_methods,
            on_admitted=dispatch_or_continue_inline,
        )

    async def complete_task(self, task_id: str, user_id: str, *, version: int, team_id: str | None = None, now: int | None = None) -> dict[str, Any]:
        current_time = now or int(time.time())
        existing = await self._get_existing(task_id, user_id, team_id=team_id)
        task = await self._update(task_id, user_id, {
            "version": version,
            "status": "done",
            "queue_state": "none",
            "completed_at": current_time,
            "updated_at": current_time,
            "blocked_reason_code": None,
            "encrypted_blocked_reason": None,
            "ai_execution_state": "completed",
        }, team_id=team_id)
        admission = await self.admission_service.admit_available(
            user_id,
            team_id=team_id,
            now=current_time,
            preferred_chat_id=existing.get("primary_chat_id"),
        )
        queue_result = await self.evaluate_chat_queue(
            user_id,
            existing.get("primary_chat_id"),
            exclude_task_id=task_id,
            now=current_time,
            admission=admission,
            team_id=team_id,
        )
        task["queue_result"] = queue_result
        if queue_result.get("state") == "started_next_ai_task":
            task["next_task_id"] = queue_result.get("task_id")
        return task

    async def block_task(
        self,
        task_id: str,
        user_id: str,
        *,
        version: int,
        blocked_reason_code: str | None = None,
        encrypted_blocked_reason: str | None = None,
        team_id: str | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        current_time = now or int(time.time())
        reason_code = blocked_reason_code or "needs_user_input"
        existing = await self._get_existing(task_id, user_id, team_id=team_id)
        task = await self._update(task_id, user_id, {
            "version": version,
            "status": "blocked",
            "queue_state": "waiting_for_user",
            "blocked_reason_code": reason_code,
            "encrypted_blocked_reason": encrypted_blocked_reason,
            "ai_execution_state": "waiting_for_user",
            "updated_at": current_time,
        }, team_id=team_id)
        task["queue_result"] = await self._admit_released_capacity(
            user_id,
            team_id=team_id,
            existing_chat_id=existing.get("primary_chat_id"),
            now=current_time,
        )
        return task

    async def unblock_task(self, task_id: str, user_id: str, *, version: int, team_id: str | None = None, now: int | None = None) -> dict[str, Any]:
        current_time = now or int(time.time())
        existing = await self._get_existing(task_id, user_id, team_id=team_id)
        task = await self._update(task_id, user_id, {
            "version": version,
            "status": "todo",
            "queue_state": "none",
            "blocked_reason_code": None,
            "encrypted_blocked_reason": None,
            "ai_execution_state": None,
            "updated_at": current_time,
        }, team_id=team_id)
        admission = await self.admission_service.admit_available(
            user_id,
            team_id=team_id,
            now=current_time,
            preferred_chat_id=existing.get("primary_chat_id"),
        )
        queue_result = await self.evaluate_chat_queue(
            user_id,
            existing.get("primary_chat_id"),
            now=current_time,
            admission=admission,
            team_id=team_id,
        )
        task["queue_result"] = queue_result
        if queue_result.get("state") == "started_next_ai_task":
            task["next_task_id"] = queue_result.get("task_id")
        return task

    async def skip_task(self, task_id: str, user_id: str, *, version: int, team_id: str | None = None, now: int | None = None) -> dict[str, Any]:
        current_time = now or int(time.time())
        existing = await self._get_existing(task_id, user_id, team_id=team_id)
        task = await self._update(task_id, user_id, {
            "version": version,
            "status": "backlog",
            "queue_state": "skipped",
            "blocked_reason_code": None,
            "encrypted_blocked_reason": None,
            "ai_execution_state": "skipped",
            "updated_at": current_time,
        }, team_id=team_id)
        admission = await self.admission_service.admit_available(
            user_id,
            team_id=team_id,
            now=current_time,
            preferred_chat_id=existing.get("primary_chat_id"),
        )
        queue_result = await self.evaluate_chat_queue(
            user_id,
            existing.get("primary_chat_id"),
            exclude_task_id=task_id,
            now=current_time,
            admission=admission,
            team_id=team_id,
        )
        task["queue_result"] = queue_result
        if queue_result.get("state") == "started_next_ai_task":
            task["next_task_id"] = queue_result.get("task_id")
        return task

    async def _get_existing(self, task_id: str, user_id: str, *, team_id: str | None = None) -> dict[str, Any]:
        existing = await self.task_methods.get_task(task_id, user_id, team_id)
        if not existing:
            raise UserTaskNotFoundError("Task not found")
        return existing

    async def _update(self, task_id: str, user_id: str, patch: dict[str, Any], *, team_id: str | None = None) -> dict[str, Any]:
        expected_version = patch.get("version")
        if expected_version is None:
            raise ValueError("Task update requires expected version")
        updated = await self.task_methods.update_task_if_version(
            task_id,
            user_id,
            patch,
            int(expected_version),
            team_id=team_id,
        )
        if not updated:
            raise UserTaskConflictError("Task version changed before the action")
        return updated

    async def evaluate_chat_queue(
        self,
        user_id: str,
        chat_id: str | None,
        *,
        exclude_task_id: str | None = None,
        now: int,
        admission: dict[str, Any] | None = None,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        if not chat_id:
            return {"state": "no_chat"}
        candidates = await self.task_methods.list_tasks(user_id, chat_id=chat_id, team_id=team_id, limit=500)
        for task in self._ordered_workable_tasks(candidates, exclude_task_id=exclude_task_id):
            task_id = str(task.get("task_id") or "")
            if self._is_blocking_task(task):
                return {
                    "state": "blocked_by_human_task" if task.get("assignee_type") != "ai" else "blocked_by_ai_task",
                    "task_id": task_id,
                    **self._short_id_field(task),
                    "chat_id": chat_id,
                    "blocked_reason_code": task.get("blocked_reason_code") or "needs_user_input",
                }
            if task.get("assignee_type") != "ai":
                return {
                    "state": "blocked_by_human_task",
                    "task_id": task_id,
                    **self._short_id_field(task),
                    "chat_id": chat_id,
                    "blocked_reason_code": "waiting_for_previous_task",
                }
            if self._task_status(task) == "in_progress":
                return {
                    "state": "active_ai_task",
                    "task_id": task_id,
                    **self._short_id_field(task),
                    "chat_id": chat_id,
                }
            break
        if admission is None:
            admission = await self.admission_service.admit_available(
                user_id,
                team_id=team_id,
                now=now,
                preferred_chat_id=chat_id,
            )
        for admitted in admission.get("admitted_tasks", []):
            if admitted.get("primary_chat_id") != chat_id:
                continue
            return {
                "state": "started_next_ai_task",
                "task_id": admitted.get("task_id"),
                **self._short_id_field(admitted),
                "chat_id": chat_id,
            }
        waiting_in_chat = next(
            (
                task
                for task in candidates
                if task.get("assignee_type") == "ai" and self._task_status(task) == "todo"
            ),
            None,
        )
        if waiting_in_chat:
            return {
                "state": str(waiting_in_chat.get("ai_execution_state") or "waiting_for_capacity"),
                "task_id": waiting_in_chat.get("task_id"),
                **self._short_id_field(waiting_in_chat),
                "chat_id": chat_id,
            }
        return {"state": "no_work", "chat_id": chat_id}

    async def _admit_released_capacity(
        self,
        user_id: str,
        *,
        team_id: str | None = None,
        existing_chat_id: str | None,
        now: int,
    ) -> dict[str, Any]:
        result = await self.admission_service.admit_available(
            user_id,
            team_id=team_id,
            now=now,
            preferred_chat_id=existing_chat_id,
        )
        return {
            "state": "capacity_reconciled",
            "admitted_task_ids": result.get("admitted_task_ids", []),
        }

    def _ordered_workable_tasks(self, tasks: list[dict[str, Any]], *, exclude_task_id: str | None = None) -> list[dict[str, Any]]:
        return sorted(
            (
                task
                for task in tasks
                if task.get("task_id") != exclude_task_id
                and self._task_status(task) not in {"done", "backlog"}
                and task.get("queue_state") != "skipped"
            ),
            key=lambda task: (self._sort_int(task.get("position")), self._sort_int(task.get("created_at")), str(task.get("task_id") or "")),
        )

    def _is_blocking_task(self, task: dict[str, Any]) -> bool:
        return self._task_status(task) == "blocked" or task.get("queue_state") == "waiting_for_user"

    def _task_status(self, task: dict[str, Any]) -> str:
        return str(task.get("status") or "todo")

    def _sort_int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _short_id_field(self, task: dict[str, Any], *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        short_id = task.get("short_id") or (fallback or {}).get("short_id")
        return {"short_id": short_id} if short_id else {}
