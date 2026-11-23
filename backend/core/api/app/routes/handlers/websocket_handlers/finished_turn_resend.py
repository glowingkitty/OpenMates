"""Quiet acknowledgement of a client resend of an already finished chat turn.

A client may resend a turn (same chat_id + message_id) long after the turn was
answered, for example after a lost acknowledgement. Such a resend is never
processed again and never produces an `error` frame: the server confirms it,
tells the client the turn is over and writes one WARNING log line.
"""

import logging
from typing import Any

from fastapi import WebSocket

from backend.core.api.app.services.chat_recovery_service import (
    ChatRecoveryProtocolError,
    ChatRecoveryService,
)
from backend.core.api.app.services.directus.team_methods import hash_id

logger = logging.getLogger(__name__)

FINISHED_TURN_RESEND_LOG = "Resend of a finished turn acknowledged without processing"


async def send_origin_chat_message_confirmed(
    websocket: WebSocket,
    manager: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    """Acknowledge the sender on the same socket before any registry broadcast can race."""
    message = {"type": "chat_message_confirmed", "payload": payload}
    send_json = getattr(websocket, "send_json", None)
    if callable(send_json):
        try:
            await send_json(message)
            logger.debug(
                "Sent direct chat_message_confirmed for message %s to user %s/%s",
                payload.get("message_id"),
                user_id,
                device_fingerprint_hash,
            )
            return
        except Exception as exc:
            logger.warning(
                "Direct chat_message_confirmed send failed for message %s; falling back to manager: %s",
                payload.get("message_id"),
                exc,
            )

    await manager.send_personal_message(message, user_id, device_fingerprint_hash)


async def find_finished_turn(
    directus_service: Any,
    *,
    user_id: str,
    chat_id: str,
    message_id: Any,
) -> dict[str, Any] | None:
    """Return the finished-turn record for this user message, or None."""
    if not isinstance(chat_id, str) or not isinstance(message_id, str):
        return None
    try:
        result = await ChatRecoveryService(directus_service).execute(
            "get_finished_turn",
            {
                "protocol_version": 1,
                "hashed_user_id": hash_id(user_id),
                "chat_id": chat_id,
                "user_message_id": message_id,
            },
        )
    except ChatRecoveryProtocolError as exc:
        # Not a silent fallback: the caller keeps its original behavior, which
        # never reprocesses the turn, and the failed lookup is logged here.
        logger.warning(
            "Finished-turn lookup failed chat_id=%s message_id=%s code=%s",
            chat_id,
            message_id,
            exc.code,
        )
        return None
    if isinstance(result, dict) and result.get("finished") is True:
        return result
    return None


def log_finished_turn_resend(
    *,
    chat_id: Any,
    message_id: Any,
    finished: dict[str, Any],
    path: str,
) -> None:
    logger.warning(
        "%s chat_id=%s message_id=%s turn_state=%s path=%s",
        FINISHED_TURN_RESEND_LOG,
        chat_id,
        message_id,
        finished.get("state"),
        path,
    )


async def acknowledge_finished_turn_resend(
    *,
    websocket: WebSocket,
    manager: Any,
    user_id: str,
    device_fingerprint_hash: str,
    chat_id: str,
    message_id: str,
    temp_id: Any,
    finished: dict[str, Any],
    path: str,
) -> None:
    """Log once, confirm the message and end the (already finished) typing state."""
    log_finished_turn_resend(
        chat_id=chat_id, message_id=message_id, finished=finished, path=path
    )
    await send_finished_turn_frames(
        websocket=websocket,
        manager=manager,
        user_id=user_id,
        device_fingerprint_hash=device_fingerprint_hash,
        chat_id=chat_id,
        message_id=message_id,
        temp_id=temp_id,
        finished=finished,
    )


async def send_finished_turn_frames(
    *,
    websocket: Any,
    manager: Any,
    user_id: str,
    device_fingerprint_hash: str,
    chat_id: str,
    message_id: str,
    temp_id: Any,
    finished: dict[str, Any],
) -> None:
    """Send chat_message_confirmed and ai_typing_ended without logging."""
    assistant_message_id = finished.get("assistant_message_id")
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "temp_id": temp_id,
        "turn_already_completed": True,
        "turn_id": finished.get("turn_id"),
    }
    # The id comes only from the 24h job tombstone and can be absent.
    if assistant_message_id is not None:
        payload["assistant_message_id"] = assistant_message_id
    committed = finished.get("committed_messages_v")
    if isinstance(committed, int) and not isinstance(committed, bool):
        payload["new_messages_v"] = committed
    await send_origin_chat_message_confirmed(
        websocket,
        manager,
        user_id,
        device_fingerprint_hash,
        payload,
    )
    typing_ended = {"chat_id": chat_id, "user_message_id": message_id}
    if assistant_message_id is not None:
        typing_ended["message_id"] = assistant_message_id
    await manager.send_personal_message(
        {"type": "ai_typing_ended", "payload": typing_ended},
        user_id,
        device_fingerprint_hash,
    )


FINISHED_PREFLIGHT_STATES = ("TERMINAL", "CONSUMED")
REJECTED_ENQUEUE_CODES = ("preflight_not_found", "preflight_mismatch")


async def acknowledge_if_finished(
    directus_service: Any,
    *,
    websocket: WebSocket,
    manager: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    path: str,
) -> bool:
    """Look up the turn of a received message; acknowledge it quietly when finished."""
    message = payload.get("message")
    message = message if isinstance(message, dict) else {}
    chat_id, message_id = payload.get("chat_id"), message.get("message_id")
    finished = await find_finished_turn(
        directus_service,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
    )
    if finished is None:
        return False
    await acknowledge_finished_turn_resend(
        websocket=websocket,
        manager=manager,
        user_id=user_id,
        device_fingerprint_hash=device_fingerprint_hash,
        chat_id=chat_id,
        message_id=message_id,
        temp_id=message.get("temp_id"),
        finished=finished,
        path=path,
    )
    return True


async def acknowledge_finished_enqueue(
    directus_service: Any,
    *,
    websocket: WebSocket,
    manager: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    enqueue_result: dict[str, Any],
) -> bool:
    """Acknowledge an enqueue that the transaction reported as already finished.

    The enqueue result itself proves the turn is TERMINAL or CONSUMED, so the
    resend is acknowledged even when the follow-up lookup (which only adds the
    assistant id) finds nothing; it must never continue into processing.
    """
    if enqueue_result.get("state") not in FINISHED_PREFLIGHT_STATES:
        return False
    message = payload.get("message")
    message = message if isinstance(message, dict) else {}
    chat_id, message_id = payload.get("chat_id"), message.get("message_id")
    finished = await find_finished_turn(
        directus_service,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
    ) or {
        "finished": True,
        "state": enqueue_result.get("state"),
        "preflight_id": enqueue_result.get("preflight_id"),
        "turn_id": enqueue_result.get("turn_id"),
        "committed_messages_v": enqueue_result.get("committed_messages_v"),
    }
    await acknowledge_finished_turn_resend(
        websocket=websocket,
        manager=manager,
        user_id=user_id,
        device_fingerprint_hash=device_fingerprint_hash,
        chat_id=chat_id,
        message_id=message_id,
        temp_id=message.get("temp_id"),
        finished=finished,
        path="enqueue_finished",
    )
    return True
