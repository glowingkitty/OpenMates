# backend/tests/test_caching_http_transport.py
# Regression coverage for shared live-mock HTTP response replay.
#
# Cached provider responses are written as decoded JSON/text cassettes while
# preserving the original provider headers for debugging. Replay must strip
# wire-level compression headers so httpx does not try to decode plain text.

from __future__ import annotations

import httpx
import pytest

from backend.shared.testing.api_response_cache import ApiResponseCache
from backend.shared.testing.caching_http_transport import CachingHTTPTransport
from backend.shared.testing.mock_context import activate_mock_mode, deactivate_mock_mode


@pytest.mark.asyncio
async def test_cached_replay_strips_compression_headers_for_decoded_body(tmp_path) -> None:
    cache = ApiResponseCache(root=tmp_path)
    group_id = "replay_decoded_body"
    category = "printables"
    url = "https://api.printables.com/graphql/"
    fingerprint = cache.fingerprint_http_request(method="GET", url=url)
    cache.save(
        group_id=group_id,
        category=category,
        fingerprint=fingerprint,
        request_summary={"method": "GET", "url": url},
        response_data={
            "status_code": 200,
            "headers": {
                "content-type": "application/json",
                "content-encoding": "gzip",
                "content-length": "999",
                "transfer-encoding": "chunked",
            },
            "body": '{"data":{"searchPrints2":{"items":[{"id":"3161"}]}}}',
        },
    )

    activate_mock_mode("mock", group_id)
    try:
        async with httpx.AsyncClient(
            transport=CachingHTTPTransport(httpx.AsyncHTTPTransport(), cache, category)
        ) as client:
            response = await client.get(url)
    finally:
        deactivate_mock_mode()

    assert response.json()["data"]["searchPrints2"]["items"] == [{"id": "3161"}]
    assert "content-encoding" not in response.headers
    assert response.headers.get("content-length") != "999"
    assert "transfer-encoding" not in response.headers
