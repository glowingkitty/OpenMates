"""
Anonymous AI/app operation metering regression tests.

These tests verify that provider work receives a conservative reservation before
execution and that actual AI/app charges settle against the same anonymous
request ledger instead of being skipped as unauthenticated usage.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY

import pytest

from backend.apps.ai.processing import main_processor
from backend.apps.ai.tasks import stream_consumer


def anonymous_request() -> SimpleNamespace:
    return SimpleNamespace(
        is_anonymous=True,
        anonymous_reservation_id="anonymous-request-1",
        orchestration_id=None,
        user_id_hash="",
        root_chat_id=None,
        chat_id="anonymous-chat-1",
        root_turn_id=None,
        message_id="anonymous-message-1",
        sub_chat_depth=0,
        team_id=None,
        team_workspace_type="chat",
        team_object_id_hash=None,
        is_incognito=True,
        benchmark_metadata=None,
    )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_ai_iteration_reserves_conservative_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    reserved: list[dict] = []

    monkeypatch.setattr(main_processor, "_quote_ai_iteration_credits", lambda **_kwargs: 37)

    async def reserve(**kwargs):
        reserved.append(kwargs)

    monkeypatch.setattr(main_processor, "_reserve_anonymous_operation", reserve)

    operation_id = await main_processor._reserve_ai_iteration(
        task_id="task-1",
        iteration=2,
        model_id="google/gemini-test",
        system_prompt="system",
        message_history=[{"role": "user", "content": "hello"}],
        tools=[{"name": "web-search"}],
        output_token_limit=4096,
        request_data=anonymous_request(),
        directus_service=None,
    )

    assert operation_id == "ai-ask:task-1:main:iteration:2:model:google/gemini-test"
    assert reserved == [
        {
            "request_data": ANY,
            "operation_id": operation_id,
            "charge_id": "ai-ask:task-1:main",
            "quoted_credits": 37,
        }
    ]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_skill_requests_reserve_and_settle_each_provider_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_data = anonymous_request()
    skill_definition = SimpleNamespace(full_model_reference=None, providers=[], pricing=None)
    reserved: list[dict] = []
    settled: list[tuple[str, int]] = []

    async def resolve_config(**_kwargs):
        return skill_definition, {"per_unit": {"credits": 12}}

    async def reserve(**kwargs):
        reserved.append(kwargs)

    async def settle(*, charge_id: str, actual_credits: int):
        settled.append((charge_id, actual_credits))

    monkeypatch.setattr(main_processor, "_resolve_skill_billing_config", resolve_config)
    monkeypatch.setattr(main_processor, "_reserve_anonymous_operation", reserve)
    monkeypatch.setattr(main_processor, "_finalize_anonymous_charge", settle)

    operation_ids = await main_processor._reserve_skill_credits(
        task_id="task-1",
        execution_id="execution-1",
        request_data=request_data,
        app_id="web",
        skill_id="search",
        discovered_apps_metadata={},
        parsed_args={"requests": [{"q": "one"}, {"q": "two"}]},
        directus_service=None,
        log_prefix="test",
    )
    await main_processor._charge_skill_credits(
        task_id="task-1",
        execution_id="execution-1",
        request_data=request_data,
        app_id="web",
        skill_id="search",
        discovered_apps_metadata={},
        results=[{"status": "finished"}, {"status": "finished"}],
        parsed_args={"requests": [{"q": "one"}, {"q": "two"}]},
        log_prefix="test",
        grouped_results=[{"results": [{}]}, {"results": [{}]}],
        directus_service=None,
        reserved_operation_ids=operation_ids,
    )

    assert operation_ids == [
        "web.search:task-1:execution-1:0",
        "web.search:task-1:execution-1:1",
    ]
    assert [item["quoted_credits"] for item in reserved] == [12, 12]
    assert settled == [(operation_ids[0], 12), (operation_ids[1], 12)]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,app-skills.surface.semantic-parity
async def test_weather_chat_billing_uses_executed_provider_and_flat_execution_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_data = anonymous_request()
    request_data.is_anonymous = False
    request_data.user_id = "user-1"
    request_data.user_id_hash = "user-hash-1"
    skill_definition = SimpleNamespace(
        full_model_reference=None,
        providers=[
            SimpleNamespace(name="deutscher_wetterdienst"),
            SimpleNamespace(name="open_meteo"),
        ],
        pricing=SimpleNamespace(model_dump=lambda **_kwargs: {"fixed": 1}),
    )
    provider_info_requests: list[str] = []
    charge_payloads: list[dict] = []

    async def resolve_config(**_kwargs):
        return skill_definition, {"fixed": 1}

    async def internal_request(method: str, endpoint: str, *_args, **_kwargs):
        assert method == "GET"
        provider_info_requests.append(endpoint)
        return {"name": "Open-Meteo", "region": "EU"}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"status": "success"}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, _url: str, *, json: dict, **_kwargs):
            charge_payloads.append(json)
            return FakeResponse()

    monkeypatch.setattr(main_processor, "_resolve_skill_billing_config", resolve_config)
    monkeypatch.setattr(main_processor, "_make_internal_api_request", internal_request)
    monkeypatch.setattr(main_processor.httpx, "AsyncClient", FakeClient)

    await main_processor._charge_skill_credits(
        task_id="task-weather",
        execution_id="execution-weather",
        request_data=request_data,
        app_id="weather",
        skill_id="forecast",
        discovered_apps_metadata={},
        results=[
            {
                "provider_id": "open_meteo",
                "results": [{"date": "day-1"}, {"date": "day-2"}, {"date": "day-3"}],
            }
        ],
        parsed_args={"location": "London", "days": 3},
        log_prefix="test",
    )

    assert provider_info_requests == ["internal/config/provider_info/open_meteo"]
    assert len(charge_payloads) == 1
    assert charge_payloads[0]["credits"] == 1
    assert charge_payloads[0]["usage_details"]["units_processed"] == 1
    assert charge_payloads[0]["usage_details"]["server_provider"] == "Open-Meteo"
    assert charge_payloads[0]["usage_details"]["server_region"] == "EU"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_main_ai_usage_settles_internal_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, *, json: dict, headers: dict):
            captured.update({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(stream_consumer.httpx, "AsyncClient", FakeClient)

    await stream_consumer._settle_anonymous_ai_credits("task-1", anonymous_request(), 29)

    assert captured["url"].endswith("/internal/anonymous-usage/finalize-charge")
    assert captured["json"] == {"charge_id": "ai-ask:task-1:main", "actual_credits": 29}
