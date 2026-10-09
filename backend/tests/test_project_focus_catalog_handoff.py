"""Only the current selected Project can complete the staged metadata handoff."""
import sys
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.project_recommendation_service import project_item_revision

pytest_plugins = ["backend.tests.test_async_skill_continuation"]

PROJECT = "11111111-1111-4111-8111-111111111111"
ITEM = "22222222-2222-4222-8222-222222222222"


# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy,projects.focus.inferred-consent
@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_project", [False, True])
async def test_catalog_result_is_owner_and_original_turn_bound(monkeypatch, async_skill_continuation, wrong_project):
    tasks = ModuleType("backend.apps.ai.tasks")
    tasks.__path__ = []
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks", tasks)
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.async_skill_continuation", async_skill_continuation)
    from backend.core.api.app.routes.handlers.websocket_handlers import project_focus_catalog_handler as handler

    item = {"project_item_id": ITEM, "item_type": "embed", "target_id_hash": "opaque",
            "encrypted_metadata": "cipher", "updated_at": 3, "deleted_target_state": None}
    focus = {"item_id": ITEM, "revision": project_item_revision(item), "title": "Debug",
             "description": "Services", "when_to_use": "Failures", "document": "PRIVATE BODY"}
    request = {"user_id": "owner", "chat_id": "chat", "message_id": "turn", "team_id": None,
               "project_focus_candidates": [{"project_id": PROJECT, "name": "Garden", "auto_selection": True}]}
    context = {"app_id": "system", "skill_id": "project_focus_catalog",
               "tool_arguments": {"project_id": PROJECT}, "cached_at": int(time.time()),
               "request_data": request}
    cache = SimpleNamespace(get=AsyncMock(side_effect=lambda key: context if key.endswith(":request") else "turn"),
                            client=AsyncMock(return_value=SimpleNamespace(set=AsyncMock(return_value=True)))())
    directus = SimpleNamespace(project=SimpleNamespace(list_items=AsyncMock(return_value=[item])))
    auth = SimpleNamespace(_require_chat_access=AsyncMock(),
                           _require_project_access=AsyncMock(return_value=({}, None)))
    monkeypatch.setattr(handler, "ProjectWriteAuthorizationService", lambda *_: auth)
    dispatch = AsyncMock()
    monkeypatch.setattr(handler, "dispatch_async_skill_continuation", dispatch)
    websocket = SimpleNamespace(send_json=AsyncMock())
    await handler.handle_project_focus_catalog_result(
        websocket=websocket, manager=SimpleNamespace(can_execute_project_file_job=lambda *_: True),
        cache_service=cache, directus_service=directus, user_id="owner", device_fingerprint_hash="device",
        payload={"chat_id": "chat", "request_id": "request",
                 "project_id": "33333333-3333-4333-8333-333333333333" if wrong_project else PROJECT,
                 "focuses": [focus]},
    )
    if wrong_project:
        dispatch.assert_not_awaited()
        assert websocket.send_json.await_args.args[0]["type"] == "project_focus_catalog_error"
    else:
        dispatch.assert_awaited_once()
        arguments = dispatch.await_args.kwargs
        assert arguments["project_routing_focus_id"] == f"project-{PROJECT}"
        validated = arguments["selected_project_focus_candidates"][0]["focuses"]
        assert len(validated) == 1
        assert validated[0]["item_id"] == ITEM
        assert "PRIVATE BODY" not in str(validated)
        assert websocket.send_json.await_args.args[0]["type"] == "project_focus_catalog_confirmed"
