# contract-test-file: infrastructure
"""Main inference holds use the final charge identity and fit to durable capacity."""

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.apps.ai.processing import main_processor
from backend.apps.ai.utils import llm_utils
from backend.apps.ai.processing.model_usage_tracker import ModelUsageTracker
from backend.apps.ai.llm_providers.mistral_client import MistralUsage
from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata
from backend.shared.python_schemas.llm_usage import NormalizedLLMUsage
from backend.shared.python_utils.billing_utils import snapshot_model_tariff


pytestmark = pytest.mark.asyncio


def _request(*, team_id=None):
    return SimpleNamespace(
        is_anonymous=False, orchestration_id=None,
        user_id="user-id", user_id_hash="user-hash", team_id=team_id,
    )


def _pricing():
    return {
        "features": {"max_output_tokens": 1_000},
        "pricing": {"tokens": {
            "input": {"per_credit_unit": 1_000},
            "output": {"per_credit_unit": 10},
        }},
    }


def _long_context_pricing():
    base = {
        "input": {"per_credit_unit": 1_000},
        "cache_read": {"per_credit_unit": 2_000},
        "cache_write": {"per_credit_unit": 800},
        "output": {"per_credit_unit": 10},
    }
    band = {
        "input": {"per_credit_unit": 500},
        "cache_read": {"per_credit_unit": 1_000},
        "cache_write": {"per_credit_unit": 400},
        "output": {"per_credit_unit": 6},
    }
    return {
        "default_server": "openai", "features": {"max_output_tokens": 1_000},
        "pricing": {"tokens": base, "context_bands": {"over_272k": {
            "min_input_tokens": 272_001, "eligible_hosts": ["openai"], "tokens": band,
        }}},
        "cache_pricing": {
            "enabled": True, "status": "verified_for_activation",
            "eligible_hosts": ["openai"], "write_billing": "separate",
            "source_url": "https://example.com/pricing", "reviewed_on": "2026-10-01",
            "expires_on": "2099-12-31",
        },
        "supplier_cost_profiles": {"openai": {"context_bands": {"over_272k": {
            "input": 2, "cache_read": 2, "cache_write": 2, "output": 1.5,
        }}}},
    }


def _system_prompt_for_serialized_input_bytes(size):
    overhead = len(json.dumps({"system": "", "messages": [], "tools": []}, separators=(",", ":")).encode("utf-8"))
    return "x" * (size - overhead)


def _kwargs(request, tracker, state, *, output_limit=100):
    return {
        "task_id": "reservation-bridge", "request_data": request,
        "model_id": "provider/model", "system_prompt": "system",
        "message_history": [{"role": "user", "content": "hello"}],
        "tools": None, "requested_output_token_limit": output_limit,
        "model_usage_tracker": tracker, "reservation_state": state,
    }


async def test_personal_reservation_tops_up_same_final_charge_from_observed_usage(monkeypatch):
    pricing = _pricing()
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: pricing)
    sent = []

    async def reserve(_method, endpoint, payload):
        sent.append((endpoint, dict(payload)))
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"], "idempotent": False}

    monkeypatch.setattr(main_processor, "_make_internal_api_request", reserve)
    tracker = ModelUsageTracker()
    state = {}
    request = _request()
    assert await main_processor._reserve_authenticated_ai_turn(**_kwargs(request, tracker, state)) == 100
    first_quote = state["quoted_credits"]
    tracker.record_reported_usage(
        model_id="provider/model", attempt_id="attempt-one",
        normalized_usage=NormalizedLLMUsage(
            model_id="provider/model", input_total=10, input_uncached=10,
            output_billable=10, attempt_id="attempt-one",
            inference_host="provider", tariff_snapshot=snapshot_model_tariff(pricing),
        ),
    )
    assert await main_processor._reserve_authenticated_ai_turn(**_kwargs(request, tracker, state)) == 100
    assert sent[0][0] == sent[1][0] == "internal/billing/reserve"
    assert sent[0][1]["idempotency_key"] == sent[1][1]["idempotency_key"] == "ai-ask:reservation-bridge:main"
    assert sent[0][1]["user_id"] == "user-id" and sent[0][1]["user_id_hash"] == "user-hash"
    assert state["quoted_credits"] >= first_quote


async def test_team_reservation_fits_output_to_authoritative_402_limit(monkeypatch):
    pricing = _pricing()
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: pricing)
    sent = []

    async def reserve(_method, endpoint, payload):
        sent.append((endpoint, dict(payload)))
        if payload["quoted_credits"] > 15:
            response = httpx.Response(
                402, json={"detail": {"code": "reservation_budget_exceeded", "max_quotable_credits": 15}},
                request=httpx.Request("POST", "http://api/internal/billing/team/reserve"),
            )
            raise httpx.HTTPStatusError("capacity", request=response.request, response=response)
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"], "idempotent": False}

    monkeypatch.setattr(main_processor, "_make_internal_api_request", reserve)
    state = {}
    fitted = await main_processor._reserve_authenticated_ai_turn(
        **_kwargs(_request(team_id="team-id"), ModelUsageTracker(), state, output_limit=1_000),
    )
    assert 0 < fitted < 1_000
    assert sent[0][0] == sent[1][0] == "internal/billing/team/reserve"
    assert sent[1][1]["quoted_credits"] <= 15
    assert sent[1][1]["team_id"] == "team-id" and sent[1][1]["actor_user_id"] == "user-id"
    assert state["active"] is True


async def test_confirmed_terminal_release_clears_ordinary_hold(monkeypatch):
    sent = []

    async def release(_method, endpoint, payload):
        sent.append((endpoint, payload))
        return {"state": "released"}

    monkeypatch.setattr(main_processor, "_make_internal_api_request", release)
    state = {"active": True, "charge_id": "ai-ask:reservation-bridge:main", "quoted_credits": 7}
    await main_processor._release_authenticated_ai_reservation(
        request_data=_request(), reservation_state=state, reason="provider_failed",
    )
    assert sent == [("internal/billing/reservation/release", {
        "subject_kind": "personal", "idempotency_key": "ai-ask:reservation-bridge:main",
        "reason": "provider_failed", "user_id": "user-id", "user_id_hash": "user-hash",
    })]
    assert state["active"] is False and state["released"] is True


async def test_payment_disabled_reservation_skips_hold_without_blocking_inference(monkeypatch):
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: _pricing())

    async def skipped(_method, _endpoint, payload):
        return {"state": "skipped", "charge_id": payload["idempotency_key"], "quoted_credits": 0}

    monkeypatch.setattr(main_processor, "_make_internal_api_request", skipped)
    state = {}
    assert await main_processor._reserve_authenticated_ai_turn(
        **_kwargs(_request(), ModelUsageTracker(), state),
    ) == 100
    assert not state.get("active")


async def test_ordinary_reservation_uses_model_output_cap_when_unspecified(monkeypatch):
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: _pricing())

    async def reserved(_method, _endpoint, payload):
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"]}

    monkeypatch.setattr(main_processor, "_make_internal_api_request", reserved)
    kwargs = _kwargs(_request(), ModelUsageTracker(), {})
    kwargs["requested_output_token_limit"] = None
    assert await main_processor._reserve_authenticated_ai_turn(**kwargs) == 1_000


async def test_openai_long_context_quote_switches_cold_input_and_output_units_at_boundary(monkeypatch):
    pricing = _long_context_pricing()
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: pricing)

    def quote(size, host="openai"):
        return main_processor._quote_ai_iteration_credits(
            model_id="openai/model", system_prompt=_system_prompt_for_serialized_input_bytes(size),
            message_history=[], tools=None, output_token_limit=60, inference_host=host,
        )

    assert quote(272_000) == 346  # Cold writes use 800 tokens/credit; output uses 10.
    assert quote(272_001) == 690  # Cold writes use 400 tokens/credit; output uses 6.
    assert quote(272_001, "mistral") == 346  # Ineligible route keeps base units and existing cold-write bound.
    pricing["cache_pricing"]["enabled"] = False
    assert quote(272_001) == 278  # Proposed tariffs remain inert while disabled.


@pytest.mark.parametrize("image", [
    "https://images.example.test/photo.jpg",
    {"url": "https://images.example.test/photo.jpg", "detail": "high"},
])
async def test_remote_image_quote_reserves_model_context_and_long_context_rates(monkeypatch, image):
    pricing = _long_context_pricing()
    pricing["costs"] = {"input_per_million_token": {"max_context": 300_000}}
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: pricing)
    messages = [{"role": "tool", "content": [{"type": "image_url", "image_url": image}]}]

    def quote(host):
        return main_processor._quote_ai_iteration_credits(
            model_id="openai/model", system_prompt="system", message_history=messages,
            tools=None, output_token_limit=60, inference_host=host,
        )

    assert quote("openai") == 760  # 300k cold input / 400, plus 60 output / 6.
    assert quote("mistral") == 381  # Ineligible host uses base input and output rates.


async def test_remote_image_quote_requires_configured_context_limit(monkeypatch):
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: _pricing())
    with pytest.raises(RuntimeError, match="context limit is unavailable"):
        main_processor._quote_ai_iteration_credits(
            model_id="openai/model", system_prompt="system",
            message_history=[{"role": "user", "content": [
                {"type": "image_url", "image_url": "https://images.example.test/photo.jpg"},
            ]}], tools=None, output_token_limit=60,
        )


async def test_long_context_reservation_fits_output_and_tops_up_for_actual_openai_host(monkeypatch):
    pricing = _long_context_pricing()
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: pricing)
    prompt = _system_prompt_for_serialized_input_bytes(272_001)
    quotes = []
    capacity = 683

    async def reserve(_method, _endpoint, payload):
        quotes.append(payload["quoted_credits"])
        if payload["quoted_credits"] > capacity:
            response = httpx.Response(
                402, json={"detail": {"code": "reservation_budget_exceeded", "max_quotable_credits": capacity}},
                request=httpx.Request("POST", "http://api/internal/billing/reserve"),
            )
            raise httpx.HTTPStatusError("capacity", request=response.request, response=response)
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"]}

    monkeypatch.setattr(main_processor, "_make_internal_api_request", reserve)
    state = {}
    kwargs = _kwargs(_request(), ModelUsageTracker(), state, output_limit=100)
    kwargs.update(model_id="openai/model", system_prompt=prompt, message_history=[])
    assert await main_processor._reserve_authenticated_ai_turn(**kwargs, inference_host="mistral") == 100
    first_hold = state["quoted_credits"]
    fitted = await main_processor._reserve_authenticated_ai_turn(**kwargs, inference_host="openai")
    assert 0 < fitted < 100
    assert first_hold < state["quoted_credits"] <= capacity
    assert quotes[-1] == state["quoted_credits"]


@pytest.mark.parametrize("capacity_mode", ["full", "fit", "deny"])
async def test_hidden_usage_requires_fresh_hold_before_internal_host_fallback(monkeypatch, capacity_mode):
    pricing = _pricing()
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: pricing)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _model: ("openai", "openai/model"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _model: ["mistral/model"])
    first_hold = None
    reserve_quotes = []

    async def reserve(_method, _endpoint, payload):
        nonlocal first_hold
        quote = payload["quoted_credits"]
        reserve_quotes.append(quote)
        if first_hold is None:
            first_hold = quote
        ceiling = first_hold if capacity_mode == "deny" else first_hold + 5
        if capacity_mode != "full" and quote > ceiling:
            response = httpx.Response(
                402, json={"detail": {"code": "reservation_budget_exceeded", "max_quotable_credits": ceiling}},
                request=httpx.Request("POST", "http://api/internal/billing/reserve"),
            )
            raise httpx.HTTPStatusError("capacity", request=response.request, response=response)
        return {"state": "reserved", "charge_id": payload["idempotency_key"], "quoted_credits": quote}

    monkeypatch.setattr(main_processor, "_make_internal_api_request", reserve)
    dispatched = []

    async def primary(**kwargs):
        dispatched.append(("openai", kwargs["max_tokens"]))

        async def stream():
            # A provider can report nearly all of its output allowance without
            # producing user-visible text. Those tokens count before fallback.
            yield OpenAIUsageMetadata(input_tokens=1_000, output_tokens=100, total_tokens=1_100)
            yield "[ERROR 503 provider failed]"

        return stream()

    async def fallback(**kwargs):
        dispatched.append(("mistral", kwargs["max_tokens"]))

        async def stream():
            yield "recovered"
            yield MistralUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13)

        return stream()

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda host: primary if host == "openai" else fallback)
    tracker = ModelUsageTracker()
    state = {}
    request = _request()
    initial_limit = await main_processor._reserve_authenticated_ai_turn(
        **_kwargs(request, tracker, state, output_limit=100),
    )

    async def admit(_host, dispatch_limit):
        return await main_processor._reserve_authenticated_ai_turn(
            **_kwargs(request, tracker, state, output_limit=dispatch_limit),
        )

    chunks = []
    stream = llm_utils.call_main_llm_stream(
        task_id="reservation-bridge", model_id="provider/model", system_prompt="system",
        message_history=[{"role": "user", "content": "hello"}], temperature=0.2,
        max_tokens=initial_limit, pre_dispatch_admission=admit,
    )
    if capacity_mode == "deny":
        with pytest.raises(main_processor.AuthenticatedReservationLimitError):
            async for chunk in stream:
                if usage := getattr(chunk, "_normalized_llm_usage", None):
                    tracker.record_reported_usage(model_id=usage.model_id, normalized_usage=usage, attempt_id=usage.attempt_id)
                chunks.append(chunk)
        assert dispatched == [("openai", 100)]
    else:
        async for chunk in stream:
            if usage := getattr(chunk, "_normalized_llm_usage", None):
                tracker.record_reported_usage(model_id=usage.model_id, normalized_usage=usage, attempt_id=usage.attempt_id)
            chunks.append(chunk)
        assert dispatched[0] == ("openai", 100)
        assert dispatched[1][0] == "mistral"
        if capacity_mode == "fit":
            assert 0 < dispatched[1][1] < 100
        else:
            assert dispatched[1][1] == 100
        assert reserve_quotes[-1] > first_hold
        assert state["quoted_credits"] == reserve_quotes[-1]
        assert "recovered" in chunks


async def test_auxiliary_supplier_telemetry_counts_google_thoughts_once(monkeypatch):
    pricing = {
        "pricing": {"tokens": {"input": {"per_credit_unit": 1000},
                               "output": {"per_credit_unit": 100}}},
        "costs": {"input_per_million_token": {"price": 1.0},
                  "output_per_million_token": {"price": 2.0}},
    }
    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", lambda *_args: pricing)
    telemetry = llm_utils._auxiliary_usage_telemetry(
        {"prompt_token_count": 100, "candidates_token_count": 10,
         "thoughts_token_count": 5, "cached_content_token_count": 0},
        logical_model_id="google/test-model", route_id="google_ai_studio",
        server_model_id="test-model",
    )
    assert telemetry["output_tokens"] == 15
    assert telemetry["output_reasoning_tokens"] == 5
    assert telemetry["supplier_cost_usd"] == pytest.approx(0.00013)
    assert telemetry["supplier_cost_upper_bound_usd"] == pytest.approx(0.00013)
    assert telemetry["supplier_cost_complete"] is True
