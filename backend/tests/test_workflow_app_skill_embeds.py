"""Workflow app-skill embed contract tests.

Workflow create/modify is intentionally one workflow per skill call, while
workflow search can return many server-side encrypted workflow matches. These
tests keep that distinction out of the later frontend embed work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from types import SimpleNamespace

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


class FakeWorkflowInputService:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def start(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.result


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.authoring.atomic-update
@pytest.mark.anyio
async def test_natural_language_chat_saves_confirmed_disabled_workflows() -> None:
    saved = {"id": "workflow-1", "title": "Morning weather", "status": "disabled", "enabled": False}
    service = FakeWorkflowInputService(SimpleNamespace(
        status="executed", workflow=saved, workflows=[saved], message=None, error=None,
    ))

    response = await _create_skill().execute(
        instruction="Every morning, send me the weather in Graz",
        user_id="user-1", chat_id="chat-1", message_id="message-1",
        timezone="Europe/Vienna", user_vault_key_id="vault-key-1",
        workflow_input_service=service,
    )

    assert response.success is True
    assert response.status == "finished"
    assert response.result_count == 1
    assert response.workflow == saved
    assert response.results[0]["workflow_id"] == "workflow-1"
    assert service.calls == [{
        "user_id": "user-1", "text": "Every morning, send me the weather in Graz",
        "selected_workflow_id": None, "timezone": "Europe/Vienna",
        "vault_key_id": "vault-key-1", "source_chat_id": "chat-1",
        "optimistic_save": False,
        "idempotency_key": "chat:chat-1:message-1",
    }]


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
@pytest.mark.anyio
async def test_natural_language_chat_does_not_claim_clarification_or_queued_save() -> None:
    for status in ("needs_clarification", "queued", "draft"):
        service = FakeWorkflowInputService(SimpleNamespace(
            status=status, workflow=None, workflows=[], message="Which calendar?", error=None,
        ))
        response = await _create_skill().execute(
            instruction="Find calendar events", user_id="user-1", workflow_input_service=service,
        )
        assert response.success is True
        assert response.status == status
        assert response.message == "Which calendar?"
        assert response.result_count == 0
        assert response.results == []


# contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect,workflows.authoring.atomic-update
@pytest.mark.anyio
async def test_natural_language_chat_reports_saved_empty_draft_as_draft() -> None:
    saved = {"id": "workflow-1", "title": "Morning reminder", "status": "draft", "enabled": False}
    service = FakeWorkflowInputService(SimpleNamespace(
        status="draft", workflow=saved, workflows=[saved], message=None, error=None,
    ))
    response = await _create_skill().execute(
        instruction="Morning reminder", user_id="user-1", workflow_input_service=service,
    )
    assert response.success is True
    assert response.status == "draft"
    assert response.result_count == 1


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.authoring.atomic-update
@pytest.mark.anyio
async def test_natural_language_chat_preserves_partial_recovery_notice() -> None:
    saved = {"id": "workflow-1", "title": "Weather alert", "status": "draft", "enabled": False}
    notice = "A later step failed. Valid steps were saved disabled; ask for a concrete update."
    service = FakeWorkflowInputService(SimpleNamespace(
        status="draft", workflow=saved, workflows=[saved], message=notice, error=None,
        partial_reason="provider_error", partial_warning=notice,
    ))
    response = await _create_skill().execute(
        instruction="Update my weather alert", workflow_id="workflow-1", user_id="user-1",
        workflow_input_service=service,
    )
    assert response.success is True
    assert response.status == "draft"
    assert response.workflow["id"] == "workflow-1"
    assert response.workflow["enabled"] is False
    assert response.message == notice


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update,workflows.access.boundaries
@pytest.mark.anyio
async def test_natural_language_chat_passes_selected_edit_target_to_owner_scoped_service() -> None:
    saved = {"id": "workflow-1", "title": "Updated alert", "status": "active", "enabled": True}
    service = FakeWorkflowInputService(SimpleNamespace(
        status="executed", workflow=saved, workflows=[saved], message=None, error=None,
    ))
    response = await _create_skill().execute(
        instruction="Change my selected alert to 9am", workflow_id="workflow-1",
        user_id="owner-1", workflow_input_service=service,
    )
    assert response.success is True
    assert response.workflow["enabled"] is True
    assert service.calls[0]["user_id"] == "owner-1"
    assert service.calls[0]["selected_workflow_id"] == "workflow-1"


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.authoring.atomic-update
@pytest.mark.anyio
async def test_natural_language_chat_rejects_assistant_graph_and_supports_batch_result() -> None:
    saved = [
        {"id": "workflow-1", "title": "Weather", "status": "disabled", "enabled": False},
        {"id": "workflow-2", "title": "News", "status": "disabled", "enabled": False},
    ]
    service = FakeWorkflowInputService(SimpleNamespace(
        status="executed", workflow=saved[0], workflows=saved, message=None, error=None,
    ))
    rejected = await _create_skill().execute(
        instruction="Create both", graph={"nodes": []}, user_id="user-1",
        workflow_input_service=service,
    )
    assert rejected.success is False
    assert service.calls == []

    response = await _create_skill().execute(
        instruction="Create a weather and news workflow", user_id="user-1",
        workflow_input_service=service,
    )
    assert response.success is True
    assert response.result_count == 2
    assert [item["workflow_id"] for item in response.results] == ["workflow-1", "workflow-2"]


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
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


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity
@pytest.mark.anyio
async def test_workflow_create_or_modify_rejects_batch_creation() -> None:
    response = await _create_skill().execute(
        workflows=[{"title": "One"}, {"title": "Two"}],
        user_id="user-1",
        workflow_assistant_service=FakeWorkflowAssistantService(),
    )

    assert response.success is False
    assert "one workflow" in str(response.error)


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity,workflows.access.boundaries
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


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained,workflows.access.boundaries
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
