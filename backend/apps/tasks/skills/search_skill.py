# backend/apps/tasks/skills/search_skill.py
#
# Tasks app search skill. Task content is client-side encrypted, so backend
# execution either receives client-provided matches or creates a pending request
# for a connected capable client. There is no server metadata fallback.

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.tasks.skills.assignment import product_assignee_from_storage

logger = logging.getLogger(__name__)


class SearchTasksResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "tasks"
    skill_id: str = "search"
    status: str = "waiting_for_client"
    query: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int = 0
    pending_client_search: dict[str, Any] | None = None
    error: str | None = None


class PendingClientTaskSearchService:
    """Default no-client task search requester used until a capable client answers."""

    async def search_or_request(
        self,
        *,
        user_id: str,
        chat_id: str | None,
        message_id: str | None,
        query: str,
    ) -> dict[str, Any]:
        return {
            "status": "waiting_for_client",
            "request_id": f"task-search-request-{uuid.uuid4()}",
            "notification_queued": False,
        }


class SearchSkill(BaseSkill):
    """Search client-encrypted tasks through a connected capable client."""

    async def execute(
        self,
        query: str,
        user_id: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        task_search_service: Any = None,
        **kwargs: Any,
    ) -> SearchTasksResponse:
        try:
            if not user_id:
                raise ValueError("Task search requires an authenticated user")
            search_query = str(query or "").strip()
            if not search_query:
                raise ValueError("Task search requires a query")
            service = task_search_service or PendingClientTaskSearchService()
            search = await service.search_or_request(
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                query=search_query,
            )
            if search.get("status") == "waiting_for_client":
                return SearchTasksResponse(
                    success=True,
                    status="waiting_for_client",
                    query=search_query,
                    pending_client_search={
                        "request_id": search.get("request_id"),
                        "notification_queued": bool(search.get("notification_queued")),
                    },
                )
            results = [_task_search_embed_result(task) for task in search.get("results", [])]
            return SearchTasksResponse(
                success=True,
                status="finished",
                query=search_query,
                results=results,
                result_count=len(results),
            )
        except Exception as exc:
            logger.error("Task search skill failed: %s", exc, exc_info=True)
            return SearchTasksResponse(success=False, query=str(query or ""), error=str(exc))


def _task_search_embed_result(task: dict[str, Any]) -> dict[str, Any]:
    assignee_type = task.get("assignee_type") or "user"
    return {
        "type": "task",
        "parent_app_skill_type": "app_skill_use",
        "task_id": task.get("task_id"),
        "short_id": task.get("short_id"),
        "title": task.get("title") or "",
        "description": task.get("description") or "",
        "status": task.get("status") or "todo",
        "assignee": product_assignee_from_storage(assignee_type),
        "assignee_type": assignee_type,
    }
