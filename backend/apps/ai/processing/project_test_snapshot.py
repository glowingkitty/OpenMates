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
import json
import uuid
from typing import Any

SNAPSHOT_TTL_SECONDS = 900
SNAPSHOT_OPERATION = "snapshot"


# Arguments of the paused code-run call that the model repeats after the snapshot.
REPEATABLE_CALL_KEYS = ("target", "argv", "cwd", "background", "ready_url", "timeout_seconds", "test_run")


def repeat_call_key(operation_id: str) -> str:
    return f"project_snapshot_repeat_call:{operation_id}"


def repeatable_call(arguments: dict[str, Any]) -> dict[str, Any]:
    """The paused code-run call without files or pipeline-only fields.

    Quoted back in the snapshot result so the model repeats this exact call after
    the pause instead of choosing a different one (for example a test run in
    place of a command, whose file changes would not sync back).
    """
    return {key: arguments[key] for key in REPEATABLE_CALL_KEYS if arguments.get(key) is not None}


async def take_repeat_call(cache: Any, operation_id: str) -> dict[str, Any] | None:
    """The paused call stored for this snapshot job, read once."""
    key = repeat_call_key(operation_id)
    call = await cache.get(key)
    if not isinstance(call, dict):
        return None
    await cache.delete(key)
    return call


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


def route_machine_test_run(arguments: Any, sources: list[dict[str, Any]]) -> Any:
    """Send a test run without a target to the Project's machine source.

    Tool contract (code app ``test_run.target``): an omitted target means the
    connected source that grants run_command, else E2B. A Project whose files live
    on its only remote source (created on the user's machine) has no hosted
    snapshot, so its test run also goes to that source, where a missing
    run_command grant is reported instead of collecting an empty snapshot again
    and again. ``sources`` is the routing context of the active Project.
    """
    if not isinstance(arguments, dict):
        return arguments
    test_run = arguments.get("test_run")
    if not isinstance(test_run, dict) or test_run.get("target") is not None or test_run.get("source_id"):
        return arguments
    from backend.apps.ai.processing.project_file_tools import default_operation_source_id

    source_id = next(
        (str(source["source_id"]) for source in sources
         if "run_command" in set(source.get("capabilities") or [])),
        None,
    ) or default_operation_source_id(sources, "write_request")
    if source_id is None:
        return arguments
    return {**arguments, "test_run": {**test_run, "target": "remote_source", "source_id": source_id}}


def is_cloud_command(arguments: Any) -> bool:
    """A code-run argv command for the E2B workspace (code-run.cloud.commands)."""
    return (
        isinstance(arguments, dict)
        and not isinstance(arguments.get("test_run"), dict)
        and isinstance(arguments.get("argv"), list) and bool(arguments.get("argv"))
        and arguments.get("target", "e2b") == "e2b"
    )


def without_forged_snapshot(arguments: Any) -> Any:
    """Drop model-supplied files and snapshot markers from a cloud command.

    Only the pipeline injects the client's snapshot; a model cannot substitute
    invented files for the Project the command runs against.
    """
    if not is_cloud_command(arguments):
        return arguments
    return {key: value for key, value in arguments.items() if key not in {"files", "project_snapshot", "project_sandbox"}}


def use_project_sandbox(arguments: dict[str, Any]) -> dict[str, Any]:
    """Mark a cloud command to run in the hosted Project sandbox: no client snapshot is needed."""
    return {**arguments, "project_sandbox": True, "project_snapshot": True}


def needs_snapshot(arguments: Any) -> bool:
    if not isinstance(arguments, dict):
        return False
    if is_cloud_command(arguments):
        return not arguments.get("project_snapshot")
    test_run = arguments.get("test_run")
    if not isinstance(test_run, dict) or test_run.get("target") == "remote_source":
        return False
    return not arguments.get("files")


def snapshot_prefix(arguments: dict[str, Any]) -> str | None:
    """Relative cwd folder of the test command, or None for the whole Project.

    A cloud command always takes the whole Project: the workspace mirrors every
    Project file so files changed outside cwd are detected against their base.
    """
    if is_cloud_command(arguments):
        return None
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
    if is_cloud_command(arguments):
        result["project_snapshot"] = True
        return result
    result["test_run"] = {**arguments["test_run"], "revisions": revisions}
    return result


def compact_snapshot_result(
    operation_id: str, files: list[Any], truncated: bool, repeat_call: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if repeat_call:
        message = (
            "Project snapshot ready. Repeat the paused code-run call now with exactly these "
            f"arguments and no files: {json.dumps(repeat_call, sort_keys=True)}. "
            "The snapshot is attached automatically."
        )
    else:
        message = (
            "Project snapshot ready. Call code-run again with the same test_run or "
            "command arguments and no files; the snapshot is attached automatically."
        )
    result = {
        "status": "completed",
        "operation": SNAPSHOT_OPERATION,
        "operation_id": operation_id,
        "file_count": len(files),
        "truncated": bool(truncated),
        "message": message,
    }
    if repeat_call:
        result["repeat_call"] = repeat_call
    return result


async def dispatch_snapshot_operation(
    *, cache_service: Any, directus_service: Any, request_data: Any,
    active_project_focus: dict[str, Any], skill_config_dict: Any, task_id: Any,
    preprocessing_results: Any, prefix: str | None, repeat_call: dict[str, Any] | None = None,
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
    if repeat_call:
        await cache_service.set(
            repeat_call_key(operation_id), repeat_call, ttl=PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS,
        )
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
