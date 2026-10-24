# backend/tests/test_brave_search_provider.py
#
# Unit tests for Brave Search provider request handling.
# Covers free-key quota exhaustion fallback and transient 429 retry behavior.
# Tests use mocked HTTP responses only; no live Brave API calls are made.
#
# Architecture: docs/architecture/apps/app-skills.md

import asyncio
from contextlib import asynccontextmanager
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.shared.providers.brave.brave_search import (
    _get_brave_api_key_candidates,
    _is_monthly_quota_limited,
    _parse_retry_after_seconds,
    _request_with_429_retry,
    search_web,
)
from backend.shared.providers.brave.rate_limit import (
    BraveRateGate, LEARN_LIMIT, RESERVE_SLOT, MAX_QUEUE_WAIT_MS,
)
from backend.shared.testing.mock_context import activate_mock_mode, deactivate_mock_mode

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def isolated_rate_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit checks never open a connection to a product cache."""
    @asynccontextmanager
    async def gate():
        yield BraveRateGate(None)

    monkeypatch.setattr("backend.shared.providers.brave.brave_search.brave_rate_gate", gate)


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


class _RateCache:
    """Virtual-time cache boundary; isolated E2E also executes the real Lua in Redis."""
    def __init__(self) -> None:
        self.values: dict[str, tuple[int, float]] = {}
        self.keys: set[str] = set()

    @staticmethod
    def now_ms() -> float:
        return time.monotonic() * 100_000

    async def eval(self, script: str, count: int, interval_key: str, queue_key: str, *args) -> int:
        assert count == 2
        self.keys.update((interval_key, queue_key))
        now = self.now_ms()
        period, expiry = self.values.get(interval_key, (0, 0))
        remaining = max(0, self.values.get(queue_key, (0, now))[1] - now)
        if script == RESERVE_SLOT:
            if expiry <= now:
                return 0
            if remaining > args[0]:
                return -1
            self.values[queue_key] = (1, now + remaining + period)
            return int(remaining)
        assert script == LEARN_LIMIT
        period, cooldown, ttl = args
        self.values[interval_key] = (period, now + ttl * 1000)
        self.values[queue_key] = (1, now + max(remaining, cooldown))
        return 1


# contract-test: supporting surface=rest_api assertions=web-search.provider-error.visible,web-search.secrets.never-exposed
async def test_concurrent_requests_share_actual_credential_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eight competing callers must not exhaust six synchronized retry waves."""
    cache = _RateCache()
    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(seconds / 100)

    @asynccontextmanager
    async def gate():
        # Separate gate objects represent independent provider clients/workers.
        yield BraveRateGate(cache)

    monkeypatch.setattr("backend.shared.providers.brave.brave_search.brave_rate_gate", gate)
    monkeypatch.setattr("backend.shared.providers.brave.brave_search.asyncio.sleep", fast_sleep)
    accepted_at: list[float] = []
    attempts: list[int] = []

    class Provider:
        async def get(self, url, params, headers):
            attempts.append(params["id"])
            now = cache.now_ms()
            if accepted_at and now - accepted_at[-1] < 1000:
                return _response(429, {"error": {"code": "RATE_LIMITED", "meta": {"rate_limit": 1}}})
            accepted_at.append(now)
            response = _response(200)
            response.headers["X-RateLimit-Limit"] = "1, 2000"
            return response

    responses = await asyncio.gather(*[
        _request_with_429_retry(
            Provider(), "https://fixture.invalid/search", {"id": index},
            {"X-Subscription-Token": "private-unit-key"}, "synthetic query",
        )
        for index in range(8)
    ])
    assert len(responses) == len(accepted_at) == 8
    assert all(response.status_code == 200 for response in responses)
    assert all(attempts.count(index) <= 2 for index in range(8))
    assert all(right - left >= 1000 for left, right in zip(accepted_at, accepted_at[1:]))
    assert all("private-unit-key" not in key for key in cache.keys)


# contract-test: supporting surface=rest_api assertions=web-search.provider-error.visible
async def test_rate_queue_is_credential_scoped_and_bounded() -> None:
    cache = _RateCache()
    gate = BraveRateGate(cache)
    first = {"X-Subscription-Token": "first-placeholder"}
    other = {"X-Subscription-Token": "second-placeholder"}
    response = _response(429, {"error": {"code": "RATE_LIMITED", "meta": {"rate_limit": 1}}})
    await gate.observe(first, response, 1.1)
    interval_key, queue_key = gate._keys(first)
    cache.values[queue_key] = (1, cache.now_ms() + MAX_QUEUE_WAIT_MS + 1000)
    await gate.wait(other)
    assert gate._keys(other)[0] not in cache.values
    with pytest.raises(httpx.TimeoutException, match="queue is temporarily full"):
        await gate.wait(first)
    assert cache.values[interval_key][0] == 1100


@pytest.mark.parametrize("reset,expected", [("1, 1419704", 1), ("2", 2), ("invalid", 1.1)])
# contract-test: supporting surface=rest_api assertions=web-search.provider-error.visible
async def test_brave_reset_headers_are_relative_seconds(reset: str, expected: float) -> None:
    response = _response(429)
    response.headers["X-RateLimit-Reset"] = reset
    assert _parse_retry_after_seconds(response) == expected
