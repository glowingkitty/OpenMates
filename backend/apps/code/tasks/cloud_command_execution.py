# backend/apps/code/tasks/cloud_command_execution.py
#
# Worker half of a cloud Project command (code.run target e2b with argv): loads
# the workspace state, runs the command through the E2B workspace provider,
# stores the new state, and, when the command changed Project files, hands the
# changes to the client as one ordered apply_changes file job. The code-run
# completion is parked until that job settles so the assistant continues with
# both the command result and what was synced back.
# Spec: feature.app-skill.code-run code-run.cloud.commands, code-run.cloud.workspace,
# code-run.cloud.command-changes-sync-back.

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from backend.apps.code.cloud_command import WORKSPACE_STATE_TTL_SECONDS, command_display, workspace_cache_key
from backend.shared.providers.e2b_code_runner import CancelCallback, CodeRunResult, OutputCallback
from backend.shared.providers.e2b_project_workspace import (
    WorkspaceCommand,
    WorkspaceOutcome,
    WorkspaceState,
    run_workspace_command,
    truncate_for_model,
)

logger = logging.getLogger(__name__)

PARKED_COMPLETION_TTL_SECONDS = 30 * 60


def parked_completion_key(operation_id: str) -> str:
    return f"code_cloud_sync_completion:{operation_id}"


def _snapshot(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(item["path"]): str(item.get("content") or "")
        for item in payload.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }


def execute_cloud_command(
    payload: dict[str, Any],
    on_output: OutputCallback,
    api_key: str,
    should_cancel: CancelCallback,
    cache_service: Any,
    run_async: Callable[[Any], Any],
) -> tuple[CodeRunResult, WorkspaceOutcome]:
    command = payload["command_run"]
    key = workspace_cache_key(str(payload["user_id"]), str(payload["chat_id"]), str(command["project_id"]))
    state = WorkspaceState.from_dict(run_async(cache_service.get(key)))
    outcome = run_workspace_command(
        _snapshot(payload),
        state,
        WorkspaceCommand(
            argv=tuple(command["argv"]), cwd=str(command.get("cwd") or "."),
            timeout_seconds=int(command["timeout_seconds"]), background=bool(command.get("background")),
            ready_url=command.get("ready_url"),
        ),
        on_output,
        api_key,
        should_cancel,
    )
    run_async(cache_service.set(key, outcome.state.to_dict(), ttl=WORKSPACE_STATE_TTL_SECONDS))
    return CodeRunResult(
        exit_code=outcome.exit_code,
        duration_seconds=outcome.duration_seconds,
        output_truncated=False,
        sandbox_id=outcome.sandbox_id,
        artifacts=[],
        skipped_artifacts=[],
    ), outcome


def command_status_fields(outcome: WorkspaceOutcome) -> dict[str, Any]:
    """Safe, bounded fields the run record and the model receive."""
    fields: dict[str, Any] = {
        "workspace": {"reused": outcome.reused},
        "changed_files": [{"path": c.path, "kind": c.kind} for c in outcome.changes],
        "not_synced_files": outcome.not_synced,
    }
    if outcome.ready is not None:
        fields["server_ready"] = outcome.ready
    return fields


def command_completion(
    completion: dict[str, Any], final_status: dict[str, Any], command_run: dict[str, Any],
) -> dict[str, Any]:
    """Bound the model's view of a command: 64 KiB output plus the command fields.

    The result names the command that ran, so the assistant can tell which of
    its commands this output belongs to and does not run it again.
    """
    result = dict(completion)
    result["command"] = command_display(list(command_run.get("argv") or []), str(command_run.get("cwd") or ".")).strip()
    # The Project snapshot paths are not part of what the command did.
    result["files"] = []
    if isinstance(result.get("output"), str):
        result["output"], truncated = truncate_for_model(result["output"])
        if truncated:
            result["output_truncated"] = True
    for key in ("workspace", "changed_files", "not_synced_files", "server_ready"):
        if key in final_status:
            result[key] = final_status[key]
    return result


async def dispatch_sync_back(
    *, payload: dict[str, Any], execution_id: str, outcome: WorkspaceOutcome,
    cache_service: Any, completion: dict[str, Any], result_status: str,
    request_metadata: dict[str, Any],
) -> str | None:
    """Create the apply_changes job and park the completion; None when nothing to sync.

    Raises PermissionError when the chat's Project focus changed since the
    command started: then nothing is written and the caller reports it.
    """
    if not outcome.changes:
        return None
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.project_file_operation_service import ProjectFileOperationService
    from backend.core.api.app.services.project_write_authorization_service import (
        ProjectWriteAuthorizationService,
    )
    from backend.core.api.app.tasks.project_file_operation_tasks import schedule_project_file_operation_deadlines

    command = payload["command_run"]
    user_id, chat_id = str(payload["user_id"]), str(payload["chat_id"])
    focus = await ProjectWriteAuthorizationService(
        DirectusService(cache_service=cache_service), cache_service,
    ).get_active_focus(user_id=user_id, chat_id=chat_id)
    if (
        not focus or focus.get("project_id") != command["project_id"]
        or (command.get("focus_id_hash") and focus.get("focus_id_hash") != command.get("focus_id_hash"))
    ):
        raise PermissionError("Project focus changed before the command's file changes could be synced back")
    operation_id = str(uuid.uuid4())
    await cache_service.set(parked_completion_key(operation_id), {
        "completion": completion, "result_status": result_status, "request_metadata": request_metadata,
    }, ttl=PARKED_COMPLETION_TTL_SECONDS)
    service = ProjectFileOperationService(cache_service)
    await service.create_operation(
        user_id=user_id, chat_id=chat_id, project_focus=dict(focus), operation="apply_changes",
        arguments={"origin": "command", "execution_id": execution_id,
                   "changes": [change.to_dict() for change in outcome.changes]},
        continuation_task_id=execution_id, message_id=payload.get("message_id"),
        operation_id=operation_id, publish=False,
    )
    record = await service.get_job(user_id=user_id, operation_id=operation_id)
    schedule_project_file_operation_deadlines(
        user_id=user_id, operation_id=operation_id, episode_id=str(record["episode_id"]),
    )
    await service.publish_available(record)
    return operation_id


async def take_parked_completion(
    cache_service: Any, operation_id: str, file_status: str, file_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the parked code-run continuation for a settled apply_changes job.

    The command result goes on with the sync-back outcome attached, so the
    assistant sees one command result. None when nothing was parked (the job
    was not created by a cloud command).
    """
    key = parked_completion_key(operation_id)
    parked = await cache_service.get(key)
    if not isinstance(parked, dict) or not isinstance(parked.get("completion"), dict):
        return None
    await cache_service.delete(key)
    sync_back = {"status": file_status, **{
        k: v for k, v in file_result.items() if k in {"results", "applied", "refused", "reason"}
    }}
    return {
        "completed_results": [{**parked["completion"], "sync_back": sync_back}],
        "result_status": str(parked.get("result_status") or "finished"),
        "request_metadata": parked.get("request_metadata") or {},
    }
