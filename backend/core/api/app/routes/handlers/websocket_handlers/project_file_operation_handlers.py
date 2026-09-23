"""WebSocket claim/result handlers for client-executed Project file jobs."""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket
from pydantic import ValidationError

from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation
from backend.core.api.app.schemas.project_file_operation_schemas import (
    ProjectFileOperationClaim,
    ProjectFileOperationReject,
    ProjectFileOperationResult,
)
from backend.core.api.app.services.project_file_operation_service import (
    PROJECT_FILE_MUTATIONS,
    ProjectFileOperationError,
    ProjectFileOperationService,
)
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
)


def _start_ws_span(event_type: str, user_id: str, payload: dict[str, Any] | None, user_otel_attrs: dict | None):
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span

        return start_ws_handler_span(event_type, user_id, payload, user_otel_attrs)
    except Exception:
        return None, None


def _end_ws_span(span: Any, token: Any) -> None:
    if span is None:
        return
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span

        end_ws_handler_span(span, token)
    except Exception:
        pass


async def send_available_project_file_operations(
    *,
    manager: Any,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    chat_id: str,
) -> None:
    """Deliver reconnect work only to an authorized, assigned executor."""
    if not manager.can_execute_project_file_job(user_id, device_fingerprint_hash, chat_id):
        return
    focus = await ProjectWriteAuthorizationService(
        directus_service, cache_service
    ).get_active_focus(user_id=user_id, chat_id=chat_id)
    if not focus:
        return
    jobs = await ProjectFileOperationService(cache_service).list_available(
        user_id=user_id,
        chat_id=chat_id,
    )
    for job in jobs:
        if job.get("project_id") != focus.get("project_id"):
            continue
        await manager.send_personal_message(
            {"type": "project_file_operation_available", "payload": job},
            user_id,
            device_fingerprint_hash,
        )


async def handle_project_file_operation_claim(
    *,
    websocket: WebSocket,
    manager: Any,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    span, token = _start_ws_span("project_file_operation_claim", user_id, payload, user_otel_attrs)
    try:
        claim = ProjectFileOperationClaim.model_validate(payload)
        if not manager.can_execute_project_file_job(
            user_id, device_fingerprint_hash, claim.chat_id
        ):
            raise ProjectFileOperationError("project_executor_not_ready", status_code=403)
        focus = await ProjectWriteAuthorizationService(
            directus_service, cache_service
        ).get_active_focus(user_id=user_id, chat_id=claim.chat_id)
        if not focus or focus.get("project_id") != claim.project_id:
            raise ProjectFileOperationError("project_focus_required", status_code=403)
        request = await ProjectFileOperationService(cache_service).claim(
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
            operation_id=claim.operation_id,
            chat_id=claim.chat_id,
            project_id=claim.project_id,
        )
        await websocket.send_json(
            {"type": "project_file_operation_request", "payload": request}
        )
    except (ValidationError, ProjectFileOperationError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)
    finally:
        _end_ws_span(span, token)


async def handle_project_file_operation_result(
    *,
    websocket: WebSocket,
    manager: Any,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    span, token = _start_ws_span("project_file_operation_result", user_id, payload, user_otel_attrs)
    try:
        submitted = ProjectFileOperationResult.model_validate(payload)
        if not manager.can_execute_project_file_job(
            user_id, device_fingerprint_hash, submitted.chat_id
        ):
            raise ProjectFileOperationError("project_executor_not_ready", status_code=403)
        authorization = ProjectWriteAuthorizationService(directus_service, cache_service)
        focus = await authorization.get_active_focus(
            user_id=user_id,
            chat_id=submitted.chat_id,
        )
        if not focus or focus.get("project_id") != submitted.project_id:
            raise ProjectFileOperationError("project_focus_required", status_code=403)

        service = ProjectFileOperationService(cache_service)
        job = await service.get_job(user_id=user_id, operation_id=submitted.operation_id)
        if job.get("operation") in PROJECT_FILE_MUTATIONS and submitted.status == "completed":
            proposal_commitment = submitted.result.get("proposal_commitment")
            if not isinstance(proposal_commitment, str):
                raise ProjectFileOperationError("proposal_commitment_required")
            await authorization.require_write_authorization(
                requester_user_id=user_id,
                chat_id=submitted.chat_id,
                project_id=submitted.project_id,
                operation_id=submitted.operation_id,
                proposal_digest=proposal_commitment,
                team_id=focus.get("team_id"),
                consume_approval=submitted.status == "completed",
            )

        outcome = await service.settle(
            user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
            operation_id=submitted.operation_id,
            chat_id=submitted.chat_id,
            project_id=submitted.project_id,
            lease_token=submitted.lease_token,
            lease_generation=submitted.lease_generation,
            status=submitted.status,
            result=submitted.result,
        )
        if not outcome["terminal"]:
            if outcome.get("deferred"):
                await websocket.send_json(
                    {
                        "type": "project_file_operation_waiting",
                        "payload": {
                            **service.public_summary(outcome["job"]),
                            "reason": outcome["result"]["reason"],
                        },
                    }
                )
                return
            # The proposal is intentionally sent directly and never written to
            # the job/cache record. Approval is performed by the user/client.
            await websocket.send_json(
                {
                    "type": "project_file_operation_awaiting_approval",
                    "payload": {
                        **service.public_summary(outcome["job"]),
                        "proposal": submitted.result["proposal"],
                        "proposal_commitment": submitted.result["proposal_commitment"],
                    },
                }
            )
            return

        if outcome.get("late_after_pause"):
            # A callback that crossed the fixed boundary may be acknowledged
            # and reconciled, but it must never restart model inference. The
            # user starts a new chat turn to resume from durable chat state.
            await websocket.send_json(
                {
                    "type": "project_file_operation_late_result_recorded",
                    "payload": service.public_summary(outcome["job"]),
                }
            )
            return

        if outcome.get("replayed"):
            await websocket.send_json(
                {
                    "type": "project_file_operation_completed",
                    "payload": service.public_summary(outcome["job"]),
                }
            )
            return

        continuation_id = str(outcome["job"].get("continuation_task_id") or "")
        safe_result = await _sanitize_project_result_for_model(
            outcome.get("result", submitted.result),
            operation_id=submitted.operation_id,
            cache_service=cache_service,
            secrets_manager=getattr(websocket.app.state, "secrets_manager", None),
        )
        if safe_result is None:
            safe_result = {
                "output_withheld": True,
                "reason": "OUTPUT_SAFETY_UNAVAILABLE",
            }
        await dispatch_async_skill_continuation(
            cache_service=cache_service,
            async_task_id=continuation_id,
            completed_results=[
                {
                    "operation_id": submitted.operation_id,
                    "operation": outcome["job"].get("operation"),
                    "status": submitted.status,
                    **safe_result,
                }
            ],
            result_status=submitted.status,
            request_metadata={
                "project_id": submitted.project_id,
                "chat_id": submitted.chat_id,
            },
        )
        await websocket.send_json(
            {
                "type": "project_file_operation_completed",
                "payload": service.public_summary(outcome["job"]),
            }
        )
    except (ValidationError, ProjectFileOperationError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)
    finally:
        _end_ws_span(span, token)


async def handle_project_file_operation_reject(
    *,
    websocket: WebSocket,
    manager: Any,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    span, token = _start_ws_span("project_file_operation_reject", user_id, payload, user_otel_attrs)
    try:
        rejected = ProjectFileOperationReject.model_validate(payload)
        if not manager.can_execute_project_file_job(
            user_id, device_fingerprint_hash, rejected.chat_id
        ):
            raise ProjectFileOperationError("project_executor_not_ready", status_code=403)
        focus = await ProjectWriteAuthorizationService(
            directus_service, cache_service
        ).get_active_focus(user_id=user_id, chat_id=rejected.chat_id)
        if not focus or focus.get("project_id") != rejected.project_id:
            raise ProjectFileOperationError("project_focus_required", status_code=403)
        service = ProjectFileOperationService(cache_service)
        outcome = await service.reject_approval(
            user_id=user_id,
            operation_id=rejected.operation_id,
            chat_id=rejected.chat_id,
            project_id=rejected.project_id,
        )
        job = outcome["job"]
        if not outcome.get("replayed"):
            await dispatch_async_skill_continuation(
                cache_service=cache_service,
                async_task_id=str(job.get("continuation_task_id") or ""),
                completed_results=[
                    {
                        "operation_id": rejected.operation_id,
                        "operation": job.get("operation"),
                        "status": "user_declined",
                    }
                ],
                result_status="user_declined",
                request_metadata={"project_id": rejected.project_id, "chat_id": rejected.chat_id},
            )
        await websocket.send_json(
            {
                "type": "project_file_operation_completed",
                "payload": service.public_summary(job),
            }
        )
    except (ValidationError, ProjectFileOperationError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)
    finally:
        _end_ws_span(span, token)


async def _sanitize_project_result_for_model(
    result: dict[str, Any],
    *,
    operation_id: str,
    cache_service: Any,
    secrets_manager: Any,
) -> dict[str, Any] | None:
    """Always scan the complete client result before autonomous continuation."""
    from backend.apps.ai.processing.content_sanitization import sanitize_external_content

    serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    sanitized = await sanitize_external_content(
        serialized,
        content_type="text",
        task_id=f"project_file_result_{operation_id}",
        secrets_manager=secrets_manager,
        cache_service=cache_service,
    )
    if not sanitized:
        return None
    try:
        parsed = json.loads(sanitized)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def _send_error(websocket: WebSocket, payload: dict[str, Any], exc: Exception) -> None:
    code = getattr(exc, "code", "invalid_project_file_operation")
    await websocket.send_json(
        {
            "type": "project_file_operation_error",
            "payload": {
                "operation_id": payload.get("operation_id"),
                "chat_id": payload.get("chat_id"),
                "code": code,
            },
        }
    )
