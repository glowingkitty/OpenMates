"""Personal chat output bounds recover from an unavailable cache projection."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.processing import main_processor
from backend.core.api.app.services.billing_service import BillingService


def _request() -> SimpleNamespace:
    user_id = "00000000-0000-4000-8000-000000000001"
    return SimpleNamespace(
        user_id=user_id,
        user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(),
    )


async def _fit(cache: SimpleNamespace, *, directus_service: object = ...) -> int:
    if directus_service is ...:
        directus_service = SimpleNamespace()
    return await main_processor._fit_personal_chat_output_token_limit(
        request_data=_request(),
        cache_service=cache,
        directus_service=directus_service,
        encryption_service=SimpleNamespace(),
        model_usage_tracker=SimpleNamespace(usage_by_model=[]),
        model_id="test/model",
        system_prompt="system",
        message_history=[],
        tools=None,
        requested_output_token_limit=512,
        inference_host="test",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [
    None, {"credits": None}, {"credits": "100"}, {"credits": True},
    {"credits": 1.5}, RuntimeError("cache unavailable"),
])
# contract-test: supporting surface=rest_api assertions=billing.credits.encrypted-authority-cache-projection
async def test_missing_cache_balance_uses_durable_wallet(monkeypatch: pytest.MonkeyPatch, profile: object) -> None:
    authoritative = AsyncMock(return_value=125)
    monkeypatch.setattr(BillingService, "get_authoritative_personal_balance", authoritative)
    quote = Mock(return_value=64)
    monkeypatch.setattr(main_processor, "_max_affordable_ai_output_tokens", quote)
    monkeypatch.setattr(main_processor, "_normal_chat_cache_pricing_scope", lambda _request: False)
    lookup = (
        AsyncMock(side_effect=profile) if isinstance(profile, Exception)
        else AsyncMock(return_value=profile)
    )
    cache = SimpleNamespace(get_user_by_id=lookup)

    assert await _fit(cache) == 64
    authoritative.assert_awaited_once_with(
        user_id=_request().user_id, user_id_hash=_request().user_id_hash,
    )
    assert quote.call_args.kwargs["available_credits"] == 625


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.encrypted-authority-cache-projection
async def test_durable_balance_failure_aborts_before_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    authoritative = AsyncMock(side_effect=RuntimeError("durable wallet unavailable"))
    monkeypatch.setattr(BillingService, "get_authoritative_personal_balance", authoritative)
    quote = Mock(return_value=64)
    monkeypatch.setattr(main_processor, "_max_affordable_ai_output_tokens", quote)
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={"credits": None}))

    with pytest.raises(main_processor.AuthenticatedReservationError, match="balance is unavailable"):
        await _fit(cache)
    authoritative.assert_awaited_once()
    quote.assert_not_called()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.encrypted-authority-cache-projection
async def test_valid_cache_balance_keeps_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    authoritative = AsyncMock(side_effect=AssertionError("durable read is not needed"))
    monkeypatch.setattr(BillingService, "get_authoritative_personal_balance", authoritative)
    quote = Mock(return_value=64)
    monkeypatch.setattr(main_processor, "_max_affordable_ai_output_tokens", quote)
    monkeypatch.setattr(main_processor, "_normal_chat_cache_pricing_scope", lambda _request: False)
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={"credits": 200}))

    assert await _fit(cache) == 64
    authoritative.assert_not_awaited()
    assert quote.call_args.kwargs["available_credits"] == 700


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.encrypted-authority-cache-projection
async def test_missing_cache_balance_without_services_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    authoritative = AsyncMock(return_value=125)
    monkeypatch.setattr(BillingService, "get_authoritative_personal_balance", authoritative)
    quote = Mock(return_value=64)
    monkeypatch.setattr(main_processor, "_max_affordable_ai_output_tokens", quote)
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={"credits": None}))

    with pytest.raises(main_processor.AuthenticatedReservationError, match="balance is unavailable"):
        await _fit(cache, directus_service=None)
    authoritative.assert_not_awaited()
    quote.assert_not_called()
