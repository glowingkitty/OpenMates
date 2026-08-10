# backend/core/api/app/services/user_task_share_bundle.py
#
# Pure helper for adding encrypted task records to shared chat bundles. The share
# route imports this module, while tests can exercise it without importing the
# full FastAPI route stack or cache dependencies.

import hashlib
from typing import Any


SHARED_TASK_FIELDS = (
    "task_id,status,assignee_type,assignee_hash,primary_chat_id,plan_id,plan_step_id,"
    "task_type,verification_id,due_at,priority,position,queue_state,version,created_at,"
    "updated_at,started_at,completed_at,blocked_reason_code,ai_execution_state,"
    "encrypted_title,encrypted_description,encrypted_tags,encrypted_linked_project_ids,"
    "encrypted_activity_summary,encrypted_latest_instruction"
)
SHARED_TASK_KEY_WRAPPER_FIELDS = "hashed_task_id,key_type,hashed_chat_id,encrypted_task_key,created_at,expires_at"


async def get_shared_chat_tasks(
    chat_id: str,
    hashed_chat_id: str,
    directus_service: Any,
) -> dict[str, list[dict[str, Any]]]:
    tasks = await directus_service.get_items(
        "user_tasks",
        params={
            "filter[hashed_primary_chat_id][_eq]": hashed_chat_id,
            "fields": SHARED_TASK_FIELDS,
            "sort": "position,created_at",
            "limit": -1,
        },
        admin_required=True,
    ) or []
    task_key_wrappers: list[dict[str, Any]] = []
    for task in tasks:
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        hashed_task_id = hashlib.sha256(task_id.encode()).hexdigest()
        wrappers = await directus_service.get_items(
            "user_task_key_wrappers",
            params={
                "filter[hashed_task_id][_eq]": hashed_task_id,
                "filter[key_type][_eq]": "chat",
                "filter[hashed_chat_id][_eq]": hashed_chat_id,
                "fields": SHARED_TASK_KEY_WRAPPER_FIELDS,
                "limit": -1,
            },
            admin_required=True,
        ) or []
        task_key_wrappers.extend(wrappers)
    return {"tasks": tasks, "task_key_wrappers": task_key_wrappers}
