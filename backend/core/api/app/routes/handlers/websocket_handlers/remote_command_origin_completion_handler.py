"""Origin-client completion boundary for client-encrypted remote commands."""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket
from pydantic import ValidationError

from backend.core.api.app.schemas.remote_command_schemas import RemoteCommandOriginCompletion
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
)
from backend.core.api.app.services.remote_command_service import (
    RemoteCommandError,
    RemoteCommandService,
)
from backend.shared.python_utils.terminal_output_safety import (
    sanitize_terminal_output_for_model,
)


REMOTE_COMMAND_UPSTREAM_TRUNCATION_MARKER = (
    "[Remote command transcript is incomplete: upstream output was truncated"
    "{omitted}.]\n"
)


async def _dispatch_async_skill_continuation(**kwargs: Any) -> Any:
    # Keep this WebSocket boundary importable in the API process and focused
    # unit tests without eagerly importing the Celery AI task package.
    from backend.apps.ai.tasks.async_skill_continuation import (
        dispatch_async_skill_continuation,
    )

    return await dispatch_async_skill_continuation(**kwargs)


async def complete_remote_command_output(
    *,
    websocket: WebSocket,
    cache_service: Any,
    service: RemoteCommandService,
    job: dict[str, Any],
    user_id: str,
    execution_id: str,
    chat_id: str,
    project_id: str,
    result_status: str,
    model_text: str,
    upstream_truncated: bool = False,
    omitted_chars: int | None = None,
) -> dict[str, Any]:
    """Guard one transient excerpt and dispatch at most one continuation."""

    scan_text = model_text
    if upstream_truncated:
        omitted = (
            f"; at least {omitted_chars} characters were omitted"
            if omitted_chars is not None
            else "; the omitted size is unknown"
        )
        scan_text = REMOTE_COMMAND_UPSTREAM_TRUNCATION_MARKER.format(omitted=omitted) + model_text
    checked = await sanitize_terminal_output_for_model(
        scan_text,
        task_id=f"remote_command_completion_{execution_id}",
        secrets_manager=getattr(websocket.app.state, "secrets_manager", None),
        cache_service=cache_service,
    )
    receipt = checked.receipt.to_dict()
    receipt["upstream_truncated"] = upstream_truncated
    receipt["upstream_omitted_chars"] = omitted_chars
    if upstream_truncated:
        # The scanner covered the supplied marked excerpt, not the absent
        # upstream transcript. Never report full semantic coverage in that case.
        receipt["coverage"] = "selected_excerpt"
        receipt["truncated"] = True
    outcome = await service.complete_from_origin(
        user_id=user_id,
        execution_id=execution_id,
        chat_id=chat_id,
        project_id=project_id,
        result_status=result_status,
        safety_receipt=receipt,
    )
    completed_job = outcome["job"]
    if not outcome.get("replayed"):
        result: dict[str, Any] = {
            "execution_id": execution_id,
            "status": result_status,
            "output_safety_receipt": receipt,
            "upstream_truncated": upstream_truncated,
            "upstream_omitted_chars": omitted_chars,
        }
        if checked.model_text is None:
            result.update(
                output_withheld=True,
                reason=receipt.get("scan_reason") or "OUTPUT_SAFETY_UNAVAILABLE",
            )
        else:
            result["output"] = checked.model_text
        await _dispatch_async_skill_continuation(
            cache_service=cache_service,
            async_task_id=str(completed_job.get("continuation_task_id") or ""),
            completed_results=[result],
            result_status=result_status,
            request_metadata={
                "project_id": project_id,
                "chat_id": chat_id,
                "source_id": completed_job.get("source_id") or job.get("source_id"),
            },
        )
    return outcome


async def handle_remote_command_origin_completion(
    *,
    websocket: WebSocket,
    manager: Any,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    **_: Any,
) -> None:
    """Scan transient decrypted output, finalize once, and resume inference."""

    try:
        submitted = RemoteCommandOriginCompletion.model_validate(payload)
        if not manager.can_execute_remote_command_job(
            user_id, device_fingerprint_hash, submitted.chat_id
        ):
            raise RemoteCommandError("origin_completion_client_not_current", status_code=403)

        focus = await ProjectWriteAuthorizationService(
            directus_service, cache_service
        ).get_active_focus(user_id=user_id, chat_id=submitted.chat_id)
        if not focus or focus.get("project_id") != submitted.project_id:
            raise RemoteCommandError("project_focus_required", status_code=403)

        service = RemoteCommandService(cache_service)
        job = await service.require_origin_job(
            user_id=user_id,
            execution_id=submitted.execution_id,
            chat_id=submitted.chat_id,
            project_id=submitted.project_id,
        )
        if job.get("state") == "TERMINAL":
            if job.get("result_status") != submitted.result_status:
                raise RemoteCommandError("completion_mismatch", status_code=409)
            await websocket.send_json(
                {
                    "type": "remote_command_origin_completion_ack",
                    "payload": service.public_summary(job),
                }
            )
            return
        if (
            job.get("state") != "AWAITING_ORIGIN_COMPLETION"
            or job.get("result_status") != submitted.result_status
        ):
            raise RemoteCommandError("origin_completion_not_ready", status_code=409)

        outcome = await complete_remote_command_output(
            websocket=websocket,
            cache_service=cache_service,
            service=service,
            job=job,
            user_id=user_id,
            execution_id=submitted.execution_id,
            chat_id=submitted.chat_id,
            project_id=submitted.project_id,
            result_status=submitted.result_status,
            model_text=submitted.model_text,
            upstream_truncated=submitted.upstream_truncated,
            omitted_chars=submitted.omitted_chars,
        )
        completed_job = outcome["job"]
        await websocket.send_json(
            {
                "type": "remote_command_origin_completion_ack",
                "payload": service.public_summary(completed_job),
            }
        )
    except (ValidationError, RemoteCommandError, ProjectWriteAuthorizationError) as exc:
        code = getattr(exc, "code", None)
        if not isinstance(code, str):
            code = "invalid_remote_command_message" if isinstance(exc, ValidationError) else "remote_command_failed"
        await websocket.send_json(
            {
                "type": "remote_command_error",
                "payload": {
                    "execution_id": payload.get("execution_id"),
                    "code": code,
                },
            }
        )
