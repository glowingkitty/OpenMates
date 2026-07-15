# backend/tests/test_app_skill_rest_context.py
#
# Contract tests for the generic REST app-skill context. The CLI and SDK use
# `/v1/apps/{app}/skills/{skill}` for direct app-skill parity checks, so this
# route must pass the same authenticated user metadata that chat/websocket skill
# dispatch receives. In particular, encryption-backed skills need the user's
# Vault key ID.

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.routes import apps_api
from backend.core.api.app.services import skill_registry


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def dispatch_skill(self, app_id: str, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((app_id, skill_id, request))
        return {"success": True, "results": []}


@pytest.mark.anyio
async def test_call_app_skill_passes_user_vault_key_context(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = FakeRegistry()
    monkeypatch.setattr(skill_registry, "get_global_registry", lambda: registry)
    monkeypatch.setattr(apps_api, "assert_rest_skill_execution_allowed", lambda *_args, **_kwargs: None)

    result = await apps_api.call_app_skill(
        "tasks",
        "create",
        {"title": "Draft release checklist"},
        {},
        {
            "user_id": "user-1",
            "vault_key_id": "vault-key-1",
            "api_key_hash": None,
            "device_hash": "device-1",
        },
    )

    assert result == {"success": True, "results": []}
    assert registry.calls == [
        (
            "tasks",
            "create",
            {
                "title": "Draft release checklist",
                "_user_id": "user-1",
                "_api_key_name": "",
                "_api_key_hash": None,
                "_device_hash": "device-1",
                "_external_request": True,
                "_user_vault_key_id": "vault-key-1",
            },
        )
    ]
