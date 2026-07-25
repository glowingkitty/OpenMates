# backend/apps/plans/skills/create_skill.py
#
# Plans app create skill. Plan records are client-side encrypted, so this skill
# never writes durable content server-side. It returns a pending client action
# for a capable first-party client to encrypt and apply.

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)


class CreatePlanResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "plans"
    skill_id: str = "create"
    status: str = "waiting_for_client"
    pending_client_action: dict[str, Any] | None = None
    error: str | None = None


class CreateSkill(BaseSkill):
    """Request client-side encrypted plan creation."""

    async def execute(
        self,
        title: str,
        summary: str | None = None,
        goal: str | None = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> CreatePlanResponse:
        try:
            if not user_id:
                raise ValueError("Plan create requires an authenticated user")
            plan_title = str(title or "").strip()
            if not plan_title:
                raise ValueError("Plan create requires a title")
            return CreatePlanResponse(
                success=True,
                pending_client_action={
                    "request_id": f"plan-create-request-{uuid.uuid4()}",
                    "action": "create",
                    "title": plan_title,
                    "summary": str(summary or ""),
                    "goal": str(goal or ""),
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "notification_queued": False,
                },
            )
        except Exception as exc:
            logger.error("Plan create skill failed: %s", exc, exc_info=True)
            return CreatePlanResponse(success=False, error=str(exc))
