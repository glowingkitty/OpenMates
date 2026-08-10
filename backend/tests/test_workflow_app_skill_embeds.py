"""Workflow app-skill embed contract tests.

Workflow create/modify is intentionally one workflow per skill call, while
workflow search can return many server-side encrypted workflow matches. These
tests keep that distinction out of the later frontend embed work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.apps.base_app import BaseApp
from backend.apps.workflows.skills import search_skill
from backend.apps.workflows.skills.create_or_modify_skill import CreateOrModifySkill
from backend.apps.workflows.skills.search_skill import SearchSkill


WORKFLOWS_APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "workflows"


class FakeWorkflowAssistantService:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []

    def create_or_modify(
        self,
        user_id: str,
        *,
        title: str,
        graph: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        source_chat_id: str | None = None,
    ) -> dict[str, Any]:
        workflow = {
            "workflow_id": workflow_id or "workflow-1",
            "title": title,
            "graph": graph or {"nodes": []},
            "source_chat_id": source_chat_id,
            "status": "draft",
            "owner_id": user_id,
        }
        self.created.append(workflow)
        return workflow

    def search(
        self,
        user_id: str,
        query: str,
        *,
        include_temporary: bool = False,
        vault_key_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.search_calls.append({
            "user_id": user_id,
            "query": query,
            "include_temporary": include_temporary,
            "vault_key_id": vault_key_id,
        })
        return [
            {"workflow_id": "workflow-1", "title": "Morning weather", "status": "enabled"},
            {"workflow_id": "workflow-2", "title": "Weather digest", "status": "draft"},
        ]


def _create_skill() -> CreateOrModifySkill:
    return CreateOrModifySkill(
        app=None,
        app_id="workflows",
        skill_id="create-or-modify",
        skill_name="Create or modify workflow",
        skill_description="Create or modify one workflow.",
    )


def _search_skill() -> SearchSkill:
    return SearchSkill(
        app=None,
        app_id="workflows",
        skill_id="search",
        skill_name="Search workflows",
        skill_description="Search workflows.",
    )


@pytest.mark.anyio
async def test_workflow_create_or_modify_returns_exactly_one_child_workflow_embed() -> None:
    assistant = FakeWorkflowAssistantService()

    response = await _create_skill().execute(
        title="Morning weather",
        graph={"nodes": [{"id": "trigger"}]},
        user_id="user-1",
        chat_id="chat-1",
        workflow_assistant_service=assistant,
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["app_id"] == "workflows"
    assert payload["skill_id"] == "create-or-modify"
    assert payload["result_count"] == 1
    assert payload["results"] == [
        {
            "type": "workflow",
            "parent_app_skill_type": "app_skill_use",
            "workflow_id": "workflow-1",
            "title": "Morning weather",
            "status": "draft",
            "source_chat_id": "chat-1",
        }
    ]


@pytest.mark.anyio
async def test_workflow_create_or_modify_rejects_batch_creation() -> None:
    response = await _create_skill().execute(
        workflows=[{"title": "One"}, {"title": "Two"}],
        user_id="user-1",
        workflow_assistant_service=FakeWorkflowAssistantService(),
    )

    assert response.success is False
    assert "one workflow" in str(response.error)


@pytest.mark.anyio
async def test_workflow_search_returns_server_side_child_workflow_embed_results() -> None:
    assistant = FakeWorkflowAssistantService()

    response = await _search_skill().execute(
        query="weather",
        include_temporary=True,
        user_id="user-1",
        user_vault_key_id="vault-key-1",
        workflow_assistant_service=assistant,
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["app_id"] == "workflows"
    assert payload["skill_id"] == "search"
    assert payload["status"] == "finished"
    assert payload["result_count"] == 2
    assert [result["type"] for result in payload["results"]] == ["workflow", "workflow"]
    assert payload["requires_connected_client"] is False
    assert assistant.search_calls == [{
        "user_id": "user-1",
        "query": "weather",
        "include_temporary": True,
        "vault_key_id": "vault-key-1",
    }]


@pytest.mark.anyio
async def test_workflow_search_dispatch_receives_user_vault_key_context(monkeypatch: pytest.MonkeyPatch) -> None:
    assistant = FakeWorkflowAssistantService()
    monkeypatch.setattr(search_skill, "get_assistant_service", lambda *_args, **_kwargs: assistant)

    app = BaseApp(
        app_dir=str(WORKFLOWS_APP_DIR),
        register_http_routes=False,
    )
    response = await app.dispatch_skill(
        "search",
        {
            "query": "weather",
            "_user_id": "user-1",
            "_user_vault_key_id": "vault-key-1",
        },
    )

    assert response["success"] is True
    assert assistant.search_calls == [{
        "user_id": "user-1",
        "query": "weather",
        "include_temporary": False,
        "vault_key_id": "vault-key-1",
    }]
