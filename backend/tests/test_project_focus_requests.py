"""Focused ownership, current-turn, and explicit Project consent guards."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.project_focus_request_service import ProjectFocusRequestService, validated_project_candidates
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationError
from backend.tests.test_project_write_authorization import MemoryCache
from backend.tests.test_async_skill_continuation import async_skill_continuation  # noqa: F401

PROJECT = "11111111-1111-4111-8111-111111111111"
REQUEST = "22222222-2222-4222-8222-222222222222"


# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent
def test_web_dispatch_preserves_project_routing_metadata():
    from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as WebRequest
    from backend.apps.ai.skills.ask_skill import AskSkillRequest as AIRequest

    routed = WebRequest(
        chat_id="chat", message_id="message", user_id="user", user_id_hash="hash",
        message_history=[], project_focus_candidates=[{"project_id": PROJECT, "name": "Garden notes"}],
    )
    inference = AIRequest(**routed.model_dump())
    assert inference.project_focus_candidates == [{"project_id": PROJECT, "name": "Garden notes"}]
    assert inference.active_project_focus is None


@pytest.fixture(autouse=True)
def isolated_continuation_import(monkeypatch, request):
    continuation = request.getfixturevalue("async_skill_continuation")
    import sys
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.async_skill_continuation", continuation)


# contract-test: direct surface=rest_api assertions=projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_candidates_filter_foreign_projects_and_strip_content():
    directus = SimpleNamespace(project=SimpleNamespace(list_projects=AsyncMock(return_value=[{"project_id": PROJECT}]),
                                                      get_project_settings=AsyncMock(return_value=None)))
    result = await validated_project_candidates([
        {"project_id": PROJECT, "name": "Garden notes", "instruction": "secret", "content": "secret"},
        {"project_id": "33333333-3333-4333-8333-333333333333", "name": "Foreign"},
        {"project_id": PROJECT, "name": "Duplicate"},
    ], directus_service=directus, user_id="user", team_id=None)
    assert result == [{"project_id": PROJECT, "name": "Garden notes", "summary": "", "auto_selection": True}]


async def make_pending():
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    cache = MemoryCache()
    service = ProjectFocusRequestService(cache, SimpleNamespace(project=SimpleNamespace(get_project_settings=AsyncMock(return_value=None))))
    service.authorization._require_chat_access = AsyncMock()
    service.authorization._require_project_access = AsyncMock(return_value=({}, None))
    pending = {"request_id": REQUEST, "user_id": "user", "project_id": PROJECT,
               "chat_id": "chat", "message_id": "turn", "expires_at": 9_999_999_999}
    await cache.set(service.key("user", "chat"), pending)
    await cache.set(service.key("user", "chat") + ":" + REQUEST, pending)
    await cache.set(async_skill_latest_user_turn_key("user", "chat"), "turn")
    return cache, service, pending


# contract-test: direct surface=rest_api assertions=projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_request_validation_checks_current_permissions_without_activating():
    _, service, pending = await make_pending()
    assert await service.require_pending(user_id="user", chat_id="chat", request_id=REQUEST, project_id=PROJECT) == pending
    service.authorization._require_project_access.assert_awaited_once_with("user", PROJECT, None, write=False)


# contract-test: direct surface=rest_api assertions=projects.focus.inferred-consent
@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["expired", "new_turn", "other_chat", "other_project", "consumed", "revoked"])
async def test_stale_or_unauthorized_request_cannot_activate(case):
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    cache, service, pending = await make_pending()
    chat, project = "chat", PROJECT
    if case == "expired":
        pending["expires_at"] = 0
    elif case == "new_turn":
        await cache.set(async_skill_latest_user_turn_key("user", "chat"), "new-turn")
    elif case == "other_chat":
        chat = "other-chat"
    elif case == "other_project":
        project = "other-project"
    elif case == "consumed":
        await cache.get_and_delete(service.key("user", "chat") + ":" + REQUEST)
    elif case == "revoked":
        service.authorization._require_project_access.side_effect = ProjectWriteAuthorizationError("PROJECT_NOT_FOUND")
    with pytest.raises(ProjectWriteAuthorizationError):
        await service.require_pending(user_id="user", chat_id=chat, request_id=REQUEST, project_id=project)


# contract-test: direct surface=rest_api assertions=projects.focus.inferred-consent,focus-modes.countdown
@pytest.mark.asyncio
async def test_countdown_deadline_is_authoritative_and_separate_from_expiry(monkeypatch):
    cache, service, _ = await make_pending()
    monkeypatch.setattr("backend.core.api.app.services.project_focus_request_service.time.time", lambda: 100)
    pending = await service.create_pending(user_id="user", chat_id="chat", request_id=REQUEST,
                                           project_id=PROJECT, message_id="turn")
    assert service.pending_event(pending)["expires_at"] == 104
    assert pending["expires_at"] > 104
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_COUNTDOWN_PENDING"):
        await service.require_pending(user_id="user", chat_id="chat", request_id=REQUEST, require_completed_countdown=True)
    monkeypatch.setattr("backend.core.api.app.services.project_focus_request_service.time.time", lambda: 104)
    assert await service.require_pending(user_id="user", chat_id="chat", request_id=REQUEST, require_completed_countdown=True) == pending
    await cache.get_and_delete(service.key("user", "chat") + ":" + REQUEST)
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUEST_EXPIRED"):
        await service.require_pending(user_id="user", chat_id="chat", request_id=REQUEST, require_completed_countdown=True)


# contract-test: direct surface=rest_api assertions=projects.focus.auto-selection-setting
@pytest.mark.asyncio
async def test_auto_selection_uses_owner_settings_and_bounded_metadata():
    directus = SimpleNamespace(project=SimpleNamespace(list_projects=AsyncMock(return_value=[{"project_id": PROJECT}]),
                                                      get_project_settings=AsyncMock(return_value={"auto_selection": False})))
    result = await validated_project_candidates([{"project_id": PROJECT, "name": "Garden", "summary": "x" * 1000,
                                                "auto_selection": True}], directus_service=directus, user_id="user", team_id=None)
    assert result[0]["auto_selection"] is False
    assert len(result[0]["summary"]) == 640
    from backend.core.api.app.services.project_focus_request_service import explicitly_named_project_focus_ids
    assert explicitly_named_project_focus_ids("Work on Garden", result) == []
    result[0]["auto_selection"] = True
    assert explicitly_named_project_focus_ids("Work on Garden", result) == [f"project-{PROJECT}"]


# contract-test: supporting surface=rest_api assertions=projects.focus.inferred-consent
def test_named_project_file_request_selects_only_one_offered_eligible_project():
    from backend.apps.ai.processing.project_file_tools import (
        requests_project_file_work, uniquely_named_project_focus_id,
    )

    first = {"project_id": PROJECT, "name": "OpenMates", "auto_selection": True}
    second = {"project_id": "33333333-3333-4333-8333-333333333333",
              "name": "Garden notes", "auto_selection": True}
    candidates = [first, second]
    offered = [f"project-{PROJECT}"]
    assert uniquely_named_project_focus_id(
        "can you read the readme from my OpenMates project?", candidates, offered,
    ) == f"project-{PROJECT}"
    assert requests_project_file_work("can you read the readme from my OpenMates project?")
    assert requests_project_file_work("create a README in my OpenMates project")
    assert not requests_project_file_work("create a new OpenMates project")
    assert not requests_project_file_work("write an email about the OpenMates project")
    assert uniquely_named_project_focus_id("OpenMates and Garden notes", candidates,
                                           offered + [f"project-{second['project_id']}"]) is None
    assert uniquely_named_project_focus_id("OpenMates", candidates, []) is None
    first["auto_selection"] = False
    assert uniquely_named_project_focus_id("OpenMates", candidates, offered) is None


# contract-test: supporting surface=rest_api assertions=projects.focus.inferred-consent
def test_legacy_unscoped_project_search_is_hidden_from_model_tools():
    from backend.apps.ai.processing.project_file_tools import without_unscoped_project_search

    tools = [{"function": {"name": name}} for name in
             ("projects-search", "projects_search", "projects|search", "project_search_files")]
    assert [tool["function"]["name"] for tool in without_unscoped_project_search(tools)] == [
        "project_search_files",
    ]
