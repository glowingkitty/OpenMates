# backend/tests/test_pdf_upload_billing_record.py
#
# Whichever dispatch wins the per-embed claim (upload route or message handler), the PDF is
# refunded for a failure and for pages the decision model proved to be text-layer. The upload
# records its charge and page routes; the processing task reads them when its own dispatch has none.
# Specification: feature.pdf-processing (examples pricing, refund).

from __future__ import annotations

import asyncio
import json

import pytest

from backend.apps.pdf.tasks.process_task import _load_upload_billing

ROUTES = [{"page_number": 1, "route": "text_layer", "decided_by": "clean_text_layer"}]


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict = {}

    async def set(self, key, value, nx=False, ex=None):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)


class _FakeCache:
    def __init__(self, client) -> None:
        self._client = client

    @property
    async def client(self):
        return self._client


def _record(user_id: str = "owner", credits: int = 12, routes=ROUTES) -> str:
    return json.dumps({"user_id": user_id, "credits_charged": credits, "page_routes": routes})


# contract-test: supporting surface=rest_api assertions=pdf-processing.billing.refund-on-failure
def test_recorded_charge_and_routes_are_used_for_the_owner():
    client = _FakeRedis()
    client.values["pdf:e1:billing"] = _record()
    recorded = asyncio.run(_load_upload_billing(_FakeCache(client), "e1", "owner"))
    assert recorded == {"credits_charged": 12, "page_routes": ROUTES}


# contract-test: supporting surface=rest_api assertions=pdf-processing.billing.refund-on-failure
@pytest.mark.parametrize("stored", [None, _record(user_id="someone-else"), "{not json", json.dumps(["list"])])
def test_missing_foreign_or_unreadable_record_is_ignored(stored):
    client = _FakeRedis()
    if stored is not None:
        client.values["pdf:e1:billing"] = stored
    assert asyncio.run(_load_upload_billing(_FakeCache(client), "e1", "owner")) == {}


# contract-test: supporting surface=rest_api assertions=pdf-processing.billing.refund-on-failure
def test_no_cache_means_no_record_and_bad_values_are_not_trusted():
    assert asyncio.run(_load_upload_billing(_FakeCache(None), "e1", "owner")) == {}
    client = _FakeRedis()
    client.values["pdf:e1:billing"] = _record(credits=-5, routes="oops")
    assert asyncio.run(_load_upload_billing(_FakeCache(client), "e1", "owner")) == {
        "credits_charged": 0, "page_routes": None,
    }


# contract-test: supporting surface=rest_api assertions=pdf-processing.billing.refund-on-failure
def test_cache_embed_endpoint_stores_the_billing_record_apart_from_the_embed():
    from backend.core.api.app.routes.internal_api import UploadCacheEmbedRequest, cache_upload_embed

    client = _FakeRedis()
    payload = UploadCacheEmbedRequest(
        embed_id="e1", user_id="owner", vault_wrapped_aes_key="vault:v1:k", aes_nonce="n",
        s3_base_url="https://s3", files={}, content_type="application/pdf", original_filename="a.pdf",
        pdf_billing={"credits_charged": 12, "page_routes": ROUTES},
    )
    result = asyncio.run(cache_upload_embed(payload, cache_service=_FakeCache(client)))
    assert result["status"] == "success"
    assert json.loads(client.values["pdf:e1:billing"]) == {
        "user_id": "owner", "credits_charged": 12, "page_routes": ROUTES,
    }
    assert "embed:e1" in client.values
