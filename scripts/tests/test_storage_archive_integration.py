# contract-test-file: infrastructure
"""The archive DB/S3 probe cannot run outside its disposable profile."""

import pytest
import asyncio
import sys
from types import ModuleType

from scripts.storage_archive_integration import require_isolated_storage, _load_archive_services


def test_archive_probe_requires_exact_isolated_storage_profile(monkeypatch) -> None:
    for key, value in {
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "CHAT_MESSAGE_ARCHIVE_READS_ENABLED": "1",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000",
        "SERVER_ENVIRONMENT": "development",
        "INTERNAL_API_SHARED_TOKEN": "disposable-token",
    }.items():
        monkeypatch.setenv(key, value)
    require_isolated_storage()
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://storage.example.com")
    with pytest.raises(RuntimeError, match="exact isolated"):
        require_isolated_storage()
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://storage.ci.test:9000")
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="refuses production"):
        require_isolated_storage()


def test_archive_probe_initializes_only_directus_and_s3_without_celery(monkeypatch) -> None:
    events = []

    class SecretsManager:
        async def initialize(self):
            events.append("secrets_initialized")

        async def aclose(self):
            events.append("secrets_closed")

    class DirectusService:
        async def close(self):
            events.append("directus_closed")

    class S3UploadService:
        def __init__(self, *, secrets_manager, directus_service):
            assert isinstance(secrets_manager, SecretsManager)
            assert isinstance(directus_service, DirectusService)

        async def initialize(self, *, configure_buckets):
            assert configure_buckets is False
            events.append("s3_initialized")

    for path, name, value in (
        ("backend.core.api.app.utils.secrets_manager", "SecretsManager", SecretsManager),
        ("backend.core.api.app.services.directus", "DirectusService", DirectusService),
        ("backend.core.api.app.services.s3.service", "S3UploadService", S3UploadService),
    ):
        module = ModuleType(path)
        setattr(module, name, value)
        monkeypatch.setitem(sys.modules, path, module)

    secrets, directus, s3 = asyncio.run(_load_archive_services())
    assert isinstance(secrets, SecretsManager)
    assert isinstance(directus, DirectusService)
    assert isinstance(s3, S3UploadService)
    assert events == ["secrets_initialized", "s3_initialized"]
