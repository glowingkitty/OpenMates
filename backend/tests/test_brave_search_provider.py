# backend/tests/test_brave_search_provider.py
#
# Unit tests for Brave Search provider request handling.
# Covers free-key quota exhaustion fallback and transient 429 retry behavior.
# Tests use mocked HTTP responses only; no live Brave API calls are made.
#
# Architecture: docs/architecture/apps/app-skills.md

from unittest.mock import AsyncMock

import httpx
import pytest

from backend.shared.providers.brave.brave_search import (
    _get_brave_api_key_candidates,
    _request_with_429_retry,
)


class _FakeSecretsManager:
    def __init__(self, values: dict[tuple[str, str], str]) -> None:
        self.values = values

    async def get_secret(self, secret_path: str, secret_key: str) -> str | None:
        return self.values.get((secret_path, secret_key))


def _response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=json_body or {},
        request=httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
    )


class _FakeClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, str]] = []

    async def get(self, url: str, params: dict, headers: dict) -> httpx.Response:
        self.calls.append(headers)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_monthly_quota_exhaustion_uses_paid_fallback() -> None:
    free_quota_response = _response(
        429,
        {
            "error": {
                "code": "QUOTA_LIMITED",
                "detail": "Request quota limit exceeded for plan.",
                "meta": {"plan": "Free AI", "quota_limit": 2000, "quota_current": 2001},
            }
        },
    )
    paid_success_response = _response(200, {"web": {"results": []}})
    client = _FakeClient([free_quota_response, paid_success_response])

    response = await _request_with_429_retry(
        client=client,
        url="https://api.search.brave.com/res/v1/web/search",
        params={"q": "OpenMates"},
        headers={"X-Subscription-Token": "free-key"},
        query="OpenMates",
        search_type="web",
        fallback_headers=[("paid", {"X-Subscription-Token": "paid-key"})],
    )

    assert response.status_code == 200
    assert [call["X-Subscription-Token"] for call in client.calls] == ["free-key", "paid-key"]


@pytest.mark.asyncio
async def test_transient_rate_limit_retries_without_paid_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    transient_response = _response(
        429,
        {
            "error": {
                "code": "RATE_LIMITED",
                "detail": "Too many requests.",
                "meta": {"rate_limit": 1, "rate_current": 1},
            }
        },
    )
    success_response = _response(200, {"web": {"results": []}})
    client = _FakeClient([transient_response, success_response])
    sleep_mock = AsyncMock()
    monkeypatch.setattr("backend.shared.providers.brave.brave_search.asyncio.sleep", sleep_mock)

    response = await _request_with_429_retry(
        client=client,
        url="https://api.search.brave.com/res/v1/web/search",
        params={"q": "OpenMates"},
        headers={"X-Subscription-Token": "free-key"},
        query="OpenMates",
        search_type="web",
        fallback_headers=[("paid", {"X-Subscription-Token": "paid-key"})],
    )

    assert response.status_code == 200
    assert [call["X-Subscription-Token"] for call in client.calls] == ["free-key", "free-key"]
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_candidate_order_uses_one_default_then_explicit_paid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET__BRAVE__API_KEY", "placeholder-env-key")
    secrets_manager = _FakeSecretsManager(
        {
            ("kv/data/providers/brave", "api_key"): "free-vault-key",
            ("kv/data/providers/brave", "paid_api_key"): "paid-vault-key",
        }
    )

    candidates = await _get_brave_api_key_candidates(secrets_manager)

    assert candidates == [
        ("vault:brave:default", "free-vault-key"),
        ("vault:brave:paid", "paid-vault-key"),
    ]
