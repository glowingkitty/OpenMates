"""Bounded AI naming for an explicit chat group, without workspace planning."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()
from backend.apps.ai.processing import workspace_ask_planner as planner  # noqa: E402
from backend.core.api.app.routes import projects  # noqa: E402


# contract-test: supporting surface=rest_api assertions=chat-navigation.projects.organize
@pytest.mark.asyncio
async def test_chat_titles_use_one_inference_without_workspace_resolution():
    caller = AsyncMock(return_value={"name": "  Website launch  "})
    result = await planner.run_chat_project_title(["Launch copy", "Market research"], object(), llm_caller=caller)
    assert result.proposal.name == "Website launch"
    assert result.processing["purpose"] == "chat_project_title"
    caller.assert_awaited_once()
    request = caller.call_args.kwargs
    assert request["task_id"] == "chat-project-title"
    assert '"Launch copy"' in request["instruction"]
    assert request["tool_definition"]["function"]["name"] == "name_chat_project"
    assert request["dynamic_context"] is None


# contract-test: supporting surface=rest_api assertions=chat-navigation.projects.organize
@pytest.mark.asyncio
async def test_invalid_generated_name_is_rejected():
    with pytest.raises(planner.WorkspaceAskPlanningError):
        await planner.run_chat_project_title(["Launch copy"], object(), llm_caller=AsyncMock(return_value={"name": "   "}))


# contract-test: supporting surface=rest_api assertions=chat-navigation.projects.organize
@pytest.mark.asyncio
async def test_route_uses_structured_titles_without_general_planning(monkeypatch):
    title = AsyncMock(return_value=SimpleNamespace(proposal=planner.ProjectProposal(name="Website launch"), processing={"purpose": "chat_project_title"}))
    general = AsyncMock()
    monkeypatch.setattr(projects, "run_chat_project_title", title)
    monkeypatch.setattr(projects, "run_project_ask_pipeline", general)
    secrets = object()
    result = await projects.plan_project_ask_route(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(secrets_manager=secrets))),
        projects.ProjectAskPlanRequest(instruction="ignored client instruction", chat_titles=["Launch copy"]), current_user=SimpleNamespace())
    title.assert_awaited_once_with(["Launch copy"], secrets)
    general.assert_not_awaited()
    assert result["proposed_project"]["name"] == "Website launch"


# contract-test: supporting surface=rest_api assertions=chat-navigation.projects.organize
@pytest.mark.parametrize("titles", [[], ["title"] * 9, ["x" * 201]])
def test_title_payload_is_bounded(titles):
    with pytest.raises(ValidationError):
        projects.ProjectAskPlanRequest(instruction="Name a project", chat_titles=titles)
