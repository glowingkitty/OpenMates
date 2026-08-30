# backend/shared/testing/caching_http_transport.py
# Custom httpx transport with record-and-replay caching for skill providers.
#
# When live mock mode is active (per-request via contextvars), this transport
# intercepts outgoing HTTP requests and returns cached responses. Record/real
# modes fail closed until provider-specific HTTP pricing is available.
#
# When mock mode is NOT active (regular user requests), all requests pass
# through to the real transport with zero overhead beyond a single contextvar check.
#
# Security: Only active when MOCK_EXTERNAL_APIS=true and per-request marker is set.
#
# Architecture context: See docs/architecture/live-mock-testing.md

import json
import logging
import os
from typing import Any

import httpx

from backend.shared.testing.api_response_cache import (
    ApiResponseCache,
    MockCacheMiss,
    get_shared_cache,
)
from backend.shared.testing.mock_context import (
    DailyAITestBudgetExceeded,
    get_mock_group,
    is_mock_active,
    is_real_mode,
    is_record_mode,
)

logger = logging.getLogger(__name__)

_DECODED_BODY_HEADER_NAMES = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
}


class CachingHTTPTransport(httpx.AsyncBaseTransport):
    """
    Async httpx transport that caches responses by request fingerprint.

    Wraps a real transport (httpx.AsyncHTTPTransport). For each request:
    - If live mock mode is OFF: passes through to real transport unchanged.
    - If mode is "mock": returns cached response or raises MockCacheMiss.
    - If mode is "record" or "real": rejects variable-price HTTP providers.

    Usage:
        transport = CachingHTTPTransport(
            real_transport=httpx.AsyncHTTPTransport(),
            cache=get_shared_cache(),
            category="brave",
        )
        client = httpx.AsyncClient(transport=transport)
    """

    def __init__(
        self,
        real_transport: httpx.AsyncBaseTransport,
        cache: ApiResponseCache,
        category: str,
    ):
        self._real_transport = real_transport
        self._cache = cache
        self._category = category

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Handle an outgoing HTTP request with optional caching."""
        # Fast path: no mock mode → pass through directly
        if not is_mock_active():
            return await self._real_transport.handle_async_request(request)

        if is_real_mode() or is_record_mode():
            raise DailyAITestBudgetExceeded(
                f"Daily AI real/record tests do not allow variable-price HTTP providers: {self._category}"
            )

        group_id = get_mock_group()

        # Read and buffer the request body for fingerprinting. Redirected httpx
        # requests can expose an unread stream instead of eager .content.
        body_content = await request.aread()
        body_bytes = body_content or None

        fingerprint = self._cache.fingerprint_http_request(
            method=str(request.method),
            url=str(request.url),
            body=body_bytes,
        )

        cached = self._cache.load(group_id, self._category, fingerprint)
        if cached is not None:
            response_data = cached.get("response", {})
            return httpx.Response(
                status_code=response_data.get("status_code", 200),
                headers=self._replay_headers(response_data.get("headers", {})),
                content=self._decode_body(response_data.get("body", "")),
                request=request,
            )

        raise MockCacheMiss(
            category=self._category,
            fingerprint=fingerprint,
            details=f"URL: {request.method} {request.url}",
        )

    async def aclose(self) -> None:
        """Close the underlying transport."""
        await self._real_transport.aclose()

    @staticmethod
    def _decode_body(body: Any) -> bytes:
        """Convert stored body back to bytes for httpx.Response."""
        if isinstance(body, bytes):
            return body
        if isinstance(body, str):
            return body.encode("utf-8")
        if isinstance(body, dict) or isinstance(body, list):
            return json.dumps(body, ensure_ascii=False).encode("utf-8")
        return str(body).encode("utf-8")

    @staticmethod
    def _replay_headers(headers: Any) -> dict[str, str]:
        """Return cached headers safe for a decoded replay body."""
        if not isinstance(headers, dict):
            return {}
        return {
            str(name): str(value)
            for name, value in headers.items()
            if str(name).lower() not in _DECODED_BODY_HEADER_NAMES
        }

def create_http_client(category: str, **httpx_kwargs: Any) -> httpx.AsyncClient:
    """
    Create an httpx.AsyncClient, optionally wrapped with caching transport.

    When MOCK_EXTERNAL_APIS=true, wraps the client with CachingHTTPTransport
    that checks mock_mode_var per-request. When the env var is not set,
    returns a plain httpx.AsyncClient (zero overhead).

    Handles proxy kwargs correctly: when wrapping with caching transport, the
    proxy is moved to the underlying real transport (since httpx.AsyncClient
    doesn't allow both transport= and proxy= simultaneously).

    Usage in skill providers:
        # Instead of: async with httpx.AsyncClient(timeout=30.0, proxy=proxy_url) as client:
        async with create_http_client("brave", timeout=30.0, proxy=proxy_url) as client:
            response = await client.get("https://api.search.brave.com/...")

    Args:
        category: API category for cache organization (e.g., "brave", "doctolib")
        **httpx_kwargs: Additional kwargs passed to httpx.AsyncClient
    """
    if os.getenv("MOCK_EXTERNAL_APIS") == "true":
        cache = get_shared_cache()
        # Extract proxy from kwargs — it must go on the real transport, not the client
        # (httpx doesn't allow both transport= and proxy= on the same client)
        proxy = httpx_kwargs.pop("proxy", None)
        transport_kwargs: dict[str, Any] = {}
        if proxy:
            transport_kwargs["proxy"] = proxy
        real_transport = httpx.AsyncHTTPTransport(**transport_kwargs)
        transport = CachingHTTPTransport(real_transport, cache, category)
        return httpx.AsyncClient(transport=transport, **httpx_kwargs)

    return httpx.AsyncClient(**httpx_kwargs)
