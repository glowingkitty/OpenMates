# contract-test-file: infrastructure
# backend/tests/test_skill_executor_registry_refresh.py
#
# Regression tests for app-skill dispatch from AI worker processes.
# Workers cache an in-process SkillRegistry, so newly deployed skills must get a
# one-shot registry refresh before returning stale 404 errors to chat.
#
# Architecture: docs/architecture/apps/app-skills.md

import sys
import types

import pytest

from tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

skill_registry_module = types.ModuleType("backend.core.api.app.services.skill_registry")
skill_registry_module.get_global_registry = lambda: None
skill_registry_module.build_skill_registry = lambda **_kwargs: (None, {})
skill_registry_module.set_global_registry = lambda _registry: None
sys.modules["backend.core.api.app.services.skill_registry"] = skill_registry_module

from backend.apps.ai.processing import skill_executor  # noqa: E402
from backend.apps.ai.processing.skill_executor import execute_skill  # noqa: E402


class FakeRegistry:
    def __init__(self, *, skill_available: bool) -> None:
        self.skill_available = skill_available
        self.dispatch_calls: list[tuple[str, str, dict]] = []

    def has_app(self, app_id: str) -> bool:
        return app_id == "weather"

    def is_skill_available(self, app_id: str, skill_id: str) -> bool:
        return app_id == "weather" and skill_id == "rain_radar" and self.skill_available

    def get_metadata(self, app_id: str):
        return None

    async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
        self.dispatch_calls.append((app_id, skill_id, request_body))
        return {"status": "ok", "app_id": app_id, "skill_id": skill_id}


@pytest.mark.anyio
async def test_execute_skill_refreshes_stale_registry_before_missing_skill_404(monkeypatch) -> None:
    stale_registry = FakeRegistry(skill_available=False)
    refreshed_registry = FakeRegistry(skill_available=True)
    build_calls: list[dict] = []
    registered: list[FakeRegistry] = []

    def fake_build_skill_registry(*, server_environment: str):
        build_calls.append({"server_environment": server_environment})
        return refreshed_registry, {"weather": object()}

    async def fake_sanitize_app_skill_output(result, _context):
        return result

    monkeypatch.setattr(skill_registry_module, "get_global_registry", lambda: stale_registry)
    monkeypatch.setattr(skill_registry_module, "build_skill_registry", fake_build_skill_registry)
    monkeypatch.setattr(skill_registry_module, "set_global_registry", lambda registry: registered.append(registry))
    monkeypatch.setattr(skill_executor, "sanitize_app_skill_output", fake_sanitize_app_skill_output)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")

    result = await execute_skill("weather", "rain_radar", {"location": "Berlin"}, max_retries=0)

    assert result == {"status": "ok", "app_id": "weather", "skill_id": "rain_radar"}
    assert stale_registry.dispatch_calls == []
    assert refreshed_registry.dispatch_calls == [
        ("weather", "rain_radar", {"location": "Berlin"}),
    ]
    assert registered == [refreshed_registry]
    assert build_calls == [{"server_environment": "development"}]


@pytest.mark.anyio
async def test_execute_skill_passes_secrets_manager_only_as_server_context(monkeypatch) -> None:
    registry = FakeRegistry(skill_available=True)
    captured_contexts = []
    secrets_manager = object()
    cache_service = object()

    async def fake_sanitize_app_skill_output(result, context):
        captured_contexts.append(context)
        return result

    monkeypatch.setattr(skill_registry_module, "get_global_registry", lambda: registry)
    monkeypatch.setattr(skill_executor, "sanitize_app_skill_output", fake_sanitize_app_skill_output)

    result = await execute_skill(
        "weather",
        "rain_radar",
        {"location": "Berlin"},
        cache_service=cache_service,
        secrets_manager=secrets_manager,
        max_retries=0,
    )

    assert result == {"status": "ok", "app_id": "weather", "skill_id": "rain_radar"}
    assert registry.dispatch_calls == [
        (
            "weather",
            "rain_radar",
            {
                "location": "Berlin",
                "_cache_service": cache_service,
                "_secrets_manager": secrets_manager,
            },
        )
    ]
    assert captured_contexts[0].request_body == {"location": "Berlin"}
    assert captured_contexts[0].cache_service is cache_service
    assert captured_contexts[0].secrets_manager is secrets_manager


@pytest.mark.anyio
async def test_execute_skill_does_not_redispatch_after_output_safety_failure(monkeypatch) -> None:
    registry = FakeRegistry(skill_available=True)

    async def fake_sanitize_app_skill_output(_result, _context):
        raise RuntimeError("Prompt-injection protection failed for app-skill output")

    monkeypatch.setattr(skill_registry_module, "get_global_registry", lambda: registry)
    monkeypatch.setattr(skill_executor, "sanitize_app_skill_output", fake_sanitize_app_skill_output)

    with pytest.raises(RuntimeError, match="Prompt-injection protection failed"):
        await execute_skill("weather", "rain_radar", {"location": "Berlin"}, max_retries=1)

    assert registry.dispatch_calls == [
        (
            "weather",
            "rain_radar",
            {"location": "Berlin"},
        )
    ]
