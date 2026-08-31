# backend/tests/test_daily_ai_test_budget.py
# contract-test-file: infrastructure
#
# Verifies the dev-only real-inference canary budget fails before provider
# dispatch, remains request-scoped, and never changes ordinary inference.
# Contract: architecture.daily-ai-test-inference@2.

import asyncio
import base64
import hashlib
import sys
from decimal import Decimal
from types import ModuleType, SimpleNamespace

import httpx
import pytest

import backend.shared.testing.mock_context as mock_context

from backend.apps.ai.testing.caching_llm_wrapper import (
    _real_request_input_token_upper_bound,
    wrap_provider_with_cache,
)
from backend.shared.testing.api_response_cache import ApiResponseCache
from backend.shared.testing.caching_http_transport import CachingHTTPTransport
from backend.shared.testing.mock_context import (
    DailyAITestBudgetExceeded,
    MAX_REAL_LLM_OUTPUT_TOKENS,
    activate_mock_mode,
    current_daily_real_group,
    deactivate_mock_mode,
    detect_live_marker,
    get_real_budget_summary,
    reserve_real_provider_call,
    resolve_live_marker_or_raise,
    should_reject_disabled_live_marker,
    sign_live_marker,
)


@pytest.mark.asyncio
async def test_backfill_record_shares_the_daily_canary_budget_key(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    async def reserve(_state, group_id, _category, amount):
        captured.append(group_id)
        return amount

    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "redis")
    monkeypatch.setattr(mock_context, "_reserve_in_redis", reserve)
    activate_mock_mode(
        "record",
        "application_preview_share",
        candidate_run_id="daily-cache-backfill-20260831-0123456789ab",
    )
    try:
        await reserve_real_provider_call("llm/test", Decimal("0.01"))
    finally:
        deactivate_mock_mode()

    assert captured == ["daily_canary_20260831"]


def _hash_email(email: str) -> str:
    return base64.b64encode(hashlib.sha256(email.lower().strip().encode()).digest()).decode()


def test_real_marker_is_dev_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "test-secret")
    group = current_daily_real_group()
    assert sign_live_marker(f"<<<TEST_LIVE_REAL:{group}>>>", "ordinary-user") is None
    signed = sign_live_marker(
        f"<<<TEST_LIVE_REAL:{group}>>>",
        "test-user",
        is_allowlisted_test_account=True,
    )
    assert signed is not None
    detected = detect_live_marker(f"hello {signed}", "test-user")
    assert detected is not None
    assert detected.mode == "real"
    assert detected.group_id == group
    assert detected.run_id is None
    assert sign_live_marker(
        "<<<TEST_LIVE_REAL:daily_canary_other>>>",
        "test-user",
        is_allowlisted_test_account=True,
    ) is None
    assert detect_live_marker(f"hello {signed}", "other-user") is None
    assert detect_live_marker(f"hello <<<TEST_LIVE_REAL:{group}>>>", "test-user") is None

    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert detect_live_marker(f"hello {signed}", "test-user") is None


def test_live_real_marker_signing_requires_mock_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "test-secret")
    monkeypatch.delenv("MOCK_EXTERNAL_APIS", raising=False)

    assert sign_live_marker(
        f"<<<TEST_LIVE_REAL:{current_daily_real_group()}>>>",
        "test-user",
        is_allowlisted_test_account=True,
    ) is None


def test_live_record_marker_requires_signed_run_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "test-secret")

    assert sign_live_marker(
        "<<<TEST_LIVE_RECORD:wikipedia_search>>>",
        "test-user",
        is_allowlisted_test_account=True,
    ) is None
    signed = sign_live_marker(
        "<<<TEST_LIVE_RECORD:wikipedia_search:nightly-20260831>>>",
        "test-user",
        is_allowlisted_test_account=True,
    )
    assert signed is not None
    detected = detect_live_marker(signed, "test-user")
    assert detected is not None
    assert detected.mode == "record"
    assert detected.group_id == "wikipedia_search"
    assert detected.run_id == "nightly-20260831"


def test_disabled_live_marker_rejection_is_non_production_only(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = f"literal <<<TEST_LIVE_REAL:{current_daily_real_group()}>>> text"
    monkeypatch.delenv("MOCK_EXTERNAL_APIS", raising=False)

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    assert should_reject_disabled_live_marker(marker) is True

    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert should_reject_disabled_live_marker(marker) is False


def test_resolve_live_marker_rejects_malformed_unknown_and_unsigned_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "test-secret")

    for content in (
        "<<<TEST_LIVE_REAL>>>",
        "<<<TEST_LIVE_BAD:daily_canary_20260830>>>",
        f"<<<TEST_LIVE_REAL:{current_daily_real_group()}>>>",
    ):
        with pytest.raises(RuntimeError, match="Invalid or unauthorized"):
            resolve_live_marker_or_raise(content, "test-user")


def test_resolve_live_marker_treats_production_literal_text_as_ordinary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")

    assert resolve_live_marker_or_raise("literal <<<TEST_LIVE_REAL:daily_canary_20260830>>>", "user") is None


# contract-test: direct surface=cli assertions=daily-ai-tests.budget.shared-hard-cap,daily-ai-tests.reporting.content-free
def test_real_budget_fails_before_thirteenth_default_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "memory")
    monkeypatch.delenv("DAILY_AI_TEST_BUDGET_EUR", raising=False)
    monkeypatch.delenv("DAILY_AI_TEST_CALL_RESERVATION_EUR", raising=False)
    activate_mock_mode("real", current_daily_real_group())
    try:
        for _ in range(12):
            asyncio.run(reserve_real_provider_call("llm/test", Decimal("0.02")))
        with pytest.raises(DailyAITestBudgetExceeded, match="before provider dispatch"):
            asyncio.run(reserve_real_provider_call("llm/test", Decimal("0.02")))

        assert get_real_budget_summary() == {
            "active": True,
            "provider_calls": 12,
            "reserved_eur": 0.24,
            "limit_eur": 0.25,
        }
    finally:
        deactivate_mock_mode()


# contract-test: direct surface=cli assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_ordinary_requests_do_not_consult_test_budget() -> None:
    deactivate_mock_mode()
    for _ in range(20):
        asyncio.run(reserve_real_provider_call("llm/ordinary", Decimal("1")))
    assert get_real_budget_summary() == {
        "active": False,
        "provider_calls": 0,
        "reserved_eur": 0.0,
    }


def test_invalid_budget_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_EUR", "not-a-number")
    with pytest.raises(ValueError, match="must be a decimal"):
        activate_mock_mode("real", current_daily_real_group())

    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_EUR", "0.26")
    with pytest.raises(ValueError, match="cannot exceed EUR 0.25"):
        activate_mock_mode("real", current_daily_real_group())


# contract-test: direct surface=cli assertions=daily-ai-tests.budget.shared-hard-cap
def test_real_llm_wrapper_reserves_before_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "memory")
    provider_calls = 0

    async def provider(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def stream():
            yield "ok"

        return stream()

    async def run() -> list[str]:
        activate_mock_mode("real", current_daily_real_group())
        try:
            wrapped = wrap_provider_with_cache(provider, ApiResponseCache(root=tmp_path))
            response = await wrapped(model="gemma-4-31b", messages=[], stream=True)
            return [chunk async for chunk in response]
        finally:
            deactivate_mock_mode()

    assert asyncio.run(run()) == ["ok"]
    assert provider_calls == 1


def test_real_non_stream_llm_wrapper_reserves_and_clamps_before_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "memory")
    observed_max_tokens = None

    async def provider(**kwargs):
        nonlocal observed_max_tokens
        observed_max_tokens = kwargs.get("max_tokens")
        return "ok"

    async def run() -> str:
        activate_mock_mode("real", current_daily_real_group())
        try:
            wrapped = wrap_provider_with_cache(provider, ApiResponseCache(root=tmp_path))
            return await wrapped(
                model="gemma-4-31b",
                messages=[{"role": "user", "content": "hello"}],
                stream=False,
                max_tokens=999_999,
            )
        finally:
            deactivate_mock_mode()

    assert asyncio.run(run()) == "ok"
    assert observed_max_tokens == MAX_REAL_LLM_OUTPUT_TOKENS


# contract-test: direct surface=cli assertions=daily-ai-tests.budget.shared-hard-cap,daily-ai-tests.cache.manual-transactional-promotion
def test_record_llm_wrapper_reserves_and_clamps_before_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "memory")
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_EUR", "0.0005")
    monkeypatch.setattr(
        "backend.apps.ai.testing.caching_llm_wrapper.conservative_llm_reservation_eur",
        lambda *_args, **_kwargs: Decimal("0.001"),
    )
    provider_calls = 0
    observed_max_tokens = None

    async def provider(**kwargs):
        nonlocal provider_calls, observed_max_tokens
        provider_calls += 1
        observed_max_tokens = kwargs.get("max_tokens")
        return "should not dispatch"

    async def run() -> None:
        activate_mock_mode("record", current_daily_real_group(), tmp_path / "candidate")
        try:
            wrapped = wrap_provider_with_cache(provider, ApiResponseCache(root=tmp_path))
            with pytest.raises(DailyAITestBudgetExceeded, match="before provider dispatch"):
                await wrapped(
                    model="test-model",
                    messages=[{"role": "user", "content": "hello"}],
                    stream=False,
                    max_tokens=999_999,
                )
        finally:
            deactivate_mock_mode()

    asyncio.run(run())

    assert provider_calls == 0
    assert observed_max_tokens is None


def test_real_llm_input_reservation_uses_utf8_byte_upper_bound() -> None:
    message = {"role": "user", "content": "emoji: 🙂"}
    bound = _real_request_input_token_upper_bound({"messages": [message], "tools": None})

    assert bound >= len(message["content"].encode("utf-8"))
    assert bound > len(message["content"])


# contract-test: direct surface=cli assertions=daily-ai-tests.budget.shared-hard-cap,daily-ai-tests.replay.cache-miss-fails-closed
def test_real_http_wrapper_is_rejected_before_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "memory")
    class RealTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.calls = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(200, json={"ok": True}, request=request)

    async def run() -> int:
        real_transport = RealTransport()
        transport = CachingHTTPTransport(
            real_transport=real_transport,
            cache=ApiResponseCache(root=tmp_path),
            category="test",
        )
        activate_mock_mode("real", current_daily_real_group())
        try:
            with pytest.raises(DailyAITestBudgetExceeded, match="do not allow"):
                await transport.handle_async_request(
                    httpx.Request("GET", "https://example.invalid/test")
                )
            return real_transport.calls
        finally:
            deactivate_mock_mode()

    assert asyncio.run(run()) == 0


# contract-test: direct surface=cli assertions=daily-ai-tests.replay.cache-miss-fails-closed,daily-ai-tests.isolation.ordinary-inference-unchanged
def test_live_context_rejects_unregistered_raw_httpx_dispatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "memory")

    async def run() -> None:
        activate_mock_mode("record", current_daily_real_group(), tmp_path / "candidate")
        try:
            with pytest.raises(DailyAITestBudgetExceeded, match="unregistered raw HTTP provider dispatch"):
                async with httpx.AsyncClient(timeout=0.01) as client:
                    await client.get("https://example.invalid/live-test-bypass")
        finally:
            deactivate_mock_mode()

    asyncio.run(run())


# contract-test: direct surface=cli assertions=daily-ai-tests.replay.cache-miss-fails-closed,daily-ai-tests.isolation.ordinary-inference-unchanged
def test_live_context_rejects_unregistered_requests_send_dispatch(tmp_path, monkeypatch) -> None:
    requests = pytest.importorskip("requests")
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "memory")

    class FakeAdapter(requests.adapters.BaseAdapter):
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request, **_kwargs):
            self.calls += 1
            response = requests.Response()
            response.status_code = 204
            response.url = request.url
            response.request = request
            return response

        def close(self) -> None:
            pass

    session = requests.Session()
    adapter = FakeAdapter()
    session.mount("https://", adapter)
    request = requests.Request("GET", "https://example.invalid/live-test-bypass").prepare()

    activate_mock_mode("record", current_daily_real_group(), tmp_path / "candidate")
    try:
        with pytest.raises(DailyAITestBudgetExceeded, match="unregistered raw HTTP provider dispatch"):
            session.send(request)
    finally:
        deactivate_mock_mode()

    assert adapter.calls == 0
    assert session.send(request).status_code == 204
    assert adapter.calls == 1


# contract-test: direct surface=cli assertions=daily-ai-tests.budget.shared-hard-cap,daily-ai-tests.isolation.ordinary-inference-unchanged
def test_ws_auth_cached_profile_enables_signed_daily_real_budget_path(tmp_path, monkeypatch) -> None:
    redis_module = ModuleType("redis")
    redis_asyncio_module = ModuleType("redis.asyncio")
    redis_asyncio_module.Redis = object
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(ConnectionError=ConnectionError)
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_asyncio_module)
    directus_module = ModuleType("backend.core.api.app.services.directus")
    directus_module.DirectusService = object
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.directus", directus_module)

    from backend.core.api.app.routes import auth_ws
    from backend.shared.python_utils.e2e_user_detection import is_configured_test_account_profile

    token = "refresh-token"
    user_id = "user-1"
    test_email = "testacct1@example.test"
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    class FakeCache:
        SESSION_KEY_PREFIX = "session:"
        USER_KEY_PREFIX = "user_profile:"

        async def get(self, key: str):
            if key == f"session:{token_hash}":
                return {"user_id": user_id}
            if key == f"user_profile:{user_id}":
                return {"id": user_id, "hashed_email": _hash_email(test_email)}
            return None

        async def get_user_by_id(self, requested_user_id: str):
            return await self.get(f"user_profile:{requested_user_id}")

    class FakeDirectus:
        async def get_user_device_hashes(self, requested_user_id: str):
            assert requested_user_id == user_id
            return ["device-hash"]

    fake_ws = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(cache_service=FakeCache(), directus_service=FakeDirectus())),
        cookies={"auth_refresh_token": token},
        query_params={"sessionId": "session-1"},
        headers={},
        close=lambda **_kwargs: None,
    )
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "test-secret")
    monkeypatch.setenv("DAILY_AI_TEST_BUDGET_BACKEND", "memory")
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_EMAIL", test_email)
    monkeypatch.setattr(
        auth_ws,
        "generate_device_fingerprint_hash",
        lambda *_args, **_kwargs: (
            "device-hash",
            "connection-hash",
            None,
            None,
            None,
            None,
            None,
            None,
        ),
    )
    monkeypatch.setattr(auth_ws.ComplianceService, "log_auth_event_safe", lambda **_kwargs: None)

    async def run() -> dict:
        auth_data = await auth_ws.get_current_user_ws(fake_ws)
        assert auth_data is not None
        assert auth_data["user_id"] == user_id
        assert is_configured_test_account_profile(auth_data["user_data"]) is True

        group = current_daily_real_group()
        signed_marker = sign_live_marker(
            f"<<<TEST_LIVE_REAL:{group}>>>",
            user_id,
            is_allowlisted_test_account=is_configured_test_account_profile(auth_data["user_data"]),
        )
        assert signed_marker is not None
        detected = detect_live_marker(signed_marker, user_id)
        assert detected is not None
        assert detected.mode == "real"
        assert detected.group_id == group
        assert detected.run_id is None

        provider_calls = 0

        async def provider(**_kwargs):
            nonlocal provider_calls
            provider_calls += 1

            async def stream():
                yield "ok"

            return stream()

        activate_mock_mode(detected.mode, detected.group_id, candidate_run_id=detected.run_id)
        try:
            wrapped = wrap_provider_with_cache(provider, ApiResponseCache(root=tmp_path))
            response = await wrapped(model="gemma-4-31b", messages=[], stream=True)
            assert [chunk async for chunk in response] == ["ok"]
            summary = get_real_budget_summary()
        finally:
            deactivate_mock_mode()

        assert provider_calls == 1
        return summary

    summary = asyncio.run(run())
    assert summary["active"] is True
    assert summary["provider_calls"] == 1
    assert summary["reserved_eur"] > 0
    assert summary["reserved_eur"] <= summary["limit_eur"] <= 0.25
