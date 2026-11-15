"""Contract tests for the public GET /v1/health/liveness logic."""



from __future__ import annotations

import asyncio

import pytest

from backend.core.api.app.services import liveness_probe as lp


class FakeClient:
    def __init__(self, store: dict) -> None:
        self.store = store

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)


class FakeCache:
    def __init__(self) -> None:
        self.store: dict = {}

    @property
    async def client(self):
        return FakeClient(self.store)

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=None):
        self.store[key] = value
        return True


# contract-test: direct surface=rest_api assertions=external-status-monitoring.liveness.public-route
@pytest.mark.asyncio
async def test_ok_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(lp, "_dispatch_probe_blocking", lambda: calls.append(1) or True)
    cache = FakeCache()
    first = await lp.get_liveness(cache)
    second = await lp.get_liveness(cache)
    assert set(first) == {"status", "api", "ai_worker", "checked_at"}
    assert first["status"] == "ok" and first["ai_worker"] == "ok" and first["api"] == "ok"
    assert second["ai_worker"] == "ok"
    assert len(calls) == 1


# contract-test: direct surface=rest_api assertions=external-status-monitoring.liveness.public-route
@pytest.mark.asyncio
async def test_timeout_reports_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> bool:
        raise TimeoutError("no worker")

    monkeypatch.setattr(lp, "_dispatch_probe_blocking", boom)
    result = await lp.get_liveness(FakeCache())
    assert result["status"] == "degraded"
    assert result["ai_worker"] == "unavailable"
    assert "no worker" not in str(result)


# contract-test: direct surface=rest_api assertions=external-status-monitoring.liveness.public-route
@pytest.mark.asyncio
async def test_concurrent_callers_dispatch_one_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def slow() -> bool:
        import time

        calls.append(1)
        time.sleep(0.3)
        return True

    monkeypatch.setattr(lp, "_dispatch_probe_blocking", slow)
    cache = FakeCache()
    results = await asyncio.gather(*[lp.get_liveness(cache) for _ in range(5)])
    assert len(calls) == 1
    assert all(r["ai_worker"] == "ok" for r in results)
