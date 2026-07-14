# backend/core/api/app/services/user_task_queue_service.py
#
# Queue transition logic for Tasks V1. This keeps explicit task actions such as
# complete, block, unblock, and skip deterministic and separate from FastAPI
# route parsing. Durable task content remains client-encrypted; this service only
# mutates safe metadata used for queue orchestration.

import time
from typing import Any

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods
from backend.core.api.app.services.user_task_service import UserTaskConflictError, UserTaskNotFoundError


class UserTaskQueueService:
    def __init__(self, task_methods: UserTaskMethods):
        self.task_methods = task_methods

    async def complete_task(self, task_id: str, user_id: str, *, version: int, now: int | None = None) -> dict[str, Any]:
        current_time = now or int(time.time())
        existing = await self._get_existing(task_id, user_id)
        task = await self._update(task_id, user_id, {
            "version": version,
            "status": "done",
            "queue_state": "none",
            "completed_at": current_time,
            "updated_at": current_time,
            "blocked_reason_code": None,
            "ai_execution_state": "completed",
        })
        next_task = await self._start_next_eligible(user_id, existing.get("primary_chat_id"), exclude_task_id=task_id, now=current_time)
        if next_task:
            task["next_task_id"] = next_task.get("task_id")
        return task

    async def block_task(
        self,
        task_id: str,
        user_id: str,
        *,
        version: int,
        blocked_reason_code: str | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        current_time = now or int(time.time())
        return await self._update(task_id, user_id, {
            "version": version,
            "status": "blocked",
            "queue_state": "waiting_for_user",
            "blocked_reason_code": blocked_reason_code or "needs_user_input",
            "ai_execution_state": "waiting_for_user",
            "updated_at": current_time,
        })

    async def unblock_task(self, task_id: str, user_id: str, *, version: int, now: int | None = None) -> dict[str, Any]:
        current_time = now or int(time.time())
        existing = await self._get_existing(task_id, user_id)
        task = await self._update(task_id, user_id, {
            "version": version,
            "status": "todo",
            "queue_state": "none",
            "blocked_reason_code": None,
            "ai_execution_state": None,
            "updated_at": current_time,
        })
        next_task = await self._start_next_eligible(user_id, existing.get("primary_chat_id"), now=current_time)
        if next_task:
            task["next_task_id"] = next_task.get("task_id")
        return task

    async def skip_task(self, task_id: str, user_id: str, *, version: int, now: int | None = None) -> dict[str, Any]:
        current_time = now or int(time.time())
        existing = await self._get_existing(task_id, user_id)
        task = await self._update(task_id, user_id, {
            "version": version,
            "status": "backlog",
            "queue_state": "skipped",
            "blocked_reason_code": None,
            "ai_execution_state": "skipped",
            "updated_at": current_time,
        })
        next_task = await self._start_next_eligible(user_id, existing.get("primary_chat_id"), exclude_task_id=task_id, now=current_time)
        if next_task:
            task["next_task_id"] = next_task.get("task_id")
        return task

    async def _get_existing(self, task_id: str, user_id: str) -> dict[str, Any]:
        existing = await self.task_methods.get_task(task_id, user_id)
        if not existing:
            raise UserTaskNotFoundError("Task not found")
        return existing

    async def _update(self, task_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        expected_version = patch.get("version")
        if expected_version is None:
            raise ValueError("Task update requires expected version")
        updated = await self.task_methods.update_task_if_version(task_id, user_id, patch, int(expected_version))
        if not updated:
            raise UserTaskConflictError("Task version changed before the action")
        return updated

    async def _start_next_eligible(
        self,
        user_id: str,
        chat_id: str | None,
        *,
        exclude_task_id: str | None = None,
        now: int,
    ) -> dict[str, Any] | None:
        if not chat_id:
            return None
        candidates = await self.task_methods.list_tasks(user_id, chat_id=chat_id, status="todo")
        next_task = next(
            (
                task
                for task in candidates
                if task.get("task_id") != exclude_task_id and task.get("assignee_type") == "ai"
            ),
            None,
        )
        if not next_task:
            return None
        return await self._update(str(next_task["task_id"]), user_id, {
            "version": next_task.get("version"),
            "status": "in_progress",
            "queue_state": "active",
            "ai_execution_state": "queued",
            "started_at": next_task.get("started_at") or now,
            "updated_at": now,
        })
