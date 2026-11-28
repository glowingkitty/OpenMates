"""Regression: the webhook rate-limit digest must start its services with the
methods they actually have (prod: 'DirectusService' object has no attribute 'initialize')."""
# contract-test-file: infrastructure
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from backend.core.api.app.tasks.email_tasks import webhook_rate_limit_digest_email_task as digest


def test_digest_does_not_call_cacheservice_initialize():
    assert "cache_service.initialize()" not in Path(digest.__file__).read_text()


def test_digest_starts_real_directus_service_without_error(monkeypatch):
    from backend.core.api.app.services import cache as cache_module
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.utils import encryption as encryption_module

    monkeypatch.setattr(digest, "SecretsManager", lambda: MagicMock(initialize=AsyncMock(), aclose=AsyncMock()))
    monkeypatch.setattr(encryption_module, "EncryptionService", lambda: MagicMock(initialize=AsyncMock(), close=AsyncMock()))

    class FakeCache:
        @property
        async def client(self):
            return None  # stop right after service start-up (cache-unavailable branch)

        async def close(self):
            return None

    monkeypatch.setattr(cache_module, "CacheService", FakeCache)
    monkeypatch.setattr(DirectusService, "close", AsyncMock())
    errors = []
    monkeypatch.setattr(digest.logger, "error", lambda *args, **kwargs: errors.append(args))

    assert asyncio.run(digest._async_process_webhook_rate_limit_digest()) is False
    assert errors == []
