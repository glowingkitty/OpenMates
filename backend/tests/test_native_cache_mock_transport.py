"""Keep native-cache replay's internal HTTP allowance inside isolated CI."""

# contract-test-file: infrastructure

import base64

import httpx
import pytest

from backend.core.api.app.utils.encryption import EncryptionService
from backend.shared.testing import mock_context
from backend.shared.testing.mock_context import (
    DailyAITestBudgetExceeded,
    activate_mock_mode,
    deactivate_mock_mode,
    get_live_mock_receipt,
    resolve_live_marker_or_raise,
    sign_live_marker,
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
@pytest.mark.parametrize("group", ["native_cache_tools_v1", "diagram_html_web", "web_search_web", "web_search_zero_results"])
async def test_signed_mock_allows_only_isolated_internal_transport(
    monkeypatch: pytest.MonkeyPatch, group: str,
) -> None:
    _native_fixture_environment(monkeypatch)
    dispatched: list[str] = []

    async def fake_async(_transport, request):
        dispatched.append(f"{request.method} {request.url}")
        return httpx.Response(204, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_async)
    activate_mock_mode("mock", group, task_id="signed-fixture-task")
    try:
        mock_context._install_httpx_transport_guard()
        allowed = [
            ("GET", "http://cms:8055/items/chats"),
            ("POST", "http://cms:8055/chat-recovery-transaction"),
            ("GET", "http://vault:8200/v1/kv/data/user-keys"),
            ("POST", "http://vault:8200/v1/transit/decrypt/test-user-key"),
            ("POST", "http://api:8000/internal/billing/reserve"),
            ("POST", "http://api:8000/internal/billing/charge"),
            ("POST", "http://api:8000/internal/billing/reservation/release"),
        ]
        image_resolver = ("POST", "http://api:8000/internal/uploads/resolve-image")
        for method, url in allowed:
            response = await httpx.AsyncHTTPTransport.handle_async_request(
                object(), httpx.Request(method, url),
            )
            assert response.status_code == 204

        blocked = [
            ("GET", "https://api.openai.com/v1/responses"),
            ("POST", "https://api.typesafe.ai/v1/systemone"),
            ("POST", "https://generativelanguage.googleapis.com/v1beta/models/test:generateContent"),
            ("GET", "http://cms:8056/items/chats"),
            ("GET", "https://cms:8055/items/chats"),
            ("GET", "http://vault:8200/not-v1/kv/data/user-keys"),
            ("GET", "http://api:8000/internal/billing/charge"),
            ("POST", "http://api:8000/internal/billing/charge?override=1"),
            ("POST", "http://api:8000/internal/billing/charge/other"),
            ("POST", "http://api:8000/internal/billing/team/reserve"),
            ("POST", "http://api:8000/internal/billing/team/charge"),
            ("POST", "http://api:8000@evil.example/internal/billing/charge"),
            ("GET", "http://api:8000/internal/uploads/resolve-image"),
            ("POST", "http://api:8000/internal/uploads/resolve-image?override=1"),
            ("POST", "http://api:8000/internal/uploads/resolve-image/other"),
            ("POST", "http://api:8001/internal/uploads/resolve-image"),
        ]
        blocked.append(image_resolver)
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


@pytest.mark.parametrize("group", ["native_cache_tools_v1", "diagram_html_web", "web_search_web", "web_search_zero_results"])
@pytest.mark.parametrize("invalid", [
    {"CI": "false"},
    {"OPENMATES_CI_ISOLATED": "0"},
    {"OPENMATES_CI_AI_FIXTURES": "0"},
    {"MOCK_EXTERNAL_APIS": "false"},
    {"SERVER_ENVIRONMENT": "production"},
    {"CMS_URL": "http://other:8055"},
    {"VAULT_URL": "http://other:8200"},
    {"S3_ENDPOINT_URL": "http://other-storage.ci.test:9000"},
    {"OPENMATES_STORAGE_CAPACITY_FIXTURES": "true"},
    {"HTTPS_PROXY": "http://proxy.example"},
])
def test_signed_mock_rejects_nonmarker_profiles(
    monkeypatch: pytest.MonkeyPatch, group: str, invalid: dict[str, str],
) -> None:
    _native_fixture_environment(monkeypatch)
    for key, value in invalid.items():
        monkeypatch.setenv(key, value)
    activate_mock_mode("mock", group, task_id="signed-fixture-task")
    try:
        assert not mock_context._allow_isolated_capacity_internal("http://cms:8055/items/chats", "GET")
        assert not mock_context._allow_isolated_capacity_internal(
            "http://api:8000/internal/billing/charge", "POST",
        )
    finally:
        deactivate_mock_mode()


@pytest.mark.parametrize("group", ["native_cache_tools_v1", "diagram_html_web", "web_search_web", "web_search_zero_results"])
def test_native_replay_rejects_storage_and_temp_upload_exceptions(monkeypatch, group):
    _native_fixture_environment(monkeypatch)
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://storage.ci.test:9000")
    activate_mock_mode("mock", group, task_id="signed-fixture-task")
    try:
        expected = False
        assert mock_context._allow_isolated_capacity_internal("http://cms:8055/items/chats", "GET") is expected
        assert mock_context._allow_isolated_capacity_internal("http://api:8000/internal/s3/upload-temp-image", "POST") is expected
    finally:
        deactivate_mock_mode()


def test_native_mock_requires_exact_group_and_task(monkeypatch: pytest.MonkeyPatch) -> None:
    _native_fixture_environment(monkeypatch)
    for group, task_id in (("native_cache_tools_v2", "task"), ("diagram_html_web_v2", "task"),
                           ("shopping_images_web_v2", "task"),
                           ("other_flow", "task"), ("native_cache_tools_v1", None),
                           ("diagram_html_web", None), ("shopping_images_web", None),
                           ("web_search_web_v2", "task"), ("web_search_zero_results_v2", "task"),
                           ("web_search_web", None), ("web_search_zero_results", None)):
        activate_mock_mode("mock", group, task_id=task_id)
        try:
            assert not mock_context._allow_isolated_capacity_internal("http://cms:8055/items/chats", "GET")
        finally:
            deactivate_mock_mode()


@pytest.mark.parametrize("group", ["diagram_html_web", "web_search_web", "web_search_zero_results"])
def test_internal_transport_requires_signed_replay_marker(
    monkeypatch: pytest.MonkeyPatch, group: str,
) -> None:
    _native_fixture_environment(monkeypatch)
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "isolated-fixture-test-secret")
    marker = f"<<<TEST_LIVE_MOCK:{group}>>>"
    with pytest.raises(RuntimeError, match="Invalid or unauthorized"):
        resolve_live_marker_or_raise(marker, "test-user")
    signed = sign_live_marker(marker, "test-user", is_allowlisted_test_account=True)
    assert signed is not None
    validated = resolve_live_marker_or_raise(signed, "test-user")
    assert validated is not None
    activate_mock_mode(validated.mode, validated.group_id, task_id="signed-fixture-task")
    try:
        assert mock_context._allow_isolated_capacity_internal(
            "http://cms:8055/items/user_credits", "GET",
        )
        assert not mock_context._allow_isolated_capacity_internal(
            "https://api.openai.com/v1/responses", "POST",
        )
    finally:
        deactivate_mock_mode()

    activate_mock_mode("record", group, task_id="signed-fixture-task")
    try:
        assert not mock_context._allow_isolated_capacity_internal(
            "http://cms:8055/items/user_credits", "GET",
        )
    finally:
        deactivate_mock_mode()


@pytest.mark.parametrize("method,url", [
    ("GET", "http://cms:8055/items/chats"),
    ("POST", "http://api:8000/internal/billing/charge"),
    ("POST", "http://api:8000/internal/s3/upload-temp-image"),
    ("DELETE", "http://api:8000/internal/s3/temp-image?s3_key=reverse_search/1234.png"),
    ("POST", "http://api:8000/internal/uploads/resolve-image"),
])
def test_retired_shopping_replay_has_no_internal_transport_allowances(monkeypatch, method, url):
    _native_fixture_environment(monkeypatch)
    activate_mock_mode("mock", "shopping_images_web", task_id="retired-fixture-task")
    try:
        assert not mock_context._allow_isolated_capacity_internal(url, method)
    finally:
        deactivate_mock_mode()


@pytest.mark.asyncio
@pytest.mark.parametrize("group", ["web_search_web", "web_search_zero_results"])
@pytest.mark.parametrize("cached_validation", [False, True])
async def test_web_replay_decrypts_isolated_context_without_provider_credentials(
    monkeypatch: pytest.MonkeyPatch, group: str, cached_validation: bool,
) -> None:
    _native_fixture_environment(monkeypatch)
    for name in ("HTTP_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    dispatched: list[str] = []
    plaintext = '{"synthetic_context":true}'

    async def fake_async(_transport, request):
        assert request.url.host == "vault" and request.url.port == 8200
        dispatched.append(request.url.path)
        if request.url.path == "/v1/auth/token/lookup-self":
            assert request.method == "GET"
            data = {"policies": ["synthetic-api-encryption"]}
        else:
            assert request.url.path == "/v1/transit/decrypt/synthetic-user-key"
            assert request.method == "POST"
            data = {"plaintext": base64.b64encode(plaintext.encode()).decode()}
        return httpx.Response(200, json={"data": data}, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_async)
    activate_mock_mode("mock", group, task_id="signed-fixture-task")
    try:
        mock_context._install_httpx_transport_guard()
        # Skip token-file initialization: every value and HTTP response is synthetic.
        encryption = EncryptionService.__new__(EncryptionService)
        encryption.vault_url = "http://vault:8200"
        encryption.transit_mount = "transit"
        encryption.vault_token = "synthetic-token"
        encryption._token_valid_until = float("inf") if cached_validation else 0
        encryption._token_validation_ttl = 300
        encryption._get_token_from_file = lambda: None

        assert await encryption.decrypt_with_user_key(
            "vault:v1:synthetic-ciphertext", "synthetic-user-key",
        ) == plaintext
        assert dispatched == (["/v1/transit/decrypt/synthetic-user-key"] if cached_validation else [
            "/v1/auth/token/lookup-self", "/v1/transit/decrypt/synthetic-user-key",
        ])
        with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
            await httpx.AsyncHTTPTransport.handle_async_request(
                object(), httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
            )
        assert mock_context.live_mock_receipt_var.get().blocked_provider_calls == 1
        assert get_live_mock_receipt()["real_provider_calls"] == 0
    finally:
        deactivate_mock_mode()
