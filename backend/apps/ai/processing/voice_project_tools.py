"""Reuse first-party Project file jobs for a bound voice function response.

The client remains the file executor and approval authority. Private results
cross the worker/API boundary only under the owner's Vault key; this lane never
starts the ordinary chat continuation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any

from backend.apps.ai.processing.project_file_tools import (
    PROJECT_FILE_TOOL_TO_OPERATION, build_project_file_tools,
)
from backend.apps.ai.processing.voice_call_broker import (
    REQUEST_TIMEOUT, require_binding, transport_key, user_vault_key,
)
from backend.core.api.app.services.project_file_operation_service import (
    PROJECT_FILE_MUTATIONS, PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS,
    ProjectFileOperationError, ProjectFileOperationService,
)
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService

VOICE_PROJECT_CONTINUATION_PREFIX = "voice-project:"
_BINDING_FIELDS = ("call_id", "session_id", "user_id", "chat_id", "user_message_id", "operation_id")
_FOCUS_FIELDS = ("project_id", "focus_id_hash", "activation_id")


def _key(operation_id: str, suffix: str) -> str:
    return f"voice:project:v1:{operation_id}:{suffix}"


async def require_voice_project_job_active(cache_service: Any, job: dict) -> dict:
    """Prevent canceled voice work from being claimed on a later reconnect."""
    binding = await cache_service.get(_key(job["operation_id"], "binding"))
    if not isinstance(binding, dict) or any(binding.get(field) != job.get(field) for field in ("user_id", "chat_id")):
        raise ProjectFileOperationError("voice_project_binding_unavailable", status_code=403)
    client = await cache_service.client
    if await client.exists(transport_key(binding["operation_id"], "cancel")):
        raise ProjectFileOperationError("voice_project_operation_canceled", status_code=409)
    focus = await cache_service.get(ProjectWriteAuthorizationService._focus_key(binding["user_id"], binding["chat_id"]))
    expected = binding.get("project_focus")
    if not isinstance(focus, dict) or not isinstance(expected, dict) or any(
        focus.get(field) != expected.get(field) for field in _FOCUS_FIELDS
    ):
        raise ProjectFileOperationError("project_focus_changed", status_code=403)
    try:
        await require_binding(cache_service, {**binding, "operation": "process_request"})
    except (PermissionError, ValueError) as exc:
        raise ProjectFileOperationError("voice_project_call_inactive", status_code=403) from exc
    return binding


async def complete_voice_project_operation(*, cache_service: Any, directus_service: Any,
                                         encryption_service: Any, job: dict, result: dict,
                                         status: str, replayed: bool = False) -> None:
    """Seal a normally validated terminal callback, never dispatch a text turn."""
    if replayed:
        return
    try:
        binding = await require_voice_project_job_active(cache_service, job)
    except ProjectFileOperationError:
        # A terminal callback can acknowledge a write already committed by the
        # client, but cancellation never resumes inference or replays that write.
        return
    envelope = {**{field: binding[field] for field in _BINDING_FIELDS},
                "project_operation_id": job["operation_id"],
                "result": {"operation_id": job["operation_id"], "operation": job["operation"], "status": status,
                           **{key: value for key, value in result.items() if key not in {"operation_id", "operation", "status"}}}}
    vault_key = await user_vault_key(cache_service, directus_service, binding["user_id"])
    sealed, _ = await encryption_service.encrypt_with_user_key(json.dumps(envelope), vault_key)
    if not sealed:
        raise RuntimeError("Voice Project result could not be sealed")
    if not await cache_service.set(_key(job["operation_id"], "result"), sealed,
                                   ttl=PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS):
        raise RuntimeError("Voice Project result transport unavailable")


def _compact(value: Any, depth: int = 0, budget: list[int] | None = None) -> Any:
    budget = [24_000] if budget is None else budget
    if budget[0] <= 0:
        return "[Additional Project details omitted]"
    if depth > 6:
        return "[Additional Project details omitted]"
    if isinstance(value, dict):
        return {key[:128]: _compact(item, depth + 1, budget) for key, item in list(value.items())[:40]
                if key not in {"vault_key_id", "encrypted_content", "_user_id", "_team_id"}}
    if isinstance(value, list):
        return [_compact(item, depth + 1, budget) for item in value[:12]]
    if isinstance(value, str):
        admitted = value[:min(8000, budget[0])]
        budget[0] -= len(admitted)
        return admitted + ("\n[Content truncated for voice]" if len(admitted) < len(value) else "")
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)[:1600]


async def execute_voice_project_tool(*, tool_name: str, arguments: dict,
                                     call_binding: dict, operation_identity: str,
                                     cache_service: Any, directus_service: Any,
                                     encryption_service: Any) -> dict:
    """Dispatch one existing tool and wait within the active voice request budget."""
    schema = next((tool["function"]["parameters"] for tool in build_project_file_tools()
                   if tool["function"]["name"] == tool_name), None)
    if schema is None or tool_name not in PROJECT_FILE_TOOL_TO_OPERATION:
        raise ProjectFileOperationError("unsupported_operation")
    if not isinstance(arguments, dict) or set(arguments) - set(schema["properties"]) or any(
        field not in arguments for field in schema.get("required", [])
    ):
        raise ProjectFileOperationError("invalid_operation_arguments")
    if not isinstance(operation_identity, str) or not operation_identity or len(operation_identity) > 256:
        raise ProjectFileOperationError("invalid_operation_identity")
    if call_binding.get("expires_at") and float(call_binding["expires_at"]) <= time.time():
        raise ProjectFileOperationError("voice_project_request_expired", status_code=409)
    if "project_file_jobs" not in call_binding.get("context", {}).get("client_capabilities", []):
        raise ProjectFileOperationError("project_executor_not_ready", status_code=403)
    await require_binding(cache_service, {**call_binding, "operation": "process_request"})
    client = await cache_service.client
    if await client.exists(transport_key(call_binding["operation_id"], "cancel")):
        raise asyncio.CancelledError
    active = await ProjectWriteAuthorizationService(directus_service, cache_service).get_active_focus(
        user_id=call_binding["user_id"], chat_id=call_binding["chat_id"])
    expected = call_binding.get("project_focus")
    if not active or not isinstance(expected, dict) or not expected.get("focus_id_hash") or any(
        active.get(field) != expected.get(field) for field in _FOCUS_FIELDS
    ):
        raise ProjectFileOperationError("project_focus_changed", status_code=403)
    operation = PROJECT_FILE_TOOL_TO_OPERATION[tool_name]
    operation_arguments = dict(arguments)
    source_id = operation_arguments.pop("source_id", None)
    dispatch_focus = dict(active)
    if operation == "search":
        operation_arguments["target"] = "files" if tool_name == "project_search_files" else "content"
    if source_id is not None:
        if not isinstance(source_id, str) or not source_id or len(source_id) > 128:
            raise ProjectFileOperationError("invalid_project_source")
        source = await directus_service.project.get_source(str(active["project_id"]),
            call_binding["user_id"], source_id, team_id=active.get("team_id"))
        capability = "write_request" if operation in PROJECT_FILE_MUTATIONS else "search" if operation == "search" else "read"
        capabilities = set(source.get("capabilities") or []) if source else set()
        if not source or source.get("status") == "revoked" or capability not in capabilities or (
            operation == "search" and operation_arguments.get("include_content") is True and "read" not in capabilities
        ):
            raise ProjectFileOperationError("project_source_not_authorized", status_code=403)
        dispatch_focus["source_id"] = source_id
    service = ProjectFileOperationService(cache_service)
    service._validate_arguments(operation, operation_arguments)
    binding = {field: call_binding[field] for field in _BINDING_FIELDS}
    operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([*binding.values(), operation_identity])))
    continuation = VOICE_PROJECT_CONTINUATION_PREFIX + operation_id
    fingerprint = hashlib.sha256(json.dumps([tool_name, arguments], sort_keys=True).encode()).hexdigest()
    created = False
    async with service._state_lock(hashlib.sha256(binding["user_id"].encode()).hexdigest(), operation_id):
        existing_binding = await cache_service.get(_key(operation_id, "binding"))
        try:
            job = await service.get_job(user_id=binding["user_id"], operation_id=operation_id)
        except ProjectFileOperationError as exc:
            if exc.code != "operation_not_found":
                raise
            if not await cache_service.set(_key(operation_id, "binding"), {**binding, "fingerprint": fingerprint,
                                           "project_focus": {field: active.get(field) for field in _FOCUS_FIELDS}},
                                           ttl=PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS):
                raise RuntimeError("Voice Project binding transport unavailable")
            await service.create_operation(user_id=binding["user_id"], chat_id=binding["chat_id"],
                project_focus=dispatch_focus, operation=operation, arguments=operation_arguments,
                continuation_task_id=continuation, message_id=binding["user_message_id"],
                operation_id=operation_id, publish=False)
            job = await service.get_job(user_id=binding["user_id"], operation_id=operation_id)
            created = True
        else:
            if not isinstance(existing_binding, dict) or existing_binding.get("fingerprint") != fingerprint or (
                job.get("continuation_task_id") != continuation
            ):
                raise ProjectFileOperationError("voice_project_operation_identity_reused", status_code=409)
    deadline = min(time.time() + REQUEST_TIMEOUT - 10, float(call_binding.get("expires_at") or time.time() + REQUEST_TIMEOUT - 10))
    try:
        if created:
            from backend.core.api.app.tasks.project_file_operation_tasks import schedule_project_file_operation_deadlines
            schedule_project_file_operation_deadlines(user_id=binding["user_id"], operation_id=operation_id,
                                                      episode_id=str(job["episode_id"]))
            await service.publish_available(job)
        vault_key = await user_vault_key(cache_service, directus_service, binding["user_id"])
        while time.time() < deadline:
            await require_voice_project_job_active(cache_service, job)
            sealed = await cache_service.get(_key(operation_id, "result"))
            if sealed:
                envelope = json.loads(await encryption_service.decrypt_with_user_key(sealed, vault_key))
                if any(envelope.get(field) != binding[field] for field in _BINDING_FIELDS) or envelope.get("project_operation_id") != operation_id:
                    raise PermissionError("Voice Project result binding mismatch")
                return _compact(envelope["result"])
            current = await service.get_job(user_id=binding["user_id"], operation_id=operation_id)
            if current.get("state") == "PAUSED_REQUIRES_EXPLICIT_RESUME":
                return {"status": "paused_requires_explicit_resume", "operation_id": operation_id}
            await asyncio.sleep(0.5)
        return {"status": "paused_requires_explicit_resume", "operation_id": operation_id,
                "message": "The Project request exceeded the voice wait budget; ask again explicitly to resume."}
    finally:
        await service.cancel_voice_operation(user_id=binding["user_id"], operation_id=operation_id,
                                             continuation_task_id=continuation)
