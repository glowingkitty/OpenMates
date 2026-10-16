"""First-party, authenticated-session recovery of committed voice artifacts.

Recovery/ACK does no paid inference or write replay. Reads are bounded to the
original owner session and personal chat; ACK requires the durable encrypted row.
"""
from __future__ import annotations

import time
import hashlib
import re
from typing import Any

from backend.shared.python_utils.voice_action_receipts import (
    _client, _key, load_voice_action_receipt, receipt_payload, MAX_PENDING_RECEIPTS,
)
from .call_message_completed_handler import _load_message
from backend.core.api.app.services.directus.chat_methods import _validate_client_encrypted_message_content


async def send_pending_voice_actions(*, manager: Any, cache_service: Any,
                                     directus_service: Any, encryption_service: Any,
                                     user_id: str, user_id_hash: str, session_hash: str,
                                     device_fingerprint_hash: str,
                                     request_id: str | None = None) -> None:
    if not session_hash:
        return
    client = await _client(cache_service)
    if request_id is not None:
        ids = [request_id]
    else:
        ids = await client.smembers(_key("pending", user_id, session_hash))
    for receipt_id in list(ids)[:MAX_PENDING_RECEIPTS]:
        if isinstance(receipt_id, bytes):
            receipt_id = receipt_id.decode()
        try:
            receipt = await load_voice_action_receipt(cache_service=cache_service,
                directus_service=directus_service, encryption_service=encryption_service,
                user_id=user_id, user_hash=user_id_hash, session_id=session_hash,
                request_id=receipt_id)
        except ValueError:
            continue
        if receipt:
            await manager.send_personal_message({"type": "voice_action_completed",
                "payload": receipt_payload(receipt)}, user_id, device_fingerprint_hash)
        else:
            await client.srem(_key("pending", user_id, session_hash), receipt_id)


async def handle_voice_action_completed(*, manager: Any, cache_service: Any,
                                        directus_service: Any, encryption_service: Any,
                                        user_id: str, user_id_hash: str, session_hash: str,
                                        device_fingerprint_hash: str, payload: Any,
                                        confirmed: bool) -> None:
    identity_fields = {"request_id", "call_id", "chat_id", "assistant_message_id"}
    allowed = identity_fields | ({"revision", "ciphertext_hash"} if confirmed else set())
    if not isinstance(payload, dict) or set(payload) != allowed:
        return
    if not all(isinstance(payload[k], str) and 8 <= len(payload[k]) <= 128 for k in identity_fields):
        return
    if confirmed and (type(payload["revision"]) is not int or not 1 <= payload["revision"] <= 64
            or not isinstance(payload["ciphertext_hash"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", payload["ciphertext_hash"])):
        return
    client = await _client(cache_service)
    # Recovery is free, but bounded to 60 metadata/ACK requests per session minute.
    admitted = await client.eval(
        "local count = redis.call('INCR', KEYS[1]); "
        "if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end; return count",
        1, _key("rate", user_id, session_hash, str(int(time.time()) // 60)))
    if admitted > 60:
        return
    try:
        receipt = await load_voice_action_receipt(cache_service=cache_service,
            directus_service=directus_service, encryption_service=encryption_service,
            user_id=user_id, user_hash=user_id_hash, session_id=session_hash,
            request_id=payload["request_id"])
    except ValueError:
        return
    if not receipt or any(receipt[k] != payload[k] for k in identity_fields):
        return
    if not confirmed:
        await send_pending_voice_actions(manager=manager, cache_service=cache_service,
            directus_service=directus_service, encryption_service=encryption_service,
            user_id=user_id, user_id_hash=user_id_hash, session_hash=session_hash,
            device_fingerprint_hash=device_fingerprint_hash, request_id=payload["request_id"])
        return
    row = await _load_message(directus_service, receipt["assistant_message_id"])
    if (not row or row.get("chat_id") != receipt["chat_id"]
            or row.get("hashed_user_id") != user_id_hash or row.get("role") != "assistant"
            or row.get("user_message_id") != receipt["user_message_id"]
            or row.get("created_at") != receipt["created_at"]
            or not isinstance(row.get("encrypted_content"), str)
            or int(row.get("queue_revision") or 0) < 1
            or row.get("queue_pending_revision") is not None):
        return
    try:
        _validate_client_encrypted_message_content(receipt["assistant_message_id"], row["encrypted_content"])
    except ValueError:
        return
    if (int(row.get("queue_revision") or 0) != payload["revision"]
            or hashlib.sha256(row["encrypted_content"].encode()).hexdigest() != payload["ciphertext_hash"]):
        await send_pending_voice_actions(manager=manager, cache_service=cache_service,
            directus_service=directus_service, encryption_service=encryption_service,
            user_id=user_id, user_id_hash=user_id_hash, session_hash=session_hash,
            device_fingerprint_hash=device_fingerprint_hash, request_id=payload["request_id"])
        return
    # Retain sealed exact-row authority until expiry for duplicate ciphertext
    # outbox ACK retries; remove only the pending notification index.
    client = await _client(cache_service)
    await client.eval(
        "redis.call('SREM', KEYS[1], ARGV[1]); redis.call('ZREM', KEYS[2], ARGV[1]); return 1",
        2, _key("pending", user_id, session_hash), _key("slots", user_id, session_hash),
        payload["request_id"])
