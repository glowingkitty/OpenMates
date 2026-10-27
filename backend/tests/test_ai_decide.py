"""Public typed decision validation, bounded attempts, and metering contracts."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from backend.apps.ai.skills import decide_skill
from backend.shared.providers.typesafe.client import JevDecisionClient
from backend.shared.python_utils.ai_decide import (
    DecideRequest, DecisionExecutionError, account_decision_attempts, decision_configuration,
    decision_quote, decision_result_credits, validate_decision_answers,
)
from backend.shared.providers.typesafe.models import DecisionResponse


BODY = {"state": {"message": "Reset my password"}, "questions": {
    "route": {"type": "choice", "instructions": "Choose a queue.", "criteria": {"account": "Account access", "billing": "Payments"}},
    "safe": {"type": "noul", "instructions": "Is this safe?"},
    "priority": {"type": "score", "instructions": "Rate priority.", "criteria": ["Low", "High"]},
}}
ANSWER = {"model": "jev-1.14.0", "answers": {
    "route": {"type": "choice", "choice": "account", "probabilities": {"account": .9, "billing": .1}, "confidence": .8},
    "safe": {"type": "noul", "noul": .95},
    "priority": {"type": "score", "score": .8, "legend": {"0": "Low", "1": "High"}, "probabilities": {"0": .2, "1": .8}, "confidence": .6},
}, "usage": {"input_tokens": 15_800, "output_tokens": 30}}


# contract-test: direct surface=rest_api assertions=ai-decide.request.bounded
@pytest.mark.parametrize("patch", [
    {"model": "other/model"}, {"usage": {"credits": 0}}, {"credits": 0},
    {"state": "é" * 9000}, {"questions": {}},
    {"questions": {"q": {"type": "choice", "instructions": "route", "criteria": {"one": "Only"}}}},
    {"questions": {"q": {"type": "score", "instructions": "rate", "criteria": ["Only"]}}},
    {"questions": {"q": {"type": "noul", "instructions": "safe?", "unknown": True}}},
    {"questions": {"q": {"type": "noul", "instructions": "safe?", "criteria": {"true": "True only"}}}},
    {"questions": {str(i): {"type": "noul", "instructions": "safe?"} for i in range(17)}},
])
# contract-test: supporting surface=rest_api assertions=ai-decide.request.bounded
def test_invalid_requests_fail_before_dispatch(patch: dict) -> None:
    with pytest.raises(ValidationError):
        DecideRequest.model_validate({**BODY, **patch})


# contract-test: direct surface=rest_api assertions=ai-decide.answers.typed
def test_all_answer_types_match_the_requested_categories() -> None:
    request = DecideRequest.model_validate(BODY)
    response = DecisionResponse.model_validate(ANSWER)
    validate_decision_answers(request, response.answers)
    response.answers["route"].probabilities["invented"] = .1
    with pytest.raises(ValueError):
        validate_decision_answers(request, response.answers)


# contract-test: direct surface=rest_api assertions=ai-decide.answers.typed
@pytest.mark.parametrize("invalid", ["swapped_legend", "zero_distribution", "excess_distribution"])
def test_answer_semantics_reject_swapped_scale_and_invalid_distributions(invalid: str) -> None:
    request = DecideRequest.model_validate(BODY)
    response = DecisionResponse.model_validate(ANSWER)
    if invalid == "swapped_legend":
        response.answers["priority"].legend = {"0": "High", "1": "Low"}
    else:
        response.answers["route"].probabilities = {"account": 0 if invalid == "zero_distribution" else .9, "billing": 0 if invalid == "zero_distribution" else .9}
    with pytest.raises(ValueError):
        validate_decision_answers(request, response.answers)


# contract-test: direct surface=rest_api assertions=ai-decide.billing.bounded
def test_quote_bounds_both_providers_and_actual_credits_use_catalog() -> None:
    _, pricing = decision_configuration()
    assert pricing["tokens"]["input"]["per_credit_unit"] == 7900
    assert pricing["tokens"]["output"]["per_credit_unit"] == 0
    assert decision_quote(pricing) == 43
    direct = account_decision_attempts([{"provider": "typesafe", "success": True, **ANSWER["usage"]}], pricing)
    assert direct.model_dump() == {"input_tokens": 15_800, "output_tokens": 30, "credits": 2, "complete": True}
    fallback = account_decision_attempts([
        {"provider": "typesafe", "success": False, "input_tokens": None, "output_tokens": None},
        {"provider": "openrouter", "success": True, **ANSWER["usage"]},
    ], pricing)
    assert fallback.credits == 11  # 9 retained + 2 actual; never assume unknown spend is zero.
    assert fallback.complete is False


# contract-test: direct surface=rest_api assertions=ai-decide.billing.bounded,ai-decide.failures.distinct
@pytest.mark.parametrize("usage", [{}, {"input_tokens": 0, "output_tokens": 1},
    {"input_tokens": True, "output_tokens": 1}, {"input_tokens": 64_001, "output_tokens": 1}])
def test_missing_invalid_or_excessive_native_usage_fails_closed(usage: dict) -> None:
    _, pricing = decision_configuration()
    with pytest.raises((ValueError, KeyError)):
        account_decision_attempts([{"provider": "typesafe", "success": True,
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}], pricing)


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.answers.typed,ai-decide.billing.bounded,ai-decide.failures.distinct
@pytest.mark.parametrize("first_status", [200, 503])
async def test_skill_uses_server_model_no_retry_and_accounts_fallback(monkeypatch: pytest.MonkeyPatch, first_status: int) -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        assert body["model"] in {"jev-1.14.0", "typesafe/jev-1.14"}
        assert body["questions"] == BODY["questions"]
        # Optional supplier cost metadata must never erase authoritative token
        # accounting, even if its number cannot be represented as a float.
        metered_answer = {**ANSWER, "usage": {**ANSWER["usage"], "cost": 10 ** 1000}}
        return httpx.Response(first_status if len(calls) == 1 else 200, json=metered_answer if first_status == 200 or len(calls) > 1 else {})

    monkeypatch.setenv("SECRET__TYPESAFE__API_KEY", "test")
    monkeypatch.setenv("SECRET__OPENROUTER__API_KEY", "test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        def client(**kwargs):
            assert kwargs["max_retries"] == 0
            return JevDecisionClient(http_client=http_client, **kwargs)
        monkeypatch.setattr(decide_skill, "JevDecisionClient", client)
        result = await object.__new__(decide_skill.DecideSkill).execute(DecideRequest.model_validate(BODY))
    assert len(calls) == (1 if first_status == 200 else 2)
    assert result.usage.credits == (2 if first_status == 200 else 11)
    assert result.usage.complete is (first_status == 200)
    assert decision_result_credits(result.model_dump()) == result.usage.credits
    assert not any(key.startswith("_") for key in result.model_dump())


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.failures.distinct,ai-decide.billing.bounded
async def test_skill_rejects_success_without_native_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**ANSWER, "usage": {}})
    monkeypatch.setenv("SECRET__TYPESAFE__API_KEY", "test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        monkeypatch.setattr(decide_skill, "JevDecisionClient", lambda **kwargs: JevDecisionClient(http_client=http_client, **kwargs))
        with pytest.raises(HTTPException) as caught:
            await object.__new__(decide_skill.DecideSkill).execute(DecideRequest.model_validate(BODY))
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "decision_provider_unavailable"
    assert caught.value.incurred_credits == 9


def _request(accept: bytes = b"application/json") -> Request:
    return Request({"type": "http", "method": "POST", "path": "/v1/anonymous/apps/ai/skills/decide",
        "headers": [(b"accept", accept), (b"x-openmates-anonymous-id", b"guest-test")],
        "client": ("198.51.100.9", 443), "app": SimpleNamespace(state=SimpleNamespace())})


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.failures.distinct,billing.anonymous.hard-capped-provider-metering
@pytest.mark.parametrize("accept", [b"application/json", b"text/event-stream"])
@pytest.mark.parametrize("reason", ["budget_exhausted", "per_identity_exhausted", "disabled"])
async def test_chat_admission_denials_are_429_signup_for_both_transports(monkeypatch: pytest.MonkeyPatch, accept: bytes, reason: str) -> None:
    from backend.core.api.app.routes import anonymous
    monkeypatch.setattr(anonymous.limiter, "enabled", False, raising=False)
    monkeypatch.setattr(anonymous, "_require_official_cloud", lambda request: None)
    service = SimpleNamespace(open_request=AsyncMock(return_value=SimpleNamespace(accepted=False, reason=reason)), consume_local_rate_limit=AsyncMock(return_value=True))
    monkeypatch.setattr(anonymous, "_anonymous_usage_service", lambda *args: service)
    with pytest.raises(HTTPException) as caught:
        await anonymous.anonymous_chat_stream(request=_request(accept), payload=anonymous.AnonymousChatStreamRequest(
            anonymous_id="test", client_chat_id="test-chat", client_message_id="test-message", plaintext_message="Hello"), directus_service=None, cache_service=None)
    assert caught.value.status_code == 429
    assert caught.value.detail["code"] == reason
    assert caught.value.detail["signup_required"] is True
    assert "Create an account" in caught.value.detail["message"]
    assert "processing failed" not in caught.value.detail["message"].lower()


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.billing.bounded,billing.anonymous.local-only-content
@pytest.mark.parametrize("result_valid", [True, False])
async def test_anonymous_decision_reserves_envelope_and_settles_only_actual_usage(monkeypatch: pytest.MonkeyPatch, result_valid: bool) -> None:
    from backend.core.api.app.routes import anonymous
    from backend.core.api.app.services import skill_registry
    from backend.shared.python_schemas.app_metadata_schemas import AppYAML
    from backend.shared.python_utils import app_skill_output_safety
    raw = yaml.safe_load((Path(__file__).resolve().parents[1] / "apps/ai/app.yml").read_text())
    raw["icon_image"] = raw["icon_image"].strip()
    metadata = AppYAML.model_validate(raw)
    result = {**ANSWER, "success": True, "usage": {**ANSWER["usage"], "credits": 2, "complete": True}}
    if not result_valid:
        result["usage"] = {}
    registry = SimpleNamespace(get_metadata=lambda app: metadata, is_skill_available=lambda *args: True, dispatch_skill=AsyncMock(return_value=result))
    service = SimpleNamespace(open_request=AsyncMock(return_value=SimpleNamespace(accepted=True)),
        consume_local_rate_limit=AsyncMock(return_value=True), reserve_operation=AsyncMock(return_value=SimpleNamespace(accepted=True)),
        finalize_charge=AsyncMock(), release_reservation=AsyncMock())
    monkeypatch.setattr(anonymous.limiter, "enabled", False, raising=False)
    monkeypatch.setattr(anonymous, "_require_official_cloud", lambda request: None)
    monkeypatch.setattr(anonymous, "_anonymous_usage_service", lambda *args: service)
    monkeypatch.setattr(skill_registry, "get_global_registry", lambda: registry)
    monkeypatch.setattr(app_skill_output_safety, "sanitize_app_skill_output", lambda result, ctx: asyncio.sleep(0, result=result))
    if result_valid:
        response = await anonymous.anonymous_app_skill(_request(), "ai", "decide", BODY, None, None)
        assert response["credits_charged"] == 2
        service.finalize_charge.assert_awaited_once()
        assert service.finalize_charge.call_args.kwargs["actual_credits"] == 2
    else:
        with pytest.raises(HTTPException) as caught:
            await anonymous.anonymous_app_skill(_request(), "ai", "decide", BODY, None, None)
        assert caught.value.status_code == 503
        service.finalize_charge.assert_awaited_once()
        assert service.finalize_charge.call_args.kwargs["actual_credits"] == 43
    assert service.reserve_operation.call_args.kwargs["quoted_credits"] == 43
    registry.dispatch_skill.assert_awaited_once_with("ai", "decide", BODY)
    service.release_reservation.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.billing.bounded
async def test_chat_tool_reserves_envelope_and_settles_native_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.ai.processing import main_processor
    from backend.tests.test_anonymous_operation_metering import anonymous_request
    request = anonymous_request()
    skill = SimpleNamespace(full_model_reference="typesafe/jev-1.14", providers=[])
    _, pricing = decision_configuration()
    resolve = AsyncMock(return_value=(skill, pricing))
    reserve = AsyncMock()
    finalize = AsyncMock()
    release = AsyncMock()
    monkeypatch.setattr(main_processor, "_resolve_skill_billing_config", resolve)
    monkeypatch.setattr(main_processor, "_reserve_anonymous_operation", reserve)
    monkeypatch.setattr(main_processor, "_finalize_anonymous_charge", finalize)
    monkeypatch.setattr(main_processor, "_release_anonymous_operation", release)
    monkeypatch.setattr(main_processor, "_make_internal_api_request", AsyncMock(return_value={}))
    operations = await main_processor._reserve_skill_credits(
        task_id="test-task", execution_id="execution", request_data=request,
        app_id="ai", skill_id="decide", discovered_apps_metadata={}, parsed_args=BODY,
        directus_service=None, log_prefix="[test]",
    )
    assert len(operations) == 1
    assert reserve.call_args.kwargs["quoted_credits"] == 43
    result = {**ANSWER, "success": True, "usage": {**ANSWER["usage"], "credits": 2, "complete": True}}
    await main_processor._charge_skill_credits(
        task_id="test-task", execution_id="execution", request_data=request,
        app_id="ai", skill_id="decide", discovered_apps_metadata={}, parsed_args=BODY,
        results=[result], provider_result_data=[result], reserved_operation_ids=operations, log_prefix="[test]",
    )
    finalize.assert_awaited_once_with(charge_id=operations[0], actual_credits=2)
    release.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.billing.bounded
async def test_interrupted_chat_tool_settles_ambiguous_spend_before_hold_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.ai.processing import main_processor
    finalize = AsyncMock()
    monkeypatch.setattr(main_processor, "_finalize_anonymous_charge", finalize)
    assert await main_processor._settle_anonymous_skill_quote(
        app_id="ai", skill_id="decide", parsed_args=BODY, discovered_apps_metadata={},
        reserved_operation_ids=["operation"], log_prefix="[test]",
    ) == 43
    finalize.assert_awaited_once_with(charge_id="operation", actual_credits=43)


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.billing.bounded,ai-decide.failures.distinct,billing.anonymous.hard-capped-provider-metering
async def test_failed_provider_spend_survives_hold_expiry_and_blocks_redispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.api.app.routes import anonymous
    from backend.core.api.app.services import skill_registry
    from backend.core.api.app.services.anonymous_free_usage_service import AnonymousFreeUsageService
    from backend.shared.python_schemas.app_metadata_schemas import AppYAML
    from backend.tests.test_anonymous_free_usage_budget import FakeDirectus, FakeCache
    now = [datetime(2026, 10, 16, 12, tzinfo=timezone.utc)]
    service = AnonymousFreeUsageService(directus_service=FakeDirectus(), cache_service=FakeCache(), hmac_secret="test", now_provider=lambda: now[0])
    await service.save_budget(enabled=True, monthly_budget_credits=43, daily_hard_cap_percent=100,
        weekly_cap_percent=100, per_identity_daily_cap_credits=43, admin_user_id="test-admin")
    raw = yaml.safe_load((Path(__file__).resolve().parents[1] / "apps/ai/app.yml").read_text())
    raw["icon_image"] = raw["icon_image"].strip()
    metadata = AppYAML.model_validate(raw)
    registry = SimpleNamespace(get_metadata=lambda app: metadata, is_skill_available=lambda *args: True,
        dispatch_skill=AsyncMock(side_effect=DecisionExecutionError(incurred_credits=9)))
    monkeypatch.setattr(anonymous.limiter, "enabled", False, raising=False)
    monkeypatch.setattr(anonymous, "_require_official_cloud", lambda request: None)
    monkeypatch.setattr(anonymous, "_anonymous_usage_service", lambda *args: service)
    monkeypatch.setattr(skill_registry, "get_global_registry", lambda: registry)
    with pytest.raises(HTTPException) as caught:
        await anonymous.anonymous_app_skill(_request(), "ai", "decide", BODY, None, None)
    assert caught.value.status_code == 503
    assert "incurred_credits" not in caught.value.detail
    assert (await service.get_budget_status()).daily_used_credits == 9
    now[0] += timedelta(hours=2)
    assert (await service.get_budget_status()).daily_used_credits == 9
    with pytest.raises(HTTPException) as denied:
        await anonymous.anonymous_app_skill(_request(), "ai", "decide", BODY, None, None)
    assert denied.value.status_code == 429
    assert denied.value.detail["signup_required"] is True
    assert registry.dispatch_skill.await_count == 1


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.billing.bounded
async def test_chat_executor_does_not_retry_the_public_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.ai.processing import skill_executor
    from backend.core.api.app.services import skill_registry
    registry = SimpleNamespace(has_app=lambda app: True, is_skill_available=lambda *args: True,
        dispatch_skill=AsyncMock(side_effect=DecisionExecutionError(incurred_credits=9)))
    monkeypatch.setattr(skill_registry, "get_global_registry", lambda: registry)
    with pytest.raises(DecisionExecutionError):
        await skill_executor.execute_skill("ai", "decide", BODY, max_retries=3)
    registry.dispatch_skill.assert_awaited_once()
