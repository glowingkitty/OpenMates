"""Cross-chat write safety for chat orchestration: chats never message each other without a reason.

Spec: chat-orchestration.safety.* in specifications/features/chat-orchestration/specification.yml.

Every assistant turn has an origin, recorded per (user, chat, triggering message id):
- ``user``: the user typed the triggering message (hop 0; also the chat's last user input).
- ``creator``: a linked creator chat sent it (start-chat brief or send-to-spawned-chat);
  hop = the sending turn's hop + 1, carried in the device job record.
- ``automatic``: an interpreting turn started by stored reports or platform events.

Writes to another chat (start-chat, send-to-spawned-chat, report-to-creator) need a
``user`` turn or a ``creator`` turn below MAX_RELAY_HOPS, so every write traces back to
something the user asked for. Automatic turns and turns of unknown origin (fail closed)
never write. On top, a write X -> Y is refused as ping-pong when the latest write between
the two chats was Y -> X and X had no user input since. Only ids and timestamps are
stored here (plaintext Redis keys, 24 h TTL); no chat content.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

from backend.shared.python_utils.chat_orchestration_spawns import hash_user, key, redis_client

ORIGINS = ("user", "creator", "automatic")
WRITE_SKILLS = ("start-chat", "send-to-spawned-chat", "report-to-creator")
MAX_RELAY_HOPS = 3
ORIGIN_TTL_SECONDS = 24 * 3600
REPORT_REPEAT_WINDOW_SECONDS = 3600


def _origin_key(user_id: str, chat_id: str, message_id: str) -> str:
    return key("origin", hash_user(user_id), chat_id, message_id)


def _user_input_key(user_id: str, chat_id: str) -> str:
    return key("user_input", hash_user(user_id), chat_id)


def _edge_key(user_id: str, chat_a: str, chat_b: str) -> str:
    first, second = sorted((chat_a, chat_b))
    return key("edge", hash_user(user_id), first, second)


async def record_turn_origin(*, cache_service: Any, user_id: str, chat_id: str, message_id: str,
                             origin: str, hop: int = 0, sender_chat_id: Optional[str] = None) -> None:
    """Remember why a turn runs; a ``user`` origin also marks the chat's last user input."""
    if origin not in ORIGINS:
        raise ValueError(f"unknown turn origin: {origin}")
    record = {"origin": origin, "hop": int(hop), "sender_chat_id": sender_chat_id, "at": time.time()}
    await cache_service.set(_origin_key(user_id, chat_id, message_id), record, ttl=ORIGIN_TTL_SECONDS)
    if origin == "user":
        await cache_service.set(_user_input_key(user_id, chat_id), {"at": record["at"]}, ttl=ORIGIN_TTL_SECONDS)


async def get_turn_origin(*, cache_service: Any, user_id: str, chat_id: str,
                          message_id: Optional[str]) -> Optional[dict]:
    if not message_id:
        return None
    record = await cache_service.get(_origin_key(user_id, chat_id, message_id))
    return record if isinstance(record, dict) and record.get("origin") in ORIGINS else None


async def record_message_origin(*, cache_service: Any, user_id: str, chat_id: str, message_id: str,
                                job_id: Any) -> dict:
    """Classify an incoming chat message as creator-sent (valid claimed job) or user-typed and record it."""
    from backend.shared.python_utils.chat_orchestration_jobs import get_job_record, is_creator_sent
    if await is_creator_sent(cache_service=cache_service, user_id=user_id, spawned_chat_id=chat_id, job_id=job_id):
        job = await get_job_record(cache_service=cache_service, user_id=user_id, job_id=job_id) or {}
        hop, sender = int(job.get("origin_hop") or 0) + 1, job.get("creator_chat_id")
        await record_turn_origin(cache_service=cache_service, user_id=user_id, chat_id=chat_id,
                                 message_id=message_id, origin="creator", hop=hop, sender_chat_id=sender)
        return {"origin": "creator", "hop": hop, "sender_chat_id": sender}
    await record_turn_origin(cache_service=cache_service, user_id=user_id, chat_id=chat_id,
                             message_id=message_id, origin="user")
    return {"origin": "user", "hop": 0, "sender_chat_id": None}


async def write_refusal(*, cache_service: Any, user_id: str, chat_id: str, message_id: Optional[str],
                        target_chat_id: Optional[str]) -> Optional[tuple[str, str]]:
    """(error_code, message) when this turn may not write to target_chat_id, else None."""
    origin = await get_turn_origin(cache_service=cache_service, user_id=user_id, chat_id=chat_id,
                                   message_id=message_id)
    if origin is None or origin["origin"] == "automatic":
        return ("not_user_requested",
                "Only a message the user sent can make this chat write to another chat. Tell the user "
                "here instead; they can ask for it explicitly.")
    if origin["origin"] == "creator" and origin.get("hop", 0) >= MAX_RELAY_HOPS:
        return ("relay_limit_reached", "This request was already passed on through too many chats.")
    if target_chat_id and await _is_ping_pong(cache_service, user_id, chat_id, target_chat_id):
        return ("ping_pong", "That chat just wrote to this chat; answering it back needs a new user message.")
    return None


async def _is_ping_pong(cache_service: Any, user_id: str, chat_id: str, target_chat_id: str) -> bool:
    edge = await cache_service.get(_edge_key(user_id, chat_id, target_chat_id))
    if not isinstance(edge, dict) or edge.get("from") != target_chat_id:
        return False
    user_input = await cache_service.get(_user_input_key(user_id, chat_id))
    last_input = user_input.get("at", 0) if isinstance(user_input, dict) else 0
    return float(edge.get("at", 0)) >= float(last_input)


async def record_write(*, cache_service: Any, user_id: str, from_chat_id: str, to_chat_id: str) -> None:
    """Remember the latest write between two chats (direction and time) for ping-pong detection."""
    await cache_service.set(_edge_key(user_id, from_chat_id, to_chat_id),
                            {"from": from_chat_id, "at": time.time()}, ttl=ORIGIN_TTL_SECONDS)


async def is_repeated_report(*, cache_service: Any, user_id: str, chat_id: str, text: str) -> bool:
    """True when this chat already reported exactly this text to its creator within the window."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    client = await redis_client(cache_service)
    marker = key("report_seen", hash_user(user_id), chat_id, digest)
    return not await client.set(marker, "1", nx=True, ex=REPORT_REPEAT_WINDOW_SECONDS)


def report_discriminator(message_id: Optional[str], text: str) -> str:
    """Event id part for a report: two different reports in one turn are two events."""
    return f"{message_id or ''}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
