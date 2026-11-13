"""Project snapshot hand-off for hosted-Project code-run test runs.

Project files are client-encrypted, so only the authorized client can read them.
When the assistant calls ``code-run`` with a ``test_run`` but no ``files``, the
pipeline asks the client for a ``snapshot`` Project file job, parks the files
here and the repeated ``code-run`` call picks them up (``take_snapshot``) and
injects them as inline files plus revisions.

Privacy note: the snapshot is stored as plaintext in Redis, like inference
caches, so the short TTL (15 minutes) and read-once deletion are the controls.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

SNAPSHOT_TTL_SECONDS = 900
SNAPSHOT_OPERATION = "snapshot"


def snapshot_cache_key(user_id: str, chat_id: str, project_id: str) -> str:
    user_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return f"project_test_snapshot:{user_hash}:{chat_id}:{project_id}"


async def store_snapshot(
    cache: Any, *, user_id: str, chat_id: str, project_id: str,
    files: list[dict[str, Any]], truncated: bool,
) -> None:
    await cache.set(
        snapshot_cache_key(user_id, chat_id, project_id),
        {"files": files, "truncated": bool(truncated)},
        ttl=SNAPSHOT_TTL_SECONDS,
    )


async def take_snapshot(
    cache: Any, *, user_id: str, chat_id: str, project_id: str,
) -> dict[str, Any] | None:
    """Return the cached snapshot once; it is deleted so stale files never run."""
    key = snapshot_cache_key(user_id, chat_id, project_id)
    snapshot = await cache.get(key)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("files"), list):
        return None
    await cache.delete(key)
    return snapshot


def needs_snapshot(arguments: Any) -> bool:
    if not isinstance(arguments, dict):
        return False
    test_run = arguments.get("test_run")
    if not isinstance(test_run, dict) or test_run.get("target") == "remote_source":
        return False
    return not arguments.get("files")


def snapshot_prefix(arguments: dict[str, Any]) -> str | None:
    """Relative cwd folder of the test command, or None for the whole Project."""
    command = (arguments.get("test_run") or {}).get("test_command")
    cwd = command.get("cwd") if isinstance(command, dict) else None
    if not isinstance(cwd, str):
        return None
    cleaned = cwd.replace("\\", "/").strip("/")
    if not cleaned or cleaned == "." or cleaned.startswith(("~", "./.")) or ".." in cleaned.split("/"):
        return None
    return cleaned[:512]


def inject_snapshot(arguments: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Attach snapshot files and revisions to a code-run call's arguments."""
    files = [
        {"path": item["path"], "code": item.get("code", "")}
        for item in snapshot.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]
    revisions = [
        {"path": item["path"], "revision": item["revision"]}
        for item in snapshot.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
        and isinstance(item.get("revision"), str) and item["revision"]
    ]
    result = dict(arguments)
    result["files"] = files
    result["test_run"] = {**arguments["test_run"], "revisions": revisions}
    return result


def compact_snapshot_result(operation_id: str, files: list[Any], truncated: bool) -> dict[str, Any]:
    return {
        "status": "completed",
        "operation": SNAPSHOT_OPERATION,
        "operation_id": operation_id,
        "file_count": len(files),
        "truncated": bool(truncated),
        "message": (
            "Project snapshot ready. Call code-run again with the same test_run "
            "arguments and no files; the snapshot is attached automatically."
        ),
    }


async def dispatch_snapshot_operation(
    *, cache_service: Any, directus_service: Any, request_data: Any,
    active_project_focus: dict[str, Any], skill_config_dict: Any, task_id: Any,
    preprocessing_results: Any, prefix: str | None,
) -> str:
    """Create the client-executed snapshot job; returns its operation id.

    Mirrors the system Project file tool dispatch: focus re-check, continuation
    context, job creation, deadlines and publication to the executor.
    """
    from backend.apps.ai.tasks.async_skill_continuation import (
        async_skill_continuation_key, cache_async_skill_continuation_context,
    )
    from backend.core.api.app.services.project_file_operation_service import (
        PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS, ProjectFileOperationService,
    )
    from backend.core.api.app.services.project_write_authorization_service import (
        ProjectWriteAuthorizationService,
    )
    from backend.core.api.app.tasks.project_file_operation_tasks import (
        schedule_project_file_operation_deadlines,
    )

    current_focus = await ProjectWriteAuthorizationService(
        directus_service, cache_service
    ).get_active_focus(user_id=request_data.user_id, chat_id=request_data.chat_id)
    if (
        not current_focus
        or current_focus.get("project_id") != active_project_focus.get("project_id")
        or current_focus.get("focus_id_hash") != active_project_focus.get("focus_id_hash")
    ):
        raise PermissionError("Project focus changed before snapshot dispatch")
    operation_id = str(uuid.uuid4())
    arguments = {"prefix": prefix} if prefix else {}
    await cache_async_skill_continuation_context(
        cache_service=cache_service, async_task_id=operation_id, request_data=request_data,
        skill_config_dict=skill_config_dict, app_id="system",
        source_delivery_task_id=task_id, directus_service=directus_service,
        skill_id="project_snapshot", tool_name="project_snapshot", tool_arguments=arguments,
        preprocessing_result=preprocessing_results,
        ttl_seconds=PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS,
        requires_current_turn=True, defer_until_initial_response_complete=True,
    )
    service = ProjectFileOperationService(cache_service)
    created = False
    try:
        await service.create_operation(
            user_id=request_data.user_id, chat_id=request_data.chat_id,
            project_focus=dict(current_focus), operation=SNAPSHOT_OPERATION,
            arguments=arguments, continuation_task_id=operation_id,
            message_id=request_data.message_id, operation_id=operation_id, publish=False,
        )
        created = True
    finally:
        if not created:
            # No job exists: drop the continuation context so nothing resumes the turn.
            await cache_service.delete(async_skill_continuation_key(operation_id))
    record = await service.get_job(user_id=request_data.user_id, operation_id=operation_id)
    schedule_project_file_operation_deadlines(
        user_id=request_data.user_id, operation_id=operation_id,
        episode_id=str(record["episode_id"]),
    )
    await service.publish_available(record)
    return operation_id
