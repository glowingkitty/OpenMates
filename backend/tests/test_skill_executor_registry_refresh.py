# backend/tests/test_skill_executor_registry_refresh.py
#
# Regression tests for app-skill dispatch from AI worker processes.
# Workers cache an in-process SkillRegistry, so newly deployed skills must get a
# one-shot registry refresh before returning stale 404 errors to chat.
#
# Architecture: docs/architecture/apps/app-skills.md

from types import SimpleNamespace

import pytest

from backend.apps.ai.processing.skill_executor import execute_skill
from backend.core.api.app.services import skill_registry as skill_registry_module
from backend.core.api.app.utils import config_manager as config_manager_module


class FakeRegistry:
    def __init__(self, *, skill_available: bool) -> None:
        self.skill_available = skill_available
        self.dispatch_calls: list[tuple[str, str, dict]] = []

    def has_app(self, app_id: str) -> bool:
        return app_id == "weather"

    def is_skill_available(self, app_id: str, skill_id: str) -> bool:
        return app_id == "weather" and skill_id == "rain_radar" and self.skill_available

    async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
        self.dispatch_calls.append((app_id, skill_id, request_body))
        return {"status": "ok", "app_id": app_id, "skill_id": skill_id}


@pytest.mark.anyio
async def test_execute_skill_refreshes_stale_registry_before_missing_skill_404(monkeypatch) -> None:
    stale_registry = FakeRegistry(skill_available=False)
    refreshed_registry = FakeRegistry(skill_available=True)
    build_calls: list[dict] = []
    registered: list[FakeRegistry] = []

    def fake_build_skill_registry(*, disabled_app_ids: list, server_environment: str):
        build_calls.append({"disabled_app_ids": disabled_app_ids, "server_environment": server_environment})
        return refreshed_registry, {"weather": object()}

    monkeypatch.setattr(skill_registry_module, "get_global_registry", lambda: stale_registry)
    monkeypatch.setattr(skill_registry_module, "build_skill_registry", fake_build_skill_registry)
    monkeypatch.setattr(skill_registry_module, "set_global_registry", lambda registry: registered.append(registry))
    monkeypatch.setattr(
        config_manager_module,
        "ConfigManager",
        lambda: SimpleNamespace(get_disabled_apps=lambda: ["disabled_app"]),
    )
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")

    result = await execute_skill("weather", "rain_radar", {"location": "Berlin"}, max_retries=0)

    assert result == {"status": "ok", "app_id": "weather", "skill_id": "rain_radar"}
    assert stale_registry.dispatch_calls == []
    assert refreshed_registry.dispatch_calls == [
        ("weather", "rain_radar", {"location": "Berlin"}),
    ]
    assert registered == [refreshed_registry]
    assert build_calls == [{"disabled_app_ids": ["disabled_app"], "server_environment": "development"}]
