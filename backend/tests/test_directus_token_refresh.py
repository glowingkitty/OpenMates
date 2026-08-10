# backend/tests/test_directus_token_refresh.py
#
# Regression coverage for Directus API token refresh behavior.

from unittest.mock import AsyncMock

import httpx
import pytest


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
