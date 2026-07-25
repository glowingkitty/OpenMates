# backend/apps/projects/skills/search_skill.py
#
# Projects app search skill. Project content is client-side encrypted, so
# backend execution requests a connected capable client and never falls back to
# server-visible metadata for private content search.

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)


class SearchProjectsResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "projects"
    skill_id: str = "search"
    status: str = "waiting_for_client"
    query: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int = 0
    pending_client_search: dict[str, Any] | None = None
    error: str | None = None


class SearchSkill(BaseSkill):
    """Search client-encrypted projects through a connected capable client."""

    async def execute(
        self,
        query: str,
        user_id: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> SearchProjectsResponse:
        try:
            if not user_id:
                raise ValueError("Project search requires an authenticated user")
            search_query = str(query or "").strip()
            if not search_query:
                raise ValueError("Project search requires a query")
            return SearchProjectsResponse(
                success=True,
                query=search_query,
                pending_client_search={
                    "request_id": f"project-search-request-{uuid.uuid4()}",
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "notification_queued": False,
                },
            )
        except Exception as exc:
            logger.error("Project search skill failed: %s", exc, exc_info=True)
            return SearchProjectsResponse(success=False, query=str(query or ""), error=str(exc))
