"""Ephemeral authority for encrypted messages issued by a live voice call.

Only identities and lifecycle state are stored in Redis. Transcript text and
audio never enter this registry. A completed call retains its issued identities
briefly so a browser can retry ciphertext synchronization after hangup.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


ACTIVE_TTL_SECONDS = 90
FINALIZATION_GRACE_SECONDS = 300


@dataclass(frozen=True)
class VoiceCallBinding:
    state: str
    grace_expires_at: int | None


def _keys(call_id: str) -> tuple[str, str]:
    if len(call_id) != 32 or any(c not in "0123456789abcdef" for c in call_id):
        raise ValueError("Invalid call identity")
    key = f"voice:call:{call_id}"
    return key, f"{key}:messages"


async def _client(cache: Any) -> Any:
    client = await cache.client
    if client is None:
        raise RuntimeError("Voice call authority unavailable")
    return client


async def register_active_call(
    cache: Any, *, user_id: str, session_id: str, chat_id: str, call_id: str,
    ttl_seconds: int = ACTIVE_TTL_SECONDS,
) -> None:
    key, _ = _keys(call_id)
    if not all(isinstance(value, str) and value for value in (user_id, session_id, chat_id)):
        raise ValueError("Invalid call binding")
    client = await _client(cache)
    created = await client.eval(
        "if redis.call('EXISTS', KEYS[1]) ~= 0 then return 0 end "
        "redis.call('HSET', KEYS[1], 'user', ARGV[1], 'session', ARGV[2], 'chat', ARGV[3], 'state', 'active') "
        "redis.call('EXPIRE', KEYS[1], ARGV[4]) return 1",
        1, key, user_id, session_id, chat_id, ttl_seconds,
    )
    if created != 1:
        raise RuntimeError("Call identity already exists")


async def renew_active_call(
    cache: Any, *, user_id: str, session_id: str, chat_id: str, call_id: str,
    ttl_seconds: int = ACTIVE_TTL_SECONDS,
) -> None:
    key, messages_key = _keys(call_id)
    client = await _client(cache)
    renewed = await client.eval(
        "if redis.call('HGET', KEYS[1], 'user') ~= ARGV[1] or "
        "redis.call('HGET', KEYS[1], 'session') ~= ARGV[2] or "
        "redis.call('HGET', KEYS[1], 'chat') ~= ARGV[3] or "
        "redis.call('HGET', KEYS[1], 'state') ~= 'active' then return 0 end "
        "redis.call('EXPIRE', KEYS[1], ARGV[4]) "
        "if redis.call('EXISTS', KEYS[2]) == 1 then redis.call('EXPIRE', KEYS[2], ARGV[4]) end return 1",
        2, key, messages_key, user_id, session_id, chat_id, ttl_seconds,
    )
    if renewed != 1:
        raise RuntimeError("Voice call authority lost")


async def issue_message_id(
    cache: Any, *, user_id: str, session_id: str, chat_id: str, call_id: str,
    message_id: str, role: str,
) -> None:
    key, messages_key = _keys(call_id)
    if role not in ("user", "assistant") or not isinstance(message_id, str) or not (1 <= len(message_id) <= 128):
        raise ValueError("Invalid call message identity")
    client = await _client(cache)
    issued = await client.eval(
        "if redis.call('HGET', KEYS[1], 'user') ~= ARGV[1] or "
        "redis.call('HGET', KEYS[1], 'session') ~= ARGV[2] or "
        "redis.call('HGET', KEYS[1], 'chat') ~= ARGV[3] or "
        "redis.call('HGET', KEYS[1], 'state') ~= 'active' then return 0 end "
        "local previous = redis.call('HGET', KEYS[2], ARGV[4]) "
        "if previous and previous ~= ARGV[5] then return -1 end "
        "redis.call('HSET', KEYS[2], ARGV[4], ARGV[5]) "
        "redis.call('EXPIRE', KEYS[2], redis.call('TTL', KEYS[1])) return 1",
        2, key, messages_key, user_id, session_id, chat_id, message_id, role,
    )
    if issued != 1:
        raise ValueError("Call message not authorized")


async def require_active_call(
    cache: Any, *, user_id: str, session_id: str, chat_id: str, call_id: str,
    message_id: str, role: str,
) -> VoiceCallBinding:
    key, messages_key = _keys(call_id)
    client = await _client(cache)
    values = await client.hmget(key, "user", "session", "chat", "state", "grace_expires_at")
    decoded = [value.decode() if isinstance(value, bytes) else value for value in values]
    if decoded[:3] != [user_id, session_id, chat_id] or decoded[3] not in ("active", "finalizing"):
        raise ValueError("Call message not authorized")
    issued_role = await client.hget(messages_key, message_id)
    if isinstance(issued_role, bytes):
        issued_role = issued_role.decode()
    if issued_role != role:
        raise ValueError("Call message not authorized")
    expiry = int(decoded[4]) if decoded[4] else None
    if decoded[3] == "finalizing" and (expiry is None or expiry <= int(time.time())):
        raise ValueError("Call message not authorized")
    return VoiceCallBinding(state=decoded[3], grace_expires_at=expiry)


async def finalize_active_call(
    cache: Any, *, user_id: str, session_id: str, chat_id: str, call_id: str,
    grace_seconds: int = FINALIZATION_GRACE_SECONDS,
) -> None:
    key, messages_key = _keys(call_id)
    client = await _client(cache)
    expiry = int(time.time()) + grace_seconds
    finalized = await client.eval(
        "if redis.call('HGET', KEYS[1], 'user') ~= ARGV[1] or "
        "redis.call('HGET', KEYS[1], 'session') ~= ARGV[2] or "
        "redis.call('HGET', KEYS[1], 'chat') ~= ARGV[3] then return 0 end "
        "redis.call('HSET', KEYS[1], 'state', 'finalizing', 'grace_expires_at', ARGV[4]) "
        "redis.call('EXPIRE', KEYS[1], ARGV[5]) "
        "if redis.call('EXISTS', KEYS[2]) == 1 then redis.call('EXPIRE', KEYS[2], ARGV[5]) end return 1",
        2, key, messages_key, user_id, session_id, chat_id, expiry, grace_seconds,
    )
    if finalized != 1:
        raise RuntimeError("Voice call authority lost")


async def active_call_session(cache: Any, *, user_id: str, chat_id: str, call_id: str) -> str | None:
    """Return the owning session only while this owner/chat call is active.

    Speech status delivery uses call ownership rather than the visible chat.
    This lookup exposes identities only and never extends finalization grace.
    """
    if not all(isinstance(value, str) and value for value in (user_id, chat_id, call_id)):
        return None
    try:
        key, _ = _keys(call_id)
    except ValueError:
        return None
    client = await _client(cache)
    values = await client.hmget(key, "user", "session", "chat", "state")
    values = [value.decode() if isinstance(value, bytes) else value for value in values]
    if values[0] != user_id or values[2:] != [chat_id, "active"]:
        return None
    session_id = values[1]
    return session_id if isinstance(session_id, str) and session_id else None
