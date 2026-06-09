# backend/tests/test_cache_base.py
#
# Regression tests for the shared Redis/Dragonfly cache service wrapper.
# Health checks and Celery tasks create several short-lived CacheService
# instances in parallel, so connection failures must remain visible without
# flooding degraded-service reports with duplicate warnings in the same sweep.

import pytest

try:
    from backend.core.api.app.services import cache_base
    from backend.core.api.app.services.cache_base import CacheServiceBase
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend cache dependencies not installed: {_exc}")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_cache_connection_warning_is_throttled(monkeypatch):
    class FailingRedis:
        async def ping(self):
            raise TimeoutError("Timeout connecting to server")

    monkeypatch.setattr(cache_base.redis, "Redis", lambda **_kwargs: FailingRedis())
    monkeypatch.setattr(CacheServiceBase, "_next_connection_retry_at", 0.0)
    monkeypatch.setattr(CacheServiceBase, "_last_connection_warning_at", -1000.0)
    warning_messages = []
    monkeypatch.setattr(cache_base.logger, "warning", warning_messages.append)

    assert await CacheServiceBase().client is None
    assert await CacheServiceBase().client is None

    assert warning_messages == ["Failed to connect to cache at cache:6379: Timeout connecting to server"]
