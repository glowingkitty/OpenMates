"""Encrypted, short-lived internal routing decisions; references grant no authority."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

TTL_SECONDS = 120
KEY_PREFIX = "ai:stage-one:v1:"


def request_fingerprint(request: dict, config: dict) -> str:
    return hashlib.sha256(json.dumps([request, config], sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


async def routing_turn_is_current(cache: Any, request: Any, task_id: str) -> bool:
    """Only the currently admitted assistant task may publish or reuse a route."""
    return bool(request.user_id and task_id and
                await cache.get_active_ai_task(request.chat_id) == task_id)


async def routing_admission_is_current(directus: Any, request: Any, task_id: str) -> bool:
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
    result = await ChatRecoveryService(directus).execute("verify_routing_admission", {
        "protocol_version": 1, "preflight_id": request.recovery_preflight_id,
        "inference_task_id": task_id, "hashed_user_id": request.user_id_hash,
        "hashed_team_id": request.team_id_hash, "chat_id": request.chat_id,
        "message_id": request.message_id, "turn_id": request.recovery_turn_id,
    })
    return result.get("authorized") is True


async def store_stage_one(*, cache: Any, encryption: Any, request: Any,
                         task_id: str, fingerprint: str, routing: dict,
                         typing_started: bool) -> str:
    vault_key = await cache.get_user_vault_key_id(request.user_id)
    if not vault_key or not await routing_turn_is_current(cache, request, task_id):
        raise RuntimeError("Routing handoff authority unavailable")
    record = {"version": 1, "user_id": request.user_id, "team_id": request.team_id,
              "chat_id": request.chat_id, "message_id": request.message_id,
              "task_id": task_id, "fingerprint": fingerprint,
              "expires_at": time.time() + TTL_SECONDS,
              "routing": routing, "typing_started": typing_started}
    ciphertext, _ = await encryption.encrypt_with_user_key(json.dumps(record), vault_key)
    if not ciphertext:
        raise RuntimeError("Routing handoff encryption unavailable")
    reference = secrets.token_urlsafe(32)
    client = await cache.client
    if not await client.set(KEY_PREFIX + reference, ciphertext, ex=TTL_SECONDS, nx=True):
        raise RuntimeError("Routing handoff storage unavailable")
    return reference


async def load_stage_one(*, cache: Any, encryption: Any, request: Any, directus: Any,
                        task_id: str, fingerprint: str, reference: str | None) -> dict | None:
    """Missing/expired/mismatched entries use the full existing routing path."""
    if not isinstance(reference, str) or not 32 <= len(reference) <= 128:
        return None
    try:
        if not await routing_turn_is_current(cache, request, task_id):
            return None
        if not await routing_admission_is_current(directus, request, task_id):
            return None
        vault_key = await cache.get_user_vault_key_id(request.user_id)
        client = await cache.client
        ciphertext = await client.get(KEY_PREFIX + reference)
        if not vault_key or not ciphertext:
            return None
        if isinstance(ciphertext, bytes):
            ciphertext = ciphertext.decode()
        record = json.loads(await encryption.decrypt_with_user_key(ciphertext, vault_key))
        expected = {"version": 1, "user_id": request.user_id, "team_id": request.team_id,
                    "chat_id": request.chat_id, "message_id": request.message_id,
                    "task_id": task_id, "fingerprint": fingerprint}
        if (any(record.get(key) != value for key, value in expected.items())
                or record.get("expires_at", 0) <= time.time()
                or not isinstance(record.get("routing"), dict)):
            return None
        return record
    except Exception:
        return None
