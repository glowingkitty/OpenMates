"""Single-response shopping discovery caps; all provider traffic is mocked."""
# contract-test-file: infrastructure
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.apps.shopping.providers import amazon_provider, rewe_provider, stoffe_provider


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["amazon", "rewe", "stoffe"])
@pytest.mark.parametrize("available", [20, 45])
async def test_forty_candidates_use_only_one_provider_response(monkeypatch, provider, available):
    calls = []
    modules = {"amazon": amazon_provider, "rewe": rewe_provider, "stoffe": stoffe_provider}
    module = modules[provider]
    if provider == "amazon":
        body = {"organic_results": [{"title": f"Product {i}"} for i in range(available)]}
        monkeypatch.setattr(module, "get_serpapi_key_async", AsyncMock(return_value="synthetic-key"))
    elif provider == "rewe":
        body = {"products": [{"id": str(i), "productName": f"Product {i}"} for i in range(available)]}
    else:
        body = {"data": {"itemList": {"total": 100, "documents": [
            {"data": {"item": {"id": i}, "texts": {"name1": f"Product {i}"}}}
            for i in range(available)
        ]}}}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, **kwargs):
            calls.append(kwargs["params"])
            return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(module, "create_http_client", lambda *args, **kwargs: Client())
    products, _ = await module.search_products("fabric", max_results=40)
    assert len(products) == min(available, 40)
    assert len(calls) == 1 and calls[0]["page"] == 1
    if provider == "rewe":
        assert calls[0]["objectsPerPage"] == 40
    elif provider == "stoffe":
        assert calls[0]["items"] == 40
