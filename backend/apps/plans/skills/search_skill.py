# backend/apps/plans/skills/search_skill.py
#
# Plans app search skill. Plan content is client-side encrypted, so backend
# execution requests a connected capable client and never falls back to
# server-visible metadata for private content search.

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)


class SearchPlansResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "plans"
    skill_id: str = "search"
    status: str = "waiting_for_client"
    query: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int = 0
    pending_client_search: dict[str, Any] | None = None
    error: str | None = None


class SearchSkill(BaseSkill):
    """Search client-encrypted plans through a connected capable client."""

    async def execute(
        self,
        query: str,
        user_id: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> SearchPlansResponse:
        try:
            if not user_id:
                raise ValueError("Plan search requires an authenticated user")
            search_query = str(query or "").strip()
            if not search_query:
                raise ValueError("Plan search requires a query")
            return SearchPlansResponse(
                success=True,
                query=search_query,
                pending_client_search={
                    "request_id": f"plan-search-request-{uuid.uuid4()}",
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "notification_queued": False,
                },
            )
        except Exception as exc:
            logger.error("Plan search skill failed: %s", exc, exc_info=True)
            return SearchPlansResponse(success=False, query=str(query or ""), error=str(exc))
