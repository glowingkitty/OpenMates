"""Warm saved Workflow metadata after an authenticated composer focus.

The hint carries only owner/Team scope and optional trace context, never draft
text. It rechecks Team access, bounds repeated work, and only populates the
encrypted shared cache used by normal Workflow discovery. Authenticated use
renews two-hour retention; current versions and permissions are never cached
as an execution grant.
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
    WORKFLOW_METADATA_TTL_SECONDS, _cached_workflow_metadata,
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
    await warm_encrypted_discovery_indices(
        cache_service=cache_service, directus_service=directus_service,
        user_id=user_id, team_id=team_id,
    )
    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not vault_key_id:
        return "unavailable"
    key = await _versioned_workflow_metadata_key(cache_service, user_id, team_id, vault_key_id)
    async def readable_metadata() -> bool:
        try:
            return await _cached_workflow_metadata(cache_service, key, vault_key_id) is not None
        except Exception:
            return False

    if await readable_metadata() and key == await _versioned_workflow_metadata_key(
        cache_service, user_id, team_id, vault_key_id,
    ):
        await client.expire(key, WORKFLOW_METADATA_TTL_SECONDS)
        return "ready"
    lock_key = f"{key}:warming"
    lock_token = uuid.uuid4().hex
    if not client or not await client.set(lock_key, lock_token, ex=60, nx=True):
        return "in_progress"
    try:
        await discover_workflow_metadata(
            SimpleNamespace(user_id=user_id, team_id=team_id, is_external=False,
                            is_incognito=False, is_anonymous=False), cache_service)
        # Discovery can fail closed without raising. A leftover unreadable cache
        # entry must never make a warm-up look successful.
        current_key = await _versioned_workflow_metadata_key(cache_service, user_id, team_id, vault_key_id)
        if current_key != key:
            return "unavailable"
        return "ready" if await readable_metadata() else "unavailable"
    finally:
        await client.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                          1, lock_key, lock_token)


async def warm_encrypted_discovery_indices(
    *, cache_service: Any, directus_service: Any, user_id: str, team_id: str | None,
    project_id: str | None = None,
) -> None:
    """Best-effort metadata warm-up after caller has authenticated scope."""
    # Prepare encrypted summaries and opaque keys. Failures cannot block Send.
    try:
        from backend.core.api.app.services.encrypted_discovery_index import (
            list_encrypted_project_discovery, list_project_focus_discovery,
            list_team_memory_key_discovery,
        )
        projects = await list_encrypted_project_discovery(
            cache=cache_service, directus=directus_service, user_id=user_id, team_id=team_id,
        )
        # Bound speculative Focus metadata reads to the three most relevant
        # Projects. Each remains fresh owner/Team scoped and contains no body.
        project_ids = [project_id] if project_id else [
            project.get("project_id") for project in projects[:3] if isinstance(project, dict)
        ]
        for selected_project_id in project_ids:
            if isinstance(selected_project_id, str):
                try:
                    await list_project_focus_discovery(
                        cache=cache_service, directus=directus_service, user_id=user_id,
                        team_id=team_id, project_id=selected_project_id,
                    )
                except Exception:
                    pass
    except Exception:
        pass
    if team_id:
        try:
            from backend.core.api.app.services.encrypted_discovery_index import list_team_memory_key_discovery
            await list_team_memory_key_discovery(
                cache=cache_service, directus=directus_service, user_id=user_id, team_id=team_id,
            )
        except Exception:
            pass


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
