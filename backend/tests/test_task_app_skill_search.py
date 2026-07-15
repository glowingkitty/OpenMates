"""Task app-skill search privacy contract tests.

Durable task content remains client-side encrypted, so backend search can only
create a connected-client request and later accept client-provided matches. It
must not pretend server-visible metadata is a private-content search fallback.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.apps.tasks.skills.search_skill import SearchSkill


class FakeClientTaskSearchService:
    def __init__(self, *, online: bool, results: list[dict[str, Any]] | None = None) -> None:
        self.online = online
        self.results = results or []
        self.requests: list[dict[str, Any]] = []
        self.server_search_calls = 0

    async def search_or_request(
        self,
        *,
        user_id: str,
        chat_id: str | None,
        message_id: str | None,
        query: str,
    ) -> dict[str, Any]:
        self.requests.append({"user_id": user_id, "chat_id": chat_id, "message_id": message_id, "query": query})
        if not self.online:
            return {
                "status": "waiting_for_client",
                "request_id": "task-search-request-1",
                "notification_queued": True,
            }
        return {"status": "finished", "results": self.results}

    async def server_search_private_task_content(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        self.server_search_calls += 1
        return []


def _skill() -> SearchSkill:
    return SearchSkill(
        app=None,
        app_id="tasks",
        skill_id="search",
        skill_name="Search tasks",
        skill_description="Search tasks on a connected client.",
    )


@pytest.mark.asyncio
async def test_task_search_returns_waiting_embed_state_when_no_client_is_online() -> None:
    search_service = FakeClientTaskSearchService(online=False)

    response = await _skill().execute(
        query="invoice follow-up",
        user_id="user-1",
        chat_id="chat-1",
        message_id="message-1",
        task_search_service=search_service,
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["status"] == "waiting_for_client"
    assert payload["app_id"] == "tasks"
    assert payload["skill_id"] == "search"
    assert payload["results"] == []
    assert payload["pending_client_search"]["request_id"] == "task-search-request-1"
    assert search_service.server_search_calls == 0


@pytest.mark.asyncio
async def test_task_search_returns_client_matches_as_child_task_embed_results() -> None:
    search_service = FakeClientTaskSearchService(
        online=True,
        results=[
            {
                "task_id": "task-1",
                "short_id": "TASK-1",
                "title": "Invoice follow-up",
                "description": "Email finance",
                "assignee_type": "user",
                "status": "todo",
            }
        ],
    )

    response = await _skill().execute(
        query="invoice follow-up",
        user_id="user-1",
        chat_id="chat-1",
        message_id="message-1",
        task_search_service=search_service,
    )
    payload = response.model_dump()

    assert payload["status"] == "finished"
    assert payload["result_count"] == 1
    assert payload["results"][0]["type"] == "task"
    assert payload["results"][0]["assignee"] == "user"
    assert search_service.server_search_calls == 0
