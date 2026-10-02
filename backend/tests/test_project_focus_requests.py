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


@pytest.fixture(autouse=True)
def isolated_continuation_import(monkeypatch, request):
    continuation = request.getfixturevalue("async_skill_continuation")
    import sys
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.async_skill_continuation", continuation)


# contract-test: direct surface=rest_api assertions=projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_candidates_filter_foreign_projects_and_strip_content():
    directus = SimpleNamespace(project=SimpleNamespace(list_projects=AsyncMock(return_value=[{"project_id": PROJECT}])))
    result = await validated_project_candidates([
        {"project_id": PROJECT, "name": "Garden notes", "instruction": "secret", "content": "secret"},
        {"project_id": "33333333-3333-4333-8333-333333333333", "name": "Foreign"},
        {"project_id": PROJECT, "name": "Duplicate"},
    ], directus_service=directus, user_id="user", team_id=None)
    assert result == [{"project_id": PROJECT, "name": "Garden notes"}]


async def make_pending():
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    cache = MemoryCache()
    service = ProjectFocusRequestService(cache, SimpleNamespace())
    service.authorization._require_chat_access = AsyncMock()
    service.authorization._require_project_access = AsyncMock()
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
