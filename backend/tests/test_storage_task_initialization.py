"""Storage maintenance must work without finance configuration or providers."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from celery import Celery
import pytest


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def storage_modules(monkeypatch):
    """Load real task lifecycle methods without importing unrelated task modules."""
    tasks = ModuleType("backend.core.api.app.tasks")
    tasks.__path__ = []
    celery_config = ModuleType("backend.core.api.app.tasks.celery_config")
    registered_bases = {}

    def task_decorator(*, name, base, bind):
        assert bind
        registered_bases[name] = base
        return lambda function: function

    celery_config.app = SimpleNamespace(task=task_decorator)
    email_template = ModuleType("backend.core.api.app.services.email_template")
    email_template.EmailTemplateService = Mock(side_effect=AssertionError("no email templates"))
    path = Path(__file__).parents[1] / "core/api/app/tasks"
    with patch.dict(sys.modules, {
        "backend.core.api.app.tasks": tasks,
        "backend.core.api.app.tasks.celery_config": celery_config,
        "backend.core.api.app.services.email_template": email_template,
    }):
        base = _load_module("backend.core.api.app.tasks.base_task", path / "base_task.py")
        monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.base_task", base)
        storage = _load_module("storage_tasks_under_test", path / "storage_tasks.py")

    # No invoice configuration exists, and any finance/template initialization
    # is a hard failure. Core initialization and cleanup remain real methods.
    secrets = SimpleNamespace(initialize=AsyncMock(), aclose=AsyncMock(),
                              get_secret=AsyncMock(return_value=None))
    cache = SimpleNamespace(get_active_ai_task=AsyncMock(return_value=None), close=AsyncMock())
    directus = SimpleNamespace(close=AsyncMock())
    encryption = SimpleNamespace(initialize=AsyncMock())
    s3 = SimpleNamespace(initialize=AsyncMock())
    for name, service in [("SecretsManager", secrets), ("CacheService", cache),
                          ("DirectusService", directus), ("EncryptionService", encryption)]:
        monkeypatch.setattr(base, name, Mock(return_value=service))
    s3_factory = Mock(return_value=s3)
    monkeypatch.setattr(storage, "S3UploadService", s3_factory)
    finance_initializer = AsyncMock(side_effect=AssertionError("finance initialization forbidden"))
    monkeypatch.setattr(base.BaseServiceTask, "initialize_services", finance_initializer)
    monkeypatch.setattr(storage, "archive_feature_enabled", lambda _feature: True)
    storage.StorageServiceTask.bind(Celery("storage-unit-test"))
    task = storage.StorageServiceTask()
    return SimpleNamespace(storage=storage, task=task, secrets=secrets, cache=cache,
                           directus=directus, s3=s3, s3_factory=s3_factory,
                           finance_initializer=finance_initializer,
                           registered_bases=registered_bases)


# contract-test: supporting surface=rest_api assertions=storage.compression.incremental-archive
def test_storage_adapters_register_core_and_storage_only(storage_modules):
    fixture = storage_modules
    assert len(fixture.registered_bases) == 6
    assert all(base is fixture.storage.StorageServiceTask
               for base in fixture.registered_bases.values())

    async def initialize_twice():
        await fixture.task.initialize_services()
        await fixture.task.initialize_services()
        assert fixture.task.directus_service is fixture.directus
        assert fixture.task.s3_service is fixture.s3
        await fixture.task.cleanup_services()

    asyncio.run(initialize_twice())
    fixture.secrets.initialize.assert_awaited_once()
    fixture.s3_factory.assert_called_once_with(secrets_manager=fixture.secrets,
                                             directus_service=fixture.directus)
    fixture.s3.initialize.assert_awaited_once_with(configure_buckets=False)
    fixture.finance_initializer.assert_not_awaited()
    fixture.secrets.get_secret.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=storage.compression.incremental-archive,storage.integrity.observable-reconcilable
@pytest.mark.parametrize("failure", [None, OSError("regional archive outage"),
                                     "archive_checksum_mismatch", "within_warm_limits"])
def test_archive_attempt_without_invoice_config_preserves_failures_and_cleanup(
    storage_modules, monkeypatch, failure,
):
    from backend.core.api.app.services import chat_message_archive_service as archive
    fixture = storage_modules
    if isinstance(failure, str):
        failure = archive.ArchiveIntegrityError(failure)
    copy = AsyncMock(return_value={"state": "copying"}, side_effect=failure)
    factory = Mock(return_value=SimpleNamespace(copy_segment=copy))
    monkeypatch.setattr(archive, "ChatMessageArchiveService", factory)

    if failure is not None and str(failure) != "within_warm_limits":
        with pytest.raises(type(failure), match=str(failure)):
            fixture.storage.archive_cold_chat(fixture.task, chat_id="fixture-chat")
        # A subsequent delivery initializes fresh core/S3 dependencies and can
        # retry the original archive work; failures are never returned as success.
        copy.side_effect = None
        assert fixture.storage.archive_cold_chat(fixture.task, chat_id="fixture-chat") == {"state": "copying"}
        assert copy.await_count == 2
        assert fixture.s3.initialize.await_count == 2
    else:
        result = fixture.storage.archive_cold_chat(fixture.task, chat_id="fixture-chat")
        assert result["state"] == ("deferred" if failure else "copying")
        if failure:
            assert result["reason"] == "within_warm_limits"
            assert "fixture-chat" not in str(result)
        copy.assert_awaited_once_with(chat_id="fixture-chat")
    factory.assert_called_with(directus_service=fixture.directus, s3_service=fixture.s3)
    fixture.finance_initializer.assert_not_awaited()
    assert fixture.secrets.aclose.await_count == copy.await_count
    assert fixture.directus.close.await_count == copy.await_count
    assert fixture.cache.close.await_count == copy.await_count
    assert fixture.task._s3_service is None


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable
def test_storage_initialization_failure_propagates_and_cleans_up(storage_modules, monkeypatch):
    from backend.core.api.app.services import chat_message_archive_service as archive
    fixture = storage_modules
    fixture.s3.initialize.side_effect = OSError("storage unavailable")
    copy = AsyncMock()
    monkeypatch.setattr(archive, "ChatMessageArchiveService", Mock(return_value=SimpleNamespace(copy_segment=copy)))
    with pytest.raises(OSError, match="storage unavailable"):
        fixture.storage.archive_cold_chat(fixture.task, chat_id="fixture-chat")
    copy.assert_not_awaited()
    fixture.secrets.aclose.assert_awaited_once()
    fixture.directus.close.assert_awaited_once()
    fixture.cache.close.assert_awaited_once()
    fixture.finance_initializer.assert_not_awaited()
