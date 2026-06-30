# backend/core/api/app/services/directus/user_task_methods.py
#
# Directus access helpers for Tasks V1. User task title, description, tags, and
# activity text are client-encrypted; the backend stores only minimal metadata
# needed for ownership, filtering, scheduling, ordering, and execution.

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


USER_TASK_FIELDS = (
    "id,task_id,hashed_user_id,status,assignee_type,assignee_hash,"
    "primary_chat_id,hashed_primary_chat_id,linked_project_ids,parent_task_id,"
    "plan_id,plan_step_id,task_type,verification_id,"
    "due_at,priority,position,version,created_at,updated_at,started_at,"
    "completed_at,blocked_reason_code,ai_execution_state,encrypted_title,"
    "encrypted_task_key,encrypted_description,encrypted_tags,"
    "encrypted_activity_summary,encrypted_latest_instruction"
)


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class UserTaskMethods:
    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def list_tasks(
        self,
        user_id: str,
        *,
        status: str | None = None,
        chat_id: str | None = None,
        project_id: str | None = None,
        assignee_hash: str | None = None,
        due_before: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": USER_TASK_FIELDS,
            "sort": "position,created_at",
            "limit": max(1, min(limit, 500)),
        }
        if status:
            params["filter[status][_eq]"] = status
        if chat_id:
            params["filter[hashed_primary_chat_id][_eq]"] = hash_id(chat_id)
        if project_id:
            params["filter[linked_project_ids][_contains]"] = hash_id(project_id)
        if assignee_hash:
            params["filter[assignee_hash][_eq]"] = assignee_hash
        if due_before is not None:
            params["filter[due_at][_lte]"] = due_before

        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def get_task(self, task_id: str, user_id: str) -> dict[str, Any] | None:
        params = {
            "filter[task_id][_eq]": task_id,
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": USER_TASK_FIELDS,
            "limit": 1,
        }
        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        if response and isinstance(response, list):
            return response[0]
        return None

    async def list_due_ai_tasks(self, due_before: int, *, limit: int = 100) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[assignee_type][_eq]": "ai",
            "filter[due_at][_lte]": due_before,
            "filter[status][_in]": ["backlog", "todo"],
            "fields": USER_TASK_FIELDS,
            "sort": "due_at,position,created_at",
            "limit": max(1, min(limit, 500)),
        }
        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def create_task(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        now = payload.get("created_at") or payload.get("updated_at")
        primary_chat_id = payload.get("primary_chat_id")
        linked_project_ids = payload.get("linked_project_ids") or []
        record = {
            **payload,
            "hashed_user_id": hash_id(user_id),
            "status": payload.get("status") or "todo",
            "assignee_type": payload.get("assignee_type") or "user",
            "linked_project_ids": [hash_id(project_id) for project_id in linked_project_ids if project_id],
            "hashed_primary_chat_id": hash_id(primary_chat_id) if primary_chat_id else None,
            "version": payload.get("version", 1),
            "created_at": now,
            "updated_at": payload.get("updated_at", now),
        }
        success, data = await self.directus_service.create_item("user_tasks", record)
        if not success:
            logger.error("Failed to create user task: %s", data)
            return None
        return data

    async def update_task(self, task_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        existing = await self.get_task(task_id, user_id)
        if not existing:
            return None
        update = dict(patch)
        update.pop("task_id", None)
        update.pop("hashed_user_id", None)
        if "primary_chat_id" in update:
            primary_chat_id = update.get("primary_chat_id")
            update["hashed_primary_chat_id"] = hash_id(primary_chat_id) if primary_chat_id else None
        if "linked_project_ids" in update:
            update["linked_project_ids"] = [hash_id(project_id) for project_id in (update.get("linked_project_ids") or []) if project_id]
        update["version"] = int(existing.get("version") or 1) + 1
        return await self.directus_service.update_item("user_tasks", existing["id"], update)

    async def start_due_ai_task(self, task: dict[str, Any], now: int) -> dict[str, Any] | None:
        row_id = task.get("id")
        if not row_id:
            return None
        update = {
            "status": "in_progress",
            "ai_execution_state": "queued",
            "started_at": now,
            "updated_at": now,
            "version": int(task.get("version") or 1) + 1,
        }
        return await self.directus_service.update_item("user_tasks", row_id, update)

    async def delete_task(self, task_id: str, user_id: str) -> bool:
        existing = await self.get_task(task_id, user_id)
        if not existing:
            return False
        return await self.directus_service.delete_item("user_tasks", existing["id"])
