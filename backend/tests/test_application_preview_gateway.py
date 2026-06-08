# backend/tests/test_application_preview_gateway.py
#
# Tests for the user-content preview gateway authorization contract.
# The gateway cannot use OpenMates auth cookies because it intentionally runs on
# a separate site, so it validates short-lived session path tokens before later
# proxy code can forward traffic to E2B sandbox ports.

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.application_preview import (
    ApplicationPreviewStartRequest,
    application_preview_session_key,
    create_application_preview_session,
)
from backend.core.api.app.routes.application_preview_gateway import (
    GatewayUpstreamResponse,
    build_preview_gateway_response,
    redact_preview_gateway_tokens,
    validate_preview_gateway_access,
)
from backend.tests.test_application_preview_config import FakeCache, _user


@pytest.mark.anyio
async def test_create_session_returns_path_token_url_but_stores_only_hash() -> None:
    cache = FakeCache()
    response = await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )

    assert response.preview_url == "https://openmatesusercontent.org/p/session-1/token-abc/"

    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    assert stored["preview_token_hash"]
    assert "token-abc" not in json.dumps(stored)


@pytest.mark.anyio
async def test_gateway_access_accepts_matching_active_token() -> None:
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

    session = await validate_preview_gateway_access(cache, "session-1", "token-abc", now=2_030.0)

    assert session["session_id"] == "session-1"
    assert session["application_embed_id"] == "app-embed-1"


@pytest.mark.anyio
async def test_gateway_access_rejects_wrong_stopped_and_expired_tokens() -> None:
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

    with pytest.raises(HTTPException) as wrong_token:
        await validate_preview_gateway_access(cache, "session-1", "wrong-token", now=2_030.0)
    assert wrong_token.value.status_code == 403

    with pytest.raises(HTTPException) as expired:
        await validate_preview_gateway_access(cache, "session-1", "token-abc", now=2_000.0 + 301)
    assert expired.value.status_code == 403

    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    stored["status"] = "stopped"
    await cache.redis.set(application_preview_session_key("session-1"), json.dumps(stored))

    with pytest.raises(HTTPException) as stopped:
        await validate_preview_gateway_access(cache, "session-1", "token-abc", now=2_030.0)
    assert stopped.value.status_code == 403


def test_redact_preview_gateway_tokens_removes_path_secret() -> None:
    redacted = redact_preview_gateway_tokens(
        "GET /p/session-1/token-abc/src/main.js and https://openmatesusercontent.org/p/session-2/token-def/"
    )

    assert "token-abc" not in redacted
    assert "token-def" not in redacted
    assert "/p/session-1/<REDACTED_PREVIEW_TOKEN>/src/main.js" in redacted
    assert "/p/session-2/<REDACTED_PREVIEW_TOKEN>/" in redacted


@pytest.mark.anyio
async def test_gateway_rewrites_root_relative_html_assets_to_signed_path() -> None:
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
    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    stored.update({"status": "running", "upstream_base_url": "https://sandbox.example"})
    await cache.redis.set(application_preview_session_key("session-1"), json.dumps(stored))

    async def upstream_fetch(_url: str, _method: str, **_kwargs):
        return GatewayUpstreamResponse(
            status_code=200,
            body=b'<link rel="stylesheet" href="/src/style.css"><script type="module" src="/src/main.js"></script>',
            headers={"content-type": "text/html; charset=utf-8"},
        )

    response = await build_preview_gateway_response(
        cache,
        "session-1",
        "token-abc",
        "",
        now=2_030.0,
        upstream_fetch=upstream_fetch,
    )

    body = response.body.decode("utf-8")
    assert 'href="/p/session-1/token-abc/src/style.css"' in body
    assert 'src="/p/session-1/token-abc/src/main.js"' in body


@pytest.mark.anyio
async def test_gateway_rewrites_root_relative_module_imports_to_signed_path() -> None:
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
    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    stored.update({"status": "running", "upstream_base_url": "https://sandbox.example"})
    await cache.redis.set(application_preview_session_key("session-1"), json.dumps(stored))

    async def upstream_fetch(_url: str, _method: str, **_kwargs):
        return GatewayUpstreamResponse(
            status_code=200,
            body=b'import "/src/style.css"; import app from "/src/App.js";',
            headers={"content-type": "application/javascript"},
        )

    response = await build_preview_gateway_response(
        cache,
        "session-1",
        "token-abc",
        "src/main.js",
        now=2_030.0,
        upstream_fetch=upstream_fetch,
    )

    body = response.body.decode("utf-8")
    assert '"/p/session-1/token-abc/src/style.css"' in body
    assert '"/p/session-1/token-abc/src/App.js"' in body
