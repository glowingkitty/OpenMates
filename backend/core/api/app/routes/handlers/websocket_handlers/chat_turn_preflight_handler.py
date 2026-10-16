"""
WebSocket handler for durable encrypted chat-turn preflight.

The client provides both encrypted durable user content and the transient
inference request. Only a server-keyed commitment to plaintext crosses the
Directus persistence boundary, and inference remains blocked until this handler
returns a committed acknowledgement.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from typing import Any

from backend.core.api.app.services.chat_recovery_service import (
    ChatRecoveryProtocolError,
    ChatRecoveryService,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.core.api.app.services.direct_chat_access import is_direct_chat, require_direct_chat_access
from backend.core.api.app.services.team_chat_ai_service import (
    normalize_team_ai_inference_request,
    parse_team_message_transport,
)
from backend.core.api.app.services.chat_recovery_telemetry import (
    record_recovery_duration,
    start_recovery_timing,
)


logger = logging.getLogger(__name__)
COMMITMENT_VERSION = 1


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


def canonicalize_inference_request(inference_request: dict[str, Any]) -> bytes:
    if not isinstance(inference_request, dict) or not inference_request:
        raise ValueError("inference_request must be a non-empty object")
    # Live Project authority is revalidated at dispatch and every file job.
    # A new chat must be saved before its Project focus can be activated, so
    # these server-derived bindings intentionally change after preflight.
    committed_request = {
        key: None if key in {"current_project", "active_project_focus"} else value
        for key, value in inference_request.items()
    }
    return json.dumps(
        committed_request,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _commitment_key() -> bytes:
    commitment_key = os.getenv("CHAT_RECOVERY_COMMITMENT_KEY")
    if commitment_key:
        return commitment_key.encode("utf-8")

    # Existing deployments already require this secret for internal transactions.
    # Derive a purpose-bound key so an API restart cannot disable all saved-chat
    # sends when the optional recovery-specific variable has not been provisioned.
    internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if internal_token:
        return hmac.new(
            internal_token.encode("utf-8"),
            b"openmates:chat-recovery-commitment:v1",
            hashlib.sha256,
        ).digest()
    raise RuntimeError("CHAT_RECOVERY_COMMITMENT_KEY or INTERNAL_API_SHARED_TOKEN is required")


def build_inference_commitment(inference_request: dict[str, Any]) -> str:
    return hmac.new(
        _commitment_key(),
        canonicalize_inference_request(inference_request),
        hashlib.sha256,
    ).hexdigest()


def server_client_capabilities(manager: Any, user_id: str, device_fingerprint_hash: str) -> list[str]:
    capabilities: list[str] = []
    supports_task_update_jobs = getattr(manager, "supports_task_update_jobs", None)
    if callable(supports_task_update_jobs) and supports_task_update_jobs(user_id, device_fingerprint_hash):
        capabilities.append("task_update_jobs")
    supports_project_file_jobs = getattr(manager, "supports_project_file_jobs", None)
    if callable(supports_project_file_jobs) and supports_project_file_jobs(user_id, device_fingerprint_hash):
        capabilities.append("project_file_jobs")
    supports_remote_command_jobs = getattr(manager, "supports_remote_command_jobs", None)
    if callable(supports_remote_command_jobs) and supports_remote_command_jobs(user_id, device_fingerprint_hash):
        capabilities.append("remote_command_jobs")
    return capabilities


async def enqueue_chat_turn(
    *,
    directus_service: Any,
    user_id_hash: str,
    device_fingerprint_hash: str,
    preflight_id: str,
    inference_request: dict[str, Any],
    include_first_personal_projection: bool = False,
    expected_wrapped_chat_key: str | None = None,
) -> dict[str, Any]:
    namespace = uuid.UUID(preflight_id)
    started_at = start_recovery_timing()
    try:
        return await ChatRecoveryService(directus_service).execute(
            "enqueue_inference",
            {
                "protocol_version": 1,
                "preflight_id": preflight_id,
                "hashed_user_id": user_id_hash,
                "device_hash": device_fingerprint_hash,
                "inference_commitment": build_inference_commitment(inference_request),
                "inference_task_id": str(uuid.uuid5(namespace, "inference-task")),
                "billing_identity": str(uuid.uuid5(namespace, "billing-identity")),
                "outbox_id": str(uuid.uuid5(namespace, "inference-outbox")),
                **({"include_first_personal_projection": True,
                    "expected_wrapped_chat_key": expected_wrapped_chat_key}
                   if include_first_personal_projection else {}),
            },
        )
    finally:
        record_recovery_duration("enqueue_inference", started_at)


async def handle_chat_turn_preflight(
    *,
    websocket: Any | None = None,
    manager: Any,
    directus_service: Any,
    user_id: str,
    user_id_hash: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    stable_device_fingerprint_hash: str | None = None,
    user_otel_attrs: dict | None = None,
    atomic_before_ack: Any | None = None,
    allow_atomic_first_personal: bool = False,
    server_queued_after_task_id: str | None = None,
) -> dict[str, Any] | None:
    async def send_response(message: dict[str, Any]) -> None:
        if websocket is not None:
            await websocket.send_json(message)
            return
        await manager.send_personal_message(
            message,
            user_id,
            device_fingerprint_hash,
        )

    _otel_span, _otel_token = _start_ws_span(
        "chat_turn_preflight",
        user_id,
        payload,
        user_otel_attrs,
    )
    try:
        turn_id = str(payload.get("turn_id", ""))
        inference_request_payload = payload.get("inference_request")
        debug_enabled = (
            isinstance(inference_request_payload, dict)
            and isinstance(inference_request_payload.get("test_mock_marker"), str)
        )

        async def send_debug_phase(phase: str) -> None:
            if not debug_enabled:
                return
            await send_response(
                {
                    "type": "chat_turn_preflight_debug",
                    "payload": {"turn_id": turn_id, "phase": phase},
                }
            )

        await send_debug_phase("received")
        # The one-frame first Personal path lets the transaction read and lock
        # epoch, owner, chat and preflight together. Every other shape retains
        # the established cutover/prepare sequence.
        message = inference_request_payload.get("message") if isinstance(inference_request_payload, dict) else None
        atomic_first_personal = (
            allow_atomic_first_personal
            and payload.get("team_id") is None
            and type(payload.get("expected_messages_v")) is int
            and payload["expected_messages_v"] == 0
            and isinstance(payload.get("encrypted_chat_metadata"), dict)
            and isinstance(payload.get("encrypted_chat_key"), str)
            and isinstance(inference_request_payload, dict)
            and inference_request_payload.get("encrypted_chat_key") == payload["encrypted_chat_key"]
            and isinstance(message, dict) and message.get("role") == "user"
            and message.get("chat_id") in (None, payload.get("chat_id"))
            and (inference_request_payload.get("client_context_pending") is None
                 or type(inference_request_payload["client_context_pending"]) is bool)
            and not inference_request_payload.get("is_incognito")
            and not any(payload.get(key) or inference_request_payload.get(key)
                        for key in ("embeds", "encrypted_embeds", "attachments", "is_fork",
                                    "message_history", "current_project", "active_project_focus",
                                    "active_focus_id", "project_focus_candidates", "project_focus_catalog",
                                    "project_focus_documents", "queue_mode", "queue_revision",
                                    "queued_message_id", "accepted_plan_context"))
            and not any(message.get(key) for key in ("embeds", "encrypted_embeds", "attachments",
                                                       "message_history", "queue_mode", "queue_revision"))
        )
        if atomic_first_personal:
            atomic_request = dict(inference_request_payload)
            atomic_request["client_capabilities"] = server_client_capabilities(
                manager, user_id, device_fingerprint_hash,
            )
            atomic_request["current_project"] = None
            atomic_request["active_project_focus"] = None
            encrypted_message = dict(payload["encrypted_user_message"])
            encrypted_message["hashed_user_id"] = user_id_hash
            atomic_data = {
                "protocol_version": payload["protocol_version"],
                "hashed_user_id": user_id_hash,
                "chat_id": payload["chat_id"], "turn_id": payload["turn_id"],
                "user_message_id": payload["message_id"],
                "device_hash": device_fingerprint_hash,
                "chat_key_version": payload["chat_key_version"],
                "wrapped_chat_key": payload["encrypted_chat_key"],
                "recovery_public_key": payload["recovery_public_key"],
                "inference_commitment": build_inference_commitment(atomic_request),
                "commitment_version": COMMITMENT_VERSION,
                "expected_messages_v": payload["expected_messages_v"],
                "encrypted_user_message": encrypted_message,
                "encrypted_chat_metadata": payload["encrypted_chat_metadata"],
            }
            started_at = start_recovery_timing()
            try:
                try:
                    result = await ChatRecoveryService(directus_service).execute(
                        "admit_first_personal", atomic_data,
                    )
                except ChatRecoveryProtocolError as exc:
                    if exc.code != "unsupported_operation":
                        raise
                    # Rolling API/CMS updates retain the established path.
                    result = {"atomic_fallback": True}
            finally:
                record_recovery_duration("durable_preflight", started_at)
            if not result.get("atomic_fallback"):
                # The outbox is HELD until dispatch. Bind deferred context only
                # after durable admission but before ACK permits context frames.
                if atomic_before_ack is not None:
                    result["client_context_binding_ref"] = await atomic_before_ack(result)
                result["turn_id"] = payload["turn_id"]
                public_result = {key: value for key, value in result.items()
                                 if key not in ("admission_chat_projection", "admission_protocol_epoch",
                                                "admission_sends_paused", "client_context_binding_ref")}
                await send_debug_phase("prepare_completed")
                await send_response({"type": "chat_turn_preflight_ack", "payload": public_result})
                logger.info("Chat preflight phase=ack_sent turn=%s", turn_id[:8])
                return result
        logger.info("Chat preflight phase=cutover_started turn=%s", turn_id[:8])
        recovery_service = ChatRecoveryService(directus_service)
        cutover_state = await recovery_service.execute(
            "get_cutover_state",
            {"protocol_version": 1},
        )
        logger.info(
            "Chat preflight phase=cutover_completed turn=%s epoch=%s",
            turn_id[:8],
            cutover_state.get("protocol_epoch"),
        )
        await send_debug_phase("cutover_completed")
        inference_request_payload = payload.get("inference_request")
        team_id = payload.get("team_id")
        is_team_turn = isinstance(team_id, str) and bool(team_id)
        # An ordinary first Personal frame carries version zero and encrypted
        # metadata. Atomic prepare locks the chat, owner and deletion fence and
        # rejects Direct metadata; the preceding admin GET duplicates that work.
        first_personal_metadata_candidate = (
            team_id is None
            and type(payload.get("expected_messages_v")) is int
            and payload["expected_messages_v"] == 0
            and isinstance(payload.get("encrypted_chat_metadata"), dict)
            and isinstance(inference_request_payload, dict)
            and isinstance(inference_request_payload.get("message"), dict)
            and inference_request_payload["message"].get("role") == "user"
        )
        existing_chat = (
            None if first_personal_metadata_candidate
            else await directus_service.chat.get_chat_metadata(
                str(payload["chat_id"]), admin_required=True,
            )
        )
        direct_turn = is_direct_chat(existing_chat)
        if direct_turn:
            try:
                await require_direct_chat_access(directus_service, existing_chat, user_id, team_id)
            except (PermissionError, ValueError):
                raise ChatRecoveryProtocolError(403, "direct_chat_permission_denied") from None
            if not is_team_turn:
                raise ChatRecoveryProtocolError(403, "direct_chat_permission_denied")
        ordinary_team_turn = (
            is_team_turn
            and isinstance(inference_request_payload, dict)
            and inference_request_payload.get("team_ai_invocation") is None
        )
        if is_team_turn:
            if ordinary_team_turn and cutover_state.get("sends_paused"):
                raise ChatRecoveryProtocolError(503, "inference_temporarily_paused")
            message = (
                inference_request_payload.get("message")
                if isinstance(inference_request_payload, dict) else None
            )
            if not isinstance(message, dict):
                raise ChatRecoveryProtocolError(400, "invalid_team_message_transport")
            if (
                inference_request_payload.get("team_id") != team_id
                or inference_request_payload.get("chat_id") != payload.get("chat_id")
            ):
                raise ChatRecoveryProtocolError(409, "team_chat_scope_mismatch")
            try:
                parse_team_message_transport(inference_request_payload, message)
            except ValueError:
                raise ChatRecoveryProtocolError(400, "invalid_team_message_transport") from None
            encrypted_message = payload.get("encrypted_user_message")
            if (
                not isinstance(encrypted_message, dict)
                or message.get("message_id") != payload.get("message_id")
                or encrypted_message.get("client_message_id") != payload.get("message_id")
                or encrypted_message.get("chat_id") != payload.get("chat_id")
                or message.get("encrypted_content") != encrypted_message.get("encrypted_content")
            ):
                raise ChatRecoveryProtocolError(409, "message_identity_mismatch")
        legacy_dispatch = cutover_state.get("protocol_epoch") == 0 and not ordinary_team_turn
        # A first saved-chat send carries the encrypted chat metadata and user
        # ciphertext in this frame. Commit both before acknowledging it: the
        # legacy inference admission requires an existing owner-scoped chat.
        # Existing chats without initial metadata retain the epoch-zero path.
        if legacy_dispatch and payload.get("encrypted_chat_metadata") is None:
            legacy_preflight_id = str(
                uuid.uuid5(uuid.UUID(payload["turn_id"]), "legacy-preflight")
            )
            acknowledgement = {
                    "type": "chat_turn_preflight_ack",
                    "payload": {
                        "preflight_id": legacy_preflight_id,
                        "state": "LEGACY",
                        "turn_id": payload["turn_id"],
                    },
                }
            result = acknowledgement["payload"]
            if atomic_before_ack is not None:
                result["client_context_binding_ref"] = await atomic_before_ack(result)
            acknowledgement["payload"] = {key: value for key, value in result.items()
                                          if key != "client_context_binding_ref"}
            await send_response(acknowledgement)
            return result
        encrypted_user_message = dict(payload["encrypted_user_message"])
        encrypted_user_message["hashed_user_id"] = user_id_hash
        inference_request = dict(payload["inference_request"])
        hashed_team_id = None
        if isinstance(team_id, str) and team_id:
            try:
                allowed_roles = {"owner", "admin", "member"}
                if direct_turn and ordinary_team_turn:
                    allowed_roles.add("viewer")
                await directus_service.team.require_team_role(team_id, user_id, allowed_roles)
            except TeamPermissionError:
                raise ChatRecoveryProtocolError(403, "team_permission_denied") from None
            hashed_team_id = hash_id(team_id)
        # Ordinary Team turns only commit and relay ciphertext. Live inference
        # metadata is irrelevant to them and can drift after a lost ACK,
        # changing the commitment for an otherwise identical retry.
        if not ordinary_team_turn:
            inference_request["client_capabilities"] = server_client_capabilities(
                manager,
                user_id,
                device_fingerprint_hash,
            )
        cache_service = getattr(getattr(websocket, "app", None), "state", None)
        cache_service = getattr(cache_service, "cache_service", None)
        if cache_service is not None and not ordinary_team_turn:
            # Keep the commitment's field shape stable. Canonicalization replaces
            # both values with null; live focus is checked at dispatch instead.
            inference_request["active_project_focus"] = None
            inference_request["current_project"] = None
        if hashed_team_id and not ordinary_team_turn:
            try:
                inference_request = normalize_team_ai_inference_request(inference_request)
            except ValueError:
                raise ChatRecoveryProtocolError(400, "invalid_team_ai_inference_request") from None
        # The WebSocket routing hash includes the tab session ID. Ordinary Team
        # commits have no recovery job, so bind their idempotent preflight to
        # the authenticated device hash across reconnects and page reloads.
        preflight_device_hash = (
            stable_device_fingerprint_hash
            if ordinary_team_turn and isinstance(stable_device_fingerprint_hash, str)
            and stable_device_fingerprint_hash
            else device_fingerprint_hash
        )
        transaction_data = {
            "protocol_version": payload["protocol_version"],
            "hashed_user_id": user_id_hash,
            "chat_id": payload["chat_id"],
            "turn_id": payload["turn_id"],
            "user_message_id": payload["message_id"],
            "device_hash": preflight_device_hash,
            "chat_key_version": payload["chat_key_version"],
            "wrapped_chat_key": payload["encrypted_chat_key"],
            "recovery_public_key": payload["recovery_public_key"],
            "inference_commitment": build_inference_commitment(inference_request),
            "commitment_version": COMMITMENT_VERSION,
            "expected_messages_v": payload["expected_messages_v"],
            "encrypted_user_message": encrypted_user_message,
        }
        if hashed_team_id:
            transaction_data["hashed_team_id"] = hashed_team_id
        elif server_queued_after_task_id:
            transaction_data["queued_after_task_id"] = server_queued_after_task_id
        if payload.get("encrypted_chat_metadata") is not None:
            transaction_data["encrypted_chat_metadata"] = payload["encrypted_chat_metadata"]
        started_at = start_recovery_timing()
        try:
            logger.info("Chat preflight phase=prepare_started turn=%s", turn_id[:8])
            result = await recovery_service.execute(
                "prepare_preflight",
                transaction_data,
            )
            logger.info("Chat preflight phase=prepare_completed turn=%s", turn_id[:8])
            await send_debug_phase("prepare_completed")
        finally:
            record_recovery_duration("durable_preflight", started_at)
        if hashed_team_id and cache_service is not None:
            try:
                from backend.core.api.app.services.team_chat_notification_service import queue_committed_team_message

                encryption_service = getattr(websocket.app.state, "encryption_service", None)
                if encryption_service is not None:
                    await queue_committed_team_message(
                        directus=directus_service,
                        cache=cache_service,
                        encryption=encryption_service,
                        team_id=team_id,
                        chat_id=str(payload["chat_id"]),
                        message_id=str(payload["message_id"]),
                        sender_id=user_id,
                    )
            except Exception:
                # Notification delivery must never invalidate a durable message commit.
                logger.exception("Team chat notification fanout failed after committed preflight")
        if legacy_dispatch:
            # The durable first turn is committed, but inference still follows
            # the epoch-zero legacy task/billing path. No recovery outbox is
            # enqueued for this preflight.
            result["state"] = "LEGACY"
        # Saved and fallback admissions accept deferred context as soon as the
        # client sees the ACK, just like atomic first-Personal admission. Bind
        # after the durable commit and before publishing that permission.
        if atomic_before_ack is not None:
            result["client_context_binding_ref"] = await atomic_before_ack(result)
        result["turn_id"] = payload["turn_id"]
        public_result = {key: value for key, value in result.items()
                         if key not in ("admission_chat_projection", "admission_protocol_epoch",
                                        "admission_sends_paused", "client_context_binding_ref")}
        await send_response({"type": "chat_turn_preflight_ack", "payload": public_result})
        logger.info("Chat preflight phase=ack_sent turn=%s", turn_id[:8])
        return result
    except ChatRecoveryProtocolError as exc:
        await send_response(
            {
                "type": "error",
                "payload": {
                    "code": exc.code,
                    "message": "Encrypted chat preflight was rejected.",
                    "turn_id": payload.get("turn_id"),
                },
            }
        )
    except Exception:
        # WebSocket boundary: fail closed and keep ciphertext/plaintext out of logs.
        logger.exception(
            "Encrypted chat preflight failed for user=%s device=%s",
            user_id[:8],
            device_fingerprint_hash[:8],
        )
        await send_response(
            {
                "type": "error",
                "payload": {
                    "code": "durable_preflight_failed",
                    "message": "Encrypted chat preflight is temporarily unavailable.",
                    "turn_id": payload.get("turn_id"),
                },
            }
        )
    finally:
        _end_ws_span(_otel_span, _otel_token)
