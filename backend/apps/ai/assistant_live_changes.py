# backend/apps/ai/assistant_live_changes.py
"""Assistant edits of live-capable embeds, delivered as changes instead of writes.

With the `feature_flags.live_collaboration` backend flag on, an assistant diff
for a document, sheet or slide deck is not written as `current_version + 1` on
the server. The requester's devices get `embed_assistant_editing` (presence)
and `embed_assistant_change` (the change set against `base_version`); the
client core merges it. The change text travels on the same per-user channel
(`websocket:user:{hash}`) and in the same form as `send_embed_data` content
today; while no device is online it waits, sealed with the user's vault key,
in a 24 h cache entry. The client reports the result back through
`POST /v1/embeds/{embed_id}/assistant-change-outcome`.

Spec: docs/plans/live-collaboration-crdt/build-contract.md section 4.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LIVE_COLLABORATION_FLAG = "live_collaboration"
LIVE_EMBED_TYPES = frozenset({"document", "sheet", "deck", "code"})
PENDING_TTL_SECONDS = 24 * 60 * 60
OUTCOME_WAIT_SECONDS = 20.0
OUTCOME_POLL_SECONDS = 0.25
OUTCOMES = frozenset({"applied", "same_spot", "target_deleted", "needs_recheck"})
# needs_recheck is the only outcome that a later report may still replace.
_TERMINAL_OUTCOMES = frozenset({"applied", "same_spot", "target_deleted"})


def live_collaboration_enabled(config_manager: Any) -> bool:
    """Return the global `feature_flags.live_collaboration` switch (off when unset)."""
    if config_manager is None:
        return False
    try:
        config = config_manager.get_backend_config() or {}
    except AttributeError:
        return False
    return (config.get("feature_flags") or {}).get(LIVE_COLLABORATION_FLAG) is True


def is_live_embed_type(embed_type: Optional[str]) -> bool:
    return embed_type in LIVE_EMBED_TYPES


def hunk_scope(parsed_diff: Any) -> List[str]:
    """Hunk headers of a parsed unified diff: the part of the embed the edit touches."""
    return [
        f"@@ -{h.old_start},{h.old_count} +{h.new_start},{h.new_count} @@"
        for h in getattr(parsed_diff, "hunks", [])
    ]


HEAD_VERSION_TTL_SECONDS = 24 * 60 * 60
# Atomic compare-and-set of the embed head version: absent key = the caller's
# expected version (the head the assistant read); mismatch -> 0, nothing written.
_CAS_SCRIPT = """
local cur = redis.call('GET', KEYS[1])
if not cur then cur = ARGV[1] end
if tonumber(cur) ~= tonumber(ARGV[1]) then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""


def _head_version_key(embed_id: str) -> str:
    return f"embed_head_version:{embed_id}"


async def claim_embed_version(cache_service: Any, embed_id: str, expected_version: int, new_version: int) -> bool:
    """Server-side compare-and-set of an embed's head version.

    True when the head was still `expected_version` and is now `new_version`;
    False when another writer (human revision or assistant) got there first,
    which turns the assistant edit into a suggestion card. Atomic in Redis, so a
    version bump between the assistant's read and its write cannot be lost.
    """
    client = await cache_service.client
    if not client:
        raise RuntimeError("Redis unavailable: embed version cannot be claimed")
    claimed = await client.eval(
        _CAS_SCRIPT, 1, _head_version_key(embed_id), expected_version, new_version, HEAD_VERSION_TTL_SECONDS,
    )
    return int(claimed) == 1


async def record_committed_embed_version(cache_service: Any, embed_id: str, version: int) -> None:
    """Publish a human-committed head version so a later `claim_embed_version` sees it."""
    client = await cache_service.client
    if client:
        await client.set(_head_version_key(embed_id), version, ex=HEAD_VERSION_TTL_SECONDS)


def _pending_key(user_id_hash: str, embed_id: str, turn_id: str) -> str:
    return f"assistant_live_change:{user_id_hash}:{embed_id}:{turn_id}"


def _pending_index_key(user_id_hash: str) -> str:
    return f"assistant_live_pending:{user_id_hash}"


def _turn_key(embed_id: str, turn_id: str) -> str:
    return f"assistant_live_turn:{embed_id}:{turn_id}"


def _outcome_key(embed_id: str, turn_id: str) -> str:
    return f"assistant_live_outcome:{embed_id}:{turn_id}"


async def _publish(client: Any, user_id: str, user_id_hash: str, event: str, payload: Dict[str, Any]) -> None:
    await client.publish(f"websocket:user:{user_id_hash}", json.dumps({
        "event": event, "type": event, "event_for_client": event,
        "user_id_uuid": user_id, "payload": payload,
    }))


async def emit_assistant_editing(
    cache_service: Any, user_id: str, user_id_hash: str, embed_id: str, scope: List[str], mate_name: str,
) -> bool:
    """Tell the requester's devices the assistant is editing `embed_id` (presence)."""
    client = await cache_service.client
    if not client:
        return False
    await _publish(client, user_id, user_id_hash, "embed_assistant_editing", {
        "embed_id": embed_id, "scope": scope, "mate_name": mate_name,
    })
    return True


async def _requester_online(cache_service: Any, user_id: str, chat_id: str) -> bool:
    from backend.core.api.app.services.notification_presence import has_active_human
    return await has_active_human(cache_service, user_id, chat_id)


async def deliver_assistant_change(
    *, cache_service: Any, encryption_service: Any, user_id: str, user_id_hash: str,
    chat_id: str, user_vault_key_id: str, embed_id: str, turn_id: str, base_version: int,
    new_text_form: str, mate_name: str, scope: List[str],
) -> str:
    """Send the change to the requester, or park it in the 24 h vault cache.

    Returns "sent" or "pending". The turn owner is recorded either way so only
    the requester may report the outcome.
    """
    client = await cache_service.client
    if not client:
        raise RuntimeError("Redis unavailable: assistant change cannot be delivered")
    payload = {
        "embed_id": embed_id, "turn_id": turn_id, "base_version": base_version,
        "new_text_form": new_text_form, "mate_name": mate_name, "scope": scope,
    }
    await client.set(_turn_key(embed_id, turn_id), user_id_hash, ex=PENDING_TTL_SECONDS)
    await client.delete(_outcome_key(embed_id, turn_id))
    if await _requester_online(cache_service, user_id, chat_id):
        await _publish(client, user_id, user_id_hash, "embed_assistant_change", payload)
        return "sent"
    sealed, key_version = await encryption_service.encrypt_with_user_key(json.dumps(payload), user_vault_key_id)
    key = _pending_key(user_id_hash, embed_id, turn_id)
    await client.set(key, json.dumps({"ciphertext": sealed, "key_version": key_version}), ex=PENDING_TTL_SECONDS)
    await client.zadd(_pending_index_key(user_id_hash), {key: time.time() + PENDING_TTL_SECONDS})
    await client.expire(_pending_index_key(user_id_hash), PENDING_TTL_SECONDS)
    return "pending"


async def flush_pending_assistant_changes(
    cache_service: Any, encryption_service: Any, user_id: str, user_id_hash: str, user_vault_key_id: str,
) -> int:
    """Deliver changes parked while no device was online. Call when a device connects.

    Returns the number of `embed_assistant_change` events published.
    """
    client = await cache_service.client
    if not client:
        return 0
    index = _pending_index_key(user_id_hash)
    await client.zremrangebyscore(index, "-inf", time.time())
    sent = 0
    for raw_key in await client.zrange(index, 0, -1):
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        stored = await client.get(key)
        await client.zrem(index, key)
        if not stored:
            continue
        sealed = json.loads(stored)
        plaintext = await encryption_service.decrypt_with_user_key(sealed["ciphertext"], user_vault_key_id)
        await _publish(client, user_id, user_id_hash, "embed_assistant_change", json.loads(plaintext))
        await client.delete(key)
        sent += 1
    return sent


async def record_outcome(
    cache_service: Any, *, user_id_hash: str, embed_id: str, turn_id: str, outcome: str,
    details: Optional[Dict[str, Any]] = None, encryption_service: Any = None,
    user_vault_key_id: Optional[str] = None,
) -> str:
    """Store the client's outcome. Raises PermissionError / LookupError / ValueError.

    State machine: nothing -> any outcome; needs_recheck -> any outcome;
    applied/same_spot/target_deleted are final (an identical repeat is accepted).
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown outcome {outcome!r}")
    client = await cache_service.client
    owner = await client.get(_turn_key(embed_id, turn_id))
    if not owner:
        raise LookupError("Unknown or expired assistant change")
    if (owner.decode() if isinstance(owner, bytes) else owner) != user_id_hash:
        raise PermissionError("Only the requester may report this outcome")
    stored = await client.get(_outcome_key(embed_id, turn_id))
    if stored:
        current = json.loads(stored)["outcome"]
        if current in _TERMINAL_OUTCOMES and current != outcome:
            raise ValueError(f"Outcome already final: {current}")
    sealed_details = None
    if outcome == "same_spot" and details:
        if encryption_service is None or not user_vault_key_id:
            raise ValueError("Assistant outcome details require a user key")
        sealed_details, _ = await encryption_service.encrypt_with_user_key(json.dumps(details), user_vault_key_id)
    await client.set(
        _outcome_key(embed_id, turn_id),
        json.dumps({"outcome": outcome, "sealed_details": sealed_details}), ex=PENDING_TTL_SECONDS,
    )
    return outcome


async def await_outcome(
    cache_service: Any, embed_id: str, turn_id: str, *, timeout: float = OUTCOME_WAIT_SECONDS,
    ignore_outcome: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Wait for the client's outcome; None when it did not arrive in time."""
    client = await cache_service.client
    deadline = time.monotonic() + timeout
    while True:
        stored = await client.get(_outcome_key(embed_id, turn_id))
        if stored:
            result = json.loads(stored)
            if result["outcome"] != ignore_outcome:
                return result
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(OUTCOME_POLL_SECONDS)


async def resolve_outcome_details(
    cache_service: Any, embed_id: str, turn_id: str, encryption_service: Any, user_vault_key_id: str,
) -> tuple[str, Dict[str, Any]]:
    """Like `resolve_outcome`, also returning the client's outcome details.

    For `same_spot` the client may send `details.current_text_form` (the embed's
    text form after the user's live edits) and `details.current_version`; the
    assistant uses them for its single regenerate-once attempt.
    """
    result = await await_outcome(cache_service, embed_id, turn_id)
    if result and result["outcome"] == "needs_recheck":
        result = await await_outcome(cache_service, embed_id, turn_id, ignore_outcome="needs_recheck")
        if result is None:
            return "suggestion_card", {}
    if result is None or result["outcome"] == "applied":
        return "done", {}
    if result["outcome"] == "target_deleted":
        return "dropped_note", {}
    sealed = result.get("sealed_details")
    details = json.loads(await encryption_service.decrypt_with_user_key(sealed, user_vault_key_id)) if sealed else {}
    return "suggestion_card", details


async def resolve_outcome(cache_service: Any, embed_id: str, turn_id: str) -> str:
    """Map the client's outcome to the assistant's next step.

    Returns "done" (applied or no report: the change waits for a device),
    "suggestion_card" (same_spot, or still unresolved after one re-check) or
    "dropped_note" (target_deleted). needs_recheck waits once more.
    """
    result = await await_outcome(cache_service, embed_id, turn_id)
    if result and result["outcome"] == "needs_recheck":
        result = await await_outcome(cache_service, embed_id, turn_id, ignore_outcome="needs_recheck")
        if result is None:
            return "suggestion_card"
    if result is None or result["outcome"] == "applied":
        return "done"
    if result["outcome"] == "target_deleted":
        return "dropped_note"
    return "suggestion_card"
