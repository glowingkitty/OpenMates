"""Project tile presentation proposals (TASK-1807): naming call, create request, suggest route."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()
from backend.apps.ai.processing import project_presentation as presentation  # noqa: E402 - stubs first
from backend.apps.ai.processing import workspace_ask_planner as planner  # noqa: E402 - stubs first
from backend.core.api.app.routes import projects  # noqa: E402 - stubs first
from backend.core.api.app.services import project_presentation_rules as rules  # noqa: E402 - stubs first
from backend.tests.test_project_create_request import EARLY, _Cache, _answer, _request  # noqa: E402

pytest_plugins = ["backend.tests.test_async_skill_continuation"]


# contract-test: supporting surface=rest_api assertions=projects.presentation.normalised
def test_proposals_are_normalised_to_one_line_and_known_values():
    long = "Plan and cook weekly family meals " * 8
    out = rules.normalize_presentation({"description": "  Keeps\nrecipes  ", "icon": "Chef-Hat", "category": "cooking_food"})
    assert out.model_dump() == {"description": "Keeps recipes", "icon": "chef-hat", "category": "cooking_food"}
    cut = rules.normalize_description(long)
    assert len(cut) <= rules.MAX_DESCRIPTION_CHARS and cut.endswith("…") and "\n" not in cut
    assert rules.normalize_icon("not an icon!") == "" and rules.normalize_icon("x" * 41) == ""
    assert rules.normalize_category("openmates_official") == "" and rules.normalize_category("nope") == ""


# contract-test: supporting surface=rest_api assertions=projects.presentation.creation-same-call
@pytest.mark.asyncio
async def test_naming_call_returns_presentation_in_the_same_tool_call():
    caller = AsyncMock(return_value={"name": "Recipe Keeper", "description": "Save and plan family recipes.",
                                     "icon": "chef-hat", "category": "cooking_food"})
    result = await planner.run_app_project_name("build me a recipe web app", object(), llm_caller=caller)
    caller.assert_awaited_once()
    tool = caller.call_args.kwargs["tool_definition"]["function"]
    assert set(tool["parameters"]["required"]) == {"name", "description", "icon", "category"}
    assert tool["parameters"]["properties"]["category"]["enum"] == list(rules.PROJECT_CATEGORIES)
    proposal = result.proposal
    assert (proposal.name, proposal.description, proposal.icon, proposal.category) == (
        "Recipe Keeper", "Save and plan family recipes.", "chef-hat", "cooking_food")


# contract-test: supporting surface=rest_api assertions=projects.presentation.creation-same-call
@pytest.mark.asyncio
async def test_creation_proposal_and_request_carry_presentation(monkeypatch):
    from backend.apps.ai.processing import project_creation_routing as routing
    from backend.core.api.app.services.project_create_request_service import (
        build_project_create_action, new_project_create_request_id,
    )

    monkeypatch.setattr(routing, "evaluate_jev_decisions", AsyncMock(return_value=_answer("web_app")))
    named = planner.ProjectProposal(name="Recipe Keeper", description="Save and plan family recipes.",
                                    icon="chef-hat", category="cooking_food")
    proposal = await routing.decide_project_creation(
        request_data=_request(), user_overrides=None, cache_service=_Cache(), secrets_manager=None,
        model_id="jev", message_history=[{"role": "user", "content": "build me a recipe web app"}],
        telemetry_task_id="t", log_prefix="test", early_decisions=EARLY,
        harm_threshold=7.0, misuse_threshold=7.0, name_proposer=AsyncMock(return_value=named),
    )
    assert proposal is not None
    assert (proposal.description, proposal.icon, proposal.category) == (
        "Save and plan family recipes.", "chef-hat", "cooking_food")
    action = build_project_create_action(
        request_id=new_project_create_request_id(), name=proposal.proposed_name, chat_id="chat",
        message_id="turn", team_id=None, origin="preprocessor", kind=proposal.kind,
        description=proposal.description, icon=proposal.icon, category=proposal.category,
    )
    assert (action["description"], action["icon"], action["category"]) == (
        "Save and plan family recipes.", "chef-hat", "cooking_food")
    bad = build_project_create_action(request_id=new_project_create_request_id(), name="Notes", chat_id=None,
                                      message_id=None, team_id=None, origin="skill", icon="<svg>", category="x")
    assert bad["icon"] is None and bad["category"] is None


# contract-test: supporting surface=rest_api assertions=projects.presentation.suggest-route
@pytest.mark.asyncio
async def test_suggest_route_answers_normalised_presentation(monkeypatch):
    caller = AsyncMock(return_value={"description": "A shared shopping list\nfor the family.",
                                     "icon": "shopping-cart", "category": "general_knowledge"})

    async def suggest(body, secrets_manager):
        return await presentation.suggest_project_presentation(body, secrets_manager, llm_caller=caller)

    monkeypatch.setattr(projects, "suggest_project_presentation", suggest)
    body = projects.PresentationSuggestRequest(purpose="backfill", name="Family shopping",
                                               chat_titles=["Weekly groceries"], item_names=["list.md"])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(secrets_manager=object())))
    result = await projects.suggest_project_presentation_route(request, body, current_user=SimpleNamespace())
    assert result == {"presentation": {"description": "A shared shopping list for the family.",
                                       "icon": "shopping-cart", "category": "general_knowledge"}}
    instruction = caller.call_args.kwargs["instruction"]
    assert "Weekly groceries" in instruction and "empty description" in instruction


# contract-test: supporting surface=rest_api assertions=projects.presentation.suggest-route
@pytest.mark.asyncio
async def test_suggest_route_maps_model_failure_to_502(monkeypatch):
    monkeypatch.setattr(projects, "suggest_project_presentation",
                        AsyncMock(side_effect=planner.WorkspaceAskPlanningError("down")))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(secrets_manager=object())))
    body = projects.PresentationSuggestRequest(purpose="specification_approval", name="Recipe Keeper",
                                               specification={"title": "Recipes", "summary": "Save recipes."})
    with pytest.raises(projects.HTTPException) as raised:
        await projects.suggest_project_presentation_route(request, body, current_user=SimpleNamespace())
    assert raised.value.status_code == 502


# contract-test: supporting surface=rest_api assertions=projects.presentation.suggest-route
@pytest.mark.parametrize("payload", [
    {"purpose": "other", "name": "Recipes"},
    {"purpose": "backfill", "name": ""},
    {"purpose": "backfill", "name": "Recipes", "chat_titles": ["t"] * 21},
    {"purpose": "backfill", "name": "Recipes", "item_names": ["f"] * 41},
])
def test_suggest_payload_is_bounded(payload):
    with pytest.raises(ValidationError):
        projects.PresentationSuggestRequest(**payload)
