# backend/core/api/app/services/directus/user_task_methods.py
#
# Directus access helpers for Tasks V1. User task title, description, tags, and
# activity text are client-encrypted; the backend stores only minimal metadata
# needed for ownership, filtering, scheduling, ordering, and execution.

import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
KEY_WRAPPER_TYPES = {"master", "chat", "project"}


USER_TASK_FIELDS = (
    "id,task_id,hashed_user_id,status,assignee_type,assignee_hash,"
    "primary_chat_id,hashed_primary_chat_id,linked_project_hashes,parent_task_id,"
    "plan_id,plan_step_id,task_type,verification_id,"
    "due_at,priority,position,version,created_at,updated_at,started_at,"
    "completed_at,blocked_reason_code,queue_state,ai_execution_state,encrypted_title,"
    "encrypted_task_key,encrypted_description,encrypted_tags,encrypted_linked_project_ids,"
    "encrypted_activity_summary,encrypted_latest_instruction"
)

USER_TASK_KEY_WRAPPER_FIELDS = (
    "id,hashed_task_id,hashed_user_id,key_type,hashed_chat_id,hashed_project_id,"
    "encrypted_task_key,created_at,expires_at"
)


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def is_sha256_hex(value: str | None) -> bool:
    return bool(value and SHA256_HEX_RE.fullmatch(value))


def _coerce_hashes(value: Any) -> set[str]:
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    if isinstance(value, str):
        return {value}
    return set()


def _validate_wrapper_shape(wrapper: dict[str, Any], encrypted_key_field: str) -> bool:
    key_type = wrapper.get("key_type")
    if key_type not in KEY_WRAPPER_TYPES:
        logger.error("Rejected user task key wrapper with invalid key_type")
        return False
    if not wrapper.get(encrypted_key_field):
        logger.error("Rejected user task key wrapper without encrypted key material")
        return False

    hashed_chat_id = wrapper.get("hashed_chat_id")
    hashed_project_id = wrapper.get("hashed_project_id")
    if hashed_chat_id is not None and not is_sha256_hex(hashed_chat_id):
        logger.error("Rejected user task key wrapper with invalid hashed_chat_id")
        return False
    if hashed_project_id is not None and not is_sha256_hex(hashed_project_id):
        logger.error("Rejected user task key wrapper with invalid hashed_project_id")
        return False
    if key_type == "master" and (hashed_chat_id is not None or hashed_project_id is not None):
        logger.error("Rejected user task master wrapper with scoped hash")
        return False
    if key_type == "chat" and (hashed_chat_id is None or hashed_project_id is not None):
        logger.error("Rejected user task chat wrapper with invalid scope")
        return False
    if key_type == "project" and (hashed_project_id is None or hashed_chat_id is not None):
        logger.error("Rejected user task project wrapper with invalid scope")
        return False
    return True


def _validate_wrapper_set(
    wrappers: list[dict[str, Any]],
    *,
    primary_chat_hash: str | None,
    project_hashes: set[str],
) -> bool:
    if not wrappers:
        logger.error("Rejected empty user task key wrapper set")
        return False
    master_count = 0
    chat_hashes: set[str] = set()
    wrapper_project_hashes: set[str] = set()
    for wrapper in wrappers:
        if not _validate_wrapper_shape(wrapper, "encrypted_task_key"):
            return False
        key_type = wrapper.get("key_type")
        if key_type == "master":
            master_count += 1
        elif key_type == "chat":
            hashed_chat_id = wrapper.get("hashed_chat_id")
            if hashed_chat_id != primary_chat_hash:
                logger.error("Rejected user task chat wrapper that does not match primary chat metadata")
                return False
            chat_hashes.add(hashed_chat_id)
        elif key_type == "project":
            hashed_project_id = wrapper.get("hashed_project_id")
            if hashed_project_id not in project_hashes:
                logger.error("Rejected user task project wrapper that does not match linked project metadata")
                return False
            wrapper_project_hashes.add(hashed_project_id)
    if master_count != 1:
        logger.error("Rejected user task key wrapper set without exactly one master wrapper")
        return False
    if primary_chat_hash and primary_chat_hash not in chat_hashes:
        logger.error("Rejected user task key wrapper set missing primary chat wrapper")
        return False
    if not project_hashes.issubset(wrapper_project_hashes):
        logger.error("Rejected user task key wrapper set missing linked project wrappers")
        return False
    return True


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
            params["filter[linked_project_hashes][_contains]"] = hash_id(project_id)
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

    async def list_active_ai_tasks_for_chat(
        self,
        user_id: str,
        chat_id: str,
        *,
        exclude_task_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "filter[hashed_primary_chat_id][_eq]": hash_id(chat_id),
            "filter[assignee_type][_eq]": "ai",
            "filter[status][_eq]": "in_progress",
            "fields": USER_TASK_FIELDS,
            "sort": "started_at,position,created_at",
            "limit": max(1, min(limit, 50)),
        }
        if exclude_task_id:
            params["filter[task_id][_neq]"] = exclude_task_id
        response = await self.directus_service.get_items("user_tasks", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def create_task(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        key_wrappers = payload.pop("key_wrappers", []) or []
        linked_project_ids = payload.pop("linked_project_ids", []) or []
        now = payload.get("created_at") or payload.get("updated_at")
        primary_chat_id = payload.get("primary_chat_id")
        record = {
            **payload,
            "hashed_user_id": hash_id(user_id),
            "status": payload.get("status") or "todo",
            "assignee_type": payload.get("assignee_type") or "user",
            "linked_project_hashes": [hash_id(project_id) for project_id in linked_project_ids if project_id],
            "hashed_primary_chat_id": hash_id(primary_chat_id) if primary_chat_id else None,
            "version": payload.get("version", 1),
            "created_at": now,
            "updated_at": payload.get("updated_at", now),
        }
        if key_wrappers and not _validate_wrapper_set(
            key_wrappers,
            primary_chat_hash=record.get("hashed_primary_chat_id"),
            project_hashes=_coerce_hashes(record.get("linked_project_hashes")),
        ):
            return None
        success, data = await self.directus_service.create_item("user_tasks", record)
        if not success:
            logger.error("Failed to create user task: %s", data)
            return None
        created_wrappers: list[dict[str, Any]] = []
        for wrapper in key_wrappers:
            created_wrapper = await self.create_task_key_wrapper(user_id, payload["task_id"], wrapper)
            if not created_wrapper:
                await self._delete_created_task_with_wrappers(data, created_wrappers)
                return None
            created_wrappers.append(created_wrapper)
        return data

    async def _delete_created_task_with_wrappers(self, task_row: dict[str, Any], wrappers: list[dict[str, Any]]) -> None:
        for wrapper in wrappers:
            wrapper_id = wrapper.get("id")
            if wrapper_id:
                await self.directus_service.delete_item("user_task_key_wrappers", wrapper_id, admin_required=True)
        row_id = task_row.get("id")
        if row_id:
            await self.directus_service.delete_item("user_tasks", row_id)

    async def create_task_key_wrapper(self, user_id: str, task_id: str, wrapper: dict[str, Any]) -> dict[str, Any] | None:
        hashed_chat_id = wrapper.get("hashed_chat_id")
        hashed_project_id = wrapper.get("hashed_project_id")
        if not _validate_wrapper_shape(wrapper, "encrypted_task_key"):
            return None
        record = {
            "hashed_task_id": hash_id(task_id),
            "hashed_user_id": hash_id(user_id),
            "key_type": wrapper.get("key_type"),
            "hashed_chat_id": hashed_chat_id,
            "hashed_project_id": hashed_project_id,
            "encrypted_task_key": wrapper.get("encrypted_task_key"),
            "created_at": wrapper.get("created_at"),
            "expires_at": wrapper.get("expires_at"),
        }
        success, data = await self.directus_service.create_item("user_task_key_wrappers", record, admin_required=True)
        if not success:
            logger.error("Failed to create user task key wrapper: %s", data)
            return None
        return data

    async def replace_task_key_wrappers(self, user_id: str, task_id: str, wrappers: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        task = await self.get_task(task_id, user_id)
        if not task:
            return None
        if not _validate_wrapper_set(
            wrappers,
            primary_chat_hash=task.get("hashed_primary_chat_id"),
            project_hashes=_coerce_hashes(task.get("linked_project_hashes")),
        ):
            return None
        existing_wrappers = await self.list_task_key_wrappers(user_id, task_id)
        created_wrappers: list[dict[str, Any]] = []
        for wrapper in wrappers:
            created_wrapper = await self.create_task_key_wrapper(user_id, task_id, wrapper)
            if not created_wrapper:
                for created in created_wrappers:
                    created_id = created.get("id")
                    if created_id:
                        await self.directus_service.delete_item("user_task_key_wrappers", created_id, admin_required=True)
                return None
            created_wrappers.append(created_wrapper)
        if not await self._delete_key_wrappers(existing_wrappers):
            await self._delete_key_wrappers(created_wrappers)
            raise RuntimeError("Failed to delete old user task key wrappers")
        return created_wrappers

    async def list_task_key_wrappers(self, user_id: str, task_id: str) -> list[dict[str, Any]]:
        params = {
            "filter[hashed_task_id][_eq]": hash_id(task_id),
            "filter[hashed_user_id][_eq]": hash_id(user_id),
            "fields": USER_TASK_KEY_WRAPPER_FIELDS,
            "limit": 50,
        }
        response = await self.directus_service.get_items("user_task_key_wrappers", params=params, no_cache=True)
        return response if isinstance(response, list) else []

    async def update_task(self, task_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        existing = await self.get_task(task_id, user_id)
        if not existing:
            return None
        update = dict(patch)
        key_wrappers = update.pop("key_wrappers", None)
        existing_wrappers: list[dict[str, Any]] = []
        created_wrappers: list[dict[str, Any]] = []
        existing_chat_hash = existing.get("hashed_primary_chat_id")
        if existing_chat_hash is None and existing.get("primary_chat_id"):
            existing_chat_hash = hash_id(existing["primary_chat_id"])
        existing_project_hashes = _coerce_hashes(existing.get("linked_project_hashes"))
        if not existing_project_hashes and isinstance(existing.get("linked_project_ids"), list):
            existing_project_hashes = {hash_id(project_id) for project_id in existing["linked_project_ids"] if project_id}

        next_chat_hash = existing_chat_hash
        if "primary_chat_id" in update:
            primary_chat_id = update.get("primary_chat_id")
            next_chat_hash = hash_id(primary_chat_id) if primary_chat_id else None
        next_project_hashes = existing_project_hashes
        if "linked_project_ids" in update:
            linked_project_ids = update.get("linked_project_ids") or []
            next_project_hashes = {hash_id(project_id) for project_id in linked_project_ids if project_id}

        relinks_context = next_chat_hash != existing_chat_hash or next_project_hashes != existing_project_hashes
        if relinks_context and not key_wrappers:
            logger.error("Rejected user task relink without replacement key wrappers")
            return None
        if next_project_hashes != existing_project_hashes and ("encrypted_linked_project_ids" not in update or update.get("encrypted_linked_project_ids") is None):
            logger.error("Rejected user task project relink without encrypted linked project ids")
            return None
        update.pop("task_id", None)
        update.pop("hashed_user_id", None)
        if "primary_chat_id" in update:
            primary_chat_id = update.get("primary_chat_id")
            update["hashed_primary_chat_id"] = hash_id(primary_chat_id) if primary_chat_id else None
        if "linked_project_ids" in update:
            linked_project_ids = update.pop("linked_project_ids") or []
            update["linked_project_hashes"] = [hash_id(project_id) for project_id in linked_project_ids if project_id]
        if key_wrappers is not None and not _validate_wrapper_set(
            key_wrappers,
            primary_chat_hash=next_chat_hash,
            project_hashes=next_project_hashes,
        ):
            return None
        if key_wrappers is not None:
            existing_wrappers = await self.list_task_key_wrappers(user_id, task_id)
            for wrapper in key_wrappers:
                created_wrapper = await self.create_task_key_wrapper(user_id, task_id, wrapper)
                if not created_wrapper:
                    await self._delete_key_wrappers(created_wrappers)
                    return None
                created_wrappers.append(created_wrapper)
        update["version"] = int(existing.get("version") or 1) + 1
        updated = await self.directus_service.update_item("user_tasks", existing["id"], update)
        if not updated:
            await self._delete_key_wrappers(created_wrappers)
            return None
        if not await self._delete_key_wrappers(existing_wrappers):
            raise RuntimeError("Failed to delete old user task key wrappers")
        return updated

    async def _delete_key_wrappers(self, wrappers: list[dict[str, Any]]) -> bool:
        all_deleted = True
        for wrapper in wrappers:
            wrapper_id = wrapper.get("id")
            if wrapper_id:
                deleted = await self.directus_service.delete_item("user_task_key_wrappers", wrapper_id, admin_required=True)
                if deleted is False:
                    logger.error("Failed to delete old user task key wrapper")
                    all_deleted = False
        return all_deleted

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
