"""Regression: CacheServiceBase.set(ttl=0) must store without expiry, not call SETEX 0."""
# contract-test-file: infrastructure
import asyncio
from unittest.mock import AsyncMock, MagicMock

from backend.core.api.app.services.cache_base import CacheServiceBase


def _service(client):
    svc = object.__new__(CacheServiceBase)

    async def _client():
        return client

    # `client` is a property on the base class; patch on a throwaway subclass.
    sub = type("_S", (CacheServiceBase,), {"client": property(lambda self: _client())})
    svc.__class__ = sub
    return svc


def test_set_with_zero_ttl_uses_plain_set():
    client = MagicMock(set=AsyncMock(return_value=True), setex=AsyncMock())
    assert asyncio.run(_service(client).set("software_update:config", {"a": 1}, ttl=0))
    client.set.assert_awaited_once()
    client.setex.assert_not_awaited()


def test_set_with_positive_ttl_uses_setex():
    client = MagicMock(set=AsyncMock(), setex=AsyncMock(return_value=True))
    asyncio.run(_service(client).set("k", "v", ttl=60))
    client.setex.assert_awaited_once()
