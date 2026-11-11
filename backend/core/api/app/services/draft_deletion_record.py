"""
Durable per-user record that a draft was deleted (positive delete evidence).

The 30/45-minute draft tombstone in `user:{id}:chat:{chat}:draft` stays as it
is; this separate long-lived key only answers the reconnect stale-draft probe
(`phase2_stale_draft_probe.py`) after that tombstone expired. Absence of a
server draft is never treated as a delete, because replayed or async-persisted
drafts may live only in Redis for a while. Spec: architecture.drafts
(drafts.sync.version-authoritative, drafts.draft-only.lifecycle).
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# 180 days: long enough for a device that stayed closed for months.
DRAFT_DELETION_RECORD_TTL = 180 * 24 * 3600

# Keeps the highest deleted version; an older delete never lowers the record.
_RECORD_MAX_VERSION_LUA = """
local current = tonumber(redis.call('HGET', KEYS[1], 'draft_v') or '0') or 0
local version = tonumber(ARGV[1])
if version > current then
    redis.call('HSET', KEYS[1], 'draft_v', ARGV[1], 'deleted_at', ARGV[2])
end
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""


def draft_deletion_record_key(user_id: str, chat_id: str) -> str:
    """Redis key of the durable delete record of one user's draft in one chat."""
    return f"user:{user_id}:chat:{chat_id}:draft_deleted"


async def record_draft_deletion(cache_service: Any, user_id: str, chat_id: str, draft_version: int) -> bool:
    """Store that this user's draft was deleted at `draft_version`.

    Returns False (logged) when Redis is unavailable. The delete itself has
    already succeeded then; a missing record only means a closed device keeps
    its stale copy, which is the safe direction.
    """
    client = await cache_service.client
    if not client:
        logger.warning("Draft deletion record not written for chat %s: cache unavailable", chat_id)
        return False
    try:
        await client.eval(
            _RECORD_MAX_VERSION_LUA, 1, draft_deletion_record_key(user_id, chat_id),
            int(draft_version), int(time.time()), DRAFT_DELETION_RECORD_TTL,
        )
        return True
    except Exception as exc:  # Any Redis error: keep the completed delete, log the gap.
        logger.warning("Draft deletion record not written for chat %s: %s", chat_id, exc)
        return False


async def clear_draft_deletion_record(cache_service: Any, user_id: str, chat_id: str) -> None:
    """Drop the record once a new draft is saved, so it can never remove that draft."""
    client = await cache_service.client
    if not client:
        logger.warning("Draft deletion record not cleared for chat %s: cache unavailable", chat_id)
        return
    try:
        await client.delete(draft_deletion_record_key(user_id, chat_id))
    except Exception as exc:  # The version check in the probe still protects the new draft.
        logger.warning("Draft deletion record not cleared for chat %s: %s", chat_id, exc)
