"""Keep native-cache replay's internal HTTP allowance inside isolated CI."""

# contract-test-file: infrastructure

import httpx
import pytest

from backend.shared.testing import mock_context
from backend.shared.testing.mock_context import (
    DailyAITestBudgetExceeded,
    activate_mock_mode,
    deactivate_mock_mode,
    get_live_mock_receipt,
)


def _native_fixture_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "CI": "true",
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_CI_AI_FIXTURES": "1",
        "MOCK_EXTERNAL_APIS": "true",
        "SERVER_ENVIRONMENT": "development",
        "CMS_URL": "http://cms:8055",
        "VAULT_URL": "http://vault:8200",
        "INTERNAL_API_BASE_URL": "http://api:8000",
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("S3_ENDPOINT_URL", "OPENMATES_STORAGE_CAPACITY_FIXTURES", "HTTPS_PROXY"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.asyncio
async def test_native_mock_allows_only_isolated_internal_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    _native_fixture_environment(monkeypatch)
    dispatched: list[str] = []

    async def fake_async(_transport, request):
        dispatched.append(f"{request.method} {request.url}")
        return httpx.Response(204, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_async)
    activate_mock_mode("mock", "native_cache_tools_v1", task_id="native-fixture-task")
    try:
        mock_context._install_httpx_transport_guard()
        allowed = [
            ("GET", "http://cms:8055/items/chats"),
            ("POST", "http://cms:8055/chat-recovery-transaction"),
            ("GET", "http://vault:8200/v1/kv/data/user-keys"),
            ("POST", "http://api:8000/internal/billing/reserve"),
            ("POST", "http://api:8000/internal/billing/charge"),
            ("POST", "http://api:8000/internal/billing/reservation/release"),
        ]
        for method, url in allowed:
            response = await httpx.AsyncHTTPTransport.handle_async_request(
                object(), httpx.Request(method, url),
            )
            assert response.status_code == 204

        blocked = [
            ("GET", "https://api.openai.com/v1/responses"),
            ("GET", "http://cms:8056/items/chats"),
            ("GET", "https://cms:8055/items/chats"),
            ("GET", "http://vault:8200/not-v1/kv/data/user-keys"),
            ("GET", "http://api:8000/internal/billing/charge"),
            ("POST", "http://api:8000/internal/billing/charge?override=1"),
            ("POST", "http://api:8000/internal/billing/charge/other"),
            ("POST", "http://api:8000/internal/billing/team/reserve"),
            ("POST", "http://api:8000/internal/billing/team/charge"),
            ("POST", "http://api:8000@evil.example/internal/billing/charge"),
        ]
        for method, url in blocked:
            with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
                await httpx.AsyncHTTPTransport.handle_async_request(
                    object(), httpx.Request(method, url),
                )
        assert dispatched == [f"{method} {url}" for method, url in allowed]
        assert mock_context.live_mock_receipt_var.get().blocked_provider_calls == len(blocked)
        assert get_live_mock_receipt()["real_provider_calls"] == 0
    finally:
        deactivate_mock_mode()


@pytest.mark.parametrize("invalid", [
    {"CI": "false"},
    {"OPENMATES_CI_ISOLATED": "0"},
    {"OPENMATES_CI_AI_FIXTURES": "0"},
    {"MOCK_EXTERNAL_APIS": "false"},
    {"SERVER_ENVIRONMENT": "production"},
    {"CMS_URL": "http://other:8055"},
    {"VAULT_URL": "http://other:8200"},
    {"S3_ENDPOINT_URL": "http://storage.ci.test:9000"},
    {"OPENMATES_STORAGE_CAPACITY_FIXTURES": "true"},
    {"HTTPS_PROXY": "http://proxy.example"},
])
def test_native_mock_rejects_nonmarker_profiles(monkeypatch: pytest.MonkeyPatch, invalid: dict[str, str]) -> None:
    _native_fixture_environment(monkeypatch)
    for key, value in invalid.items():
        monkeypatch.setenv(key, value)
    activate_mock_mode("mock", "native_cache_tools_v1", task_id="native-fixture-task")
    try:
        assert not mock_context._allow_isolated_capacity_internal("http://cms:8055/items/chats", "GET")
        assert not mock_context._allow_isolated_capacity_internal(
            "http://api:8000/internal/billing/charge", "POST",
        )
    finally:
        deactivate_mock_mode()


def test_native_mock_requires_exact_group_and_task(monkeypatch: pytest.MonkeyPatch) -> None:
    _native_fixture_environment(monkeypatch)
    for group, task_id in (("native_cache_tools_v2", "task"), ("other_flow", "task"),
                           ("native_cache_tools_v1", None)):
        activate_mock_mode("mock", group, task_id=task_id)
        try:
            assert not mock_context._allow_isolated_capacity_internal("http://cms:8055/items/chats", "GET")
        finally:
            deactivate_mock_mode()
