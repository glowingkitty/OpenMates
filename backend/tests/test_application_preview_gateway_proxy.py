# backend/tests/test_application_preview_gateway_proxy.py
#
# Tests for the preview gateway proxy.
# The gateway validates signed path tokens, returns safe browser headers while
# sandboxes start, and forwards running preview traffic without leaking provider
# headers or raw sandbox credentials.

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.application_preview import (
    ApplicationPreviewStartRequest,
    create_application_preview_session,
)
from backend.core.api.app.routes.application_preview_gateway import (
    GatewayUpstreamResponse,
    build_preview_gateway_response,
    preview_gateway_security_headers,
)
from backend.tests.test_application_preview_config import FakeCache, _user


@pytest.mark.anyio
async def test_gateway_skeleton_returns_sandbox_starting_response_with_security_headers() -> None:
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )

    response = await build_preview_gateway_response(cache, "session-1", "token-abc", "src/main.js", now=2_030.0)

    assert response.status_code == 202
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.headers["permissions-policy"]
    assert b"sandbox_starting" in response.body
    assert b"token-abc" not in response.body


@pytest.mark.anyio
async def test_gateway_skeleton_rejects_invalid_token_before_response() -> None:
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )

    with pytest.raises(HTTPException) as exc_info:
        await build_preview_gateway_response(cache, "session-1", "wrong-token", "", now=2_030.0)

    assert exc_info.value.status_code == 403


def test_gateway_security_headers_are_restrictive() -> None:
    headers = preview_gateway_security_headers()

    assert headers == {
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), clipboard-read=(), clipboard-write=()",
    }


@pytest.mark.anyio
async def test_gateway_forwards_to_running_upstream_with_filtered_headers() -> None:
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )
    session = await cache.redis.get("application_preview_session:session-1")
    import json

    stored = json.loads(session.decode("utf-8"))
    stored.update({"status": "running", "upstream_base_url": "https://sandbox-1-5173.e2b.dev"})
    await cache.redis.set("application_preview_session:session-1", json.dumps(stored))
    calls: list[dict[str, str]] = []

    async def fake_fetch(url: str, method: str, **_kwargs) -> GatewayUpstreamResponse:
        calls.append({"url": url, "method": method})
        return GatewayUpstreamResponse(
            status_code=200,
            body=b"console.log('ok')",
            headers={
                "content-type": "application/javascript",
                "set-cookie": "bad=1",
                "x-e2b-token": "raw-token",
            },
        )

    response = await build_preview_gateway_response(
        cache,
        "session-1",
        "token-abc",
        "src/main.js",
        now=2_030.0,
        method="GET",
        upstream_fetch=fake_fetch,
    )

    assert response.status_code == 200
    assert response.body == b"console.log('ok')"
    assert response.headers["content-type"] == "application/javascript"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "set-cookie" not in response.headers
    assert "x-e2b-token" not in response.headers
    assert calls == [{"url": "https://sandbox-1-5173.e2b.dev/src/main.js", "method": "GET"}]


@pytest.mark.anyio
async def test_gateway_routes_api_paths_to_backend_upstream_and_preserves_request_payload() -> None:
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )
    session = await cache.redis.get("application_preview_session:session-1")
    import json

    stored = json.loads(session.decode("utf-8"))
    stored.update({
        "status": "running",
        "upstream_base_url": "https://sandbox-1-5173.e2b.dev",
        "upstream_base_urls": {
            "frontend": "https://sandbox-1-5173.e2b.dev",
            "api": "https://sandbox-1-8000.e2b.dev",
        },
    })
    await cache.redis.set("application_preview_session:session-1", json.dumps(stored))
    calls: list[dict] = []

    async def fake_fetch(url: str, method: str, **kwargs) -> GatewayUpstreamResponse:
        calls.append({"url": url, "method": method, "body": kwargs.get("body"), "headers": kwargs.get("headers")})
        return GatewayUpstreamResponse(status_code=201, body=b'{"ok":true}', headers={"content-type": "application/json"})

    response = await build_preview_gateway_response(
        cache,
        "session-1",
        "token-abc",
        "api/customers",
        now=2_030.0,
        method="POST",
        query_string="limit=10",
        body=b'{"name":"Ada"}',
        request_headers={"content-type": "application/json", "cookie": "auth=bad"},
        upstream_fetch=fake_fetch,
    )

    assert response.status_code == 201
    assert response.headers["content-type"] == "application/json"
    assert calls == [
        {
            "url": "https://sandbox-1-8000.e2b.dev/api/customers?limit=10",
            "method": "POST",
            "body": b'{"name":"Ada"}',
            "headers": {"content-type": "application/json"},
        }
    ]
