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
        queue_result = await self.evaluate_chat_queue(user_id, existing.get("primary_chat_id"), exclude_task_id=task_id, now=current_time)
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
        queue_result = await self.evaluate_chat_queue(user_id, existing.get("primary_chat_id"), now=current_time)
        task["queue_result"] = queue_result
        if queue_result.get("state") == "started_next_ai_task":
            task["next_task_id"] = queue_result.get("task_id")
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
        queue_result = await self.evaluate_chat_queue(user_id, existing.get("primary_chat_id"), exclude_task_id=task_id, now=current_time)
        task["queue_result"] = queue_result
        if queue_result.get("state") == "started_next_ai_task":
            task["next_task_id"] = queue_result.get("task_id")
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

    async def evaluate_chat_queue(
        self,
        user_id: str,
        chat_id: str | None,
        *,
        exclude_task_id: str | None = None,
        now: int,
    ) -> dict[str, Any]:
        if not chat_id:
            return {"state": "no_chat"}
        candidates = await self.task_methods.list_tasks(user_id, chat_id=chat_id, limit=500)
        for task in self._ordered_workable_tasks(candidates, exclude_task_id=exclude_task_id):
            task_id = str(task.get("task_id") or "")
            if self._is_blocking_task(task):
                return {
                    "state": "blocked_by_human_task" if task.get("assignee_type") != "ai" else "blocked_by_ai_task",
                    "task_id": task_id,
                    "chat_id": chat_id,
                    "blocked_reason_code": task.get("blocked_reason_code") or "needs_user_input",
                }
            if task.get("assignee_type") != "ai":
                continue
            if self._task_status(task) == "in_progress":
                return {"state": "active_ai_task", "task_id": task_id, "chat_id": chat_id}
            if self._task_status(task) != "todo":
                continue
            updated = await self._update(task_id, user_id, {
                "version": task.get("version"),
                "status": "in_progress",
                "queue_state": "active",
                "ai_execution_state": "queued",
                "started_at": task.get("started_at") or now,
                "updated_at": now,
            })
            return {"state": "started_next_ai_task", "task_id": updated.get("task_id"), "chat_id": chat_id}
        return {"state": "no_work", "chat_id": chat_id}

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
