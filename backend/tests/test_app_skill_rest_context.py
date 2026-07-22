# backend/tests/test_app_skill_rest_context.py
#
# Contract tests for the generic REST app-skill context. The CLI and SDK use
# `/v1/apps/{app}/skills/{skill}` for direct app-skill parity checks, so this
# route must pass the same authenticated user metadata that chat/websocket skill
# dispatch receives. In particular, encryption-backed skills need the user's
# Vault key ID.

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("redis.asyncio", reason="apps_api imports backend service dependencies")
pytest.importorskip("celery", reason="skill_registry imports backend app dependencies")

slowapi_module = ModuleType("slowapi")
slowapi_util_module = ModuleType("slowapi.util")


class FakeLimiter:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def limit(self, *args: Any, **kwargs: Any):
        return lambda handler: handler


slowapi_module.Limiter = FakeLimiter
slowapi_util_module.get_remote_address = lambda request: "127.0.0.1"
sys.modules.setdefault("slowapi", slowapi_module)
sys.modules.setdefault("slowapi.util", slowapi_util_module)

from backend.core.api.app.routes import apps_api  # noqa: E402
from backend.core.api.app.services import skill_registry  # noqa: E402


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def dispatch_skill(self, app_id: str, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((app_id, skill_id, request))
        return {"success": True, "results": []}

    def get_metadata(self, app_id: str):
        return SimpleNamespace(id=app_id, skills=[])


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


@pytest.mark.anyio
async def test_call_app_skill_consumes_security_opt_out_before_skill_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeRegistry()
    captured_contexts = []

    async def fake_safety(result: Any, context: Any) -> Any:
        captured_contexts.append(context)
        return result

    monkeypatch.setattr(skill_registry, "get_global_registry", lambda: registry)
    monkeypatch.setattr(apps_api, "assert_rest_skill_execution_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(apps_api, "sanitize_app_skill_output", fake_safety)

    await apps_api.call_app_skill(
        "web",
        "search",
        {
            "requests": [{"query": "Berlin events"}],
            "security": {"prompt_injection_protection": "disabled"},
        },
        {},
        {
            "user_id": "user-1",
            "api_key_hash": None,
            "device_hash": "device-1",
        },
    )

    dispatched_payload = registry.calls[0][2]
    assert "security" not in dispatched_payload
    assert captured_contexts[0].surface == "rest"
    assert captured_contexts[0].external_data is True
    assert captured_contexts[0].request_body["security"] == {"prompt_injection_protection": "disabled"}


@pytest.mark.anyio
async def test_call_app_skill_passes_output_safety_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeRegistry()
    captured_contexts = []
    secrets_manager = object()
    cache_service = object()

    async def fake_safety(result: Any, context: Any) -> Any:
        captured_contexts.append(context)
        return result

    monkeypatch.setattr(skill_registry, "get_global_registry", lambda: registry)
    monkeypatch.setattr(apps_api, "assert_rest_skill_execution_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(apps_api, "sanitize_app_skill_output", fake_safety)

    await apps_api.call_app_skill(
        "audio",
        "transcribe",
        {"requests": []},
        {},
        {
            "user_id": "user-1",
            "api_key_hash": None,
            "device_hash": "device-1",
        },
        secrets_manager=secrets_manager,
        cache_service=cache_service,
        enforce_rest_exposure_policy=False,
    )

    assert captured_contexts[0].external_data is True
    assert captured_contexts[0].secrets_manager is secrets_manager
    assert captured_contexts[0].cache_service is cache_service
