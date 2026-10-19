"""Bounded, Vault-sealed voice metadata work independent of Live cancellation.

First-party session WebSocket only. Admission requires an owned personal chat,
issued and durably stored call messages, rate/credit limits and an exact key.
Recovery never repeats inference. Only identities enter notifications/queue logs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from backend.shared.python_utils.voice_action_receipts import _vault, _owned_chat
from backend.shared.python_utils.voice_call_registry import _client, require_active_call

TTL = 72 * 3600
TASK = "apps.ai.tasks.voice_chat_metadata"


class MetadataStale(ValueError):
    """An unpaid request needs its current owner-encrypted baseline first."""

    def __init__(self, chat: dict):
        super().__init__("Metadata baseline changed")
        self.chat = chat


@asynccontextmanager
async def mutation_lock(cache: Any, user_id: str, chat_id: str):
    client = await _client(cache)
    # Ownership-token release and a longer lease than the bounded operation
    # serialize admissions/results across the owner's concurrent connections.
    async with client.lock(key("mutation", user_id, chat_id), timeout=45, blocking_timeout=3):
        async with asyncio.timeout(20):
            yield


def key(kind: str, *parts: str) -> str:
    digest = hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()
    return f"voice:metadata:{kind}:{digest}"


def validate_request(value: Any) -> dict:
    fields = {"request_id", "call_id", "chat_id", "source_messages", "context", "current_title", "current_summary", "source_title_v", "source_metadata_v", "encrypted_chat_key", "final"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Invalid metadata request")
    for name in ("request_id", "chat_id"):
        if not isinstance(value[name], str) or str(uuid.UUID(value[name])) != value[name]:
            raise ValueError("Invalid metadata identity")
    if not isinstance(value["call_id"], str) or len(value["call_id"]) != 32 or any(c not in "0123456789abcdef" for c in value["call_id"]):
        raise ValueError("Invalid call identity")
    for name in ("source_title_v", "source_metadata_v"):
        if type(value[name]) is not int or not 0 <= value[name] <= 2**53 - 1:
            raise ValueError("Invalid metadata version")
    if type(value["final"]) is not bool:
        raise ValueError("Invalid finalization state")
    for name, limit in (("current_title", 200), ("current_summary", 1000), ("encrypted_chat_key", 4096)):
        if not isinstance(value[name], str) or len(value[name]) > limit:
            raise ValueError("Invalid metadata field")
    sources = value["source_messages"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 64:
        raise ValueError("Invalid metadata sources")
    for row in sources:
        if (not isinstance(row, dict) or set(row) != {"message_id", "role", "revision"}
                or not isinstance(row["message_id"], str) or not 8 <= len(row["message_id"]) <= 128
                or row["role"] not in {"user", "assistant"} or type(row["revision"]) is not int
                or not 1 <= row["revision"] <= 64):
            raise ValueError("Invalid metadata source")
    if not any(row["role"] == "user" for row in sources) or len({row["message_id"] for row in sources}) != len(sources):
        raise ValueError("Invalid metadata source set")
    context = value["context"]
    if not isinstance(context, dict) or set(context) != {"summary", "messages"}:
        raise ValueError("Invalid metadata context")
    if not isinstance(context["summary"], str) or len(context["summary"]) > 48_000:
        raise ValueError("Invalid metadata checkpoint")
    messages = context["messages"]
    if (not isinstance(messages, list) or not 1 <= len(messages) <= 30
            or any(not isinstance(row, dict) or not {"role", "content"}.issubset(row) or set(row) - {"role", "content", "call_turn"}
                   or ("call_turn" in row and type(row["call_turn"]) is not bool)
                   or row["role"] not in {"user", "assistant"} or not isinstance(row["content"], str) for row in messages)
            or len(json.dumps(context, ensure_ascii=False)) > 64_000):
        raise ValueError("Invalid metadata history")
    return value


async def source_rows(directus: Any, data: dict) -> bool:
    rows = await directus.get_items("messages", params={
        "filter[chat_id][_eq]": data["chat_id"], "filter[hashed_user_id][_eq]": data["user_hash"],
        "filter[client_message_id][_in]": ",".join(row["message_id"] for row in data["source_messages"]),
        "fields": "client_message_id,role,queue_revision,queue_pending_revision", "limit": 64,
    }, admin_required=True)
    stored = {row["client_message_id"]: row for row in rows or []}
    return all((row := stored.get(source["message_id"])) and row.get("role") == source["role"]
               and int(row.get("queue_revision") or 0) == source["revision"]
               and row.get("queue_pending_revision") is None for source in data["source_messages"])


async def load(*, cache: Any, directus: Any, encryption: Any, user_id: str, user_hash: str, request_id: str) -> dict | None:
    client = await _client(cache)
    sealed = await client.get(key("result", user_id, request_id))
    if not sealed:
        return None
    data = json.loads(await encryption.decrypt_with_user_key(sealed.decode() if isinstance(sealed, bytes) else sealed,
        await _vault(cache, directus, user_id)))
    if data.get("user_id") != user_id or data.get("user_hash") != user_hash or data.get("request_id") != request_id:
        raise ValueError("Metadata receipt binding mismatch")
    await _owned_chat(directus, data["chat_id"], user_hash)
    return data


async def admit(*, cache: Any, directus: Any, encryption: Any, user_id: str, user_hash: str,
                session_id: str, payload: Any) -> str:
    value = validate_request(payload)
    async with mutation_lock(cache, user_id, value["chat_id"]):
        return await _admit(cache=cache, directus=directus, encryption=encryption,
            user_id=user_id, user_hash=user_hash, session_id=session_id, payload=value)


async def _admit(*, cache: Any, directus: Any, encryption: Any, user_id: str, user_hash: str,
                 session_id: str, payload: Any) -> str:
    value = dict(validate_request(payload))
    await _owned_chat(directus, value["chat_id"], user_hash)
    client = await _client(cache)
    if await client.scard(key("pending", user_id)) >= 128:
        raise ValueError("Too many pending metadata results")
    signature = hashlib.sha256(json.dumps(value["source_messages"], sort_keys=True).encode()).hexdigest()
    dedupe = key("snapshot", user_id, value["chat_id"], value["call_id"], signature)
    previous = await client.get(dedupe)
    if previous:
        return previous.decode() if isinstance(previous, bytes) else previous
    # Even an ambiguous broker acknowledgement must retain the same paid-work
    # identity when the client retries with a fresh transport request UUID.
    value["request_id"] = str(uuid.uuid5(uuid.UUID(value["chat_id"]), value["call_id"] + ":" + signature))
    # Admission is allowed during the existing final transcript grace. Once
    # admitted, the sealed job no longer depends on an active call registry.
    for row in value["source_messages"]:
        await require_active_call(cache, user_id=user_id, session_id=session_id,
            chat_id=value["chat_id"], call_id=value["call_id"], message_id=row["message_id"], role=row["role"])
    chat = await directus.chat.get_chat_metadata(value["chat_id"], admin_required=True)
    if not value["encrypted_chat_key"] or chat.get("encrypted_chat_key") != value["encrypted_chat_key"]:
        raise ValueError("Metadata key mismatch")
    cached = await cache.get_chat_versions(user_id, value["chat_id"])
    metadata_v = max(int(chat.get("metadata_v") or 0), int(chat.get("title_v") or 0))
    cached_v = max(int(getattr(cached, "metadata_v", 0) or 0), int(getattr(cached, "title_v", 0) or 0))
    if (value["source_title_v"] != int(chat.get("title_v") or 0)
            or value["source_metadata_v"] != metadata_v or cached_v > metadata_v):
        raise MetadataStale(chat)
    data = {**value, "user_id": user_id, "user_hash": user_hash, "session_id": session_id,
            "baseline_title": chat.get("encrypted_title"), "baseline_summary": chat.get("encrypted_chat_summary"),
            "source_messages_v": int(chat.get("messages_v") or 0),
            "expires_at": int(time.time()) + 300}
    if not await source_rows(directus, data):
        raise ValueError("Metadata sources are not persisted")
    # Separate account and chat limits bound paid work, including repeated final
    # requests. Identical snapshots return their original operation for free.
    for bucket, limit in ((key("rate", user_id, str(int(time.time()) // 60)), 6),
                          (key("rate-chat", user_id, value["chat_id"], str(int(time.time()) // 60)), 3)):
        count = await client.incr(bucket)
        await client.expire(bucket, 120)
        if count > limit:
            raise ValueError("Metadata rate limit exceeded")
    sealed, _ = await encryption.encrypt_with_user_key(json.dumps(data), await _vault(cache, directus, user_id))
    if not sealed:
        raise RuntimeError("Metadata envelope unavailable")
    if not await client.set(dedupe, value["request_id"], ex=TTL, nx=True):
        previous = await client.get(dedupe)
        return previous.decode() if isinstance(previous, bytes) else previous
    # A following call can start while the previous call's accepted metadata is
    # still running. Its newer snapshot owns the chat-level result from here.
    await client.set(key("latest", user_id, value["chat_id"]), value["request_id"], ex=TTL)
    from backend.core.api.app.tasks.celery_config import app
    try:
        app.send_task(TASK, kwargs={"request_id": value["request_id"], "user_id": user_id, "ciphertext": sealed},
                      queue="app_ai", task_id=value["request_id"], expires=300, retry=False)
    except Exception:
        await client.delete(dedupe)
        raise
    return value["request_id"]


async def publish_result(*, cache: Any, directus: Any, encryption: Any, data: dict, result: dict) -> None:
    receipt = {name: value for name, value in data.items() if name not in {"context", "current_title", "current_summary"}}
    receipt["result"] = result
    sealed, _ = await encryption.encrypt_with_user_key(json.dumps(receipt), await _vault(cache, directus, data["user_id"]))
    if not sealed:
        raise RuntimeError("Metadata receipt unavailable")
    client = await _client(cache)
    await client.set(key("result", data["user_id"], data["request_id"]), sealed, ex=TTL)
    pending = key("pending", data["user_id"])
    await client.sadd(pending, data["request_id"])
    await client.expire(pending, TTL)
    await cache.publish_event(f"user_cache_events:{data['user_id']}", {
        "event_type": "voice_metadata_available", "payload": {"request_id": data["request_id"]}})


async def send_pending(*, manager: Any, cache_service: Any, directus_service: Any, encryption_service: Any,
                       user_id: str, user_id_hash: str, device_fingerprint_hash: str,
                       request_id: str | None = None) -> None:
    client = await _client(cache_service)
    ids = [request_id] if request_id else list(await client.smembers(key("pending", user_id)))[:128]
    for request_id in ids:
        request_id = request_id.decode() if isinstance(request_id, bytes) else request_id
        try:
            receipt = await load(cache=cache_service, directus=directus_service, encryption=encryption_service,
                user_id=user_id, user_hash=user_id_hash, request_id=request_id)
            if not receipt:
                await client.srem(key("pending", user_id), request_id)
                continue
            await manager.send_personal_message({"type": "voice_metadata_completed", "payload": {
                name: receipt[name] for name in ("request_id", "call_id", "chat_id", "source_messages",
                    "source_title_v", "source_metadata_v", "encrypted_chat_key", "result")}}, user_id, device_fingerprint_hash)
        except ValueError:
            await client.srem(key("pending", user_id), request_id)


async def commit(*, cache: Any, directus: Any, encryption: Any, user_id: str, user_hash: str, payload: dict) -> dict:
    """Apply client ciphertext only while exact source/key/metadata baselines hold."""
    if set(payload) != {"request_id", "encrypted_metadata"} or not isinstance(payload["request_id"], str):
        raise ValueError("Invalid metadata commit")
    receipt = await load(cache=cache, directus=directus, encryption=encryption, user_id=user_id,
                         user_hash=user_hash, request_id=payload["request_id"])
    if not receipt:
        raise ValueError("Metadata receipt unavailable")
    async with mutation_lock(cache, user_id, receipt["chat_id"]):
        return await _commit(cache=cache, directus=directus, encryption=encryption,
            user_id=user_id, user_hash=user_hash, payload=payload, receipt=receipt)


async def _commit(*, cache: Any, directus: Any, encryption: Any, user_id: str,
                  user_hash: str, payload: dict, receipt: dict) -> dict:
    client = await _client(cache)
    committed = await client.get(key("committed", user_id, payload["request_id"]))
    if committed:
        return json.loads(committed)
    fields = payload["encrypted_metadata"]
    if (not isinstance(fields, dict) or set(fields) - {"encrypted_title", "encrypted_chat_summary"}
            or any(not isinstance(value, str) or not value or len(value) > 4096 for value in fields.values())):
        raise ValueError("Invalid encrypted metadata")
    from backend.core.api.app.services.directus.chat_methods import _validate_client_encrypted_message_content
    for value in fields.values():
        _validate_client_encrypted_message_content(payload["request_id"], value)
    result = receipt["result"]
    allowed = {"encrypted_title"} if result.get("updated_chat_title") else set()
    if result.get("chat_summary"):
        allowed.add("encrypted_chat_summary")
    if set(fields) - allowed:
        raise ValueError("Metadata commit field mismatch")
    chat = await directus.chat.get_chat_metadata(receipt["chat_id"], admin_required=True)
    cached = await cache.get_chat_versions(user_id, receipt["chat_id"])
    current_meta = max(int(chat.get("metadata_v") or 0), int(chat.get("title_v") or 0),
                       int(getattr(cached, "metadata_v", 0) or 0), int(getattr(cached, "title_v", 0) or 0))
    accepted = dict(fields)
    latest = await client.get(key("latest", user_id, receipt["chat_id"]))
    latest = latest.decode() if isinstance(latest, bytes) else latest
    if latest != payload["request_id"]:
        accepted = {}
    # Ordinary text admission establishes a newer conversation turn before its
    # optional postprocessing completes. Let that turn win even if its metadata
    # version has not advanced yet; ongoing voice transcript saves alone do not
    # invalidate the early title for a still-active call.
    newer_text = await directus.get_items("chat_turn_preflights", params={
        "filter[chat_id][_eq]": receipt["chat_id"], "filter[hashed_user_id][_eq]": user_hash,
        "filter[committed_messages_v][_gt]": receipt["source_messages_v"],
        "filter[deletion_invalidated_at][_null]": True, "fields": "id", "limit": 1,
    }, admin_required=True, raise_on_error=True)
    if (chat.get("encrypted_chat_key") != receipt["encrypted_chat_key"]
            or newer_text or not await source_rows(directus, receipt)):
        accepted = {}
    if current_meta != receipt["source_metadata_v"]:
        accepted = {}
    if chat.get("title_is_manual") or chat.get("encrypted_title") != receipt["baseline_title"] or int(chat.get("title_v") or 0) != receipt["source_title_v"]:
        accepted.pop("encrypted_title", None)
    if chat.get("encrypted_chat_summary") != receipt["baseline_summary"]:
        accepted.pop("encrypted_chat_summary", None)
    versions = {"title_v": int(chat.get("title_v") or 0), "metadata_v": int(chat.get("metadata_v") or 0)}
    if accepted:
        versions = {"title_v": versions["title_v"] + int("encrypted_title" in accepted), "metadata_v": current_meta + 1}
        saved = await directus.update_item_if_version("chats", receipt["chat_id"], {
            **accepted, **versions, "updated_at": int(time.time())}, int(chat.get("metadata_v") or 0),
            version_field="metadata_v", owner_hash_field="hashed_user_id", owner_hash=user_hash,
            extra_filters={"title_v": chat.get("title_v"), "messages_v": chat.get("messages_v"),
                           "encrypted_chat_key": receipt["encrypted_chat_key"],
                           "encrypted_chat_summary": chat.get("encrypted_chat_summary"),
                           "encrypted_title": chat.get("encrypted_title"),
                           **({"title_is_manual": chat.get("title_is_manual")} if "encrypted_title" in accepted else {})},
            admin_required=True)
        if not saved:
            raise RuntimeError("Metadata commit changed concurrently")
        await cache.delete_chat_list_item_data(user_id, receipt["chat_id"])
        for name, value in versions.items():
            await cache.set_chat_version_component(user_id, receipt["chat_id"], name, value)
    response = {"request_id": payload["request_id"], "chat_id": receipt["chat_id"], "versions": versions,
                "encrypted_metadata": accepted, "superseded": bool(fields) and not accepted}
    await client.set(key("committed", user_id, payload["request_id"]), json.dumps(response), ex=TTL)
    await client.srem(key("pending", user_id), payload["request_id"])
    return response
