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
    _is_monthly_quota_limited,
    _request_with_429_retry,
    search_web,
)
from backend.shared.testing.mock_context import activate_mock_mode, deactivate_mock_mode

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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


# contract-test: supporting surface=rest_api assertions=web-search.provider-error.visible
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


# contract-test: supporting surface=rest_api assertions=web-search.provider-error.visible
async def test_monthly_quota_exhaustion_without_fallback_fails_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    client = _FakeClient([free_quota_response])
    sleep_mock = AsyncMock()
    monkeypatch.setattr("backend.shared.providers.brave.brave_search.asyncio.sleep", sleep_mock)

    with pytest.raises(httpx.HTTPStatusError):
        await _request_with_429_retry(
            client=client,
            url="https://api.search.brave.com/res/v1/web/search",
            params={"q": "OpenMates"},
            headers={"X-Subscription-Token": "free-key"},
            query="OpenMates",
            search_type="web",
        )

    assert [call["X-Subscription-Token"] for call in client.calls] == ["free-key"]
    sleep_mock.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-search.provider-error.visible
async def test_transient_rate_limit_retries_without_paid_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    transient_response = _response(
        429,
        {
            "error": {
                "code": "RATE_LIMITED",
                "detail": "Request rate limit exceeded for plan",
                "meta": {
                    "rate_limit": 1,
                    "rate_current": 1,
                    "quota_limit": 2000,
                    "quota_current": 1195,
                },
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


@pytest.mark.parametrize(
    ("code", "quota_limit", "quota_current", "expected"),
    [
        ("RATE_LIMITED", 2000, 2000, False),
        ("QUOTA_LIMITED", 2000, 1195, True),
        (None, 2000, 2000, True),
        (None, False, True, False),
    ],
)
# contract-test: supporting surface=rest_api assertions=web-search.provider-error.visible
async def test_monthly_quota_classification(
    code: str | None,
    quota_limit: int | bool,
    quota_current: int | bool,
    expected: bool,
) -> None:
    response = _response(
        429,
        {
            "error": {
                "code": code,
                "meta": {
                    "quota_limit": quota_limit,
                    "quota_current": quota_current,
                },
            }
        },
    )

    assert _is_monthly_quota_limited(response) is expected


# contract-test: supporting surface=rest_api assertions=web-search.provider-error.visible
async def test_exhausted_transient_rate_limit_uses_paid_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    transient_responses = [
        _response(
            429,
            {
                "error": {
                    "code": "RATE_LIMITED",
                    "detail": "Too many requests.",
                    "meta": {"rate_limit": 1, "rate_current": 1},
                }
            },
        )
        for _ in range(6)
    ]
    paid_success_response = _response(200, {"web": {"results": []}})
    client = _FakeClient([*transient_responses, paid_success_response])
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
    assert [call["X-Subscription-Token"] for call in client.calls] == [
        "free-key",
        "free-key",
        "free-key",
        "free-key",
        "free-key",
        "free-key",
        "paid-key",
    ]
    assert sleep_mock.await_count == 5


# contract-test: supporting surface=rest_api assertions=web-search.provider-error.visible
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


# contract-test: supporting surface=rest_api assertions=web-search.no-results.explicit
async def test_live_mock_zero_result_group_forces_empty_web_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    activate_mock_mode("mock", "web_search_zero_results")
    secrets_manager = _FakeSecretsManager({})

    try:
        result = await search_web(
            "xyznonexistentproduct123456 lokale API MQTT",
            secrets_manager=secrets_manager,
        )
    finally:
        deactivate_mock_mode()

    assert result == {
        "query": "xyznonexistentproduct123456 lokale API MQTT",
        "results": [],
        "web": {"total_results": 0, "count": 0},
        "error": None,
        "sanitize_output": True,
    }
