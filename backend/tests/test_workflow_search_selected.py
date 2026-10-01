"""Search the same owner-scoped workflows visible in the editor."""

import pytest

from backend.apps.workflows.skills._services import get_assistant_service
from backend.apps.workflows.skills.search_skill import SearchSkill
from backend.core.api.app.services.workflow_assistant_service import WorkflowAssistantService
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository
from backend.tests.test_workflow_assistant_and_events import recurring_news_graph
from backend.tests.workflow_test_utils import workflow_service


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries
def test_default_chat_search_uses_persisted_repository() -> None:
    assert isinstance(get_assistant_service().workflow_service.repository, DirectusWorkflowRepository)


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries,workflows.activation.reachable-side-effect
def test_exact_selected_disabled_workflow_returns_edit_context_without_running() -> None:
    service = workflow_service()
    selected = service.create_workflow("alice", "Weekly AI news", recurring_news_graph())
    service.create_workflow("alice", "Other", recurring_news_graph())
    assistant = WorkflowAssistantService(service)

    result = assistant.search("alice", "wrong title", workflow_id=selected.id)

    assert len(result) == 1
    assert result[0]["workflow_id"] == selected.id
    assert result[0]["enabled"] is False
    assert result[0]["graph"]["nodes"][0]["config"]["schedule"]["time"] == "09:00"
    assert result[0]["graph"]["nodes"][1]["config"]["input"]["requests"][0]["query"] == "AI news"
    assert service.list_runs(selected.id, "alice") == []


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries
def test_exact_id_is_owner_scoped_and_does_not_fallback_to_title() -> None:
    service = workflow_service()
    owned = service.create_workflow("alice", "Weekly AI news", recurring_news_graph())
    other = service.create_workflow("bob", "Weekly AI news", recurring_news_graph())
    assistant = WorkflowAssistantService(service)

    assert assistant.search("alice", "Weekly AI news", workflow_id=other.id) == []
    assert assistant.search("alice", "Weekly AI news", workflow_id="missing") == []
    assert [item["workflow_id"] for item in assistant.search("alice", "Weekly AI news")] == [owned.id]


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries
def test_selected_graph_omits_sensitive_configuration() -> None:
    service = workflow_service()
    graph = recurring_news_graph()
    graph["nodes"][1]["config"]["input"]["api_key"] = "private-value"
    selected = service.create_workflow("alice", "Weekly AI news", graph)

    result = WorkflowAssistantService(service).search("alice", "", workflow_id=selected.id)[0]

    assert "api_key" not in result["graph"]["nodes"][1]["config"]["input"]
    assert result["graph"]["nodes"][0]["config"]["schedule"]["time"] == "09:00"


# contract-test: supporting surface=rest_api assertions=workflows.surface.semantic-parity,workflows.access.boundaries
@pytest.mark.anyio
async def test_skill_forwards_selected_id_and_returns_selected_graph() -> None:
    service = workflow_service()
    selected = service.create_workflow("alice", "Weekly AI news", recurring_news_graph())
    skill = SearchSkill(app=None, app_id="workflows", skill_id="search", skill_name="Search", skill_description="Search")

    result = await skill.execute(
        query="", workflow_id=selected.id, user_id="alice",
        workflow_assistant_service=WorkflowAssistantService(service),
    )

    assert result.success is True
    assert result.total_count == 1
    assert result.results[0]["workflow_id"] == selected.id
    assert result.workflows[0]["graph"]["nodes"][0]["config"]["schedule"]["type"] == "weekly"
