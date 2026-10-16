"""Owner-Vault-sealed artifact-only receipts for already committed voice actions.

No skill is executed during recovery. Redis retains bounded ciphertext; only
routing identities enter pubsub. The original authenticated session alone can
recover and finalize the server-issued assistant row after call grace expires.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from backend.shared.python_utils.voice_call_registry import _client, require_active_call

RECEIPT_TTL_SECONDS = 72 * 3600
MAX_PENDING_RECEIPTS = 128


def _key(kind: str, *parts: str) -> str:
    digest = hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()
    return f"voice:action:{kind}:{digest}"


async def _vault(cache: Any, directus: Any, user_id: str) -> str:
    key_id = await cache.get_user_vault_key_id(user_id)
    if not key_id:
        profile = await directus.get_user_fields_direct(user_id, ["vault_key_id"])
        key_id = profile.get("vault_key_id") if isinstance(profile, dict) else None
    if not isinstance(key_id, str) or not key_id:
        raise ValueError("Voice receipt owner key unavailable")
    return key_id


async def _owned_chat(directus: Any, chat_id: str, user_hash: str) -> None:
    chat = await directus.chat.get_chat_metadata(chat_id)
    if (not chat or chat.get("hashed_user_id") != user_hash or chat.get("hashed_team_id")
            or chat.get("chat_visibility") in {"team", "direct"}):
        raise ValueError("Voice receipt chat not owned")


async def load_voice_action_receipt(*, cache_service: Any, directus_service: Any,
                                    encryption_service: Any, user_id: str, user_hash: str,
                                    session_id: str, request_id: str) -> dict | None:
    if not all(isinstance(v, str) and 1 <= len(v) <= 128
               for v in (user_id, user_hash, session_id, request_id)):
        raise ValueError("Invalid voice receipt identity")
    client = await _client(cache_service)
    sealed = await client.get(_key("receipt", user_id, session_id, request_id))
    if not sealed:
        return None
    if isinstance(sealed, bytes):
        sealed = sealed.decode()
    plaintext = await encryption_service.decrypt_with_user_key(
        sealed, await _vault(cache_service, directus_service, user_id))
    receipt = json.loads(plaintext) if plaintext else None
    if (not isinstance(receipt, dict) or receipt.get("user_id") != user_id
            or receipt.get("user_hash") != user_hash
            or receipt.get("initiator_session_id") != session_id
            or receipt.get("request_id") != request_id):
        raise ValueError("Voice receipt not authorized")
    await _owned_chat(directus_service, receipt["chat_id"], user_hash)
    return receipt


def receipt_payload(receipt: dict) -> dict:
    return {key: receipt[key] for key in (
        "request_id", "call_id", "chat_id", "assistant_message_id", "user_message_id",
        "initiator_session_id", "user_id", "embed_refs", "created_at")}


async def admit_voice_action_receipt(*, cache_service: Any, directus_service: Any,
                                     encryption_service: Any, binding: dict,
                                     request_id: str) -> None:
    """Seal exact issued-row authority before executing a committed action.

    This permit is server-only. It contains no result/artifacts and is not a
    recovery notification; it survives hangup so completed writes can be saved.
    """
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
        raise ValueError("Invalid voice receipt identity")
    timestamp = binding.get("assistant_created_at") or binding.get("created_at")
    if not timestamp:
        identity = uuid.UUID(binding["assistant_message_id"])
        if identity.version != 7:
            raise ValueError("Missing issued assistant timestamp")
        timestamp = (identity.int >> 80) // 1000
    if type(timestamp) is not int or timestamp <= 0 or timestamp > int(time.time()) + 300:
        raise ValueError("Invalid issued assistant timestamp")
    state = await require_active_call(cache_service, user_id=binding["user_id"],
        session_id=binding["session_id"], chat_id=binding["chat_id"], call_id=binding["call_id"],
        message_id=binding["assistant_message_id"], role="assistant")
    if state.state != "active":
        raise ValueError("Voice action must be admitted while active")
    await require_active_call(cache_service, user_id=binding["user_id"],
        session_id=binding["session_id"], chat_id=binding["chat_id"], call_id=binding["call_id"],
        message_id=binding["user_message_id"], role="user")
    await _owned_chat(directus_service, binding["chat_id"], binding["user_hash"])
    permit = {k: binding[k] for k in ("user_id", "user_hash", "session_id", "chat_id", "call_id",
              "user_message_id", "assistant_message_id", "operation_id")}
    permit.update(request_id=request_id, created_at=timestamp, skill_index=binding.get("skill_index", 0))
    sealed, _ = await encryption_service.encrypt_with_user_key(json.dumps(permit, separators=(",", ":")),
        await _vault(cache_service, directus_service, binding["user_id"]))
    if not isinstance(sealed, str) or not sealed.startswith("vault:v"):
        raise RuntimeError("Voice action permit encryption failed")
    client = await _client(cache_service)
    now = int(time.time())
    admitted = await client.eval(
        "if redis.call('EXISTS', KEYS[1]) == 1 then return 1 end "
        "redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[4]); "
        "if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[5]) then return 0 end "
        "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]); "
        "redis.call('ZADD', KEYS[2], ARGV[3], ARGV[6]); "
        "redis.call('EXPIRE', KEYS[2], ARGV[2]); return 1",
        2, _key("permit", binding["user_id"], binding["session_id"], request_id),
        _key("slots", binding["user_id"], binding["session_id"]), sealed,
        RECEIPT_TTL_SECONDS, now + RECEIPT_TTL_SECONDS, now, MAX_PENDING_RECEIPTS, request_id)
    if admitted != 1:
        raise RuntimeError("Voice action admission capacity exceeded")


async def release_voice_action_admission(*, cache_service: Any, binding: dict,
                                         request_id: str) -> None:
    """Release a failed/undispatched action; never discard a completed receipt."""
    client = await _client(cache_service)
    await client.eval(
        "if redis.call('EXISTS', KEYS[3]) == 1 then return 0 end "
        "redis.call('DEL', KEYS[1]); redis.call('ZREM', KEYS[2], ARGV[1]); return 1",
        3, _key("permit", binding["user_id"], binding["session_id"], request_id),
        _key("slots", binding["user_id"], binding["session_id"]),
        _key("receipt", binding["user_id"], binding["session_id"], request_id), request_id)


async def persist_voice_action_receipt(*, cache_service: Any, directus_service: Any,
                                       encryption_service: Any, binding: dict,
                                       embed_refs: list[str], request_id: str) -> dict:
    required = ("user_id", "user_hash", "session_id", "chat_id", "call_id",
                "user_message_id", "assistant_message_id", "operation_id")
    if (not isinstance(binding, dict) or not all(isinstance(binding.get(k), str)
            and 1 <= len(binding[k]) <= 128 for k in required)
            or not isinstance(request_id, str) or not 8 <= len(request_id) <= 128
            or not isinstance(embed_refs, list) or not 1 <= len(embed_refs) <= 128
            or not all(isinstance(ref, str) and 1 <= len(ref) <= 128 for ref in embed_refs)):
        raise ValueError("Invalid committed voice action receipt")
    client = await _client(cache_service)
    operation_key = _key("operation", binding["user_id"], binding["session_id"],
                         binding["call_id"], binding["operation_id"], str(binding.get("skill_index", 0)))
    previous = await client.get(operation_key)
    if previous:
        previous = previous.decode() if isinstance(previous, bytes) else previous
        existing = await load_voice_action_receipt(cache_service=cache_service,
            directus_service=directus_service, encryption_service=encryption_service,
            user_id=binding["user_id"], user_hash=binding["user_hash"],
            session_id=binding["session_id"], request_id=previous)
        if existing:
            return receipt_payload(existing)
    permit_key = _key("permit", binding["user_id"], binding["session_id"], request_id)
    sealed_permit = await client.get(permit_key)
    if not sealed_permit:
        raise ValueError("Committed voice action was not admitted")
    if isinstance(sealed_permit, bytes):
        sealed_permit = sealed_permit.decode()
    permit_text = await encryption_service.decrypt_with_user_key(sealed_permit,
        await _vault(cache_service, directus_service, binding["user_id"]))
    permit = json.loads(permit_text) if permit_text else None
    if (not isinstance(permit, dict) or any(permit.get(k) != binding[k] for k in required)
            or permit.get("request_id") != request_id
            or permit.get("skill_index") != binding.get("skill_index", 0)):
        raise ValueError("Committed voice action permit mismatch")
    await _owned_chat(directus_service, binding["chat_id"], binding["user_hash"])
    receipt = {k: binding[k] for k in required if k != "session_id"}
    receipt.update(request_id=request_id, initiator_session_id=binding["session_id"],
                   embed_refs=list(dict.fromkeys(embed_refs)), created_at=permit["created_at"])
    sealed, _ = await encryption_service.encrypt_with_user_key(
        json.dumps(receipt, separators=(",", ":")),
        await _vault(cache_service, directus_service, binding["user_id"]))
    if not isinstance(sealed, str) or not sealed.startswith("vault:v"):
        raise RuntimeError("Voice receipt encryption failed")
    pending_key = _key("pending", binding["user_id"], binding["session_id"])
    assistant_key = _key("assistant", binding["user_id"], binding["session_id"],
                         binding["call_id"], binding["chat_id"], binding["assistant_message_id"])
    # Atomic operation claim and receipt/index creation; a retry cannot replace
    # the already committed operation with another assistant or artifact set.
    winning = await client.eval(
        "local old = redis.call('GET', KEYS[1]); if old then return old end "
        "if redis.call('EXISTS', KEYS[5]) == 0 or "
        "not redis.call('ZSCORE', KEYS[6], ARGV[1]) then return false end "
        "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3]); "
        "redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3]); "
        "redis.call('SADD', KEYS[3], ARGV[1]); redis.call('EXPIRE', KEYS[3], ARGV[3]); "
        "redis.call('SET', KEYS[4], ARGV[1], 'EX', ARGV[3]); "
        "redis.call('ZADD', KEYS[6], ARGV[4], ARGV[1]); "
        "redis.call('EXPIRE', KEYS[6], ARGV[3]); return ARGV[1]",
        6, operation_key, _key("receipt", binding["user_id"], binding["session_id"], request_id),
        pending_key, assistant_key, permit_key,
        _key("slots", binding["user_id"], binding["session_id"]),
        request_id, sealed, RECEIPT_TTL_SECONDS, int(time.time()) + RECEIPT_TTL_SECONDS)
    if not winning:
        raise RuntimeError("Voice action admission unavailable")
    winning = winning.decode() if isinstance(winning, bytes) else winning
    if winning != request_id:
        existing = await load_voice_action_receipt(cache_service=cache_service,
            directus_service=directus_service, encryption_service=encryption_service,
            user_id=binding["user_id"], user_hash=binding["user_hash"],
            session_id=binding["session_id"], request_id=winning)
        if not existing:
            raise RuntimeError("Voice receipt unavailable")
        return receipt_payload(existing)
    await cache_service.publish_event(f"user_cache_events:{binding['user_id']}", {
        "event_type": "voice_action_completed", "payload": {
            "request_id": request_id, "initiator_session_id": binding["session_id"]}})
    return receipt_payload(receipt)


async def require_committed_voice_action(*, cache_service: Any, directus_service: Any,
                                         encryption_service: Any, user_id: str,
                                         user_hash: str, session_id: str, message: dict) -> None:
    if message["role"] != "assistant":
        raise ValueError("Voice receipt not authorized")
    client = await _client(cache_service)
    request_id = await client.get(_key("assistant", user_id, session_id, message["call_id"],
                                      message["chat_id"], message["message_id"]))
    if isinstance(request_id, bytes):
        request_id = request_id.decode()
    if not request_id:
        raise ValueError("Voice receipt not authorized")
    receipt = await load_voice_action_receipt(cache_service=cache_service,
        directus_service=directus_service, encryption_service=encryption_service,
        user_id=user_id, user_hash=user_hash, session_id=session_id, request_id=request_id)
    if not receipt or any(receipt[k] != message[m] for k, m in (
            ("assistant_message_id", "message_id"), ("call_id", "call_id"),
            ("chat_id", "chat_id"), ("user_message_id", "user_message_id"),
            ("created_at", "created_at"))):
        raise ValueError("Voice receipt not authorized")
