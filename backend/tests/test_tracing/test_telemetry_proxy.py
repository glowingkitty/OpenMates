# backend/tests/test_tracing/test_telemetry_proxy.py
"""Regression coverage for interrupted first-party browser telemetry uploads.

Development accepts visitors; production retains its admin/debug opt-in policy.
The proxy is free, does not load owner data, and retains its 60/minute/IP limit.
"""

import inspect
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from starlette.requests import Request

from backend.core.api.app.routes import telemetry


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setattr(telemetry, "get_server_edition", lambda: "development")
    monkeypatch.setattr(telemetry, "_get_openobserve_auth_header", lambda: "Basic test-placeholder")
    client = MagicMock()
    client.post = AsyncMock(return_value=httpx.Response(200))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(telemetry.httpx, "AsyncClient", factory)
    # Exercise the handler with a real Request without shared limiter state.
    handler = inspect.unwrap(telemetry.proxy_traces)
    return handler, client, factory


def request_for(messages):
    receive = AsyncMock(side_effect=messages)
    request = Request(
        {"type": "http", "method": "POST", "path": "/v1/telemetry/traces",
         "headers": [(b"content-type", b"application/json")]}, receive,
    )
    return request, receive


@pytest.mark.anyio
@pytest.mark.parametrize("partial", [b"", b'{"resourceSpans":'])
# contract-test: supporting surface=rest_api assertions=ai-request-observability.no-behavior-change
async def test_disconnect_drops_incomplete_batch_without_forwarding_or_error(proxy, caplog, partial):
    handler, client, factory = proxy
    request, _ = request_for([
        {"type": "http.request", "body": partial, "more_body": True},
        {"type": "http.disconnect"},
    ])
    with caplog.at_level(logging.DEBUG, logger=telemetry.__name__):
        response = await handler(request, current_user=None)
    assert response.status_code == 202
    assert json.loads(response.body)["status"] == "dropped"
    factory.assert_not_called()
    client.post.assert_not_called()
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=ai-request-observability.propagation.complete
async def test_complete_batch_preserves_payload_and_forwarding_headers(proxy):
    handler, client, _ = proxy
    body = b'{"resourceSpans":[]}'
    request, _ = request_for([{"type": "http.request", "body": body, "more_body": False}])
    assert await handler(request, current_user=None) == {"status": "ok"}
    client.post.assert_awaited_once_with(
        telemetry.OPENOBSERVE_TRACES_URL, content=body,
        headers={"Content-Type": "application/json", "Authorization": "Basic test-placeholder"},
    )


@pytest.mark.anyio
@pytest.mark.parametrize("user", [None, SimpleNamespace(is_admin=False, extended_debugging=False)])
# contract-test: supporting surface=rest_api assertions=ai-request-observability.no-behavior-change
async def test_production_rejection_does_not_read_or_forward_body(proxy, monkeypatch, user):
    handler, _, factory = proxy
    monkeypatch.setattr(telemetry, "get_server_edition", lambda: "production")
    request, receive = request_for([])
    response = await handler(request, current_user=user)
    assert response.status_code == 403
    receive.assert_not_called()
    factory.assert_not_called()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=ai-request-observability.no-behavior-change
async def test_unexpected_forwarding_failure_remains_visible(proxy, caplog):
    handler, client, _ = proxy
    client.post.side_effect = RuntimeError("synthetic forwarding failure")
    request, _ = request_for([{"type": "http.request", "body": b"{}", "more_body": False}])
    response = await handler(request, current_user=None)
    assert response.status_code == 502
    assert any(record.levelno == logging.ERROR for record in caplog.records)
