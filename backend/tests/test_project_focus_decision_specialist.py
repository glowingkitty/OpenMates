"""One accepted Project decision may activate its exact discovered specialist."""
from types import SimpleNamespace
from types import ModuleType
from unittest.mock import AsyncMock
import sys

import pytest

from backend.core.api.app.services.project_recommendation_service import project_item_revision

pytest_plugins = ["backend.tests.test_async_skill_continuation"]

PROJECT = "11111111-1111-4111-8111-111111111111"
ITEM = "22222222-2222-4222-8222-222222222222"
DOCUMENT = ("---\nname: Project debugging\ndescription: Investigate service failures.\n"
            "when_to_use: Debugging Python services.\n---\nUse the private instructions.\n")


# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy,projects.focus.inferred-consent
@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, True])
async def test_accepted_project_consumes_one_decision_and_only_current_selected_specialist(monkeypatch, stale, async_skill_continuation):
    tasks = ModuleType("backend.apps.ai.tasks")
    tasks.__path__ = []
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks", tasks)
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.async_skill_continuation", async_skill_continuation)
    from backend.core.api.app.routes.handlers.websocket_handlers import project_focus_decision_handler as handler
    item = {"project_item_id": ITEM, "item_type": "embed", "target_id_hash": "opaque",
            "encrypted_metadata": "cipher", "updated_at": 4 + int(stale), "deleted_target_state": None}
    selected = {"focus_id": f"project-focus:{PROJECT}:{ITEM}", "item_id": ITEM,
                "revision": project_item_revision({**item, "updated_at": 4}), "title": "Project debugging"}
    pending = {"request_id": "request", "project_id": PROJECT, "team_id": None,
               "continuation_id": "request", "selected_specialist": selected}
    authorization = SimpleNamespace(
        get_active_focus=AsyncMock(return_value={"project_id": PROJECT, "team_id": None}),
        validate_specialist_context=AsyncMock(return_value={
            "focus_id": selected["focus_id"], "item_id": ITEM,
            "item_revision": selected["revision"], "instruction": DOCUMENT,
        }),
        accept_specialist_focus=AsyncMock(),
    )
    service = SimpleNamespace(require_pending=AsyncMock(return_value=pending),
                              consume_decision=AsyncMock(return_value=pending),
                              authorization=authorization)
    monkeypatch.setattr(handler, "ProjectFocusRequestService", lambda *_: service)
    dispatch = AsyncMock()
    monkeypatch.setattr(handler, "dispatch_async_skill_continuation", dispatch)
    directus = SimpleNamespace(project=SimpleNamespace(list_items=AsyncMock(return_value=[item])))
    websocket = SimpleNamespace(send_json=AsyncMock())
    manager = SimpleNamespace(can_execute_project_file_job=lambda *_: True)
    await handler.handle_project_focus_decision(
        websocket=websocket, manager=manager, cache_service=object(), directus_service=directus,
        user_id="owner", device_fingerprint_hash="device",
        payload={"chat_id": "chat", "request_id": "request", "accepted": True,
                 "specialist_document": {"focus_id": selected["focus_id"], "item_id": ITEM,
                                         "revision": selected["revision"], "document": DOCUMENT}},
    )
    service.consume_decision.assert_awaited_once()
    assert dispatch.await_args.kwargs["project_focus_documents"] == (
        None if stale else [{"item_id": ITEM, "revision": selected["revision"], "document": DOCUMENT}]
    )
    assert authorization.accept_specialist_focus.await_count == (0 if stale else 1)
    assert websocket.send_json.await_args_list[0].args[0] == {
        "type": "project_focus_decision_confirmed",
        "payload": {"chat_id": "chat", "request_id": "request"},
    }
    assert websocket.send_json.await_count == (1 if stale else 2)
    if not stale:
        assert websocket.send_json.await_args_list[1].args[0] == {
            "type": "focus_mode_activated", "payload": {"chat_id": "chat",
            "focus_id": selected["focus_id"], "focus_mode_name": "Project debugging"},
        }
