"""Cold archive adapters for workspace resource types.

Chats have a full graph archiver in cold_archive_service.py. Projects, Tasks,
Plans, Workflow definitions, and Workflow runs keep separate encrypted schemas,
so this module centralizes the type-specific eligibility and safe manifest
payload rules before task-specific workers are wired in. Spec:
docs/specs/regional-cold-storage-lifecycle/spec.yml.
"""

from __future__ import annotations

import hashlib
from typing import Any

from backend.core.api.app.services.storage_reference_service import collect_storage_references


DEFAULT_WORKSPACE_COLD_INACTIVITY_DAYS = 28
SECONDS_PER_DAY = 86_400
TASK_TERMINAL_STATUSES = {"done"}
PLAN_TERMINAL_STATUSES = {"archived", "completed"}
WORKFLOW_RUN_TERMINAL_STATUSES = {"cancelled", "completed", "failed", "skipped_by_user"}
WORKFLOW_DEFINITION_COLD_STATUSES = {"disabled"}
WORKSPACE_ACTIVE_STATES = {
    "active",
    "blocked",
    "checking_assumptions",
    "executing",
    "in_progress",
    "paused",
    "queued",
    "running",
    "running_checks",
    "scheduled",
    "waiting",
    "waiting_for_capacity",
    "waiting_for_plan_dependency",
    "waiting_for_previous_task",
    "waiting_for_user",
}
RESOURCE_ID_FIELDS = {
    "plan": "plan_id",
    "project": "project_id",
    "task": "task_id",
    "workflow": "workflow_id",
    "workflow_run": "run_id",
}
SAFE_LISTING_METADATA_FIELDS = {
    "archived",
    "completed_at",
    "content_available",
    "content_storage",
    "created_at",
    "finished_at",
    "item_count",
    "last_opened_at",
    "lifecycle",
    "position",
    "priority",
    "slug_lookup_hash",
    "source",
    "status",
    "trigger_type",
    "updated_at",
    "version",
}


def workspace_resource_is_archive_eligible(
    resource_type: str,
    row: dict[str, Any],
    *,
    now_timestamp: int,
    has_active_dependency: bool = False,
    inactivity_days: int = DEFAULT_WORKSPACE_COLD_INACTIVITY_DAYS,
) -> bool:
    """Return whether one workspace row satisfies its cold eligibility rule."""
    normalized_type = _normalize_resource_type(resource_type)
    if has_active_dependency or _row_has_active_dependency(row):
        return False
    if row.get("storage_state") not in {None, "hot"} or row.get("cold_archive_id"):
        return False

    if normalized_type == "project":
        return _project_is_eligible(row, now_timestamp=now_timestamp, inactivity_days=inactivity_days)
    if normalized_type == "task":
        return _task_is_eligible(row, now_timestamp=now_timestamp, inactivity_days=inactivity_days)
    if normalized_type == "plan":
        return _plan_is_eligible(row, now_timestamp=now_timestamp, inactivity_days=inactivity_days)
    if normalized_type == "workflow_run":
        return _workflow_run_is_eligible(row, now_timestamp=now_timestamp, inactivity_days=inactivity_days)
    if normalized_type == "workflow":
        return _workflow_definition_is_eligible(row, now_timestamp=now_timestamp, inactivity_days=inactivity_days)
    raise ValueError(f"Unsupported workspace resource type: {resource_type}")


def build_workspace_archive_manifest(
    resource_type: str,
    row: dict[str, Any],
    *,
    archive_id: str,
    generation: int,
    part_count: int,
    graph_checksum: str,
    file_references: list[dict[str, str]],
    now_timestamp: int,
) -> dict[str, Any]:
    """Build the Directus manifest payload for a cold workspace resource."""
    normalized_type = _normalize_resource_type(resource_type)
    resource_id = _resource_id(normalized_type, row)
    return {
        "archive_id": archive_id,
        "resource_type": normalized_type,
        "resource_id": resource_id,
        "hashed_resource_id": _hash_id(resource_id),
        "hashed_user_id": row.get("hashed_user_id"),
        "hashed_team_id": row.get("hashed_team_id"),
        "encrypted_listing_metadata": workspace_listing_metadata(row),
        "active_generation": int(generation),
        "graph_checksum": graph_checksum,
        "part_count": int(part_count),
        "file_references": workspace_file_references({"explicit": file_references}),
        "state": "preparing",
        "version": 1,
        "archived_at": int(now_timestamp),
        "updated_at": int(now_timestamp),
    }


def workspace_listing_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Project only encrypted fields and safe indexes into archive listings."""
    return {
        key: value
        for key, value in row.items()
        if value is not None and (key.startswith("encrypted_") or key in SAFE_LISTING_METADATA_FIELDS)
    }


def workspace_file_references(graph: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    """Return stable file references without copying encrypted binary objects."""
    inventory = collect_storage_references(
        embeds=graph.get("embeds", ()),
        uploads=graph.get("upload_files", ()),
        cold_manifests=graph.get("explicit", ()),
    )
    return [
        {"logical_bucket": logical_bucket, "object_key": object_key}
        for logical_bucket, object_key in sorted(inventory.references)
    ]


def _project_is_eligible(row: dict[str, Any], *, now_timestamp: int, inactivity_days: int) -> bool:
    if row.get("pinned") or row.get("is_shared") or row.get("share_with_community"):
        return False
    return _old_enough(row, ("last_opened_at", "updated_at", "created_at"), now_timestamp, inactivity_days)


def _task_is_eligible(row: dict[str, Any], *, now_timestamp: int, inactivity_days: int) -> bool:
    if row.get("status") not in TASK_TERMINAL_STATUSES:
        return False
    if _active_state(row.get("queue_state")) or _active_state(row.get("ai_execution_state")):
        return False
    return _old_enough(row, ("completed_at", "updated_at", "created_at"), now_timestamp, inactivity_days)


def _plan_is_eligible(row: dict[str, Any], *, now_timestamp: int, inactivity_days: int) -> bool:
    if row.get("status") not in PLAN_TERMINAL_STATUSES:
        return False
    if _active_state(row.get("continuation_state")) or _active_state(row.get("approval_state")):
        return False
    return _old_enough(row, ("completed_at", "updated_at", "created_at"), now_timestamp, inactivity_days)


def _workflow_run_is_eligible(row: dict[str, Any], *, now_timestamp: int, inactivity_days: int) -> bool:
    if row.get("status") not in WORKFLOW_RUN_TERMINAL_STATUSES:
        return False
    if row.get("content_storage") not in {None, "durable"}:
        return False
    return _old_enough(row, ("finished_at", "updated_at", "accepted_at"), now_timestamp, inactivity_days)


def _workflow_definition_is_eligible(row: dict[str, Any], *, now_timestamp: int, inactivity_days: int) -> bool:
    if row.get("enabled") or row.get("status") not in WORKFLOW_DEFINITION_COLD_STATUSES:
        return False
    next_run_at = _timestamp(row.get("next_run_at"))
    if next_run_at and next_run_at >= now_timestamp:
        return False
    return _old_enough(row, ("updated_at", "created_at"), now_timestamp, inactivity_days)


def _old_enough(row: dict[str, Any], fields: tuple[str, ...], now_timestamp: int, inactivity_days: int) -> bool:
    cutoff = int(now_timestamp) - max(1, int(inactivity_days)) * SECONDS_PER_DAY
    timestamps = [_timestamp(row.get(field)) for field in fields]
    newest = max(timestamps)
    return newest > 0 and newest <= cutoff


def _row_has_active_dependency(row: dict[str, Any]) -> bool:
    if row.get("has_active_dependencies"):
        return True
    try:
        return int(row.get("active_dependency_count") or 0) > 0
    except (TypeError, ValueError):
        return True


def _active_state(value: Any) -> bool:
    return str(value or "").lower() in WORKSPACE_ACTIVE_STATES


def _resource_id(resource_type: str, row: dict[str, Any]) -> str:
    field = RESOURCE_ID_FIELDS[resource_type]
    value = row.get(field) or row.get("id")
    if not value:
        raise ValueError(f"Workspace {resource_type} row is missing {field}")
    return str(value)


def _normalize_resource_type(resource_type: str) -> str:
    normalized = resource_type.strip().lower().replace("-", "_")
    aliases = {
        "workflow_definition": "workflow",
        "workflow_run": "workflow_run",
        "workflows_run": "workflow_run",
    }
    return aliases.get(normalized, normalized)


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _timestamp(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0
