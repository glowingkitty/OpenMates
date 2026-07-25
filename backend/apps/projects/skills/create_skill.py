# backend/apps/projects/skills/create_skill.py
#
# Projects app create skill. Project records are client-side encrypted, so this
# skill never writes durable content server-side. It returns a pending client
# action for a capable first-party client to encrypt and apply.

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)


class CreateProjectResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "projects"
    skill_id: str = "create"
    status: str = "waiting_for_client"
    pending_client_action: dict[str, Any] | None = None
    error: str | None = None


class CreateSkill(BaseSkill):
    """Request client-side encrypted project creation."""

    async def execute(
        self,
        name: str,
        description: str | None = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> CreateProjectResponse:
        try:
            if not user_id:
                raise ValueError("Project create requires an authenticated user")
            project_name = str(name or "").strip()
            if not project_name:
                raise ValueError("Project create requires a name")
            return CreateProjectResponse(
                success=True,
                pending_client_action={
                    "request_id": f"project-create-request-{uuid.uuid4()}",
                    "action": "create",
                    "name": project_name,
                    "description": str(description or ""),
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "notification_queued": False,
                },
            )
        except Exception as exc:
            logger.error("Project create skill failed: %s", exc, exc_info=True)
            return CreateProjectResponse(success=False, error=str(exc))
