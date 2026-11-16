"""Health status alert contracts.

These tests cover the transition-based health alert path for provider, app, and
external-service health changes. Alerts default to Discord when configured;
email is opt-in so dev and official servers do not accidentally spam owners.
"""

# contract-test-file: infrastructure

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest

_MISSING = object()


def _module_stub(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class _FakeCeleryApp:
    def task(self, *args: object, **kwargs: object) -> object:
        def decorator(func: object) -> object:
            return func

        return decorator

    def send_task(self, *args: object, **kwargs: object) -> None:
        return None


class _FakeAsyncClose:
    async def close(self) -> None:
        return None


def _load_health_check_tasks():
    stub_names = {
        "backend.core.api.app.tasks.celery_config": {"app": _FakeCeleryApp()},
        "backend.core.api.app.services.cache": {"CacheService": _FakeAsyncClose},
        "backend.core.api.app.utils.secrets_manager": {"SecretsManager": _FakeAsyncClose},
        "backend.core.api.app.utils.config_manager": {"config_manager": types.SimpleNamespace()},
        "backend.shared.testing.caching_http_transport": {"create_http_client": lambda *args, **kwargs: None},
        "backend.core.api.app.services.degraded_services_report": {
            "build_degraded_issue_report": lambda rows: [],
            "collect_recent_degraded_log_rows": lambda: [],
            "format_degraded_report_message": lambda **kwargs: "",
            "select_degraded_report_webhook_url": lambda environment: None,
            "send_discord_degraded_report": lambda content, webhook_url: None,
        },
        "backend.apps.ai.utils.llm_utils": {
            "PROVIDER_CLIENT_REGISTRY": {},
            "_get_provider_client": lambda provider_id: None,
            "resolve_default_server_from_provider_config": lambda model_id: (None, None),
        },
    }
    previous_modules = {name: sys.modules.get(name, _MISSING) for name in stub_names}
    try:
        for name, attrs in stub_names.items():
            _module_stub(name, **attrs)

        module_path = Path(__file__).resolve().parents[1] / "core/api/app/tasks/health_check_tasks.py"
        spec = importlib.util.spec_from_file_location("health_check_tasks_under_test", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in previous_modules.items():
            if previous is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


hct = _load_health_check_tasks()


def test_health_status_alert_guard_only_alerts_incidents_and_recoveries() -> None:
    assert hct._should_send_health_status_alert(None, "healthy") is False
    assert hct._should_send_health_status_alert("healthy", "healthy") is False
    assert hct._should_send_health_status_alert("healthy", "unhealthy") is True
    assert hct._should_send_health_status_alert("healthy", "degraded") is True
    assert hct._should_send_health_status_alert("unhealthy", "unhealthy") is False
    assert hct._should_send_health_status_alert("degraded", "healthy") is True
    assert hct._should_send_health_status_alert("unhealthy", "healthy") is True
    assert hct._should_send_health_status_alert("healthy", "skipped") is False


@pytest.mark.asyncio
async def test_dispatch_health_status_alerts_sends_discord_without_email_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    class FakeCeleryApp:
        def send_task(self, name: str, **kwargs: object) -> None:
            calls.append({"name": name, **kwargs})

    async def fake_discord(content: str, webhook_url: str) -> None:
        calls.append({"discord": content, "webhook_url": webhook_url})

    monkeypatch.setenv("SERVER_OWNER_EMAIL", "owner@example.org")
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setattr(hct, "app", FakeCeleryApp())
    monkeypatch.setattr(hct, "select_degraded_report_webhook_url", lambda _environment: "https://example.test/discord")
    monkeypatch.setattr(hct, "send_discord_degraded_report", fake_discord)

    await hct._dispatch_health_status_alerts(
        service_type="provider",
        service_id="openai",
        previous_status="healthy",
        new_status="unhealthy",
        error_message="429",
        response_time_ms=123.45,
        duration_seconds=300,
        occurred_at="2026-08-15T21:00:00+00:00",
    )

    assert len(calls) == 1
    assert calls[0]["webhook_url"] == "https://example.test/discord"
    assert "provider/openai" in calls[0]["discord"]
    assert hct.HEALTH_ALERT_EMAIL_TASK_NAME not in {call.get("name") for call in calls}


@pytest.mark.anyio
async def test_unavailable_prior_health_status_does_not_write_or_alert(monkeypatch):
    import sys
    import types
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.services.directus.health_event_methods import HealthStatusUnavailable

    service = SimpleNamespace(
        health_event=SimpleNamespace(
            get_last_status=AsyncMock(side_effect=HealthStatusUnavailable("HTTP 503")),
            record_health_event=AsyncMock(),
        ),
        close=AsyncMock(),
    )
    module = types.ModuleType("backend.core.api.app.services.directus")
    module.DirectusService = lambda: service
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.directus", module)
    dispatch = AsyncMock()
    monkeypatch.setattr(hct, "_dispatch_health_status_alerts", dispatch)
    await hct._record_health_event_if_changed("app", "workflows", "healthy")
    service.health_event.record_health_event.assert_not_awaited()
    dispatch.assert_not_awaited()
    service.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_health_status_alerts_queues_email_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    class FakeCeleryApp:
        def send_task(self, name: str, **kwargs: object) -> None:
            calls.append({"name": name, **kwargs})

    monkeypatch.setenv("OPENMATES_HEALTH_ALERT_EMAIL_ENABLED", "true")
    monkeypatch.setenv("OPENMATES_HEALTH_ALERT_EMAIL_TO", "owner@example.org")
    monkeypatch.setenv("OPENMATES_HEALTH_ALERT_DISCORD_DISABLED", "true")
    monkeypatch.setenv("SERVER_ENVIRONMENT", "self_host")
    monkeypatch.setattr(hct, "app", FakeCeleryApp())

    await hct._dispatch_health_status_alerts(
        service_type="provider",
        service_id="openai",
        previous_status="healthy",
        new_status="unhealthy",
        error_message="429",
        response_time_ms=123.45,
        duration_seconds=300,
        occurred_at="2026-08-15T21:00:00+00:00",
    )

    assert calls == [
        {
            "name": hct.HEALTH_ALERT_EMAIL_TASK_NAME,
            "kwargs": {
                "admin_email": "owner@example.org",
                "service_type": "provider",
                "service_id": "openai",
                "previous_status": "healthy",
                "new_status": "unhealthy",
                "error_message": "429",
                "response_time_ms": 123.45,
                "duration_seconds": 300,
                "occurred_at": "2026-08-15T21:00:00+00:00",
                "environment": "self_host",
            },
            "queue": "email",
        }
    ]


@pytest.mark.asyncio
async def test_record_health_event_queues_alert_after_persisted_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class FakeHealthEvent:
        async def get_last_status(self, service_type: str, service_id: str) -> dict:
            return {"new_status": "healthy", "created_at": "2026-08-15T21:00:00+00:00"}

        async def record_health_event(self, **kwargs: object) -> bool:
            calls.append({"record": kwargs})
            return True

    class FakeDirectus:
        def __init__(self) -> None:
            self.health_event = FakeHealthEvent()

        async def close(self) -> None:
            calls.append({"closed": True})

    class FakeCacheService:
        pass

    class FakeCeleryApp:
        def send_task(self, name: str, **kwargs: object) -> None:
            calls.append({"name": name, **kwargs})

    async def fake_discord(content: str, webhook_url: str) -> None:
        calls.append({"discord": content, "webhook_url": webhook_url})

    directus_module = types.ModuleType("backend.core.api.app.services.directus")
    directus_module.DirectusService = FakeDirectus
    cache_module = types.ModuleType("backend.core.api.app.services.cache")
    cache_module.CacheService = FakeCacheService

    monkeypatch.setenv("SERVER_OWNER_EMAIL", "owner@example.org")
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.directus", directus_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache", cache_module)
    monkeypatch.setattr(hct, "app", FakeCeleryApp())
    monkeypatch.setattr(hct, "CacheService", FakeCacheService)
    monkeypatch.setattr(hct, "select_degraded_report_webhook_url", lambda _environment: "https://example.test/discord")
    monkeypatch.setattr(hct, "send_discord_degraded_report", fake_discord)

    await hct._record_health_event_if_changed(
        service_type="provider",
        service_id="openai",
        new_status="unhealthy",
        error_message="429",
        response_time_ms=123.45,
    )

    discord_calls = [call for call in calls if call.get("webhook_url") == "https://example.test/discord"]
    assert len(discord_calls) == 1
    assert "provider/openai" in discord_calls[0]["discord"]
    assert hct.HEALTH_ALERT_EMAIL_TASK_NAME not in {call.get("name") for call in calls}


@pytest.mark.asyncio
async def test_baseten_health_only_uses_nonbillable_catalog(monkeypatch):
    from backend.shared.providers import baseten
    calls = []
    async def key(manager):
        assert manager is sentinel
        return "test-key"
    class Client:
        def __init__(self, api_key, **kwargs):
            assert api_key == "test-key" and kwargs["timeout"] == 15
        async def models(self):
            calls.append("models")
            return [{"id": "deepseek-ai/DeepSeek-V4.1-Flash-1017"}]
    sentinel = object()
    monkeypatch.setattr(baseten, "BasetenClient", Client)
    monkeypatch.setattr(baseten, "resolve_api_key", key)
    success, error, elapsed = await hct._check_provider_via_test_request("baseten", "deepseek/deepseek-v4.1-flash", sentinel)
    assert success and error is None and elapsed >= 0 and calls == ["models"]


@pytest.mark.asyncio
async def test_unkeyed_baseten_is_not_configured_without_error_logs(monkeypatch, caplog):
    from backend.shared.providers import baseten

    async def missing_key(_manager):
        raise baseten.BasetenError("Baseten API key is not configured")

    class Secrets:
        async def initialize(self):
            return None

    monkeypatch.setattr(baseten, "resolve_api_key", missing_key)
    monkeypatch.setattr(hct, "SecretsManager", Secrets)
    with caplog.at_level("DEBUG"):
        result = await hct._check_provider_health("baseten")
    assert result["status"] == "not_configured"
    assert not [r for r in caplog.records if r.levelname in {"ERROR", "CRITICAL"}]


def test_degraded_report_has_no_baseten_rows_when_not_configured():
    from backend.core.api.app.services.degraded_services_report import build_degraded_issue_report

    rows = [{"message": '{"name":"x","message":"Health check: Checking provider \'baseten\'"}', "level": "INFO", "service": "core-worker"}] * 5
    assert not [r for r in build_degraded_issue_report(rows, min_occurrences=1) if "baseten" in str(r).lower()]


def test_deepseek_yaml_has_no_direct_baseten_server():
    from pathlib import Path
    import yaml

    text = (Path(__file__).parents[1] / "providers/deepseek.yml").read_text()
    provider = yaml.safe_load(text)
    for model in provider["models"]:
        assert "baseten" not in [s["id"] for s in model.get("servers", [])]
    assert "SECRET__BASETEN__API_KEY" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("delegated,expected_calls", [("true", 0), ("false", 2), ("", 2)])
async def test_dispatch_health_status_alerts_respects_delegation_flag(
    monkeypatch: pytest.MonkeyPatch, delegated: str, expected_calls: int
) -> None:
    calls: list[object] = []

    class FakeCeleryApp:
        def send_task(self, name: str, **kwargs: object) -> None:
            calls.append(name)

    async def fake_discord(content: str, webhook_url: str) -> None:
        calls.append("discord")

    monkeypatch.setenv("OPENMATES_HEALTH_ALERTS_DELEGATED", delegated)
    monkeypatch.setenv("OPENMATES_HEALTH_ALERT_EMAIL_ENABLED", "true")
    monkeypatch.setenv("SERVER_OWNER_EMAIL", "owner@example.org")
    monkeypatch.setattr(hct, "app", FakeCeleryApp())
    monkeypatch.setattr(hct, "select_degraded_report_webhook_url", lambda _environment: "https://example.test/discord")
    monkeypatch.setattr(hct, "send_discord_degraded_report", fake_discord)

    await hct._dispatch_health_status_alerts(
        service_type="provider",
        service_id="my_provider",
        previous_status="healthy",
        new_status="unhealthy",
        error_message="timeout",
        response_time_ms=None,
        duration_seconds=None,
        occurred_at="2026-08-15T21:00:00+00:00",
    )

    assert len(calls) == expected_calls
