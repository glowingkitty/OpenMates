# backend/apps/ai/processing/task_tool_executor.py
#
# Executes Tasks V1 main-processor tool calls. The executor keeps private task
# content out of Directus by staging title/description edits in vault-encrypted
# Redis working copies and emitting short-lived client persistence jobs.

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from backend.apps.ai.processing.task_runtime_tools import (
    TASK_TOOL_BLOCK,
    TASK_TOOL_COMPLETE,
    TASK_TOOL_CREATE,
    TASK_TOOL_MOVE,
    TASK_TOOL_REORDER,
    TASK_TOOL_UNBLOCK,
    TASK_TOOL_UPDATE,
)
from backend.apps.ai.processing.task_tool_context import TaskToolContext
from backend.core.api.app.services.directus.user_task_methods import hash_id
from backend.core.api.app.services.user_task_queue_service import UserTaskQueueService
from backend.core.api.app.services.user_task_service import UserTaskConflictError
from backend.core.api.app.services.user_task_update_job_service import DEFAULT_TASK_UPDATE_JOB_TTL_SECONDS
from backend.core.api.app.services.user_task_working_copy_service import UserTaskWorkingCopyService
from backend.core.api.app.services.workflow_service import VaultWorkflowPayloadCipher


TASK_TOOL_CANONICAL_NAMES = {
    TASK_TOOL_CREATE.replace("_", "-"),
    TASK_TOOL_UPDATE.replace("_", "-"),
    TASK_TOOL_REORDER.replace("_", "-"),
    TASK_TOOL_BLOCK.replace("_", "-"),
    TASK_TOOL_COMPLETE.replace("_", "-"),
    TASK_TOOL_UNBLOCK.replace("_", "-"),
    TASK_TOOL_MOVE.replace("_", "-"),
}
TASK_TOOL_RESOLVER_APP_ID = "tasks"
TASK_TOOL_JOB_CACHE_PREFIX = "user_task_update_job:"
TASK_APP_SKILL_MENTION_RE = re.compile(r"@skill:tasks:([a-zA-Z0-9_-]+)")
TASK_APP_SKILL_IDS = {"create", "search"}


def is_task_tool_name(tool_name: str) -> bool:
    return tool_name.replace("_", "-") in TASK_TOOL_CANONICAL_NAMES


def is_legacy_task_runtime_tool_name(tool_name: str) -> bool:
    """Return whether a tool name belongs to Tasks runtime tools, not Tasks app skills."""
    canonical_name = tool_name.replace(":", "-").replace("|", "-").replace(".", "-").replace("_", "-")
    return is_task_tool_name(tool_name) or is_task_tool_name(canonical_name)


def should_suppress_task_runtime_tools_for_app_skill(
    preselected_skills: set[str] | None,
    *,
    user_requested_skills_only: bool,
) -> bool:
    """Avoid offering legacy task tools when the user explicitly mentioned a Tasks app skill."""
    if not user_requested_skills_only or not preselected_skills:
        return False
    return any(skill.startswith(f"{TASK_TOOL_RESOLVER_APP_ID}-") for skill in preselected_skills)


def assigned_app_ids_with_task_app_for_explicit_skill(
    assigned_app_ids: list[str] | None,
    task_app_skill_mentions: set[str],
) -> list[str] | None:
    """Include Tasks app tools when a user explicitly requested a Tasks app skill."""
    if not task_app_skill_mentions or assigned_app_ids is None:
        return assigned_app_ids
    if TASK_TOOL_RESOLVER_APP_ID in assigned_app_ids:
        return assigned_app_ids
    return [*assigned_app_ids, TASK_TOOL_RESOLVER_APP_ID]


def task_app_skill_ids_from_message_text(message_text: str | None) -> set[str]:
    """Return Tasks app-skill IDs explicitly mentioned in backend wire syntax."""
    if not message_text:
        return set()
    task_skill_ids: set[str] = set()
    for match in TASK_APP_SKILL_MENTION_RE.finditer(message_text):
        skill_id = match.group(1).replace("_", "-")
        if skill_id in TASK_APP_SKILL_IDS:
            task_skill_ids.add(f"{TASK_TOOL_RESOLVER_APP_ID}-{skill_id}")
    return task_skill_ids


def task_app_skill_ids_from_user_override_skills(skills: list[tuple[str, str]] | None) -> set[str]:
    """Return Tasks app-skill IDs explicitly parsed by the override parser."""
    if not skills:
        return set()
    task_skill_ids: set[str] = set()
    for app_id, skill_id in skills:
        if app_id != TASK_TOOL_RESOLVER_APP_ID:
            continue
        normalized_skill_id = skill_id.replace("_", "-")
        if normalized_skill_id in TASK_APP_SKILL_IDS:
            task_skill_ids.add(f"{TASK_TOOL_RESOLVER_APP_ID}-{normalized_skill_id}")
    return task_skill_ids


def task_tool_name_variants(tool_name: str) -> set[str]:
    if not is_task_tool_name(tool_name):
        return set()
    return {tool_name, tool_name.replace("_", "-"), tool_name.replace("-", "_")}


def task_tool_skill_id(tool_name: str) -> str:
    canonical = tool_name.replace("_", "-")
    if not canonical.startswith("task-"):
        return canonical
    return canonical.removeprefix("task-")


async def execute_task_tool_call(
    *,
    tool_name: str,
    args: dict[str, Any],
    context: TaskToolContext,
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
    user_vault_key_id: str | None,
    message_id: str,
) -> dict[str, Any]:
    now = int(time.time())
    skill_id = task_tool_skill_id(tool_name)
    if skill_id == "create":
        task_id = str(uuid.uuid4())
        return await _stage_client_persisted_task_change(
            operation="create",
            event_type="created",
            task_id=task_id,
            args=args,
            private_patch={
                "title": str(args.get("title") or "").strip(),
                "description": str(args.get("description") or ""),
            },
            safe_metadata={
                "status": _safe_status(args.get("status"), default="todo"),
                "assignee_type": _safe_assignee_type(args.get("assignee_type")),
                "primary_chat_id": context.chat_id,
                "position": now,
                "created_at": now,
                "updated_at": now,
            },
            expected_version=0,
            context=context,
            cache_service=cache_service,
            encryption_service=encryption_service,
            user_vault_key_id=user_vault_key_id,
            message_id=message_id,
            now=now,
        )

    if skill_id == "update":
        task = _attached_task(context, str(args.get("task_id") or ""))
        private_patch = {key: args[key] for key in ("title", "description") if key in args and args[key] is not None}
        safe_metadata: dict[str, Any] = {"updated_at": now}
        if args.get("status") is not None:
            safe_metadata["status"] = _safe_status(args.get("status"), default=str(task.get("status") or "todo"))
        if args.get("assignee_type") is not None:
            safe_metadata["assignee_type"] = _safe_assignee_type(args.get("assignee_type"))
        if _already_applied_client_persisted_change(context, task, args.get("expected_version"), private_patch, safe_metadata):
            return _already_applied_result("update", task)
        _check_turn_expected_version(context, task, args.get("expected_version"))
        if private_patch:
            return await _stage_client_persisted_task_change(
                operation="update",
                event_type="updated",
                task_id=str(task["task_id"]),
                args=args,
                private_patch=private_patch,
                safe_metadata=safe_metadata,
                expected_version=_task_version(task),
                context=context,
                cache_service=cache_service,
                encryption_service=encryption_service,
                user_vault_key_id=user_vault_key_id,
                message_id=message_id,
                now=now,
            )
        updated = await directus_service.user_task.update_task_if_version(
            str(task["task_id"]),
            context.user_id,
            safe_metadata,
            _task_version(task),
        )
        if not updated:
            raise UserTaskConflictError("Task version changed before the tool call")
        _apply_turn_task_update(context, updated)
        return _event_result("updated", updated, context.chat_id, message_id, now)

    if skill_id == "block":
        task = _attached_task(context, str(args.get("task_id") or ""))
        safe_metadata = {"status": "blocked", "blocked_reason_code": str(args.get("blocked_reason_code") or "needs_input"), "updated_at": now}
        if _already_applied_direct_change(context, task, args.get("expected_version"), safe_metadata):
            return _event_result("blocked", task, context.chat_id, message_id, now, reason=task.get("blocked_reason_code"))
        if _already_applied_client_persisted_change(context, task, args.get("expected_version"), {}, safe_metadata):
            return _already_applied_result("block", task)
        try:
            _check_turn_expected_version(context, task, args.get("expected_version"))
        except UserTaskConflictError:
            already_applied = await _already_applied_direct_result_from_store(
                context=context,
                directus_service=directus_service,
                task=task,
                safe_metadata=safe_metadata,
                event_type="blocked",
                message_id=message_id,
                now=now,
                reason_key="blocked_reason_code",
            )
            if already_applied:
                return already_applied
            raise
        if _has_pending_client_persistence(context, str(task["task_id"])):
            return await _stage_client_persisted_task_change(
                operation="block",
                event_type="blocked",
                task_id=str(task["task_id"]),
                args=args,
                private_patch={},
                safe_metadata=safe_metadata,
                expected_version=_task_version(task),
                context=context,
                cache_service=cache_service,
                encryption_service=encryption_service,
                user_vault_key_id=user_vault_key_id,
                message_id=message_id,
                now=now,
            )
        try:
            updated = await UserTaskQueueService(directus_service.user_task).block_task(
                str(task["task_id"]),
                context.user_id,
                version=_task_version(task),
                blocked_reason_code=str(args.get("blocked_reason_code") or "needs_input"),
                now=now,
            )
        except UserTaskConflictError:
            already_applied = await _already_applied_direct_result_from_store(
                context=context,
                directus_service=directus_service,
                task=task,
                safe_metadata=safe_metadata,
                event_type="blocked",
                message_id=message_id,
                now=now,
                reason_key="blocked_reason_code",
            )
            if already_applied:
                return already_applied
            raise
        _apply_turn_task_update(context, updated)
        return _event_result("blocked", updated, context.chat_id, message_id, now, reason=updated.get("blocked_reason_code"))

    if skill_id == "complete":
        task = _attached_task(context, str(args.get("task_id") or ""))
        safe_metadata = {"status": "done", "updated_at": now}
        if _already_applied_direct_change(context, task, args.get("expected_version"), safe_metadata):
            return _event_result("completed", task, context.chat_id, message_id, now)
        if _already_applied_client_persisted_change(context, task, args.get("expected_version"), {}, safe_metadata):
            return _already_applied_result("complete", task)
        try:
            _check_turn_expected_version(context, task, args.get("expected_version"))
        except UserTaskConflictError:
            already_applied = await _already_applied_direct_result_from_store(
                context=context,
                directus_service=directus_service,
                task=task,
                safe_metadata=safe_metadata,
                event_type="completed",
                message_id=message_id,
                now=now,
            )
            if already_applied:
                return already_applied
            raise
        if _has_pending_client_persistence(context, str(task["task_id"])):
            return await _stage_client_persisted_task_change(
                operation="complete",
                event_type="completed",
                task_id=str(task["task_id"]),
                args=args,
                private_patch={},
                safe_metadata=safe_metadata,
                expected_version=_task_version(task),
                context=context,
                cache_service=cache_service,
                encryption_service=encryption_service,
                user_vault_key_id=user_vault_key_id,
                message_id=message_id,
                now=now,
            )
        try:
            updated = await UserTaskQueueService(directus_service.user_task).complete_task(
                str(task["task_id"]),
                context.user_id,
                version=_task_version(task),
                now=now,
            )
        except UserTaskConflictError:
            already_applied = await _already_applied_direct_result_from_store(
                context=context,
                directus_service=directus_service,
                task=task,
                safe_metadata=safe_metadata,
                event_type="completed",
                message_id=message_id,
                now=now,
            )
            if already_applied:
                return already_applied
            raise
        _apply_turn_task_update(context, updated)
        return _event_result("completed", updated, context.chat_id, message_id, now)

    if skill_id == "unblock":
        task = _attached_task(context, str(args.get("task_id") or ""))
        safe_metadata = {"status": "todo", "blocked_reason_code": None, "updated_at": now}
        if _already_applied_direct_change(context, task, args.get("expected_version"), safe_metadata):
            return _event_result("unblocked", task, context.chat_id, message_id, now)
        if _already_applied_client_persisted_change(context, task, args.get("expected_version"), {}, safe_metadata):
            return _already_applied_result("unblock", task)
        try:
            _check_turn_expected_version(context, task, args.get("expected_version"))
        except UserTaskConflictError:
            already_applied = await _already_applied_direct_result_from_store(
                context=context,
                directus_service=directus_service,
                task=task,
                safe_metadata=safe_metadata,
                event_type="unblocked",
                message_id=message_id,
                now=now,
            )
            if already_applied:
                return already_applied
            raise
        if _has_pending_client_persistence(context, str(task["task_id"])):
            return await _stage_client_persisted_task_change(
                operation="unblock",
                event_type="unblocked",
                task_id=str(task["task_id"]),
                args=args,
                private_patch={},
                safe_metadata=safe_metadata,
                expected_version=_task_version(task),
                context=context,
                cache_service=cache_service,
                encryption_service=encryption_service,
                user_vault_key_id=user_vault_key_id,
                message_id=message_id,
                now=now,
            )
        try:
            updated = await UserTaskQueueService(directus_service.user_task).unblock_task(
                str(task["task_id"]),
                context.user_id,
                version=_task_version(task),
                now=now,
            )
        except UserTaskConflictError:
            already_applied = await _already_applied_direct_result_from_store(
                context=context,
                directus_service=directus_service,
                task=task,
                safe_metadata=safe_metadata,
                event_type="unblocked",
                message_id=message_id,
                now=now,
            )
            if already_applied:
                return already_applied
            raise
        _apply_turn_task_update(context, updated)
        return _event_result("unblocked", updated, context.chat_id, message_id, now)

    if skill_id == "reorder":
        raise ValueError("task_reorder is disabled until atomic multi-task persistence is available")

    if skill_id == "move":
        task = _visible_task(context, str(args.get("task_id") or ""))
        target_chat_id = str(args.get("target_chat_id") or "").strip()
        if not target_chat_id:
            raise ValueError("target_chat_id is required")
        safe_metadata = {"primary_chat_id": target_chat_id, "updated_at": now}
        if _already_applied_client_persisted_change(context, task, args.get("expected_version"), {}, safe_metadata):
            return _already_applied_result("move", task)
        _check_turn_expected_version(context, task, args.get("expected_version"))
        return await _stage_client_persisted_task_change(
            operation="move",
            event_type="moved",
            task_id=str(task["task_id"]),
            args=args,
            private_patch={},
            safe_metadata=safe_metadata,
            source_task_chat_id=str(task.get("primary_chat_id") or "") or None,
            expected_version=_task_version(task),
            context=context,
            cache_service=cache_service,
            encryption_service=encryption_service,
            user_vault_key_id=user_vault_key_id,
            message_id=message_id,
            now=now,
        )

    raise ValueError(f"Unsupported task tool '{tool_name}'")


async def publish_task_tool_result(*, cache_service: Any, user_id: str, user_id_hash: str, result: dict[str, Any]) -> None:
    event = result.get("event")
    if not isinstance(event, dict):
        return
    chat_id = event.get("chat_id")
    message_id = event.get("message_id")
    if not chat_id or not message_id:
        return
    base = {
        **event,
        "type": "task_event",
        "user_id_uuid": user_id,
        "user_id_hash": user_id_hash,
    }
    await cache_service.publish_event(f"chat_stream::{chat_id}", base)
    job = result.get("job")
    if isinstance(job, dict):
        await cache_service.publish_event(
            f"chat_stream::{chat_id}",
            {
                "type": "task_update_jobs_available",
                "chat_id": chat_id,
                "user_id_uuid": user_id,
                "user_id_hash": user_id_hash,
                "message_id": message_id,
                "jobs": [_client_job_summary(job)],
            },
        )


async def _stage_client_persisted_task_change(
    *,
    operation: str,
    event_type: str,
    task_id: str,
    args: dict[str, Any],
    private_patch: dict[str, Any],
    safe_metadata: dict[str, Any],
    expected_version: int,
    source_task_chat_id: str | None = None,
    context: TaskToolContext,
    cache_service: Any,
    encryption_service: Any,
    user_vault_key_id: str | None,
    message_id: str,
    now: int,
) -> dict[str, Any]:
    working_copy = await UserTaskWorkingCopyService(
        cache_service=cache_service,
        payload_cipher=VaultWorkflowPayloadCipher(encryption_service),
    ).stage_private_update(
        owner_id=context.user_id,
        task_id=task_id,
        private_patch=private_patch,
        safe_metadata={**safe_metadata, "operation": operation, "expected_version": expected_version},
        vault_key_id=user_vault_key_id,
        now=now,
    )
    job = {
        "job_id": f"task-update-job-{uuid.uuid4()}",
        "owner_hash": hash_id(context.user_id),
        "task_id": task_id,
        "chat_id": context.chat_id,
        "source_task_chat_id": source_task_chat_id,
        "operation": operation,
        "message_id": message_id,
        "working_copy_ref": working_copy["ref"],
        "expected_task_version": expected_version,
        "task_key_version": 1,
        "state": "PENDING",
        "lease_token": None,
        "lease_generation": 0,
        "lease_device_hash": None,
        "lease_expires_at": None,
        "created_at": now,
        "expires_at": now + DEFAULT_TASK_UPDATE_JOB_TTL_SECONDS,
    }
    await cache_service.set(_job_cache_key(job["job_id"]), job, ttl=DEFAULT_TASK_UPDATE_JOB_TTL_SECONDS)
    event = {
        "event_id": f"task-event-{uuid.uuid4()}",
        "chat_id": context.chat_id,
        "task_id": task_id,
        "short_id": args.get("task_id") or None,
        "event_type": event_type,
        "status": safe_metadata.get("status"),
        "created_at": now,
        "message_id": message_id,
        "task_update_job_id": job["job_id"],
    }
    _mark_client_persisted_turn_update(context, task_id, expected_version, private_patch, safe_metadata)
    return {"status": "pending_client_persistence", "event": event, "job": job}


def _visible_task(context: TaskToolContext, task_id: str) -> dict[str, Any]:
    lookup_id = _normalize_task_lookup_id(task_id)
    for task in context.visible_tasks:
        if lookup_id in {_normalize_task_lookup_id(task.get("task_id")), _normalize_task_lookup_id(task.get("short_id"))}:
            return task
    raise ValueError("Task is not visible in this chat turn")


def _attached_task(context: TaskToolContext, task_id: str) -> dict[str, Any]:
    lookup_id = _normalize_task_lookup_id(task_id)
    for task in context.attached_tasks:
        if lookup_id in {_normalize_task_lookup_id(task.get("task_id")), _normalize_task_lookup_id(task.get("short_id"))}:
            return task
    raise ValueError("Task changes are limited to tasks attached to the active chat")


def _check_expected_version(task: dict[str, Any], expected_version: Any) -> None:
    if expected_version is None:
        raise UserTaskConflictError("Task version is required before mutation")
    if _parse_version(expected_version) != _task_version(task):
        raise UserTaskConflictError("Task version changed before the tool call")


def _check_turn_expected_version(context: TaskToolContext, task: dict[str, Any], expected_version: Any) -> None:
    try:
        _check_expected_version(task, expected_version)
        return
    except UserTaskConflictError:
        task_id = str(task.get("task_id") or "")
        if (
            task_id
            and task_id in context.client_persisted_task_ids
            and expected_version is not None
            and _parse_version(expected_version) + 1 == _task_version(task)
        ):
            return
        raise


def _task_version(task: dict[str, Any]) -> int:
    version = task.get("version")
    if version is None:
        raise UserTaskConflictError("Task version is required before mutation")
    return _parse_version(version)


def _parse_version(value: Any) -> int:
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        if not match:
            raise ValueError("Task version must include an integer")
        return int(match.group(0))
    return int(value)


def _normalize_task_lookup_id(value: Any) -> str:
    return str(value or "").strip().lstrip("@").strip("`'\".,:;()[]{}<>")


def _has_pending_client_persistence(context: TaskToolContext, task_id: str) -> bool:
    return task_id in context.client_persisted_task_ids


def _already_applied_client_persisted_change(
    context: TaskToolContext,
    task: dict[str, Any],
    expected_version: Any,
    private_patch: dict[str, Any],
    safe_metadata: dict[str, Any],
) -> bool:
    task_id = str(task.get("task_id") or "")
    if not task_id or task_id not in context.client_persisted_task_ids or expected_version is None:
        return False
    if _expected_version_is_ahead(expected_version, task):
        return False
    return _task_matches_patch(task, private_patch) and _task_matches_patch(task, safe_metadata, ignored_keys={"updated_at"})


def _already_applied_direct_change(
    context: TaskToolContext,
    task: dict[str, Any],
    expected_version: Any,
    safe_metadata: dict[str, Any],
) -> bool:
    task_id = str(task.get("task_id") or "")
    if not task_id or task_id in context.client_persisted_task_ids or expected_version is None:
        return False
    if _expected_version_is_ahead(expected_version, task):
        return False
    return _task_matches_patch(task, safe_metadata, ignored_keys={"updated_at"})


async def _already_applied_direct_result_from_store(
    *,
    context: TaskToolContext,
    directus_service: Any,
    task: dict[str, Any],
    safe_metadata: dict[str, Any],
    event_type: str,
    message_id: str,
    now: int,
    reason_key: str | None = None,
) -> dict[str, Any] | None:
    task_id = str(task.get("task_id") or "")
    if not task_id or task_id in context.client_persisted_task_ids:
        return None
    current = await directus_service.user_task.get_task(task_id, context.user_id)
    if not current or not _task_matches_patch(current, safe_metadata, ignored_keys={"updated_at"}):
        return None
    _apply_turn_task_update(context, current)
    reason = current.get(reason_key) if reason_key else None
    return _event_result(event_type, current, context.chat_id, message_id, now, reason=reason)


def _expected_version_is_ahead(expected_version: Any, task: dict[str, Any]) -> bool:
    try:
        return _parse_version(expected_version) > _task_version(task)
    except (TypeError, ValueError):
        return False


def _task_matches_patch(task: dict[str, Any], patch: dict[str, Any], *, ignored_keys: set[str] | None = None) -> bool:
    ignored = ignored_keys or set()
    for key, value in patch.items():
        if key in ignored:
            continue
        if task.get(key) != value:
            return False
    return True


def _already_applied_result(operation: str, task: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "already_applied",
        "operation": operation,
        "task_id": task.get("task_id"),
        "version": task.get("version"),
    }


def _mark_client_persisted_turn_update(
    context: TaskToolContext,
    task_id: str,
    expected_version: int,
    private_patch: dict[str, Any],
    safe_metadata: dict[str, Any],
) -> None:
    context.client_persisted_task_ids.add(task_id)
    patch = {**private_patch, **safe_metadata, "version": int(expected_version) + 1}
    _apply_turn_task_patch(context, task_id, patch)


def _apply_turn_task_update(context: TaskToolContext, updated_task: dict[str, Any]) -> None:
    task_id = str(updated_task.get("task_id") or "")
    if task_id:
        _apply_turn_task_patch(context, task_id, updated_task)


def _apply_turn_task_patch(context: TaskToolContext, task_id: str, patch: dict[str, Any]) -> None:
    for task in [*context.attached_tasks, *context.referenced_tasks]:
        if str(task.get("task_id") or "") == task_id:
            task.update({key: value for key, value in patch.items() if value is not None})


def _event_result(event_type: str, task: dict[str, Any], chat_id: str, message_id: str, now: int, reason: Any = None) -> dict[str, Any]:
    event = {
        "event_id": f"task-event-{uuid.uuid4()}",
        "chat_id": chat_id,
        "task_id": task.get("task_id"),
        "short_id": task.get("short_id"),
        "event_type": event_type,
        "status": task.get("status"),
        "created_at": now,
        "message_id": message_id,
    }
    if reason:
        event["reason"] = str(reason)
    return {"status": "ok", "event": event, "updated_task": task}


def _safe_status(value: Any, *, default: str) -> str:
    status = str(value or default)
    return status if status in {"backlog", "todo", "in_progress", "blocked", "done"} else default


def _safe_assignee_type(value: Any) -> str:
    return "ai" if value == "ai" else "user"


def _client_job_summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "task_id": job["task_id"],
        "chat_id": job.get("chat_id"),
        "revision": job.get("expected_task_version", 0),
        "task_key_version": job.get("task_key_version", 1),
        "expires_at": job.get("expires_at"),
    }


def _job_cache_key(job_id: str) -> str:
    return f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}"
