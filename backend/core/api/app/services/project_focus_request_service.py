"""Transient cancellable Project focus selection; never decrypts Projects."""

from __future__ import annotations

import hashlib
import asyncio
import json
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
PROJECT_FOCUS_COUNTDOWN_SECONDS = 4


def explicitly_named_project_focus_ids(text: str, candidates: list[dict[str, Any]]) -> list[str]:
    """Plain names are automatic suggestions, never explicit activation intent."""
    normalized = " ".join(text.split())
    return [
        PROJECT_FOCUS_PREFIX + candidate["project_id"]
        for candidate in candidates
        if candidate.get("auto_selection", True) is True
        and re.search(r"(?<!\w)" + re.escape(candidate["name"]) + r"(?!\w)", normalized, re.IGNORECASE)
    ]


async def validated_project_candidates(
    value: Any, *, directus_service: Any, user_id: str, team_id: str | None,
) -> list[dict[str, Any]]:
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
            summary = candidate.get("summary", "")
            result.append({"project_id": project_id, "name": name,
                           "summary": " ".join(summary.split())[:640] if isinstance(summary, str) else ""})
            seen.add(project_id)
    settings_slots = asyncio.Semaphore(8)
    async def load_preference(candidate: dict[str, Any]) -> None:
        async with settings_slots:
            settings = await directus_service.project.get_project_settings(candidate["project_id"], user_id, team_id=team_id)
            candidate["auto_selection"] = not settings or settings.get("auto_selection") is not False
    await asyncio.gather(*(load_preference(candidate) for candidate in result))
    return result


class ProjectFocusRequestService:
    def __init__(self, cache_service: Any, directus_service: Any) -> None:
        self.cache = cache_service
        self.authorization = ProjectWriteAuthorizationService(directus_service, cache_service)

    @staticmethod
    def key(user_id: str, chat_id: str) -> str:
        return f"project_focus_request:v1:{hashlib.sha256(user_id.encode()).hexdigest()}:{chat_id}"

    @staticmethod
    def decision_key(user_id: str, chat_id: str, request_id: str) -> str:
        return ProjectFocusRequestService.key(user_id, chat_id) + ":decision:" + request_id

    async def _eval(self, script: str, keys: list[str], arguments: list[Any]) -> Any:
        try:
            client = await self.cache.client
            if not client:
                raise ValueError("Cache unavailable")
            return await client.eval(script, len(keys), *keys, *arguments)
        except Exception:
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503) from None

    async def write_activation(self, pending: dict[str, Any], binding: dict[str, Any]) -> bool:
        """Serialize the final authority write with cancellation and new turns."""
        from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
        from backend.core.api.app.services.project_write_authorization_service import PROJECT_FOCUS_TTL_SECONDS
        user, chat, request_id = pending["user_id"], pending["chat_id"], pending["request_id"]
        pointer = self.key(user, chat)
        script = """-- PROJECT_FOCUS_ACTIVATE
        local raw=redis.call('GET',KEYS[1]); local current=redis.call('GET',KEYS[2])
        if not raw or not current then return 0 end
        local p=cjson.decode(raw); local c=cjson.decode(current)
        if p.request_id~=ARGV[1] or c.request_id~=ARGV[1] or p.user_id~=ARGV[2]
          or p.chat_id~=ARGV[3] or p.project_id~=ARGV[4] or p.message_id~=ARGV[5]
          or redis.call('GET',KEYS[3])~=ARGV[5] then return 0 end
        local now=tonumber(ARGV[6])
        if not p.activate_at or tonumber(p.activate_at)>now or tonumber(p.expires_at or 0)<=now then return 0 end
        local old=redis.call('GET',KEYS[4]); local old_id=''
        if old then old_id=cjson.decode(old).activation_id or '' end
        if old_id~=(p.expected_base_activation_id or '') then return 0 end
        redis.call('SET',KEYS[4],ARGV[7],'EX',ARGV[8]); return 1
        """
        return bool(await self._eval(script, [pointer + ":" + request_id, pointer,
            async_skill_latest_user_turn_key(user, chat), self.authorization._focus_key(user, chat)],
            [request_id, user, chat, pending["project_id"], pending["message_id"], time.time(),
             json.dumps(binding), PROJECT_FOCUS_TTL_SECONDS]))

    async def activation_is_current(self, *, user_id: str, chat_id: str, binding: dict[str, Any]) -> bool:
        request_id = binding.get("activation_request_id")
        if not request_id:
            current = await self.cache.get(self.authorization._focus_key(user_id, chat_id))
            return isinstance(current, dict) and current.get("activation_id") == binding.get("activation_id")
        from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
        pointer = self.key(user_id, chat_id)
        script = """-- PROJECT_FOCUS_CURRENT
        local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
        local b=cjson.decode(raw); if b.activation_id~=ARGV[1] or b.activation_request_id~=ARGV[2] then return 0 end
        local decision=redis.call('GET',KEYS[2])
        if decision then local d=cjson.decode(decision)
          if d.accepted==true and d.activation_id==ARGV[1] then return 1 else return 0 end end
        local p=redis.call('GET',KEYS[3]); local c=redis.call('GET',KEYS[4]); if not p or not c then return 0 end
        p=cjson.decode(p); c=cjson.decode(c)
        if p.request_id~=ARGV[2] or c.request_id~=ARGV[2] or p.user_id~=ARGV[3] or p.chat_id~=ARGV[4]
          or p.message_id~=redis.call('GET',KEYS[5]) or tonumber(p.expires_at or 0)<=tonumber(ARGV[5]) then return 0 end
        return 1
        """
        try:
            return bool(await self._eval(script, [self.authorization._focus_key(user_id, chat_id),
                self.decision_key(user_id, chat_id, request_id), pointer + ":" + request_id, pointer,
                async_skill_latest_user_turn_key(user_id, chat_id)],
                [binding.get("activation_id") or "", request_id, user_id, chat_id, time.time()]))
        except ProjectWriteAuthorizationError:
            return False

    async def consume_decision(self, *, user_id: str, chat_id: str, request_id: str, accepted: bool) -> dict | None:
        """Consume an exact decision and revoke only its own activation atomically."""
        from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
        from backend.core.api.app.services.project_write_authorization_service import PROJECT_FOCUS_TTL_SECONDS
        pointer = self.key(user_id, chat_id)
        script = """-- PROJECT_FOCUS_DECISION
        local raw=redis.call('GET',KEYS[1]); local current=redis.call('GET',KEYS[2]); if not raw or not current then return nil end
        local p=cjson.decode(raw); local c=cjson.decode(current)
        if p.request_id~=ARGV[1] or c.request_id~=ARGV[1] or p.user_id~=ARGV[2] or p.chat_id~=ARGV[3]
          or p.message_id~=redis.call('GET',KEYS[3]) or tonumber(p.expires_at or 0)<=tonumber(ARGV[4]) then return nil end
        local braw=redis.call('GET',KEYS[4]); local b=nil; if braw then b=cjson.decode(braw) end
        local accepted=ARGV[5]=='true'; local activation=''
        if accepted then
          if not p.activate_at or tonumber(p.activate_at)>tonumber(ARGV[4]) or not b
            or b.activation_request_id~=ARGV[1] or b.project_id~=p.project_id then return nil end
          activation=b.activation_id
        elseif b and b.activation_request_id==ARGV[1] then
          activation=b.activation_id; redis.call('DEL',KEYS[4])
          local specialist=redis.call('GET',KEYS[6])
          if specialist and cjson.decode(specialist).base_activation_id==activation then redis.call('DEL',KEYS[6]) end
        end
        redis.call('SET',KEYS[5],cjson.encode({accepted=accepted,activation_id=activation}),'EX',ARGV[6])
        redis.call('DEL',KEYS[1]); return raw
        """
        raw = await self._eval(script, [pointer + ":" + request_id, pointer,
            async_skill_latest_user_turn_key(user_id, chat_id), self.authorization._focus_key(user_id, chat_id),
            self.decision_key(user_id, chat_id, request_id), self.authorization._specialist_key(user_id, chat_id)],
            [request_id, user_id, chat_id, time.time(), "true" if accepted else "false", PROJECT_FOCUS_TTL_SECONDS])
        return json.loads(raw) if raw else None

    async def create_pending(self, *, user_id: str, chat_id: str, request_id: str,
                             project_id: str, message_id: str, team_id: str | None = None) -> dict[str, Any]:
        """Start the live countdown once; the request TTL is separate from its deadline."""
        now = time.time()
        previous = await self.cache.get(self.authorization._focus_key(user_id, chat_id))
        pending = {"request_id": request_id, "continuation_id": request_id, "user_id": user_id,
                   "chat_id": chat_id, "project_id": project_id, "message_id": message_id,
                   "team_id": team_id, "activate_at": now + PROJECT_FOCUS_COUNTDOWN_SECONDS,
                   "expires_at": now + PROJECT_FOCUS_REQUEST_TTL,
                   "expected_base_activation_id": previous.get("activation_id", "") if isinstance(previous, dict) else ""}
        key = self.key(user_id, chat_id)
        if not await self.cache.set(key + ":" + request_id, pending, ttl=PROJECT_FOCUS_REQUEST_TTL):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503)
        if not await self.cache.set(key, pending, ttl=PROJECT_FOCUS_REQUEST_TTL):
            await self.cache.delete(key + ":" + request_id)
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_CACHE_UNAVAILABLE", status_code=503)
        return pending

    async def require_pending(
        self, *, user_id: str, chat_id: str, request_id: str, project_id: str | None = None,
        require_completed_countdown: bool = False,
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
        project, _ = await self.authorization._require_project_access(
            user_id, pending["project_id"], pending.get("team_id"), write=False,
        )
        if require_completed_countdown:
            settings = await self.authorization.directus_service.project.get_project_settings(
                pending["project_id"], user_id, team_id=pending.get("team_id"),
            )
            if project.get("archived") or settings and settings.get("auto_selection") is False:
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_SELECTION_DISABLED", status_code=409)
            activate_at = pending.get("activate_at")
            if not isinstance(activate_at, (int, float)) or time.time() < activate_at:
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_COUNTDOWN_PENDING", status_code=409)
        return pending

    @staticmethod
    def pending_event(pending: dict[str, Any]) -> dict[str, Any]:
        return {
            "chat_id": pending["chat_id"],
            "focus_id": PROJECT_FOCUS_PREFIX + pending["project_id"],
            "embed_id": pending["request_id"],
            "expires_at": pending["activate_at"],
        }
