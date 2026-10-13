"""Commit an encrypted user turn and dispatch its inference from one WS frame.

The same durable transaction, commitment, replay and dispatch gates used by the
two-frame protocol remain authoritative. An ACK is still emitted for recovery,
but processing does not wait for the client to receive it and send another frame.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import (
    handle_chat_turn_preflight,
)
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError

logger = logging.getLogger(__name__)
_warm_tasks: set[asyncio.Task] = set()


@dataclass
class ContextAdmissionLane:
    """One same-socket continuation; only its exact context frames may pass it."""

    chat_id: str
    turn_id: str
    message_id: str
    request_id: str
    team_id: str | None
    task: asyncio.Task[None]

    def __post_init__(self) -> None:
        self.task.add_done_callback(self._capture_completion)

    @staticmethod
    def _capture_completion(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        failure = task.exception()
        if failure is not None:
            logger.error("Admitted chat continuation failed: %s", type(failure).__name__)

    def accepts(self, data: Any) -> bool:
        if not isinstance(data, dict) or data.get("type") not in {
            "chat_turn_context_ready", "chat_turn_context_failed",
        }:
            return False
        payload = data.get("payload")
        return isinstance(payload, dict) and all(
            payload.get(key) == value for key, value in (
                ("chat_id", self.chat_id), ("turn_id", self.turn_id),
                ("message_id", self.message_id), ("request_id", self.request_id),
                ("team_id", self.team_id),
            )
        )

    async def receive_next(self, receive: Callable[[], Awaitable[Any]]) -> tuple[Any, bool]:
        """Buffer one unrelated frame locally until admission finishes."""
        data = await receive()
        if self.task.done() or not self.accepts(data):
            await self.task
            return data, False
        return data, True

    async def close(self) -> None:
        if not self.task.done():
            self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        except Exception:
            # The completion callback already captured and logged the failure.
            pass


async def handle_chat_turn_admit(
    *, websocket: Any, manager: Any, cache_service: Any,
    directus_service: Any, encryption_service: Any,
    user_id: str, user_id_hash: str, device_fingerprint_hash: str,
    payload: dict[str, Any], stable_device_fingerprint_hash: str | None = None,
    user_otel_attrs: dict | None = None, is_allowlisted_test_account: bool = False,
    schedule_context_dispatch: Callable[[ContextAdmissionLane], None] | None = None,
) -> None:
    request = payload.get("inference_request")
    message = request.get("message") if isinstance(request, dict) else None
    try:
        if payload.get("protocol_version") != 1 or not isinstance(message, dict):
            raise ValueError("Invalid admission envelope")
        for field in ("chat_id", "turn_id"):
            UUID(str(payload[field]))
        # Client message IDs include the chat suffix before their UUID. The
        # durable preflight accepts a bounded string and binds it exactly below.
        message_id = payload["message_id"]
        if not isinstance(message_id, str) or not 1 <= len(message_id) <= 255:
            raise ValueError("Invalid message identity")
        if (
            request.get("chat_id") != payload["chat_id"]
            or request.get("turn_id") != payload["turn_id"]
            or message.get("message_id") != payload["message_id"]
            or request.get("team_id") != payload.get("team_id")
            or request.get("is_incognito") is True
            or "admission_context" in request
            or "client_context_binding_ref" in request
            or "client_context_turn_id" in request
            or "first_personal_admission" in request
            or "include_first_personal_projection" in request
            or "expected_wrapped_chat_key" in request
        ):
            raise ValueError("Admission scope mismatch")
        if request.get("client_context_pending") is True:
            UUID(str(request["client_context_request_id"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        await websocket.send_json({"type": "error", "payload": {
            "code": "invalid_chat_turn_admission", "turn_id": payload.get("turn_id"),
            "message": "The encrypted chat turn did not match its request.",
        }})
        return

    async def bind_atomic_context_before_ack(_admission: dict[str, Any]) -> str:
        from backend.core.api.app.services.client_context_continuation import register_client_context

        try:
            return await register_client_context(
                cache_service=cache_service, encryption_service=encryption_service,
                user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
                chat_id=payload["chat_id"], turn_id=payload["turn_id"],
                message_id=payload["message_id"],
                request_id=request["client_context_request_id"],
                team_id=payload.get("team_id"),
            )
        except Exception:
            logger.warning("Admitted context binding unavailable", exc_info=True)
            raise ChatRecoveryProtocolError(503, "durable_preflight_failed") from None

    queued_after_task_id = None
    if (payload.get("team_id") is None and type(payload.get("expected_messages_v")) is int
            and payload["expected_messages_v"] > 0):
        try:
            queued_after_task_id = await cache_service.get_active_ai_task(payload["chat_id"])
            if queued_after_task_id:
                try:
                    queued_after_task_id = str(UUID(str(queued_after_task_id)))
                except (TypeError, ValueError, AttributeError):
                    queued_after_task_id = None
        except Exception:
            # A cache hint never grants durable routing authority.
            logger.warning("Active-task hint unavailable for durable queue proof", exc_info=True)

    acknowledgement = await handle_chat_turn_preflight(
        websocket=websocket, manager=manager, directus_service=directus_service,
        user_id=user_id, user_id_hash=user_id_hash,
        device_fingerprint_hash=device_fingerprint_hash,
        stable_device_fingerprint_hash=stable_device_fingerprint_hash,
        payload=payload, user_otel_attrs=user_otel_attrs,
        atomic_before_ack=(bind_atomic_context_before_ack
                           if request.get("client_context_pending") is True else None),
        allow_atomic_first_personal=True,
        server_queued_after_task_id=queued_after_task_id,
    )
    if not acknowledgement or not acknowledgement.get("preflight_id"):
        return

    binding_ref = acknowledgement.get("client_context_binding_ref")
    if request.get("client_context_pending") is True and binding_ref is None:
        from backend.core.api.app.services.client_context_continuation import register_client_context

        try:
            binding_ref = await register_client_context(
                cache_service=cache_service, encryption_service=encryption_service,
                user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
                chat_id=payload["chat_id"], turn_id=payload["turn_id"],
                message_id=payload["message_id"],
                request_id=request["client_context_request_id"], team_id=payload.get("team_id"),
            )
        except Exception:
            logger.warning("Admitted context binding unavailable", exc_info=True)
            await websocket.send_json({"type": "error", "payload": {
                "code": "client_context_unavailable", "turn_id": payload["turn_id"],
                "message": "Chat context preparation is temporarily unavailable.",
            }})
            return

    # Epoch zero deliberately uses the existing legacy dispatch path. Epoch one
    # rechecks the commitment and uses its stable task/billing/outbox identities.
    dispatch = dict(request)
    first_personal_admission = None
    if acknowledgement.get("state") != "LEGACY":
        dispatch.update(protocol_version=1, preflight_id=acknowledgement["preflight_id"])
        # The transaction supplies authority; this server-only hint selects
        # the narrow first Personal path after atomic preflight has committed.
        if (
            payload.get("team_id") is None
            and type(payload.get("expected_messages_v")) is int
            and payload["expected_messages_v"] == 0
            and isinstance(payload.get("encrypted_chat_metadata"), dict)
            and acknowledgement.get("state") in ("PREPARED", "ENQUEUED")
            and acknowledgement.get("committed_messages_v") == 1
        ):
            # The preflight has committed but inference has not been enqueued.
            # Reject mismatched client wrappers before the locked enqueue call.
            if (not isinstance(payload.get("encrypted_chat_key"), str)
                or not payload["encrypted_chat_key"]
                or request.get("encrypted_chat_key") != payload["encrypted_chat_key"]):
                await websocket.send_json({"type": "error", "payload": {
                    "code": "invalid_chat_turn_admission", "turn_id": payload["turn_id"],
                    "message": "The encrypted chat turn did not match its request.",
                }})
                return
            first_personal_admission = {
                "chat_id": payload["chat_id"], "turn_id": payload["turn_id"],
                "message_id": payload["message_id"],
                "preflight_id": acknowledgement["preflight_id"],
                "wrapped_chat_key": payload["encrypted_chat_key"],
                **({"enqueue_result": acknowledgement}
                   if acknowledgement.get("state") == "ENQUEUED" else {}),
            }
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        handle_message_received,
    )

    async def continue_dispatch() -> None:
        await handle_message_received(
            websocket=websocket, manager=manager, cache_service=cache_service,
            directus_service=directus_service, encryption_service=encryption_service,
            user_id=user_id, device_fingerprint_hash=device_fingerprint_hash,
            payload=dispatch, user_otel_attrs=user_otel_attrs,
            is_allowlisted_test_account=is_allowlisted_test_account,
            client_context_binding_ref=binding_ref,
            client_context_turn_id=payload["turn_id"] if binding_ref else None,
            first_personal_admission=first_personal_admission,
        )
        # Metadata refresh is best-effort and never precedes dispatch. Keep a
        # bounded strong reference while fresh-scoped renewal completes.
        if len(_warm_tasks) < 32:
            from backend.core.api.app.routes.handlers.websocket_handlers.workflow_metadata_warmup_handler import (
                warm_encrypted_discovery_indices,
            )

            task = asyncio.create_task(warm_encrypted_discovery_indices(
                cache_service=cache_service, directus_service=directus_service,
                user_id=user_id, team_id=payload.get("team_id"),
            ))
            _warm_tasks.add(task)
            task.add_done_callback(_warm_tasks.discard)

    if binding_ref and schedule_context_dispatch is not None:
        task = asyncio.create_task(continue_dispatch())
        lane = ContextAdmissionLane(
            chat_id=payload["chat_id"], turn_id=payload["turn_id"],
            message_id=payload["message_id"],
            request_id=request["client_context_request_id"],
            team_id=payload.get("team_id"), task=task,
        )
        try:
            schedule_context_dispatch(lane)
        except BaseException:
            await lane.close()
            raise
        return
    await continue_dispatch()
