# backend/shared/testing/caching_http_transport.py
# Custom httpx transport with record-and-replay caching for skill providers.
#
# When live mock mode is active (per-request via contextvars), this transport
# intercepts outgoing HTTP requests and either returns cached responses or
# forwards to the real API and records the response.
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
from typing import Any, Dict, Optional

import httpx

from backend.shared.testing.api_response_cache import (
    ApiResponseCache,
    MockCacheMiss,
    get_shared_cache,
)
from backend.shared.testing.mock_context import (
    get_mock_group,
    is_mock_active,
    is_record_mode,
)

logger = logging.getLogger(__name__)


class CachingHTTPTransport(httpx.AsyncBaseTransport):
    """
    Async httpx transport that caches responses by request fingerprint.

    Wraps a real transport (httpx.AsyncHTTPTransport). For each request:
    - If live mock mode is OFF: passes through to real transport unchanged.
    - If mode is "mock": returns cached response or raises MockCacheMiss.
    - If mode is "record": calls real API, caches response, returns it.

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

        group_id = get_mock_group()

        # Read request body for fingerprinting
        # httpx.Request.content is bytes
        body_bytes = request.content if request.content else None

        fingerprint = self._cache.fingerprint_http_request(
            method=str(request.method),
            url=str(request.url),
            body=body_bytes,
        )

        # Try cache first
        cached = self._cache.load(group_id, self._category, fingerprint)
        if cached is not None:
            response_data = cached.get("response", {})
            return httpx.Response(
                status_code=response_data.get("status_code", 200),
                headers=response_data.get("headers", {}),
                content=self._decode_body(response_data.get("body", "")),
            )

        # Cache miss
        if not is_record_mode():
            raise MockCacheMiss(
                category=self._category,
                fingerprint=fingerprint,
                details=f"URL: {request.method} {request.url}",
            )

        # Record mode: call real API and save response
        logger.info(
            f"[LiveMock] Cache MISS (recording): {self._category}/{fingerprint} "
            f"— {request.method} {request.url}"
        )
        response = await self._real_transport.handle_async_request(request)

        # Read the response stream fully before accessing content.
        # The real transport returns a streaming response — we must call .read()
        # to buffer it before accessing .content.
        await response.aread()

        # Read response body
        response_body = response.content.decode("utf-8", errors="replace")

        # Build request summary for debugging
        request_summary = {
            "method": str(request.method),
            "url": str(request.url),
        }
        if body_bytes:
            try:
                request_summary["body_preview"] = json.loads(
                    body_bytes.decode("utf-8", errors="replace")
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                request_summary["body_preview"] = body_bytes[:500].decode(
                    "utf-8", errors="replace"
                )

        # Build response data
        response_data = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response_body,
        }

        self._cache.save(
            group_id=group_id,
            category=self._category,
            fingerprint=fingerprint,
            request_summary=request_summary,
            response_data=response_data,
        )

        return response

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
        transport_kwargs: Dict[str, Any] = {}
        if proxy:
            transport_kwargs["proxy"] = proxy
        real_transport = httpx.AsyncHTTPTransport(**transport_kwargs)
        transport = CachingHTTPTransport(real_transport, cache, category)
        return httpx.AsyncClient(transport=transport, **httpx_kwargs)

    return httpx.AsyncClient(**httpx_kwargs)
