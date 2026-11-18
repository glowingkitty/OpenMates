"""Device-claimed orchestration jobs for chats that spawn and coordinate main chats.

Access model: internal service used by the AI pipeline and first-party WebSocket
handlers only. Chat keys stay on the user's devices, so every client-side effect
(start a chat, store a creator event, read a chat, send a message) is a job that
exactly one capable online device claims (SET NX, like memory write jobs). Job
payloads and results are Vault-encrypted in Redis (24 h TTL); pending start_chat
and creator_event jobs are re-offered when a capable device connects.
Contract: docs/plans/chat-orchestration-main-chats/plan.yml (protocol).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

from backend.shared.python_utils.chat_orchestration_spawns import (
    CAPABILITY,
    ERROR_CODES,
    JobOutcome,
    OrchestrationError,
    count_unfinished_spawned,
    creator_chain_depth,
    get_creator_chat_id,
    get_spawn_state,
    hash_user,
    is_user_active,
    key,
    link_spawned_chat,
    list_spawned,
    mark_user_active,
    redis_client,
    seal,
    set_add,
    set_members,
    set_remove,
    set_spawn_state,
    unseal,
)

__all__ = [
    "CAPABILITY", "JOB_KINDS", "EVENT_ACTIONS", "OrchestrationError", "JobOutcome", "enqueue_job",
    "event_message_id", "emit_creator_event", "record_main_chat_spawn", "get_creator_chat_id",
    "link_spawned_chat", "list_spawned", "count_unfinished_spawned", "creator_chain_depth",
    "set_spawn_state", "get_spawn_state", "mark_user_active", "is_user_active",
    "build_offer", "list_pending_offers", "claim_job", "record_job_result", "get_job_record",
    "is_creator_sent", "verified_creator_link", "classify_chat_message", "ERROR_CODES",
]

logger = logging.getLogger(__name__)

JOB_KINDS = ("start_chat", "creator_event", "read_chat", "send_message")
EVENT_ACTIONS = ("started", "report", "finished", "waiting_for_user", "user_wrote", "sent", "reported")
PENDING_KINDS = ("start_chat", "creator_event")
JOB_TTL_SECONDS = 24 * 3600
STALE_CLAIM_SECONDS = 120
POLL_SECONDS = 0.1
JOB_AVAILABLE_EVENT = "chat_orchestration_job_available"
OFFER_CHANNEL_PREFIX = "chat_stream::orchestration:"
EXPIRED_CLAIM = {"by": "expired"}
MAIN_CHAT_SPAWN_LIMIT_PER_TURN = 5


def _claimant(device_hash: str) -> dict[str, Any]:
    return {"by": f"device:{device_hash}", "at": int(time.time())}


async def _set_once(cache_service: Any, name: str, value: Any) -> bool:
    client = await redis_client(cache_service)
    return bool(await client.set(name, json.dumps(value), nx=True, ex=JOB_TTL_SECONDS))


async def _wait_for(cache_service: Any, name: str, timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = await cache_service.get(name)
        if value is not None or time.monotonic() >= deadline:
            return value
        await asyncio.sleep(POLL_SECONDS)


def _job_key(user_id: str, job_id: str, part: str = "") -> str:
    return key("job", user_id, job_id, *([part] if part else []))


async def get_job_record(*, cache_service: Any, user_id: str, job_id: str) -> Optional[dict[str, Any]]:
    """Plaintext job metadata (ids only); the payload stays sealed."""
    record = await cache_service.get(_job_key(user_id, job_id)) if isinstance(job_id, str) else None
    return record if isinstance(record, dict) else None


async def enqueue_job(*, cache_service: Any, encryption_service: Any, user_id: str, kind: str,
                      payload: dict[str, Any], wait_claim_s: float = 0.0,
                      wait_result_s: float = 0.0) -> JobOutcome:
    """Store a job, offer it to capable devices and optionally wait for claim/result."""
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown orchestration job kind: {kind}")
    job_id, now = str(uuid.uuid4()), int(time.time())
    record = {
        "job_id": job_id, "kind": kind, "created_at": now, "expires_at": now + JOB_TTL_SECONDS,
        "spawned_chat_id": payload.get("spawned_chat_id"), "creator_chat_id": payload.get("creator_chat_id"),
        "origin_hop": int(payload.get("origin_hop") or 0),
        "payload": await seal(cache_service, encryption_service, user_id, payload),
    }
    if not await cache_service.set(_job_key(user_id, job_id), record, ttl=JOB_TTL_SECONDS):
        raise OrchestrationError("job_failed", "cache unavailable")
    if kind == "start_chat":
        await link_spawned_chat(cache_service=cache_service, user_id=user_id,
                                creator_chat_id=payload["creator_chat_id"],
                                spawned_chat_id=payload["spawned_chat_id"], title=payload.get("title"),
                                encryption_service=encryption_service)
        await set_spawn_state(cache_service=cache_service, encryption_service=encryption_service,
                              user_id=user_id, spawned_chat_id=payload["spawned_chat_id"], state="starting")
    if kind in PENDING_KINDS:
        await set_add(cache_service, key("pending", user_id), job_id, JOB_TTL_SECONDS)
    await cache_service.publish_event(f"{OFFER_CHANNEL_PREFIX}{user_id}", {
        "type": JOB_AVAILABLE_EVENT, "user_id_uuid": user_id, "user_id_hash": hash_user(user_id),
        "chat_id": payload.get("creator_chat_id") or "", "message_id": job_id, "job_id": job_id,
    })
    logger.info("[CHAT_ORCH] enqueued job=%s kind=%s", job_id, kind)
    if wait_claim_s <= 0 and wait_result_s <= 0:
        return JobOutcome(job_id, "pending", None, None)
    claim = await _wait_for(cache_service, _job_key(user_id, job_id, "claim"), wait_claim_s)
    if claim is None:
        if kind in PENDING_KINDS:
            return JobOutcome(job_id, "pending", None, None)
        if await _set_once(cache_service, _job_key(user_id, job_id, "claim"), EXPIRED_CLAIM):
            logger.info("[CHAT_ORCH] job=%s not claimed, expired", job_id)
            return JobOutcome(job_id, "expired", None, "device_offline")
    return await _outcome_after_claim(cache_service, encryption_service, user_id, job_id, kind, wait_result_s)


async def _outcome_after_claim(cache_service: Any, encryption_service: Any, user_id: str, job_id: str,
                               kind: str, wait_result_s: float) -> JobOutcome:
    result = await _wait_for(cache_service, _job_key(user_id, job_id, "result"), wait_result_s)
    if not isinstance(result, dict):
        if kind in PENDING_KINDS:
            return JobOutcome(job_id, "pending", None, None)
        return JobOutcome(job_id, "expired", None, "job_expired")
    if not result.get("ok"):
        return JobOutcome(job_id, "failed", None, result.get("error_code") or "job_failed")
    sealed = result.get("result")
    body = await unseal(cache_service, encryption_service, user_id, sealed) if sealed else None
    return JobOutcome(job_id, "done", body, None)


async def build_offer(*, cache_service: Any, encryption_service: Any, user_id: str,
                      job_id: str) -> Optional[dict[str, Any]]:
    """The ``chat_orchestration_job_available`` payload, or None when not offerable (claimed/expired)."""
    record = await get_job_record(cache_service=cache_service, user_id=user_id, job_id=job_id)
    if record is None or record.get("expires_at", 0) <= time.time():
        return None
    claim = await cache_service.get(_job_key(user_id, job_id, "claim"))
    if isinstance(claim, dict):
        stale = (claim.get("by") != "expired" and record["kind"] in PENDING_KINDS
                 and time.time() - claim.get("at", 0) > STALE_CLAIM_SECONDS
                 and await cache_service.get(_job_key(user_id, job_id, "result")) is None)
        if not stale:
            return None
        await cache_service.delete(_job_key(user_id, job_id, "claim"))
    payload = await unseal(cache_service, encryption_service, user_id, record["payload"])
    return {"job_id": job_id, "kind": record["kind"], "payload": payload,
            "created_at": record["created_at"], "expires_at": record["expires_at"]}


async def list_pending_offers(*, cache_service: Any, encryption_service: Any,
                              user_id: str) -> list[dict[str, Any]]:
    """Unclaimed start_chat/creator_event jobs, oldest first, for re-offer on connect."""
    offers = []
    for job_id in await set_members(cache_service, key("pending", user_id)):
        offer = await build_offer(cache_service=cache_service, encryption_service=encryption_service,
                                  user_id=user_id, job_id=job_id)
        if offer is None:
            record = await get_job_record(cache_service=cache_service, user_id=user_id, job_id=job_id)
            if record is None or record.get("expires_at", 0) <= time.time():
                await set_remove(cache_service, key("pending", user_id), job_id)
            continue
        offers.append(offer)
    return sorted(offers, key=lambda offer: offer["created_at"])


async def claim_job(*, cache_service: Any, user_id: str, device_hash: str,
                    job_id: Any) -> tuple[bool, str]:
    """First capable device wins; an expired or already claimed job cannot be claimed."""
    record = await get_job_record(cache_service=cache_service, user_id=user_id, job_id=job_id)
    if record is None:
        return False, "not_found"
    if record.get("expires_at", 0) <= time.time():
        return False, "job_expired"
    name = _job_key(user_id, job_id, "claim")
    if await _set_once(cache_service, name, _claimant(device_hash)):
        return True, "granted"
    existing = await cache_service.get(name)
    return False, "job_expired" if isinstance(existing, dict) and existing.get("by") == "expired" else "already_claimed"


async def record_job_result(*, cache_service: Any, encryption_service: Any, user_id: str, device_hash: str,
                            job_id: Any, ok: Any, error_code: Any = None,
                            result: Any = None) -> tuple[bool, str]:
    """Accept one outcome, only from the claiming device. Results are sealed; start_chat ok sets working."""
    record = await get_job_record(cache_service=cache_service, user_id=user_id, job_id=job_id)
    if record is None:
        return False, "not_found"
    claim = await cache_service.get(_job_key(user_id, job_id, "claim"))
    if not isinstance(claim, dict) or claim.get("by") != f"device:{device_hash}":
        return False, "not_claimed_by_device"
    if not isinstance(ok, bool) or (error_code is not None and error_code not in ERROR_CODES) \
            or (result is not None and not isinstance(result, dict)):
        return False, "invalid_result"
    stored = {"ok": ok, "error_code": None if ok else (error_code or "job_failed"),
              "result": await seal(cache_service, encryption_service, user_id, result) if result else None}
    if not await _set_once(cache_service, _job_key(user_id, job_id, "result"), stored):
        return False, "already_reported"
    await set_remove(cache_service, key("pending", user_id), job_id)
    if record["kind"] == "start_chat" and record.get("spawned_chat_id"):
        await set_spawn_state(cache_service=cache_service, encryption_service=encryption_service,
                              user_id=user_id, spawned_chat_id=record["spawned_chat_id"],
                              state="working" if ok else "failed")
    logger.info("[CHAT_ORCH] result job=%s kind=%s ok=%s", job_id, record["kind"], ok)
    if ok and record["kind"] == "creator_event":
        from backend.shared.python_utils.chat_orchestration_interpretation import queue_event
        try:
            event_payload = await unseal(cache_service, encryption_service, user_id, record["payload"])
            await queue_event(cache_service=cache_service, encryption_service=encryption_service,
                              user_id=user_id, payload=event_payload)
        except (OrchestrationError, RuntimeError, ConnectionError, ValueError) as exc:
            # The event is stored in the creator chat either way; only its automatic
            # interpretation is skipped, which the creator can still ask about.
            logger.warning("[CHAT_ORCH] interpretation not queued job=%s category=%s", job_id, type(exc).__name__)
    return True, "accepted"


async def is_creator_sent(*, cache_service: Any, user_id: str, spawned_chat_id: str, job_id: Any) -> bool:
    """True when job_id is a claimed start_chat/send_message job for this spawned chat."""
    record = await get_job_record(cache_service=cache_service, user_id=user_id, job_id=job_id)
    if record is None or record.get("kind") not in ("start_chat", "send_message") \
            or record.get("spawned_chat_id") != spawned_chat_id:
        return False
    return isinstance(await cache_service.get(_job_key(user_id, job_id, "claim")), dict)


async def verified_creator_link(*, cache_service: Any, user_id: str, chat_id: str,
                                creator_chat_id: Any, job_id: Any) -> bool:
    """True only for a start_chat job of this user that spawned this chat for this creator."""
    record = await get_job_record(cache_service=cache_service, user_id=user_id, job_id=job_id)
    return bool(record and record.get("kind") == "start_chat" and record.get("spawned_chat_id") == chat_id
                and isinstance(creator_chat_id, str) and record.get("creator_chat_id") == creator_chat_id)


def client_orchestration_job_id(payload: Any, message_payload: Any) -> Optional[str]:
    """Job id a client attached to a chat message: inside the message (web, CLI), else on the envelope."""
    for source in (message_payload, payload):
        job_id = source.get("orchestration_job_id") if isinstance(source, dict) else None
        if isinstance(job_id, str) and job_id:
            return job_id
    return None


async def classify_chat_message(*, cache_service: Any, encryption_service: Any, user_id: str, chat_id: str,
                                message_id: str, job_id: Any,
                                creator_chat_id: Optional[str] = None) -> Optional[str]:
    """Classify a message arriving in a possibly spawned chat; returns the creator chat id or None.

    Creator-sent (claimed start_chat/send_message job id) sets state working. Anything else in a
    linked chat is user-typed: user_active guard for ten minutes plus a user_wrote creator event.
    """
    if not creator_chat_id:
        link = await cache_service.get(key("link", chat_id))
        creator_chat_id = link.get("creator_chat_id") if isinstance(link, dict) else None
    if not creator_chat_id:
        return None
    if await is_creator_sent(cache_service=cache_service, user_id=user_id, spawned_chat_id=chat_id, job_id=job_id):
        await set_spawn_state(cache_service=cache_service, encryption_service=encryption_service,
                              user_id=user_id, spawned_chat_id=chat_id, state="working")
        return creator_chat_id
    await mark_user_active(cache_service=cache_service, spawned_chat_id=chat_id)
    await set_spawn_state(cache_service=cache_service, encryption_service=encryption_service,
                          user_id=user_id, spawned_chat_id=chat_id, state="user_active")
    await emit_creator_event(cache_service=cache_service, encryption_service=encryption_service,
                             user_id=user_id, creator_chat_id=creator_chat_id, spawned_chat_id=chat_id,
                             action="user_wrote", discriminator=message_id)
    return creator_chat_id


def event_message_id(creator_chat_id: str, spawned_chat_id: str, action: str, discriminator: Any) -> str:
    """Deterministic id so a re-offered or repeated event is stored once."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "openmates:chat-orchestration-event:"
                          f"{creator_chat_id}:{spawned_chat_id}:{action}:{discriminator or ''}"))


async def emit_creator_event(*, cache_service: Any, encryption_service: Any, user_id: str,
                             creator_chat_id: str, spawned_chat_id: str, action: str,
                             text: Optional[str] = None, discriminator: Optional[str] = None) -> JobOutcome:
    """Queue a creator_event job (no waiting); the device stores it in the creator chat."""
    if action not in EVENT_ACTIONS:
        raise ValueError(f"unknown creator event action: {action}")
    state = await get_spawn_state(cache_service=cache_service, encryption_service=encryption_service,
                                  user_id=user_id, spawned_chat_id=spawned_chat_id)
    payload: dict[str, Any] = {
        "creator_chat_id": creator_chat_id, "spawned_chat_id": spawned_chat_id, "action": action,
        "event_message_id": event_message_id(creator_chat_id, spawned_chat_id, action, discriminator),
        "created_at": int(time.time()),
    }
    if state and state.get("title"):
        payload["title"] = state["title"]
    if text:
        payload["text"] = text
    return await enqueue_job(cache_service=cache_service, encryption_service=encryption_service,
                             user_id=user_id, kind="creator_event", payload=payload)


async def record_main_chat_spawn(*, user_id: str, creator_chat_id: str, creator_message_id: str,
                                 spawned_chat_ids: list[str], directus_service: Any = None) -> None:
    """Persist the orchestration root and main_chat child rows for one creator turn (no chat rows)."""
    from backend.core.api.app.services.sub_chat_orchestration_service import (
        SubChatOrchestrationProtocolError,
        SubChatOrchestrationService,
    )
    if directus_service is None:
        from backend.core.api.app.services.directus import DirectusService
        directus_service = DirectusService()
    internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not internal_token:
        raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for orchestration records")
    owner_hash = hash_user(user_id)
    orchestration_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "openmates:main-chat-orchestration:"
                                      f"{owner_hash}:{creator_chat_id}:{creator_message_id}"))
    turn_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:main-chat-turn:{creator_chat_id}:{creator_message_id}"))
    batch_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:main-chat-batch:{orchestration_id}:"
                              + ":".join(sorted(spawned_chat_ids))))
    service = SubChatOrchestrationService(directus_service)
    try:
        await service.execute("create_root", {
            "protocol_version": 1, "orchestration_id": orchestration_id, "hashed_user_id": owner_hash,
            "root_chat_id": creator_chat_id, "root_turn_id": turn_id, "spawn_kind": "main_chat",
            "descendant_limit": MAIN_CHAT_SPAWN_LIMIT_PER_TURN,
        })
        await service.execute("prepare_batch", {
            "protocol_version": 1, "orchestration_id": orchestration_id, "hashed_user_id": owner_hash,
            "batch_id": batch_id, "parent_chat_id": creator_chat_id, "parent_depth": 0,
            "is_continuation": False,
            "children": [{
                "child_chat_id": chat_id, "user_message_id": creator_message_id, "spawn_kind": "main_chat",
                "dispatch_token": hmac.new(internal_token.encode("utf-8"), f"{orchestration_id}:{chat_id}".encode("utf-8"),
                                           hashlib.sha256).hexdigest(),
            } for chat_id in spawned_chat_ids],
        })
    except SubChatOrchestrationProtocolError as exc:
        if exc.code == "descendant_limit_exceeded":
            raise OrchestrationError("spawn_limit_reached") from exc
        if exc.code == "orchestration_root_is_sub_chat":
            raise OrchestrationError("not_eligible") from exc
        raise OrchestrationError("job_failed", exc.code) from exc
