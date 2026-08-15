# backend/core/api/app/services/user_task_execution_service.py
#
# Vault-encrypted execution context for user-facing AI Tasks. The durable Task
# row remains client-encrypted; this short-lived context lets a scheduler start a
# capacity-waiting linked-chat Task without storing plaintext instructions or raw
# owner identifiers in Directus task metadata.

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.directus.user_task_methods import hash_id

TASK_EXECUTION_CONTEXT_TTL_SECONDS = 3 * 24 * 60 * 60
AiDispatcher = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]
logger = logging.getLogger(__name__)


class UserTaskExecutionService:
    def __init__(
        self,
        task_methods: Any,
        *,
        encryption_service: Any,
        cache_service: Any | None = None,
        ai_dispatcher: AiDispatcher | None = None,
    ):
        self.task_methods = task_methods
        self.encryption_service = encryption_service
        self.cache_service = cache_service
        self.ai_dispatcher = ai_dispatcher

    async def stage(
        self,
        *,
        task_id: str,
        user_id: str,
        chat_id: str,
        instruction: str,
        current_chat_title: str | None,
        created_at: int,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "task_id": task_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "instruction": instruction,
            "current_chat_title": current_chat_title,
            "created_at": created_at,
            "team_id": team_id,
        }
        encrypted_context, _key_version = await self.encryption_service.encrypt(json.dumps(payload))
        created = await self.task_methods.create_task_execution_context(
            user_id=user_id,
            task_id=task_id,
            chat_id=chat_id,
            encrypted_context=encrypted_context,
            created_at=created_at,
            expires_at=created_at + TASK_EXECUTION_CONTEXT_TTL_SECONDS,
        )
        if not created:
            raise RuntimeError("Failed to stage user Task execution context")
        return created

    async def dispatch_admitted(self, task: dict[str, Any], now: int) -> bool:
        context = await self.task_methods.get_task_execution_context_for_admission(task, now=now)
        if not context:
            await self.task_methods.fail_claimed_ai_task(task, "missing_execution_context", now)
            return False
        try:
            plaintext = await self.encryption_service.decrypt(str(context.get("encrypted_context") or ""))
        except Exception:
            logger.exception("Failed to decrypt execution context for user Task %s", task.get("task_id"))
            await self.task_methods.fail_claimed_ai_task(task, "invalid_execution_context", now)
            return False
        try:
            payload = json.loads(plaintext or "")
        except (TypeError, ValueError):
            await self.task_methods.fail_claimed_ai_task(task, "invalid_execution_context", now)
            return False
        if not self._context_matches_task(payload, task):
            await self.task_methods.fail_claimed_ai_task(task, "invalid_execution_context", now)
            return False

        dispatcher = self.ai_dispatcher
        if dispatcher is None:
            from backend.core.api.app.services.skill_registry import get_global_registry

            dispatcher = get_global_registry().dispatch_skill
        message_id = f"task-{task['task_id']}-{uuid.uuid4()}"
        try:
            response = await dispatcher(
                "ai",
                "ask",
                {
                    "chat_id": payload["chat_id"],
                    "message_id": message_id,
                    "user_id": payload["user_id"],
                    "user_id_hash": hash_id(payload["user_id"]),
                    "message_history": [
                        AIHistoryMessage(
                            content=payload["instruction"],
                            role="user",
                            created_at=int(payload.get("created_at") or now),
                        ).model_dump()
                    ],
                    "current_user_content": payload["instruction"],
                    "chat_has_title": True,
                    "current_chat_title": payload.get("current_chat_title"),
                    "user_preferences": {},
                    "user_task_id": task["task_id"],
                    "team_id": payload.get("team_id"),
                    "team_id_hash": hash_id(payload["team_id"]) if payload.get("team_id") else None,
                },
            )
        except Exception:
            logger.exception("Failed to dispatch admitted user Task %s", task.get("task_id"))
            await self.task_methods.fail_claimed_ai_task(task, "ai_dispatch_failed", now)
            return False
        ai_task_id = response.get("task_id") if isinstance(response, dict) else None
        if ai_task_id and self.cache_service:
            await self.cache_service.set_active_ai_task(payload["chat_id"], ai_task_id)
        return True

    def _context_matches_task(self, payload: Any, task: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        user_id = str(payload.get("user_id") or "")
        chat_id = str(payload.get("chat_id") or "")
        return bool(
            user_id
            and chat_id
            and payload.get("instruction")
            and str(payload.get("task_id") or "") == str(task.get("task_id") or "")
            and chat_id == str(task.get("primary_chat_id") or "")
            and (
                hash_id(str(payload.get("team_id") or "")) == str(task.get("hashed_team_id") or "")
                if task.get("hashed_team_id")
                else hash_id(user_id) == str(task.get("hashed_user_id") or "")
            )
        )
