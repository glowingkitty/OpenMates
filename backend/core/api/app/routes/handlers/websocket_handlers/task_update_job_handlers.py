"""
WebSocket handlers for Tasks V1 client-encrypted update jobs.

The AI worker stores a vault-encrypted working copy and a metadata-only Redis
job. An authenticated client claims the job, encrypts task content locally with
the task key, then sends only encrypted fields back for durable persistence.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

from backend.apps.ai.processing.task_tool_executor import TASK_TOOL_JOB_CACHE_PREFIX
from backend.core.api.app.services.directus.user_task_methods import hash_id
from backend.core.api.app.services.user_task_update_job_service import (
    DEFAULT_TASK_UPDATE_JOB_LEASE_TTL_SECONDS,
    TaskUpdateJobConflictError,
    TaskUpdateJobNotFoundError,
)
from backend.core.api.app.services.user_task_working_copy_service import UserTaskWorkingCopyService
from backend.core.api.app.services.workflow_service import VaultWorkflowPayloadCipher


logger = logging.getLogger(__name__)
TASK_EVENT_CONFIRMATION_RECOVERY_TTL_SECONDS = 24 * 60 * 60
SYSTEM_MESSAGE_CONFIRMATION_TTL_SECONDS = TASK_EVENT_CONFIRMATION_RECOVERY_TTL_SECONDS


def system_message_confirmation_cache_key(user_id: str, chat_id: str, message_id: str) -> str:
    return f"system_message_confirmed:{hash_id(user_id)}:{hash_id(chat_id)}:{hash_id(message_id)}"


def _start_ws_span(event_type: str, user_id: str, payload: dict[str, Any] | None, user_otel_attrs: dict | None):
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span

        return start_ws_handler_span(event_type, user_id, payload, user_otel_attrs)
    except Exception:
        return None, None


def _end_ws_span(otel_span: Any, otel_token: Any) -> None:
    if otel_span is None:
        return
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span

        end_ws_handler_span(otel_span, otel_token)
    except Exception:
        pass


def _request_id(payload: dict[str, Any]) -> str | None:
    request_id = payload.get("request_id")
    if isinstance(request_id, str) and request_id and len(request_id) <= 128:
        return request_id
    return None


async def send_available_task_update_jobs(
    *,
    manager: Any,
    cache_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
) -> None:
    jobs = await _list_available_jobs(cache_service, user_id)
    if not jobs:
        return
    await manager.send_personal_message(
        {"type": "task_update_jobs_available", "payload": {"jobs": [_job_summary(job) for job in jobs]}},
        user_id,
        device_fingerprint_hash,
    )


async def handle_task_update_job_claim(
    *,
    manager: Any,
    cache_service: Any,
    encryption_service: Any,
    user_id: str,
    user_vault_key_id: str | None,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "task_update_job_claim",
        user_id,
        payload,
        user_otel_attrs,
    )
    request_id = _request_id(payload)
    job_id = str(payload.get("job_id") or "")
    try:
        _validate_protocol_version(payload)
        job = await _load_visible_job(cache_service, job_id, user_id)
        now = int(time.time())
        if int(job.get("expires_at") or 0) <= now:
            raise TaskUpdateJobNotFoundError("Task update job expired")
        if job.get("state") == "TERMINAL":
            raise TaskUpdateJobConflictError("Task update job already committed")
        if job.get("state") == "TASK_PERSISTED":
            pass
        elif job.get("state") == "LEASED" and int(job.get("lease_expires_at") or 0) > now:
            if job.get("lease_device_hash") != device_fingerprint_hash:
                raise TaskUpdateJobConflictError("Task update job is leased by another device")
        else:
            job["state"] = "LEASED"
            job["lease_token"] = secrets.token_urlsafe(24)
            job["lease_generation"] = int(job.get("lease_generation") or 0) + 1
            job["lease_device_hash"] = device_fingerprint_hash
            job["lease_expires_at"] = now + DEFAULT_TASK_UPDATE_JOB_LEASE_TTL_SECONDS
            await _save_job(cache_service, job)

        working_copy = await UserTaskWorkingCopyService(
            cache_service=cache_service,
            payload_cipher=VaultWorkflowPayloadCipher(encryption_service),
        ).load_private_update(
            owner_id=user_id,
            ref=str(job.get("working_copy_ref") or ""),
            vault_key_id=user_vault_key_id,
        )
        await manager.send_personal_message(
            {
                "type": "task_update_job_claimed",
                "payload": {
                    "request_id": request_id,
                    "job_id": job["job_id"],
                    "task_id": job["task_id"],
                    "chat_id": job.get("chat_id"),
                    "message_id": job.get("message_id"),
                    "operation": job.get("operation"),
                    "state": job["state"],
                    "lease_token": job["lease_token"],
                    "lease_generation": job["lease_generation"],
                    "lease_expires_at": job["lease_expires_at"],
                    "expected_task_version": job["expected_task_version"],
                    "task_key_version": job.get("task_key_version", 1),
                    "private_patch": working_copy.get("private_patch") or {},
                    "safe_metadata": working_copy.get("safe_metadata") or {},
                },
            },
            user_id,
            device_fingerprint_hash,
        )
    except Exception as exc:
        await _send_error(manager, user_id, device_fingerprint_hash, job_id, request_id, exc)
    finally:
        _end_ws_span(_otel_span, _otel_token)


async def handle_task_update_job_persist(
    *,
    manager: Any,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "task_update_job_persist",
        user_id,
        payload,
        user_otel_attrs,
    )
    request_id = _request_id(payload)
    job_id = str(payload.get("job_id") or "")
    lock_key: str | None = None
    lock_token = secrets.token_urlsafe(16)
    lock_acquired = False
    try:
        _validate_protocol_version(payload)
        job = await _load_visible_job(cache_service, job_id, user_id)
        encrypted_payload = dict(payload.get("encrypted_task_payload") or {})
        _validate_encrypted_payload(encrypted_payload)
        if job.get("state") == "TERMINAL":
            await manager.send_personal_message(
                {"type": "task_update_job_persisted", "payload": {"request_id": request_id, "job_id": job_id, "state": "TERMINAL", "task_id": job.get("task_id")}},
                user_id,
                device_fingerprint_hash,
            )
            return
        task_id = str(job["task_id"])
        lock_key = f"task_update_job_persist_lock:{job.get('owner_hash')}:{hash_id(task_id)}"
        lock_acquired = await _acquire_lock(cache_service, lock_key, lock_token)
        if not lock_acquired:
            raise TaskUpdateJobConflictError("Task update job for this task is already being persisted")
        job = await _load_visible_job(cache_service, job_id, user_id)
        if job.get("state") == "TERMINAL":
            await manager.send_personal_message(
                {"type": "task_update_job_persisted", "payload": {"request_id": request_id, "job_id": job_id, "state": "TERMINAL", "task_id": job.get("task_id")}},
                user_id,
                device_fingerprint_hash,
            )
            return
        if job.get("state") != "LEASED":
            raise TaskUpdateJobConflictError("Task update job has no active lease")
        if int(job.get("lease_expires_at") or 0) <= int(time.time()):
            raise TaskUpdateJobConflictError("Task update job lease expired")
        if job.get("lease_device_hash") != device_fingerprint_hash:
            raise TaskUpdateJobConflictError("Task update job lease belongs to another device")
        if job.get("lease_token") != payload.get("lease_token") or int(job.get("lease_generation") or 0) != int(payload.get("lease_generation") or 0):
            raise TaskUpdateJobConflictError("Task update job lease is stale")
        if int(job.get("expected_task_version") or 0) != int(payload.get("expected_task_version") or -1):
            raise TaskUpdateJobConflictError("Task update job expected task version is stale")

        operation = str(job.get("operation") or "update")
        task_id = str(job["task_id"])
        if operation == "create":
            if await directus_service.user_task.get_task(task_id, user_id):
                raise TaskUpdateJobConflictError("Task already exists")
            durable = await directus_service.user_task.create_task(user_id, {**encrypted_payload, "task_id": task_id})
        else:
            durable = await directus_service.user_task.update_task_if_version(
                task_id,
                user_id,
                encrypted_payload,
                int(job.get("expected_task_version") or 0),
            )
            if not durable:
                current = await directus_service.user_task.get_task(task_id, user_id)
                if not current:
                    raise TaskUpdateJobNotFoundError("Task not found")
                raise TaskUpdateJobConflictError("Task changed before encrypted persistence")
        if not durable:
            raise RuntimeError("Failed to persist encrypted task update")

        job["state"] = "TASK_PERSISTED"
        job["client_encrypted_payload"] = encrypted_payload
        job["encrypted_task_event_message"] = payload.get("encrypted_task_event_message")
        job["committed_at"] = int(time.time())
        job["expires_at"] = int(time.time()) + TASK_EVENT_CONFIRMATION_RECOVERY_TTL_SECONDS
        await UserTaskWorkingCopyService(
            cache_service=cache_service,
            payload_cipher=VaultWorkflowPayloadCipher(getattr(directus_service, "encryption_service", None)),
        ).extend_private_update_ttl(
            owner_id=user_id,
            ref=str(job.get("working_copy_ref") or ""),
            ttl_seconds=TASK_EVENT_CONFIRMATION_RECOVERY_TTL_SECONDS,
        )
        await _save_job(cache_service, job)
        await manager.send_personal_message(
            {"type": "task_update_job_persisted", "payload": {"request_id": request_id, "job_id": job_id, "state": "TASK_PERSISTED", "task_id": task_id}},
            user_id,
            device_fingerprint_hash,
        )
    except Exception as exc:
        await _send_error(manager, user_id, device_fingerprint_hash, job_id, request_id, exc)
    finally:
        if lock_acquired and lock_key:
            await _release_lock(cache_service, lock_key, lock_token)
        _end_ws_span(_otel_span, _otel_token)


async def handle_task_update_job_event_confirmed(
    *,
    manager: Any,
    cache_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    request_id = _request_id(payload)
    job_id = str(payload.get("job_id") or "")
    try:
        _validate_protocol_version(payload)
        job = await _load_visible_job(cache_service, job_id, user_id)
        if job.get("state") == "TERMINAL":
            await manager.send_personal_message(
                {"type": "task_update_job_event_confirmed", "payload": {"request_id": request_id, "job_id": job_id, "state": "TERMINAL", "task_id": job.get("task_id")}},
                user_id,
                device_fingerprint_hash,
            )
            return
        if job.get("state") != "TASK_PERSISTED":
            raise TaskUpdateJobConflictError("Task update job has no persisted task update to confirm")
        event_system_message_id = payload.get("event_system_message_id")
        if not isinstance(event_system_message_id, str) or not event_system_message_id or len(event_system_message_id) > 128:
            raise ValueError("Missing task event system message confirmation id")
        chat_id = job.get("chat_id")
        if not isinstance(chat_id, str) or not chat_id:
            raise TaskUpdateJobConflictError("Task update job has no source chat for event confirmation")
        confirmation = await cache_service.get(system_message_confirmation_cache_key(user_id, chat_id, event_system_message_id))
        if not isinstance(confirmation, dict):
            raise TaskUpdateJobConflictError("Task event system message has not been confirmed")
        if confirmation.get("user_message_id") != job.get("message_id") or confirmation.get("task_update_job_id") != job_id:
            raise TaskUpdateJobConflictError("Task event system message confirmation does not match this job")
        job["state"] = "TERMINAL"
        job["event_persisted_at"] = int(time.time())
        job["event_system_message_id"] = event_system_message_id
        await _save_job(cache_service, job)
        await manager.send_personal_message(
            {"type": "task_update_job_event_confirmed", "payload": {"request_id": request_id, "job_id": job_id, "state": "TERMINAL", "task_id": job.get("task_id")}},
            user_id,
            device_fingerprint_hash,
        )
    except Exception as exc:
        await _send_error(manager, user_id, device_fingerprint_hash, job_id, request_id, exc)


async def _list_available_jobs(cache_service: Any, user_id: str) -> list[dict[str, Any]]:
    owner_hash = hash_id(user_id)
    keys = await cache_service.get_keys_by_pattern(f"{TASK_TOOL_JOB_CACHE_PREFIX}*")
    jobs: list[dict[str, Any]] = []
    now = int(time.time())
    for key in keys:
        job = await cache_service.get(key)
        if isinstance(job, dict) and job.get("owner_hash") == owner_hash and job.get("state") != "TERMINAL" and int(job.get("expires_at") or 0) > now:
            jobs.append(job)
    return jobs


async def _load_visible_job(cache_service: Any, job_id: str, user_id: str) -> dict[str, Any]:
    job = await cache_service.get(f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}")
    if not isinstance(job, dict) or job.get("owner_hash") != hash_id(user_id):
        raise TaskUpdateJobNotFoundError("Task update job not found")
    return job


async def _save_job(cache_service: Any, job: dict[str, Any]) -> None:
    ttl = max(1, int(job.get("expires_at") or time.time()) - int(time.time()))
    stored = await cache_service.set(f"{TASK_TOOL_JOB_CACHE_PREFIX}{job['job_id']}", job, ttl=ttl)
    if stored is False:
        raise RuntimeError("Failed to save task update job")


async def _acquire_lock(cache_service: Any, key: str, token: str) -> bool:
    client = await cache_service.client
    if not client:
        return False
    return bool(await client.set(key, token, nx=True, ex=30))


async def _release_lock(cache_service: Any, key: str, token: str) -> None:
    client = await cache_service.client
    if not client:
        return
    current = await client.get(key)
    if isinstance(current, bytes):
        current = current.decode("utf-8")
    if current == token:
        await client.delete(key)


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "task_id": job.get("task_id"),
        "chat_id": job.get("chat_id"),
        "revision": job.get("expected_task_version"),
        "task_key_version": job.get("task_key_version", 1),
        "expires_at": job.get("expires_at"),
    }


def _validate_encrypted_payload(payload: dict[str, Any]) -> None:
    allowed_safe = {"version", "key_wrappers", "linked_project_ids", "task_id", "status", "assignee_type", "assignee_hash", "primary_chat_id", "position", "created_at", "updated_at", "blocked_reason_code", "priority"}
    for key in payload:
        if key.startswith("encrypted_") or key in allowed_safe:
            continue
        raise ValueError("Task update job payload contains plaintext or unsupported field")


def _validate_protocol_version(payload: dict[str, Any]) -> None:
    if payload.get("protocol_version") != 1:
        raise ValueError("Unsupported task update job protocol version")


async def _send_error(manager: Any, user_id: str, device_hash: str, job_id: str | None, request_id: str | None, exc: Exception) -> None:
    logger.warning("Task update job protocol rejected job=%s: %s", job_id, exc)
    await manager.send_personal_message(
        {
            "type": "error",
            "payload": {
                "code": exc.__class__.__name__,
                "message": "Encrypted task update was rejected.",
                "job_id": job_id,
                "request_id": request_id,
            },
        },
        user_id,
        device_hash,
    )
