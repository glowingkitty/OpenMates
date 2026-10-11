"""Warm saved Workflow metadata after an authenticated composer focus.

The hint carries only owner/Team scope and optional trace context, never draft
text. It rechecks Team access, bounds repeated work, and only populates the
short-lived encrypted shared cache used by normal Workflow discovery.
Failures leave the authoritative cold discovery path available.
"""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from types import SimpleNamespace
from typing import Any

from backend.apps.ai.processing.context_preselection import (
    _versioned_workflow_metadata_key, discover_workflow_metadata,
)

_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


async def warm_workflow_metadata(
    *, cache_service: Any, directus_service: Any, user_id: str, team_id: str | None,
) -> str:
    """A failed hint has no effect on the normal authoritative cold discovery path."""
    client = await cache_service.client
    if not client:
        return "unavailable"
    rate_key = "workflow:discovery:warmup-rate:" + hashlib.sha256(user_id.encode()).hexdigest()
    count = 1 if await client.set(rate_key, "1", ex=60, nx=True) else await client.incr(rate_key)
    if count > 6:
        return "rate_limited"
    if team_id:
        await directus_service.team.require_team_role(
            team_id, user_id, {"owner", "admin", "member", "viewer"})
    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not vault_key_id:
        return "unavailable"
    key = await _versioned_workflow_metadata_key(cache_service, user_id, team_id, vault_key_id)
    if await cache_service.get(key) is not None:
        return "ready"
    lock_key = f"{key}:warming"
    lock_token = uuid.uuid4().hex
    if not client or not await client.set(lock_key, lock_token, ex=60, nx=True):
        return "in_progress"
    try:
        await discover_workflow_metadata(
            SimpleNamespace(user_id=user_id, team_id=team_id, is_external=False,
                            is_incognito=False, is_anonymous=False), cache_service)
        return "ready" if await cache_service.get(key) is not None else "unavailable"
    finally:
        await client.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                          1, lock_key, lock_token)


def accept_workflow_warmup_request(times: list[float], payload: Any) -> tuple[str, str | None]:
    """Bound each socket to three hints per minute; reject arbitrary payload fields."""
    if not isinstance(payload, dict) or set(payload) - {"team_id", "_traceparent"}:
        return "invalid", None
    traceparent = payload.get("_traceparent")
    if traceparent is not None and (not isinstance(traceparent, str) or not _TRACEPARENT.fullmatch(traceparent)):
        return "invalid", None
    team_id = payload.get("team_id")
    if team_id is not None and (not isinstance(team_id, str) or not 1 <= len(team_id) <= 80):
        return "invalid", None
    now = time.monotonic()
    times[:] = [value for value in times if now - value < 60]
    if len(times) >= 3:
        return "rate_limited", None
    times.append(now)
    return "accepted", team_id
