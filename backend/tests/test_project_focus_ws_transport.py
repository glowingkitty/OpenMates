"""Replay the production Redis listener's bounded Project-focus event forwarding."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

WEBSOCKETS = Path(__file__).resolve().parents[1] / "core/api/app/routes/websockets.py"


def _listener(manager):
    source = ast.parse(WEBSOCKETS.read_text())
    function = next(node for node in source.body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "listen_for_cache_events")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                              function], type_ignores=[])
    ast.fix_missing_locations(module)
    logger = SimpleNamespace(**{name: lambda *_args, **_kwargs: None
                                for name in ("debug", "info", "warning", "error", "critical")})
    namespace = {"manager": manager, "logger": logger, "asyncio": asyncio,
                 "_safe_payload_summary": lambda *_: "bounded"}
    exec(compile(module, str(WEBSOCKETS), "exec"), namespace)
    return namespace["listen_for_cache_events"]


# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy,projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_redis_listener_forwards_policy_specialist_and_selected_catalog_to_owner_executor_only():
    sent = []
    manager = SimpleNamespace(
        get_connections_for_user=lambda _user: {"executor": object(), "other": object()},
        can_execute_project_file_job=lambda _user, device, _chat: device == "executor",
        send_personal_message=AsyncMock(side_effect=lambda message, user, device: sent.append((device, message))),
    )
    specialist = {"focus_id": "project-focus:project:item", "item_id": "item",
                  "revision": "a" * 64, "title": "Debug"}
    async def messages(_pattern):
        for event_type, payload in (
            ("focus_mode_pending", {"chat_id": "chat", "focus_id": "project-project",
                                    "embed_id": "request", "expires_at": 100,
                                    "activation_policy": "approval", "selected_specialist": specialist,
                                    "private_body": "DO NOT FORWARD"}),
            ("project_focus_catalog_requested", {"chat_id": "chat", "project_id": "project",
                                                 "request_id": "catalog", "team_id": None,
                                                 "private_body": "DO NOT FORWARD"}),
        ):
            yield {"channel": "user_cache_events:owner", "data": {"event_type": event_type,
                                                                     "payload": payload}}
    cache = SimpleNamespace(client=AsyncMock()(), subscribe_to_channel=messages)
    await _listener(manager)(SimpleNamespace(state=SimpleNamespace(cache_service=cache)))
    pending = [message for _, message in sent if message["type"] == "focus_mode_pending"]
    assert len(pending) == 2
    assert pending[0]["payload"]["activation_policy"] == "approval"
    assert pending[0]["payload"]["selected_specialist"] == specialist
    catalog = [(device, message) for device, message in sent
               if message["type"] == "project_focus_catalog_requested"]
    assert catalog == [("executor", {"type": "project_focus_catalog_requested", "payload": {
        "chat_id": "chat", "project_id": "project", "request_id": "catalog", "team_id": None,
    }})]
    assert "DO NOT FORWARD" not in str(sent)
