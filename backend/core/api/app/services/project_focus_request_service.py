"""Transient, explicitly confirmed Project focus selection; never decrypts Projects."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any
from uuid import UUID

from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
)

PROJECT_FOCUS_REQUEST_TTL = 20 * 60
PROJECT_CANDIDATE_LIMIT = 40
PROJECT_FOCUS_PREFIX = "project-"


def explicitly_named_project_focus_ids(text: str, candidates: list[dict[str, str]]) -> list[str]:
    """Offer owned, exact-name routing candidates; never activate or grant access."""
    normalized = " ".join(text.split())
    return [
        PROJECT_FOCUS_PREFIX + candidate["project_id"]
        for candidate in candidates
        if re.search(r"(?<!\w)" + re.escape(candidate["name"]) + r"(?!\w)", normalized, re.IGNORECASE)
    ]


async def validated_project_candidates(
    value: Any, *, directus_service: Any, user_id: str, team_id: str | None,
) -> list[dict[str, str]]:
    """Client-decrypted names are data; DB ownership decides candidate eligibility."""
    if not isinstance(value, list) or not value:
        return []
    if team_id:
        await directus_service.team.require_team_role(team_id, user_id, {"owner", "admin", "member"})
    rows = await directus_service.project.list_projects(user_id, team_id=team_id)
    allowed = {row.get("project_id") for row in rows if not row.get("archived")}
    result = []
    seen = set()
    for candidate in value[:PROJECT_CANDIDATE_LIMIT]:
        if not isinstance(candidate, dict):
            continue
        project_id, name = candidate.get("project_id"), candidate.get("name")
        if project_id not in allowed or project_id in seen or not isinstance(name, str):
            continue
        try:
            UUID(project_id)
        except (ValueError, TypeError, AttributeError):
            continue
        name = " ".join(name.split())[:160]
        if name:
            result.append({"project_id": project_id, "name": name})
            seen.add(project_id)
    return result


class ProjectFocusRequestService:
    def __init__(self, cache_service: Any, directus_service: Any) -> None:
        self.cache = cache_service
        self.authorization = ProjectWriteAuthorizationService(directus_service, cache_service)

    @staticmethod
    def key(user_id: str, chat_id: str) -> str:
        return f"project_focus_request:v1:{hashlib.sha256(user_id.encode()).hexdigest()}:{chat_id}"

    async def require_pending(
        self, *, user_id: str, chat_id: str, request_id: str, project_id: str | None = None,
    ) -> dict[str, Any]:
        from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key

        pending = await self.cache.get(self.key(user_id, chat_id) + ":" + request_id)
        current = await self.cache.get(self.key(user_id, chat_id))
        if (not isinstance(pending, dict) or pending.get("request_id") != request_id
                or not isinstance(current, dict) or current.get("request_id") != request_id
                or pending.get("user_id") != user_id
                or time.time() >= pending.get("expires_at", 0)
                or project_id is not None and pending.get("project_id") != project_id):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_EXPIRED", status_code=409)
        latest = await self.cache.get(async_skill_latest_user_turn_key(user_id, chat_id))
        if latest != pending.get("message_id"):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_STALE", status_code=409)
        await self.authorization._require_chat_access(user_id, chat_id, pending.get("team_id"))
        await self.authorization._require_project_access(
            user_id, pending["project_id"], pending.get("team_id"), write=False,
        )
        return pending

    @staticmethod
    def pending_event(pending: dict[str, Any]) -> dict[str, Any]:
        return {
            "chat_id": pending["chat_id"],
            "focus_id": PROJECT_FOCUS_PREFIX + pending["project_id"],
            "embed_id": pending["request_id"],
            "expires_at": pending["expires_at"],
        }
