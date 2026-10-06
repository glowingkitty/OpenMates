"""
WebSocket handlers for sealed completion recovery jobs.

Only authenticated owner and server-derived device identities reach the
transaction service. Clients receive sealed payloads after a fenced lease and
terminal acknowledgement only after encrypted assistant persistence commits.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable
from uuid import UUID

from backend.core.api.app.services.chat_recovery_service import (
    ChatRecoveryProtocolError,
    ChatRecoveryService,
)
from backend.shared.python_utils.chat_failure_notifications import (
    notification_environment,
    notify_chat_failure,
)


logger = logging.getLogger(__name__)
_DIRECT_COMPLETION_CURSOR_KEY = "chat_recovery:direct_completion_reconcile_cursor:v1"
_DIRECT_COMPLETION_RECONCILE_LIMIT = 100


async def begin_initial_recovery_discovery(
    *, manager: Any, directus_service: Any, user_id: str,
    user_id_hash: str, device_fingerprint_hash: str,
    supports_typed_recovery_outputs: bool,
    get_epoch: Callable[[], Awaitable[int]],
    user_otel_attrs: dict | None = None,
) -> list[asyncio.Task]:
    """Keep typed recovery dormant until the first foreground lifecycle ACK."""
    if supports_typed_recovery_outputs:
        return []
    try:
        recovery_epoch = await get_epoch()
    except Exception:
        logger.exception("Authoritative recovery discovery epoch read failed")
        recovery_epoch = None
    if recovery_epoch is not None and recovery_epoch >= 1:
        task = asyncio.create_task(send_available_recovery_jobs(
            manager=manager, directus_service=directus_service,
            user_id=user_id, user_id_hash=user_id_hash,
            device_fingerprint_hash=device_fingerprint_hash,
            user_otel_attrs=user_otel_attrs,
        ))
        await manager.send_personal_message(
            {"type": "recovery_outputs_discovery_complete", "payload": {"status": "disabled"}},
            user_id, device_fingerprint_hash,
        )
        return [task]
    await manager.send_personal_message(
        {"type": "recovery_outputs_discovery_complete", "payload": {
            "status": "failed" if recovery_epoch is None else "disabled",
        }},
        user_id, device_fingerprint_hash,
    )
    return []


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


def _create_cache_service() -> Any:
    from backend.core.api.app.services.cache import CacheService

    return CacheService()


async def _acknowledge_output_cache_if_complete(
    *, directus_service: Any, user_id_hash: str, chat_id: str,
) -> None:
    cache = _create_cache_service()
    try:
        # A task queued while another output is pending will defer at SQL policy;
        # the debounce and minute sweep cover ordinary and lost ACK deliveries.
        try:
            from backend.core.api.app.tasks.storage_tasks import enqueue_warm_archive_check
            await enqueue_warm_archive_check(cache_service=cache, chat_id=chat_id)
        except Exception:
            logger.exception("Could not enqueue warm archive check after canonical output ACK")
        pending = await ChatRecoveryService(directus_service).execute("has_pending_chat_outputs", {
            "protocol_version": 1, "hashed_user_id": user_id_hash,
            "target_chat_id": chat_id,
        })
        if pending.get("has_pending"):
            return
        await ChatRecoveryService(directus_service).execute("mark_child_canonical_acknowledged", {
            "protocol_version": 1, "hashed_user_id": user_id_hash,
            "child_chat_id": chat_id,
        })
        await cache.acknowledge_ai_context_persistence(user_id_hash, chat_id)
    finally:
        await cache.close()


async def _refresh_terminal_sync_cache(
    *,
    user_id: str,
    chat_id: Any,
    committed_messages_v: Any,
) -> None:
    if not isinstance(chat_id, str) or not chat_id:
        logger.warning("Recovery terminal cache refresh skipped: missing chat_id")
        return
    if not isinstance(committed_messages_v, int) or committed_messages_v < 1:
        logger.warning(
            "Recovery terminal cache refresh skipped for chat=%s: invalid committed_messages_v=%r",
            chat_id,
            committed_messages_v,
        )
        return

    cache_service = _create_cache_service()
    try:
        await cache_service.delete_sync_messages_history(user_id, chat_id)
        version_updated = await cache_service.set_chat_version_component(
            user_id,
            chat_id,
            "messages_v",
            committed_messages_v,
        )
        if not version_updated:
            logger.warning(
                "Recovery terminal cache version update returned false for user=%s chat=%s messages_v=%s",
                user_id[:8],
                chat_id,
                committed_messages_v,
            )
        logger.info(
            "Recovery terminal cache refreshed for user=%s chat=%s messages_v=%s",
            user_id[:8],
            chat_id,
            committed_messages_v,
        )
    finally:
        await cache_service.close()


async def invalidate_recovery_leases_for_device(
    *,
    directus_service: Any,
    user_id_hash: str,
    device_fingerprint_hash: str,
) -> dict[str, Any]:
    return await ChatRecoveryService(directus_service).execute(
        "invalidate_deletion",
        {
            "protocol_version": 1,
            "hashed_user_id": user_id_hash,
            "scope": "device",
            "device_hash": device_fingerprint_hash,
        },
    )


async def _require_chat_deletion_fence(
    directus_service: Any, chat_id: str, user_id_hash: str,
) -> dict[str, Any]:
    from backend.core.api.app.services.chat_deletion_fence import require_chat_deletion_fence

    return await require_chat_deletion_fence(
        directus_service, chat_id, hashed_user_id=user_id_hash,
    )


async def invalidate_recovery_jobs_for_chat_deletion(
    *,
    directus_service: Any,
    user_id_hash: str,
    chat_id: str,
) -> dict[str, Any]:
    return await _require_chat_deletion_fence(directus_service, chat_id, user_id_hash)


async def invalidate_recovery_jobs_for_account_deletion(
    *,
    directus_service: Any,
    user_id_hash: str,
) -> dict[str, Any]:
    return await ChatRecoveryService(directus_service).execute(
        "invalidate_deletion",
        {
            "protocol_version": 1,
            "hashed_user_id": user_id_hash,
            "scope": "account",
        },
    )


async def cleanup_expired_recovery_jobs(*, directus_service: Any) -> dict[str, Any]:
    service = ChatRecoveryService(directus_service)
    result = await service.execute(
        "cleanup_expired",
        {
            "protocol_version": 1,
            "failure_alerts_enabled": notification_environment()
            in {"development", "production"},
        },
    )
    raw_candidates = result.pop("failure_alert_candidates", [])
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    queued = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        preflight_id = candidate.get("preflight_id")
        inference_task_id = candidate.get("inference_task_id")
        chat_id = candidate.get("chat_id")
        user_message_id = candidate.get("user_message_id")
        failure_category = candidate.get("failure_category")
        metadata = {
            "claim_expired": ("dispatch", "timeout"),
            "dispatch_failed": ("dispatch", "processing_error"),
            "soft_time_limit": ("inference", "timeout"),
            "worker_timeout": ("inference", "timeout"),
        }.get(failure_category, ("inference", "processing_error"))
        if not all(isinstance(value, str) and value for value in (
            preflight_id, inference_task_id, chat_id, user_message_id,
        )) or metadata is None:
            continue
        stage, category = metadata
        if not await notify_chat_failure(
            f"{chat_id}:{user_message_id}",
            stage=stage,
            category=category,
        ):
            continue
        await service.execute(
            "acknowledge_failure_alert",
            {
                "protocol_version": 1,
                "preflight_id": preflight_id,
                "inference_task_id": inference_task_id,
                "failure_category": failure_category,
            },
        )
        queued += 1
    result["failure_alerts_queued"] = queued
    result["failure_alerts_pending"] = max(0, len(candidates) - queued)
    return result


async def reconcile_authorized_direct_completions(
    *,
    directus_service: Any,
    cache_service: Any | None = None,
) -> dict[str, Any]:
    """Advance one bounded, round-robin page of pending direct completions."""
    cache = cache_service or _create_cache_service()
    owns_cache = cache_service is None
    try:
        client = await cache.client
        if client is None:
            raise RuntimeError("Recovery reconciliation cursor cache is unavailable")
        raw_cursor = await client.get(_DIRECT_COMPLETION_CURSOR_KEY)
        if isinstance(raw_cursor, bytes):
            raw_cursor = raw_cursor.decode("utf-8")
        after_id = None
        if raw_cursor is not None:
            try:
                after_id = str(UUID(raw_cursor))
            except (TypeError, ValueError, AttributeError):
                # The cursor is only a scan hint. Corruption safely restarts at
                # the first indexed row without changing any intent authority.
                await client.delete(_DIRECT_COMPLETION_CURSOR_KEY)

        data: dict[str, Any] = {
            "protocol_version": 1,
            "limit": _DIRECT_COMPLETION_RECONCILE_LIMIT,
        }
        if after_id is not None:
            data["after_id"] = after_id
        result = await ChatRecoveryService(directus_service).execute(
            "reconcile_authorized_direct_completions",
            data,
        )
        for field in ("scanned", "completed", "pending", "blocked"):
            value = result.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RuntimeError("Direct completion reconciliation returned malformed counts")
        next_cursor = result.get("next_cursor")
        if next_cursor is not None:
            try:
                next_cursor = str(UUID(next_cursor))
            except (TypeError, ValueError, AttributeError) as exc:
                raise RuntimeError(
                    "Direct completion reconciliation returned a malformed cursor"
                ) from exc
            await client.set(_DIRECT_COMPLETION_CURSOR_KEY, next_cursor)
        else:
            # End of this indexed pass. The next maintenance tick wraps so rows
            # that became ready behind the cursor are revisited.
            await client.delete(_DIRECT_COMPLETION_CURSOR_KEY)
        return result
    finally:
        if owns_cache:
            await cache.close()


async def send_available_recovery_jobs(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    user_otel_attrs: dict | None = None,
) -> None:
    if not manager.is_connection_completion_capable(user_id, device_fingerprint_hash):
        return
    _otel_span, _otel_token = _start_ws_span(
        "send_available_recovery_jobs",
        user_id,
        None,
        user_otel_attrs,
    )
    try:
        result = await ChatRecoveryService(directus_service).execute(
            "list_available_jobs",
            {
                "protocol_version": 1,
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
            },
        )
        jobs = result.get("jobs")
        if jobs and manager.is_connection_completion_capable(user_id, device_fingerprint_hash):
            await manager.send_personal_message(
                {"type": "recovery_jobs_available", "payload": {"jobs": jobs}},
                user_id,
                device_fingerprint_hash,
            )
    except ChatRecoveryProtocolError as exc:
        if exc.status_code != 404:
            logger.warning(
                "Recovery job discovery failed for user=%s device=%s code=%s",
                user_id[:8],
                device_fingerprint_hash[:8],
                exc.code,
            )
    finally:
        _end_ws_span(_otel_span, _otel_token)


async def send_available_recovery_outputs(
    *, manager: Any, directus_service: Any, user_id: str,
    user_id_hash: str, device_fingerprint_hash: str,
) -> None:
    supports_typed = getattr(manager, "supports_typed_recovery_outputs", None)
    if not callable(supports_typed) or not supports_typed(user_id, device_fingerprint_hash):
        return
    recovery = ChatRecoveryService(directus_service)
    cursor: dict[str, str] | None = None
    try:
        while True:
            if not manager.is_connection_completion_capable(user_id, device_fingerprint_hash):
                return
            result = await recovery.execute("list_pending_outputs", {
                "protocol_version": 1, "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash, **(cursor or {}),
            })
            if not manager.is_connection_completion_capable(user_id, device_fingerprint_hash):
                return
            if result.get("outputs"):
                await manager.send_personal_message(
                    {"type": "recovery_outputs_available", "payload": {"outputs": result["outputs"]}},
                    user_id, device_fingerprint_hash,
                )
            next_cursor = result.get("next_cursor")
            if not next_cursor:
                break
            if next_cursor == cursor:
                raise RuntimeError("Recovery output discovery cursor did not advance")
            cursor = next_cursor
    except Exception:
        try:
            await manager.send_personal_message(
                {"type": "recovery_outputs_discovery_complete", "payload": {"status": "failed"}},
                user_id, device_fingerprint_hash,
            )
        except Exception:
            pass
        raise
    if not manager.is_connection_completion_capable(user_id, device_fingerprint_hash):
        return
    await manager.send_personal_message(
        {"type": "recovery_outputs_discovery_complete", "payload": {"status": "completed"}},
        user_id, device_fingerprint_hash,
    )


async def handle_recovery_output_get(
    *, manager: Any, directus_service: Any, s3_service: Any,
    user_id: str, user_id_hash: str, device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    request_id = _request_id(payload)
    if not await _require_typed_output_capability(
        manager, user_id, device_fingerprint_hash, request_id, payload.get("record_id")
    ):
        return
    try:
        result = await ChatRecoveryService(directus_service).get_sealed_output({
            "protocol_version": payload.get("protocol_version"),
            "record_id": payload.get("record_id"),
            "hashed_user_id": user_id_hash,
            "device_hash": device_fingerprint_hash,
        }, s3_service=s3_service)
        await manager.send_personal_message(
            {"type": "recovery_output_ready", "payload": {**result, "request_id": request_id}},
            user_id, device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(
            manager, user_id, device_fingerprint_hash, exc,
            payload.get("record_id"), request_id,
        )
    except Exception:
        logger.exception("Recovery output read failed for record=%s", payload.get("record_id"))
        await manager.send_personal_message({
            "type": "error", "payload": {
                "code": "recovery_output_unavailable", "message": "Encrypted recovery output is temporarily unavailable.",
                "job_id": payload.get("record_id"), "request_id": request_id,
            },
        }, user_id, device_fingerprint_hash)


async def handle_recovery_output_persist_message(
    *, manager: Any, directus_service: Any, user_id: str,
    user_id_hash: str, device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    request_id = _request_id(payload)
    if not await _require_typed_output_capability(
        manager, user_id, device_fingerprint_hash, request_id, payload.get("record_id")
    ):
        return
    try:
        message_field = "encrypted_user_message" if "encrypted_user_message" in payload else "encrypted_assistant_message"
        encrypted_message = dict(payload.get(message_field) or {})
        encrypted_message["hashed_user_id"] = user_id_hash
        result = await ChatRecoveryService(directus_service).execute("persist_output_message", {
            "protocol_version": payload.get("protocol_version"),
            "record_id": payload.get("record_id"),
            "hashed_user_id": user_id_hash,
            "device_hash": device_fingerprint_hash,
            "expected_messages_v": payload.get("expected_messages_v"),
            message_field: encrypted_message,
            **({"encrypted_chat_key": payload["encrypted_chat_key"]} if "encrypted_chat_key" in payload else {}),
            **({"encrypted_title": payload["encrypted_title"]} if "encrypted_title" in payload else {}),
        })
        if isinstance(result.get("committed_messages_v"), int):
            try:
                await _refresh_terminal_sync_cache(
                    user_id=user_id, chat_id=result["target_chat_id"],
                    committed_messages_v=result["committed_messages_v"],
                )
                await _acknowledge_output_cache_if_complete(
                    directus_service=directus_service, user_id_hash=user_id_hash,
                    chat_id=result["target_chat_id"],
                )
            except Exception:
                logger.exception("Canonical recovery cache acknowledgement failed")
        await manager.send_personal_message(
            {"type": "recovery_output_persisted", "payload": {**result, "request_id": request_id}},
            user_id, device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, exc, payload.get("record_id"), request_id)


async def handle_recovery_output_persist_summary(
    *, manager: Any, directus_service: Any, user_id: str,
    user_id_hash: str, device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    request_id = _request_id(payload)
    if not await _require_typed_output_capability(
        manager, user_id, device_fingerprint_hash, request_id, payload.get("record_id")
    ):
        return
    try:
        result = await ChatRecoveryService(directus_service).execute("persist_output_summary", {
            "protocol_version": payload.get("protocol_version"),
            "record_id": payload.get("record_id"),
            "hashed_user_id": user_id_hash,
            "device_hash": device_fingerprint_hash,
            "expected_metadata_v": payload.get("expected_metadata_v"),
            "encrypted_summary": payload.get("encrypted_summary"),
        })
        await _acknowledge_output_cache_if_complete(
            directus_service=directus_service, user_id_hash=user_id_hash,
            chat_id=result["target_chat_id"],
        )
        await manager.send_personal_message(
            {"type": "recovery_output_summary_persisted", "payload": {**result, "request_id": request_id}},
            user_id, device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, exc, payload.get("record_id"), request_id)


async def handle_recovery_output_ack_checkpoint(
    *, manager: Any, directus_service: Any, user_id: str,
    user_id_hash: str, device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    request_id = _request_id(payload)
    if not await _require_typed_output_capability(
        manager, user_id, device_fingerprint_hash, request_id, payload.get("record_id")
    ):
        return
    try:
        result = await ChatRecoveryService(directus_service).execute("acknowledge_output_checkpoint", {
            "protocol_version": payload.get("protocol_version"),
            "record_id": payload.get("record_id"),
            "hashed_user_id": user_id_hash,
            "device_hash": device_fingerprint_hash,
            "encrypted_summary": payload.get("encrypted_summary"),
            **({"compressed_up_to_message_id": payload["compressed_up_to_message_id"]}
               if payload.get("compressed_up_to_message_id") else {}),
            **({"covered_message_ids": payload["covered_message_ids"]}
               if "covered_message_ids" in payload else {}),
        })
        await _acknowledge_output_cache_if_complete(
            directus_service=directus_service, user_id_hash=user_id_hash,
            chat_id=result["target_chat_id"],
        )
        await manager.send_personal_message(
            {"type": "recovery_output_checkpoint_acknowledged", "payload": {**result, "request_id": request_id}},
            user_id, device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, exc, payload.get("record_id"), request_id)


async def handle_recovery_output_ack_embed(
    *, manager: Any, directus_service: Any, user_id: str,
    user_id_hash: str, device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    request_id = _request_id(payload)
    if not await _require_typed_output_capability(
        manager, user_id, device_fingerprint_hash, request_id, payload.get("record_id"),
        require_canonical_embed_receipts=True,
    ):
        return
    try:
        result = await ChatRecoveryService(directus_service).execute("acknowledge_output_embed", {
            "protocol_version": payload.get("protocol_version"),
            "record_id": payload.get("record_id"),
            "hashed_user_id": user_id_hash,
            "device_hash": device_fingerprint_hash,
            "canonical_digest": payload.get("canonical_digest"),
            "canonical_source": payload.get("canonical_source"),
        })
        await _acknowledge_output_cache_if_complete(
            directus_service=directus_service, user_id_hash=user_id_hash,
            chat_id=result["target_chat_id"],
        )
        await manager.send_personal_message(
            {"type": "recovery_output_embed_acknowledged", "payload": {**result, "request_id": request_id}},
            user_id, device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(manager, user_id, device_fingerprint_hash, exc, payload.get("record_id"), request_id)


async def _require_typed_output_capability(
    manager: Any,
    user_id: str,
    device_fingerprint_hash: str,
    request_id: str,
    record_id: Any,
    *,
    require_canonical_embed_receipts: bool = False,
) -> bool:
    supports_typed = getattr(manager, "negotiated_typed_recovery_outputs", None)
    supports_receipts = getattr(manager, "negotiated_canonical_embed_receipts", None)
    allowed = callable(supports_typed) and supports_typed(user_id, device_fingerprint_hash)
    if require_canonical_embed_receipts:
        allowed = allowed and callable(supports_receipts) and supports_receipts(
            user_id, device_fingerprint_hash
        )
    if allowed:
        return await _require_recovery_foreground(
            manager, user_id, device_fingerprint_hash, request_id, record_id,
        )
    await manager.send_personal_message(
        {"type": "error", "payload": {
            "code": "client_capability_required",
            "message": "This encrypted recovery operation requires an updated client.",
            "job_id": record_id,
            "request_id": request_id,
        }},
        user_id,
        device_fingerprint_hash,
    )
    return False


async def _require_recovery_foreground(
    manager: Any, user_id: str, device_fingerprint_hash: str,
    request_id: str | None, job_id: Any,
) -> bool:
    if manager.is_connection_completion_capable(user_id, device_fingerprint_hash):
        return True
    await manager.send_personal_message(
        {"type": "error", "payload": {
            "code": "recovery_requires_foreground",
            "message": "Encrypted recovery requires a foreground client.",
            "job_id": job_id,
            "request_id": request_id,
        }},
        user_id, device_fingerprint_hash,
    )
    return False


async def _send_protocol_error(
    manager: Any,
    user_id: str,
    device_hash: str,
    exc: ChatRecoveryProtocolError,
    job_id: str | None,
    request_id: str | None,
) -> None:
    await manager.send_personal_message(
        {
            "type": "error",
            "payload": {
                "code": exc.code,
                "message": "Encrypted completion recovery was rejected.",
                "job_id": job_id,
                "request_id": request_id,
            },
        },
        user_id,
        device_hash,
    )


async def handle_recovery_job_claim(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "recovery_job_claim",
        user_id,
        payload,
        user_otel_attrs,
    )
    request_id = _request_id(payload)
    try:
        if not await _require_recovery_foreground(
            manager, user_id, device_fingerprint_hash, request_id, payload.get("job_id")
        ):
            return
        result = await ChatRecoveryService(directus_service).execute(
            "lease_job",
            {
                "protocol_version": payload.get("protocol_version"),
                "job_id": payload.get("job_id"),
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
            },
        )
        await manager.send_personal_message(
            {
                "type": "recovery_job_claimed",
                "payload": {**result, "request_id": request_id},
            },
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(
            manager,
            user_id,
            device_fingerprint_hash,
            exc,
            payload.get("job_id"),
            request_id,
        )
    finally:
        _end_ws_span(_otel_span, _otel_token)


async def handle_recovery_job_renew(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "recovery_job_renew",
        user_id,
        payload,
        user_otel_attrs,
    )
    request_id = _request_id(payload)
    try:
        if not await _require_recovery_foreground(
            manager, user_id, device_fingerprint_hash, request_id, payload.get("job_id")
        ):
            return
        result = await ChatRecoveryService(directus_service).execute(
            "renew_lease",
            {
                "protocol_version": payload.get("protocol_version"),
                "job_id": payload.get("job_id"),
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
                "lease_generation": payload.get("lease_generation"),
                "lease_token": payload.get("lease_token"),
            },
        )
        await manager.send_personal_message(
            {
                "type": "recovery_job_renewed",
                "payload": {**result, "request_id": request_id},
            },
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(
            manager,
            user_id,
            device_fingerprint_hash,
            exc,
            payload.get("job_id"),
            request_id,
        )
    finally:
        _end_ws_span(_otel_span, _otel_token)


async def handle_recovery_job_persist(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = _start_ws_span(
        "recovery_job_persist",
        user_id,
        payload,
        user_otel_attrs,
    )
    request_id = _request_id(payload)
    try:
        if not await _require_recovery_foreground(
            manager, user_id, device_fingerprint_hash, request_id, payload.get("job_id")
        ):
            return
        encrypted_message = dict(payload.get("encrypted_assistant_message") or {})
        encrypted_message["hashed_user_id"] = user_id_hash
        result = await ChatRecoveryService(directus_service).execute(
            "persist_terminal",
            {
                "protocol_version": payload.get("protocol_version"),
                "job_id": payload.get("job_id"),
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
                "lease_generation": payload.get("lease_generation"),
                "lease_token": payload.get("lease_token"),
                "expected_messages_v": payload.get("expected_messages_v"),
                "encrypted_assistant_message": encrypted_message,
            },
        )
        try:
            expected_messages_v = payload.get("expected_messages_v")
            committed_messages_v = result.get("committed_messages_v")
            if not isinstance(committed_messages_v, int) and isinstance(expected_messages_v, int):
                committed_messages_v = expected_messages_v + 1
            await _refresh_terminal_sync_cache(
                user_id=user_id,
                chat_id=encrypted_message.get("chat_id"),
                committed_messages_v=committed_messages_v,
            )
            await _acknowledge_output_cache_if_complete(
                directus_service=directus_service, user_id_hash=user_id_hash,
                chat_id=encrypted_message["chat_id"],
            )
        except Exception:
            logger.exception(
                "Recovery terminal cache refresh failed after Directus commit for user=%s job=%s",
                user_id[:8],
                payload.get("job_id"),
            )
        await manager.send_personal_message(
            {
                "type": "recovery_job_persisted",
                "payload": {**result, "request_id": request_id},
            },
            user_id,
            device_fingerprint_hash,
        )
    except ChatRecoveryProtocolError as exc:
        await _send_protocol_error(
            manager,
            user_id,
            device_fingerprint_hash,
            exc,
            payload.get("job_id"),
            request_id,
        )
    finally:
        _end_ws_span(_otel_span, _otel_token)
