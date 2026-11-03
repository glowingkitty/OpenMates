"""Retire legacy per-run status notifications while preserving sent history.

Workflow execution remains visible in run history. Actual Send-message outputs use
workflow_chat_notification_service; the daily activity summary is email only.
"""
from __future__ import annotations

import time
from typing import Any

COLLECTION = "workflow_completion_notifications"


async def load_completion(directus: Any, run_id: str) -> dict[str, Any] | None:
    rows = await directus.get_items(COLLECTION, params={"filter": {"run_id": {"_eq": run_id}}, "limit": 1},
                                   admin_required=True, no_cache=True, raise_on_error=True)
    return rows[0] if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) else None


async def owner_run_completion_projection(directus: Any, run: Any, owner_user_id: str) -> dict[str, str] | None:
    """Reauthorize an existing legacy link without producing a new status alert.

    The caller already authorizes this Personal Workflow/run. Retained completion
    metadata remains useful after encrypted run content is pruned, including for
    old clients completing an already-persisted delivery. Never create or choose a
    target here; only project the exact pre-existing owner-scoped row.
    """
    if getattr(run, "status", None) != "completed" or getattr(run, "trigger_type", None) != "schedule":
        return None
    row = await load_completion(directus, run.id)
    if not row or (row.get("run_id"), row.get("workflow_id"), row.get("owner_user_id")) != (run.id, run.workflow_id, owner_user_id):
        return None
    if row.get("notification_id") != "workflow-completed-" + run.id:
        return None
    result = {"notification_id": row["notification_id"]}
    fields = ("chat_id", "message_id", "delivery_id")
    if all(isinstance(row.get(key), str) and row[key] for key in fields):
        result.update({key: row[key] for key in fields})
    return result


async def dispatch_completion(task: Any, run_id: str, workflow_service: Any = None) -> dict[str, str]:
    """Safely consume queued old tasks without contacting notification providers."""
    row = await load_completion(task.directus_service, run_id)
    if not row:
        return {"status": "missing"}
    changes = {field: "retired" for field in ("event_state", "push_state", "email_state") if row.get(field) == "pending"}
    if changes:
        if not await task.directus_service.update_item(COLLECTION, row["id"], {**changes, "updated_at": int(time.time())}, admin_required=True):
            raise RuntimeError("Legacy Workflow notification retirement was not persisted")
    return {"status": "retired"}
