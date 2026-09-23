"""Authenticated WebSocket boundaries for opaque remote-command jobs."""

from __future__ import annotations

import time
from typing import Any

from fastapi import WebSocket
from pydantic import ValidationError

from backend.core.api.app.schemas.remote_command_schemas import (
    RemoteCommandClaim,
    RemoteCommandDiscover,
    RemoteCommandPrepare,
    RemoteCommandReject,
    RemoteCommandRecover,
    RemoteCommandRevalidate,
    RemoteCommandRuntimeEvent,
    RemoteCommandSourceCompletion,
    RemoteCommandStop,
)
from backend.core.api.app.routes.handlers.websocket_handlers.remote_command_origin_completion_handler import (
    _dispatch_async_skill_continuation,
    complete_remote_command_output,
)
from backend.core.api.app.services.project_remote_access_service import (
    ProjectRemoteAccessError,
    ProjectRemoteAccessService,
)
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
)
from backend.core.api.app.services.remote_command_service import (
    RemoteCommandError,
    RemoteCommandService,
)


async def handle_remote_command_prepare(
    *, websocket: WebSocket, manager: Any, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any], **_: Any,
) -> None:
    try:
        submitted = RemoteCommandPrepare.model_validate(payload)
        if not manager.can_execute_remote_command_job(user_id, device_fingerprint_hash, submitted.chat_id):
            raise RemoteCommandError("origin_review_client_not_current", status_code=403)
        focus = await _require_focus(
            cache_service, directus_service, user_id, submitted.chat_id, submitted.project_id
        )
        source = await directus_service.project.get_source(
            submitted.project_id, user_id, submitted.source_id, team_id=focus.get("team_id")
        )
        if not source or source.get("status") == "revoked" or "run_command" not in set(source.get("capabilities") or []):
            raise RemoteCommandError("source_capability_denied", status_code=403)
        binding = await ProjectRemoteAccessService(cache_service).get_active_binding(
            user_id, submitted.project_id, submitted.source_id,
            team_id=focus.get("team_id"), now=int(time.time()),
        )
        result = await RemoteCommandService(cache_service).prepare(
            user_id=user_id,
            execution_id=submitted.execution_id,
            chat_id=submitted.chat_id,
            project_id=submitted.project_id,
            source_id=submitted.source_id,
            review_token=submitted.review_token,
            encrypted_request=submitted.encrypted_request,
            request_digest=submitted.request_digest,
            approval=submitted.approval.model_dump(exclude_none=True),
            binding=binding,
        )
        await websocket.send_json({"type": "remote_command_prepared", "payload": result})
    except (ValidationError, RemoteCommandError, ProjectRemoteAccessError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)


async def handle_remote_command_reject(
    *, websocket: WebSocket, manager: Any, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any], **_: Any,
) -> None:
    try:
        submitted = RemoteCommandReject.model_validate(payload)
        if not manager.can_execute_remote_command_job(user_id, device_fingerprint_hash, submitted.chat_id):
            raise RemoteCommandError("origin_review_client_not_current", status_code=403)
        await _require_focus(cache_service, directus_service, user_id, submitted.chat_id, submitted.project_id)
        service = RemoteCommandService(cache_service)
        outcome = await service.reject_review(
            user_id=user_id,
            execution_id=submitted.execution_id,
            chat_id=submitted.chat_id,
            project_id=submitted.project_id,
            review_token=submitted.review_token,
        )
        job = outcome["job"]
        if not outcome["replayed"]:
            await _dispatch_async_skill_continuation(
                cache_service=cache_service,
                async_task_id=str(job.get("continuation_task_id") or ""),
                completed_results=[{
                    "execution_id": submitted.execution_id,
                    "status": "rejected",
                    "error": "The user declined this remote command.",
                }],
                result_status="failed",
                request_metadata={
                    "project_id": submitted.project_id,
                    "chat_id": submitted.chat_id,
                    "source_id": job.get("source_id"),
                },
            )
        await websocket.send_json({"type": "remote_command_rejected", "payload": service.public_summary(job)})
    except (ValidationError, RemoteCommandError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)


async def handle_remote_command_claim(
    *, websocket: WebSocket, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any], **_: Any,
) -> None:
    try:
        submitted = RemoteCommandClaim.model_validate(payload)
        service = RemoteCommandService(cache_service)
        job = await service.resolve_job(execution_id=submitted.execution_id)
        _require_team_scope(job, submitted.team_id)
        await _require_focus(
            cache_service, directus_service, str(job["user_id"]), str(job["chat_id"]), submitted.project_id
        )
        binding = await ProjectRemoteAccessService(cache_service).get_active_binding(
            user_id, submitted.project_id, submitted.source_id,
            team_id=submitted.team_id, now=int(time.time()),
        )
        result = await service.claim(
            host_user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=submitted.source_session_id,
            execution_id=submitted.execution_id,
            project_id=submitted.project_id,
            source_id=submitted.source_id,
            binding=binding,
        )
        await websocket.send_json({"type": "remote_command_request", "payload": result})
    except (ValidationError, RemoteCommandError, ProjectRemoteAccessError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)


async def handle_remote_command_discover(
    *, websocket: WebSocket, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any], **_: Any,
) -> None:
    try:
        submitted = RemoteCommandDiscover.model_validate(payload)
        binding = await ProjectRemoteAccessService(cache_service).get_active_binding(
            user_id, submitted.project_id, submitted.source_id,
            team_id=submitted.team_id, now=int(time.time())
        )
        jobs = await RemoteCommandService(cache_service).list_for_source(
            host_user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=submitted.source_session_id,
            project_id=submitted.project_id,
            source_id=submitted.source_id,
            binding=binding,
        )
        jobs = [job for job in jobs if job.get("team_id") == submitted.team_id]
        # Discovery returns state/last_sequence only. The source claims an
        # unknown WAITING job or resumes its locally tracked process; it never
        # relaunches merely because discovery found LEASED/RUNNING state.
        await websocket.send_json({"type": "remote_command_jobs", "payload": {"jobs": jobs}})
    except (ValidationError, RemoteCommandError, ProjectRemoteAccessError) as exc:
        await _send_error(websocket, payload, exc)


async def handle_remote_command_recover(
    *, websocket: WebSocket, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any], **_: Any,
) -> None:
    try:
        submitted = RemoteCommandRecover.model_validate(payload)
        service = RemoteCommandService(cache_service)
        job = await service.resolve_job(execution_id=submitted.execution_id)
        _require_team_scope(job, submitted.team_id)
        await _require_focus(
            cache_service, directus_service, str(job["user_id"]), str(job["chat_id"]), submitted.project_id
        )
        binding = await ProjectRemoteAccessService(cache_service).get_active_binding(
            user_id, submitted.project_id, submitted.source_id,
            team_id=submitted.team_id, now=int(time.time()),
        )
        result = await service.recover(
            host_user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=submitted.source_session_id,
            execution_id=submitted.execution_id,
            project_id=submitted.project_id,
            source_id=submitted.source_id,
            last_sequence=submitted.last_sequence,
            runtime_status=submitted.runtime_status,
            binding=binding,
        )
        await websocket.send_json({"type": "remote_command_recovered", "payload": result})
    except (ValidationError, RemoteCommandError, ProjectRemoteAccessError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)


async def handle_remote_command_event(
    *, websocket: WebSocket, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any], **_: Any,
) -> None:
    try:
        submitted = RemoteCommandRuntimeEvent.model_validate(payload)
        service = RemoteCommandService(cache_service)
        job = await service.resolve_job(execution_id=submitted.execution_id)
        _require_team_scope(job, submitted.team_id)
        await _require_focus(
            cache_service, directus_service, str(job["user_id"]), str(job["chat_id"]), submitted.project_id
        )
        binding = await ProjectRemoteAccessService(cache_service).get_active_binding(
            user_id, submitted.project_id, submitted.source_id,
            team_id=submitted.team_id, now=int(time.time()),
        )
        result = await service.record_event(
            host_user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=submitted.source_session_id,
            execution_id=submitted.execution_id,
            project_id=submitted.project_id,
            source_id=submitted.source_id,
            lease_token=submitted.lease_token,
            lease_generation=submitted.lease_generation,
            sequence=submitted.sequence,
            event_kind=submitted.event_kind,
            status=submitted.status,
            encrypted_event=submitted.encrypted_event,
            binding=binding,
        )
        await websocket.send_json({"type": "remote_command_event_ack", "payload": result})
    except (ValidationError, RemoteCommandError, ProjectRemoteAccessError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)


async def handle_remote_command_source_completion(
    *, websocket: WebSocket, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any], **_: Any,
) -> None:
    """Accept one source-authorized terminal event and transient inference excerpt."""
    try:
        submitted = RemoteCommandSourceCompletion.model_validate(payload)
        service = RemoteCommandService(cache_service)
        job = await service.resolve_job(execution_id=submitted.execution_id)
        _require_team_scope(job, submitted.team_id)
        await _require_focus(
            cache_service,
            directus_service,
            str(job["user_id"]),
            str(job["chat_id"]),
            submitted.project_id,
        )
        binding = await ProjectRemoteAccessService(cache_service).get_active_binding(
            user_id,
            submitted.project_id,
            submitted.source_id,
            team_id=submitted.team_id,
            now=int(time.time()),
        )
        await service.record_event(
            host_user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=submitted.source_session_id,
            execution_id=submitted.execution_id,
            project_id=submitted.project_id,
            source_id=submitted.source_id,
            lease_token=submitted.lease_token,
            lease_generation=submitted.lease_generation,
            sequence=submitted.sequence,
            event_kind="terminal",
            status=submitted.status,
            encrypted_event=submitted.encrypted_event,
            binding=binding,
        )
        outcome = await complete_remote_command_output(
            websocket=websocket,
            cache_service=cache_service,
            service=service,
            job=job,
            user_id=str(job["user_id"]),
            execution_id=submitted.execution_id,
            chat_id=str(job["chat_id"]),
            project_id=submitted.project_id,
            result_status=submitted.status,
            model_text=submitted.model_text,
            upstream_truncated=submitted.upstream_truncated,
            omitted_chars=submitted.omitted_chars,
        )
        await websocket.send_json(
            {
                "type": "remote_command_source_completion_ack",
                "payload": service.public_summary(outcome["job"]),
            }
        )
    except (ValidationError, RemoteCommandError, ProjectRemoteAccessError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)


async def handle_remote_command_revalidate(
    *, websocket: WebSocket, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any], **_: Any,
) -> None:
    try:
        submitted = RemoteCommandRevalidate.model_validate(payload)
        service = RemoteCommandService(cache_service)
        job = await service.resolve_job(execution_id=submitted.execution_id)
        _require_team_scope(job, submitted.team_id)
        await _require_focus(
            cache_service, directus_service, str(job["user_id"]), str(job["chat_id"]), submitted.project_id
        )
        binding = await ProjectRemoteAccessService(cache_service).get_active_binding(
            user_id, submitted.project_id, submitted.source_id,
            team_id=submitted.team_id, now=int(time.time()),
        )
        result = await service.revalidate(
            host_user_id=user_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=submitted.source_session_id,
            execution_id=submitted.execution_id,
            project_id=submitted.project_id,
            source_id=submitted.source_id,
            lease_token=submitted.lease_token,
            lease_generation=submitted.lease_generation,
            binding=binding,
        )
        await websocket.send_json({"type": "remote_command_authority", "payload": result})
    except (ValidationError, RemoteCommandError, ProjectRemoteAccessError, ProjectWriteAuthorizationError) as exc:
        await _send_error(websocket, payload, exc)


async def handle_remote_command_stop(
    *, websocket: WebSocket, cache_service: Any, directus_service: Any,
    user_id: str, payload: dict[str, Any], **_: Any,
) -> None:
    try:
        submitted = RemoteCommandStop.model_validate(payload)
        result = await RemoteCommandService(cache_service).request_stop(
            user_id=user_id,
            execution_id=submitted.execution_id,
            chat_id=submitted.chat_id,
            project_id=submitted.project_id,
        )
        await websocket.send_json({"type": "remote_command_stop_ack", "payload": result})
    except (ValidationError, RemoteCommandError) as exc:
        await _send_error(websocket, payload, exc)


async def _require_focus(
    cache_service: Any, directus_service: Any, user_id: str, chat_id: str, project_id: str,
) -> dict[str, Any]:
    focus = await ProjectWriteAuthorizationService(directus_service, cache_service).get_active_focus(
        user_id=user_id, chat_id=chat_id
    )
    if not focus or focus.get("project_id") != project_id:
        raise RemoteCommandError("project_focus_required", status_code=403)
    return focus


def _require_team_scope(job: dict[str, Any], team_id: str | None) -> None:
    if job.get("team_id") != team_id:
        raise RemoteCommandError("command_team_scope_mismatch", status_code=403)


async def _send_error(websocket: WebSocket, payload: dict[str, Any], exc: Exception) -> None:
    code = getattr(exc, "code", None)
    if not isinstance(code, str):
        code = "invalid_remote_command_message" if isinstance(exc, ValidationError) else "remote_command_failed"
    await websocket.send_json(
        {
            "type": "remote_command_error",
            "payload": {"execution_id": payload.get("execution_id"), "code": code},
        }
    )
