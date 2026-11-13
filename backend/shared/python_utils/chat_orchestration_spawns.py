"""Spawn links, spawn state and the user-active guard for chat orchestration.

A main chat can start other main chats (plan: docs/plans/chat-orchestration-main-chats).
This module keeps the per-spawned-chat bookkeeping in Redis: the creator link
(plaintext chat ids only), the spawn state with its label (Vault-encrypted for
the owner, 72 h TTL, decision D-5) and the ten-minute user-active marker.
Durable truth is ``chats.creator_chat_id`` plus the orchestration child row.
Titles and content never appear in plaintext Redis or logs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

CAPABILITY = "chat_orchestration_jobs"
SPAWN_STATES = ("starting", "working", "finished", "waiting_for_user", "user_active", "failed")
UNFINISHED_STATES = ("starting", "working", "waiting_for_user", "user_active")
ERROR_CODES = (
    "not_spawned_by_this_chat", "device_offline", "user_active", "spawn_limit_reached",
    "chain_too_deep", "not_eligible", "no_creator", "job_failed", "job_expired",
)
STATE_TTL_SECONDS = 72 * 3600
USER_ACTIVE_TTL_SECONDS = 600
MAX_CHAIN_HOPS = 10


class OrchestrationError(Exception):
    """Failure with a code from the orchestration protocol error list."""

    def __init__(self, code: str, message: str = "") -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown orchestration error code: {code}")
        self.code = code
        super().__init__(message or code)


@dataclass
class JobOutcome:
    """Result of an orchestration job; state is done|failed|pending|expired."""

    job_id: str
    state: str
    result: Optional[dict] = None
    error_code: Optional[str] = None


def key(*parts: str) -> str:
    return ":".join(("chat_orch:v1", *parts))


def hash_user(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


async def redis_client(cache_service: Any) -> Any:
    client = await cache_service.client
    if client is None:
        raise OrchestrationError("job_failed", "cache unavailable")
    return client


async def seal(cache_service: Any, encryption_service: Any, user_id: str, value: Any) -> dict[str, str]:
    """Vault-encrypt a JSON value with the owner's key."""
    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not vault_key_id:
        raise OrchestrationError("job_failed", "owner vault key unavailable")
    ciphertext, key_version = await encryption_service.encrypt_with_user_key(
        json.dumps(value, separators=(",", ":")), vault_key_id)
    if not ciphertext:
        raise OrchestrationError("job_failed", "encryption failed")
    return {"ct": ciphertext, "kv": key_version}


async def unseal(cache_service: Any, encryption_service: Any, user_id: str, sealed: Any) -> Any:
    if not isinstance(sealed, dict) or not isinstance(sealed.get("ct"), str):
        raise OrchestrationError("job_failed", "sealed value missing")
    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    plaintext = await encryption_service.decrypt_with_user_key(sealed["ct"], vault_key_id) if vault_key_id else None
    if not plaintext:
        raise OrchestrationError("job_failed", "decryption failed")
    return json.loads(plaintext)


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


async def set_members(cache_service: Any, set_key: str) -> list[str]:
    client = await redis_client(cache_service)
    return sorted(_text(item) for item in await client.smembers(set_key))


async def set_add(cache_service: Any, set_key: str, member: str, ttl: int) -> None:
    client = await redis_client(cache_service)
    await client.sadd(set_key, member)
    await client.expire(set_key, ttl)


async def set_remove(cache_service: Any, set_key: str, member: str) -> None:
    client = await redis_client(cache_service)
    await client.srem(set_key, member)


async def link_spawned_chat(*, cache_service: Any, user_id: str, creator_chat_id: str,
                            spawned_chat_id: str, title: Optional[str] = None,
                            encryption_service: Any = None) -> None:
    """Record creator -> spawned membership and the spawned -> creator link (ids only)."""
    if not await cache_service.set(key("link", spawned_chat_id), {"creator_chat_id": creator_chat_id},
                                   ttl=STATE_TTL_SECONDS):
        raise OrchestrationError("job_failed", "cache unavailable")
    await set_add(cache_service, key("spawned", user_id, creator_chat_id), spawned_chat_id, STATE_TTL_SECONDS)
    if title and encryption_service is not None:
        await set_spawn_state(cache_service=cache_service, encryption_service=encryption_service,
                              user_id=user_id, spawned_chat_id=spawned_chat_id,
                              state=(await _current_state(cache_service, spawned_chat_id)) or "starting",
                              title=title)


async def get_creator_chat_id(*, cache_service: Any, chat_id: str,
                              directus_service: Any = None) -> Optional[str]:
    """Creator of a chat: Redis link first, then Directus ``chats.creator_chat_id`` (cached)."""
    link = await cache_service.get(key("link", chat_id))
    if isinstance(link, dict) and isinstance(link.get("creator_chat_id"), str):
        return link["creator_chat_id"]
    if directus_service is None:
        from backend.core.api.app.services.directus import DirectusService
        directus_service = DirectusService()
    metadata = await directus_service.chat.get_chat_metadata(chat_id)
    creator = metadata.get("creator_chat_id") if isinstance(metadata, dict) else None
    if not isinstance(creator, str) or not creator:
        return None
    await cache_service.set(key("link", chat_id), {"creator_chat_id": creator}, ttl=STATE_TTL_SECONDS)
    return creator


async def creator_chain_depth(*, cache_service: Any, chat_id: str, directus_service: Any = None) -> int:
    """Number of creator hops above a chat (0 for a chat nobody spawned)."""
    depth, current, seen = 0, chat_id, {chat_id}
    while depth < MAX_CHAIN_HOPS:
        creator = await get_creator_chat_id(cache_service=cache_service, chat_id=current,
                                            directus_service=directus_service)
        if creator is None or creator in seen:
            return depth
        seen.add(creator)
        current, depth = creator, depth + 1
    return depth


async def _current_state(cache_service: Any, spawned_chat_id: str) -> Optional[str]:
    record = await cache_service.get(key("state", spawned_chat_id))
    return record.get("state") if isinstance(record, dict) else None


async def set_spawn_state(*, cache_service: Any, encryption_service: Any, user_id: str,
                          spawned_chat_id: str, state: str, title: Optional[str] = None) -> None:
    """Store state (and optionally the label, Vault-encrypted) for 72 h."""
    if state not in SPAWN_STATES:
        raise ValueError(f"unknown spawn state: {state}")
    previous = await cache_service.get(key("state", spawned_chat_id))
    previous = previous if isinstance(previous, dict) and previous.get("user_id") == user_id else {}
    now = int(time.time())
    record = {
        "user_id": user_id, "state": state, "label": previous.get("label"),
        "started_at": previous.get("started_at") or now, "updated_at": now,
    }
    if title:
        record["label"] = await seal(cache_service, encryption_service, user_id, {"title": title})
    if not await cache_service.set(key("state", spawned_chat_id), record, ttl=STATE_TTL_SECONDS):
        raise OrchestrationError("job_failed", "cache unavailable")


async def get_spawn_state(*, cache_service: Any, encryption_service: Any, user_id: str,
                          spawned_chat_id: str) -> Optional[dict[str, Any]]:
    record = await cache_service.get(key("state", spawned_chat_id))
    if not isinstance(record, dict) or record.get("user_id") != user_id:
        return None
    title = None
    if record.get("label"):
        title = (await unseal(cache_service, encryption_service, user_id, record["label"])).get("title")
    return {"state": record.get("state"), "title": title,
            "started_at": record.get("started_at"), "updated_at": record.get("updated_at")}


async def mark_user_active(*, cache_service: Any, spawned_chat_id: str) -> None:
    if not await cache_service.set(key("active", spawned_chat_id), int(time.time()),
                                   ttl=USER_ACTIVE_TTL_SECONDS):
        raise OrchestrationError("job_failed", "cache unavailable")


async def is_user_active(*, cache_service: Any, spawned_chat_id: str) -> bool:
    return await cache_service.get(key("active", spawned_chat_id)) is not None


async def list_spawned(*, cache_service: Any, encryption_service: Any, user_id: str,
                       creator_chat_id: str, directus_service: Any = None) -> list[dict[str, Any]]:
    """Chats spawned by a creator: Redis state, durable ``creator_chat_id`` rows as fallback."""
    members = await set_members(cache_service, key("spawned", user_id, creator_chat_id))
    states = {chat_id: await get_spawn_state(cache_service=cache_service, encryption_service=encryption_service,
                                             user_id=user_id, spawned_chat_id=chat_id) for chat_id in members}
    items: dict[str, dict[str, Any]] = {
        chat_id: {"chat_id": chat_id, "title": s["title"], "state": s["state"],
                  "started_at": s["started_at"], "updated_at": s["updated_at"]}
        for chat_id, s in states.items() if s}
    if len(items) < len(members) or not members:
        if directus_service is None:
            from backend.core.api.app.services.directus import DirectusService
            directus_service = DirectusService()
        rows = await directus_service.get_items("chats", params={
            "filter[creator_chat_id][_eq]": creator_chat_id,
            "filter[hashed_user_id][_eq]": hash_user(user_id),
            "fields": "id,created_at,updated_at", "limit": 50,
        }) or []
        for row in rows:
            items.setdefault(row["id"], {"chat_id": row["id"], "title": None, "state": "unknown",
                                         "started_at": row.get("created_at"),
                                         "updated_at": row.get("updated_at")})
    return sorted(items.values(), key=lambda item: item.get("started_at") or 0)


async def count_unfinished_spawned(*, cache_service: Any, encryption_service: Any, user_id: str,
                                   creator_chat_id: str, directus_service: Any = None) -> int:
    """Spawned chats still starting, working, waiting or user-active (unknown/expired not counted)."""
    spawned = await list_spawned(cache_service=cache_service, encryption_service=encryption_service,
                                 user_id=user_id, creator_chat_id=creator_chat_id,
                                 directus_service=directus_service)
    return sum(1 for item in spawned if item["state"] in UNFINISHED_STATES)
