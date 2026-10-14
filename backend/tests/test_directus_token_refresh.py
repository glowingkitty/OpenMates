# backend/tests/test_directus_token_refresh.py
# contract-test-file: infrastructure
#
# Regression coverage for Directus API token refresh behavior.

import logging
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.fixture(autouse=True)
def _capture_service_logs(monkeypatch, caplog):
    logger = logging.getLogger("backend.core.api.app.services.directus.api_methods")
    monkeypatch.setattr(logger, "handlers", [*logger.handlers, caplog.handler])


@pytest.mark.asyncio
async def test_get_items_does_not_reuse_stale_regular_token():
    from backend.core.api.app.services.directus.directus import DirectusService

    class _Response:
        status_code = 200
        text = "OK"

        def json(self):
            return {"data": []}

    service = object.__new__(DirectusService)
    service.base_url = "http://cms:8055"
    service.token = "stale-token"
    service._make_api_request = AsyncMock(return_value=_Response())

    await service.get_items("encryption_keys", {"limit": 1})

    _, _, kwargs = service._make_api_request.mock_calls[0]
    assert kwargs["headers"] == {"Cache-Control": "no-store"}


@pytest.mark.asyncio
async def test_make_api_request_refreshes_only_auto_added_expired_authorization():
    from backend.core.api.app.services.directus.api_methods import _make_api_request

    seen_headers = []

    def respond(request):
        seen_headers.append(dict(request.headers))
        if len(seen_headers) == 1:
            return httpx.Response(401, text="TOKEN_EXPIRED")
        return httpx.Response(200, json={"data": []})

    service = type("_Service", (), {})()
    service.max_retries = 3
    service.ensure_auth_token = AsyncMock(side_effect=["expired-token", "fresh-token"])
    service.clear_tokens = AsyncMock()
    caller_headers = {"X-Request-Tag": "preserved"}

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service._client = client
        response = await _make_api_request(
            service, "GET", "http://cms:8055/items/example", headers=caller_headers
        )

    assert response.status_code == 200
    assert [headers["authorization"] for headers in seen_headers] == [
        "Bearer expired-token", "Bearer fresh-token"
    ]
    assert [headers["x-request-tag"] for headers in seen_headers] == ["preserved"] * 2
    assert caller_headers == {"X-Request-Tag": "preserved"}
    assert [call.kwargs for call in service.ensure_auth_token.await_args_list] == [
        {"force_refresh": False}, {"force_refresh": True}
    ]
    service.clear_tokens.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization_key", ["Authorization", "authorization"])
async def test_make_api_request_never_replaces_explicit_caller_authorization(authorization_key):
    from backend.core.api.app.services.directus.api_methods import _make_api_request

    seen_headers = []

    def respond(request):
        seen_headers.append(dict(request.headers))
        if len(seen_headers) == 1:
            return httpx.Response(401, text="TOKEN_EXPIRED")
        return httpx.Response(200, json={"data": []})

    service = type("_Service", (), {})()
    service.max_retries = 3
    service.ensure_auth_token = AsyncMock(return_value="admin-token")
    service.clear_tokens = AsyncMock()
    caller_headers = {authorization_key: "Bearer caller-token", "X-Request-Tag": "preserved"}

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service._client = client
        response = await _make_api_request(
            service, "GET", "http://cms:8055/items/example", headers=caller_headers
        )

    assert response.status_code == 200
    assert [headers["authorization"] for headers in seen_headers] == ["Bearer caller-token"] * 2
    assert [headers["x-request-tag"] for headers in seen_headers] == ["preserved"] * 2
    assert caller_headers == {authorization_key: "Bearer caller-token", "X-Request-Tag": "preserved"}
    service.ensure_auth_token.assert_not_awaited()
    service.clear_tokens.assert_awaited_once()


@pytest.mark.asyncio
async def test_make_api_request_retries_blank_read_timeouts_as_connection_failures(monkeypatch, caplog):
    from backend.core.api.app.services.directus.api_methods import _make_api_request

    class _Client:
        def __init__(self):
            self.calls = 0

        async def get(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadTimeout("")
            return type("_Response", (), {"status_code": 200, "text": "OK"})()

    service = type("_Service", (), {})()
    service.max_retries = 3
    service._client = _Client()
    service.ensure_auth_token = AsyncMock(return_value="token")
    service.clear_tokens = AsyncMock()
    monkeypatch.setattr("backend.core.api.app.services.directus.api_methods.asyncio.sleep", AsyncMock())

    response = await _make_api_request(service, "GET", "http://cms:8055/items/example")

    assert response.status_code == 200
    assert service._client.calls == 2
    assert "CMS read transport failed (ReadTimeout)" in caplog.text
    assert "Request failed: . Retrying" not in caplog.text


@pytest.mark.asyncio
async def test_make_api_request_does_not_replay_mutation_after_read_timeout(monkeypatch, caplog):
    from backend.core.api.app.services.directus.api_methods import _make_api_request

    client = type("_Client", (), {})()
    client.post = AsyncMock(side_effect=httpx.ReadTimeout(""))
    service = type("_Service", (), {})()
    service.max_retries = 3
    service._client = client
    service.ensure_auth_token = AsyncMock(return_value="token")
    service.clear_tokens = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr("backend.core.api.app.services.directus.api_methods.asyncio.sleep", sleep)

    with pytest.raises(httpx.ReadTimeout):
        await _make_api_request(service, "POST", "http://cms:8055/items/example", json={"value": 1})

    client.post.assert_awaited_once()
    sleep.assert_not_awaited()
    assert "CMS mutation transport failed (ReadTimeout); not retrying" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_error", [httpx.ReadError(""), httpx.WriteError("")])
async def test_make_api_request_does_not_replay_mutation_after_ambiguous_transport_error(
    monkeypatch,
    caplog,
    transport_error,
):
    from backend.core.api.app.services.directus.api_methods import _make_api_request

    client = type("_Client", (), {})()
    client.post = AsyncMock(side_effect=transport_error)
    service = type("_Service", (), {})()
    service.max_retries = 3
    service._client = client
    service.ensure_auth_token = AsyncMock(return_value="token")
    service.clear_tokens = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr("backend.core.api.app.services.directus.api_methods.asyncio.sleep", sleep)

    with pytest.raises(type(transport_error)):
        await _make_api_request(service, "POST", "http://cms:8055/items/example", json={"value": 1})

    client.post.assert_awaited_once()
    sleep.assert_not_awaited()
    assert f"CMS mutation transport failed ({type(transport_error).__name__}); not retrying" in caplog.text
