# contract-test-file: infrastructure
# backend/tests/test_caching_http_transport.py
# Regression coverage for shared live-mock HTTP response replay.
#
# Replay must strip wire-level compression headers so httpx does not try to
# decode plain text. Record/real modes must reject variable-price HTTP providers
# before network dispatch until provider-specific pricing is available.

from __future__ import annotations

import json

import httpx
import pytest

from backend.shared.testing.api_response_cache import ApiResponseCache
from backend.shared.testing.caching_http_transport import CachingHTTPTransport
from backend.shared.testing.mock_context import (
    DailyAITestBudgetExceeded,
    activate_mock_mode,
    deactivate_mock_mode,
    get_live_mock_receipt,
    write_live_mock_receipt,
)


class _StaticAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses[str(request.url)]
        response.request = request
        return response


def test_record_mode_requires_request_scoped_candidate_root(tmp_path) -> None:
    cache = ApiResponseCache(root=tmp_path / "canonical")

    activate_mock_mode("record", "missing_candidate")
    try:
        with pytest.raises(RuntimeError, match="request-scoped candidate cache root"):
            cache.save(
                group_id="missing_candidate",
                category="events",
                fingerprint="fingerprint",
                request_summary={},
                response_data={},
            )
    finally:
        deactivate_mock_mode()

    assert not cache.root.exists()


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


@pytest.mark.asyncio
async def test_record_mode_rejects_variable_price_http_before_dispatch(tmp_path) -> None:
    cache = ApiResponseCache(root=tmp_path)
    group_id = "reject_http_record"
    category = "rewe"
    url = "https://shop.rewe.de/api/products?search=bio+joghurt"
    real_transport = _StaticAsyncTransport(
        {
            url: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"products":[{"id":"fresh"}]}',
            )
        }
    )

    activate_mock_mode("record", group_id, tmp_path / "candidate")
    try:
        with pytest.raises(DailyAITestBudgetExceeded, match="variable-price HTTP providers"):
            async with httpx.AsyncClient(
                transport=CachingHTTPTransport(real_transport, cache, category)
            ) as client:
                await client.get(url)
    finally:
        deactivate_mock_mode()

    assert real_transport.requests == []


@pytest.mark.asyncio
async def test_record_mode_allows_allowlisted_free_http_and_sanitizes_cached_headers(tmp_path) -> None:
    cache = ApiResponseCache(root=tmp_path / "canonical")
    run_root = tmp_path / "candidates" / "nightly-20260831"
    candidate_root = run_root / "task-1"
    group_id = "wikipedia_search"
    category = "wikipedia"
    url = "https://en.wikipedia.org/w/api.php?action=query"
    real_transport = _StaticAsyncTransport(
        {
            url: httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "set-cookie": "session=secret",
                    "authorization": "Bearer secret",
                    "x-request-id": "private-request-id",
                },
                content=b'{"query":{"pages":[]}}',
            )
        }
    )

    activate_mock_mode(
        "record",
        group_id,
        candidate_root=candidate_root,
        candidate_run_id="nightly-20260831",
        task_id="task-1",
    )
    try:
        async with httpx.AsyncClient(
            transport=CachingHTTPTransport(real_transport, cache, category)
        ) as client:
            assert (await client.get(url)).json() == {"query": {"pages": []}}
        receipt = get_live_mock_receipt()
        receipt_path = write_live_mock_receipt()
    finally:
        deactivate_mock_mode()

    saved_paths = list(candidate_root.glob(f"{group_id}/{category}/*.json"))
    assert len(real_transport.requests) == 1
    assert len(saved_paths) == 1
    assert json.loads(saved_paths[0].read_text(encoding="utf-8"))["response"]["headers"] == {
        "content-type": "application/json"
    }
    assert receipt_path == run_root / "receipts" / "task-1.json"
    assert receipt_path.read_text(encoding="utf-8") == (
        '{"cache_hits":0,"cache_misses":1,"estimated_eur":0.0,"mode":"record",'
        '"real_provider_calls":1,"run_id":"nightly-20260831","task_id":"task-1"}'
    )
    assert receipt == {
        "mode": "record",
        "run_id": "nightly-20260831",
        "task_id": "task-1",
        "cache_hits": 0,
        "cache_misses": 1,
        "real_provider_calls": 1,
        "estimated_eur": 0.0,
    }


@pytest.mark.asyncio
async def test_replay_reads_selected_candidate_run_without_canonical_fallback(tmp_path) -> None:
    canonical_root = tmp_path / "canonical"
    run_root = tmp_path / "candidates" / "nightly-20260831"
    cache = ApiResponseCache(root=canonical_root)
    group_id = "wikipedia_search"
    category = "wikipedia"
    url = "https://en.wikipedia.org/w/api.php?action=query"
    fingerprint = cache.fingerprint_http_request(method="GET", url=url)
    cache.save(group_id, category, fingerprint, {}, {"body": "canonical"})
    candidate_cache = ApiResponseCache(root=run_root)
    candidate_cache.save(group_id, category, fingerprint, {}, {"body": "candidate"})

    activate_mock_mode(
        "mock",
        group_id,
        candidate_root=run_root,
        candidate_run_id="nightly-20260831",
        task_id="replay-task",
    )
    try:
        async with httpx.AsyncClient(
            transport=CachingHTTPTransport(httpx.AsyncHTTPTransport(), cache, category)
        ) as client:
            response = await client.get(url)
        receipt = get_live_mock_receipt()
    finally:
        deactivate_mock_mode()

    assert response.text == "candidate"
    assert receipt["cache_hits"] == 1
    assert receipt["cache_misses"] == 0


@pytest.mark.asyncio
async def test_real_mode_rejects_variable_price_http_before_dispatch(tmp_path) -> None:
    cache = ApiResponseCache(root=tmp_path)
    group_id = "reject_http_real"
    category = "rewe"
    url = "https://www.rewe.de/shop/api/products?search=bio+joghurt"
    real_transport = _StaticAsyncTransport(
        {
            url: httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "set-cookie": "__cf_bm=secret; HttpOnly; Secure",
                },
                content=b'{"products":[{"id":"safe"}]}',
            )
        }
    )

    activate_mock_mode("real", group_id)
    try:
        with pytest.raises(DailyAITestBudgetExceeded, match="variable-price HTTP providers"):
            async with httpx.AsyncClient(
                transport=CachingHTTPTransport(real_transport, cache, category)
            ) as client:
                await client.get(url)
    finally:
        deactivate_mock_mode()

    assert real_transport.requests == []


@pytest.mark.asyncio
async def test_cached_redirect_replay_follows_location(tmp_path) -> None:
    cache = ApiResponseCache(root=tmp_path)
    group_id = "redirect_replay"
    category = "rewe"
    original_url = "https://shop.rewe.de/api/products?search=bio+joghurt"
    redirected_url = "https://www.rewe.de/shop/api/products?search=bio+joghurt"
    original_fingerprint = cache.fingerprint_http_request(
        method="GET",
        url=original_url,
    )
    redirected_fingerprint = cache.fingerprint_http_request(
        method="GET",
        url=redirected_url,
    )
    cache.save(
        group_id=group_id,
        category=category,
        fingerprint=original_fingerprint,
        request_summary={"method": "GET", "url": original_url},
        response_data={
            "status_code": 301,
            "headers": {"location": redirected_url},
            "body": "",
        },
    )
    cache.save(
        group_id=group_id,
        category=category,
        fingerprint=redirected_fingerprint,
        request_summary={"method": "GET", "url": redirected_url},
        response_data={
            "status_code": 200,
            "headers": {"content-type": "application/json"},
            "body": '{"products":[{"id":"redirected"}]}',
        },
    )

    activate_mock_mode("mock", group_id)
    try:
        async with httpx.AsyncClient(
            transport=CachingHTTPTransport(httpx.AsyncHTTPTransport(), cache, category),
            follow_redirects=True,
        ) as client:
            response = await client.get(original_url)
    finally:
        deactivate_mock_mode()

    assert response.json()["products"] == [{"id": "redirected"}]
    assert [history.status_code for history in response.history] == [301]
