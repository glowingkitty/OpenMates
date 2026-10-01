"""Focused Amazon price-bound behavior with a mocked SerpAPI response."""
# contract-test-file: infrastructure

import httpx
import pytest

from backend.apps.shopping.providers import amazon_provider


@pytest.mark.asyncio
async def test_price_bounds_exclude_unpriced_and_unparseable_products(monkeypatch):
    raw_results = [
        {"title": "Within range", "extracted_price": 100, "price": "100,00 €"},
        {"title": "At maximum", "extracted_price": "150", "price": "150,00 €"},
        {"title": "Below minimum", "extracted_price": 50, "price": "50,00 €"},
        {"title": "Above maximum", "extracted_price": 180, "price": "180,00 €"},
        {"title": "No price"},
        {"title": "Invalid price", "extracted_price": "unknown"},
        {"title": "Non-finite price", "extracted_price": "nan"},
        {"title": "Boolean price", "extracted_price": True},
    ]

    async def fake_key(_secrets_manager):
        return "synthetic-key"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, *, params):
            assert params["amazon_domain"] == "amazon.de"
            return httpx.Response(
                200,
                json={"organic_results": raw_results},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(amazon_provider, "get_serpapi_key_async", fake_key)
    monkeypatch.setattr(amazon_provider, "create_http_client", lambda *_args, **_kwargs: FakeClient())

    bounded, _ = await amazon_provider.search_products(
        "headphones", country="de", min_price=80, max_price=150,
    )
    assert [(item.title, item.price_amount) for item in bounded] == [
        ("Within range", 100.0), ("At maximum", 150.0),
    ]

    max_only, _ = await amazon_provider.search_products(
        "headphones", country="de", max_price=150,
    )
    assert [item.title for item in max_only] == [
        "Within range", "At maximum", "Below minimum",
    ]

    raw_results[:] = [raw_results[0], raw_results[4]]
    unbounded, _ = await amazon_provider.search_products("headphones", country="de")
    assert "No price" in [item.title for item in unbounded]
    assert next(item for item in unbounded if item.title == "No price").price_amount is None
