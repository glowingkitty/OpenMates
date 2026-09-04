"""
Contract tests for worker-local push notification service initialization.

The push Celery worker must load provider credentials before accepting delivery
tasks. Tests use in-memory fakes only and never access Vault or push providers.
"""

import importlib.util
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "core/api/app/tasks/push_worker_service.py"
MODULE_SPEC = importlib.util.spec_from_file_location("push_worker_service_under_test", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
push_worker_service = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(push_worker_service)


# contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
@pytest.mark.asyncio
async def test_push_worker_initializes_push_service(monkeypatch):
    fake_secrets_manager = AsyncMock()
    fake_secrets_manager.initialize = AsyncMock()
    fake_secrets_manager.aclose = AsyncMock()
    fake_push_service = SimpleNamespace(
        initialize=AsyncMock(),
        is_ready=Mock(return_value=True),
    )

    monkeypatch.setattr(push_worker_service, "SecretsManager", lambda: fake_secrets_manager)
    monkeypatch.setattr(push_worker_service, "push_notification_service", fake_push_service)

    await push_worker_service.initialize_push_services({"push"})

    fake_secrets_manager.initialize.assert_awaited_once_with()
    fake_push_service.initialize.assert_awaited_once_with(fake_secrets_manager)
    fake_secrets_manager.aclose.assert_awaited_once_with()


# contract-test: direct surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
@pytest.mark.asyncio
async def test_push_worker_fails_startup_when_service_is_unavailable(monkeypatch):
    fake_secrets_manager = AsyncMock()
    fake_secrets_manager.initialize = AsyncMock()
    fake_secrets_manager.aclose = AsyncMock()
    fake_push_service = SimpleNamespace(
        initialize=AsyncMock(),
        is_ready=Mock(return_value=False),
    )

    monkeypatch.setattr(push_worker_service, "SecretsManager", lambda: fake_secrets_manager)
    monkeypatch.setattr(push_worker_service, "push_notification_service", fake_push_service)

    with pytest.raises(RuntimeError, match="Push notification service failed to initialize"):
        await push_worker_service.initialize_push_services({"push"})

    fake_secrets_manager.aclose.assert_awaited_once_with()


# contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
@pytest.mark.asyncio
async def test_non_push_worker_skips_push_service_initialization(monkeypatch):
    secrets_manager_factory = AsyncMock()
    monkeypatch.setattr(push_worker_service, "SecretsManager", secrets_manager_factory)

    await push_worker_service.initialize_push_services({"app_ai"})

    secrets_manager_factory.assert_not_called()


# contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
def test_celery_worker_bootstrap_initializes_push_service_before_tasks():
    source = (
        Path(__file__).resolve().parents[1]
        / "core/api/app/tasks/celery_config.py"
    ).read_text(encoding="utf-8")

    assert "asyncio.run(initialize_push_services(_get_worker_queues()))" in source
