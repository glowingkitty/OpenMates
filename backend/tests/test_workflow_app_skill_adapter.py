# backend/tests/test_workflow_app_skill_adapter.py
#
# Contract tests for Workflow app-skill request adaptation before dispatching to
# the shared SkillRegistry. These tests protect YAML Workflow shorthand shapes
# from leaking into app-specific schemas that expect API-native request bodies.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
import json

import pytest
from fastapi.responses import StreamingResponse

from backend.core.api.app import routes as routes_package
from backend.core.api.app.services import workflow_app_skill_adapter
from backend.core.api.app.services.workflow_app_skill_adapter import (
    WorkflowAppSkillAdapter,
    WorkflowSkillBillingError,
    _normalize_skill_output,
)
from backend.shared.python_utils.billing_utils import BillingError
from backend.shared.python_utils.app_skill_output_safety import is_central_app_skill_dispatch


class FakeRegistry:
    def __init__(self, response: dict[str, Any] | None = None, metadata: Any | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.response = response or {"choices": [{"message": {"content": "Workflow AI OK"}}]}
        self.metadata = metadata

    async def dispatch_skill(self, app_id: str, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((app_id, skill_id, request))
        self.central_dispatch_active = is_central_app_skill_dispatch()
        return self.response

    def get_metadata(self, app_id: str) -> Any | None:
        del app_id
        return self.metadata


def _weather_metadata() -> Any:
    return SimpleNamespace(
        id="weather",
        skills=[SimpleNamespace(id="forecast", full_model_reference=None, providers=[], pricing=None)],
    )


def _patch_apps_api_module(monkeypatch: pytest.MonkeyPatch, apps_api: Any) -> None:
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.apps_api", apps_api)
    monkeypatch.setattr(routes_package, "apps_api", apps_api, raising=False)


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
async def test_non_ai_skill_uses_authenticated_owner_context() -> None:
    registry = FakeRegistry(response={"results": []})
    adapter = WorkflowAppSkillAdapter(registry=registry)
    authored = {
        "location": "Berlin",
        "_user_id": "forged-owner",
        "_external_request": False,
        "_connected_account_access_tokens": {"forged": "token"},
        "user_id": "forged-owner",
        "external_request": False,
    }

    await adapter.execute("weather", "forecast", authored, user_id="real-owner")

    assert registry.calls[0][2] == {
        "location": "Berlin",
        "_user_id": "real-owner",
        "_external_request": True,
    }
    assert authored["_user_id"] == "forged-owner"
    assert authored["_external_request"] is False


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.billing.skill-usage
async def test_workflow_skill_uses_actual_pricing_and_stable_charge_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = {"provider_id": "open_meteo", "results": [{"temperature_max_c": 20}]}
    registry = FakeRegistry(response=result, metadata=_weather_metadata())
    adapter = WorkflowAppSkillAdapter(registry=registry)
    estimates: list[int] = []
    charges: list[dict[str, Any]] = []
    attributed_results: list[dict[str, Any]] = []

    async def fake_calculate_skill_credits(**kwargs: Any) -> int:
        return 7 if kwargs.get("result_data") else 3

    async def fake_precheck(**kwargs: Any) -> None:
        estimates.append(kwargs["estimated_credits"])

    async def fake_charge(**kwargs: Any) -> dict[str, Any]:
        charges.append(kwargs)
        return {"status": "success", "charged_credits": kwargs["credits"]}

    def resolve_provider_info(*args):
        attributed_results.append(args[3])
        return {"model_used": None, "server_provider": "Open-Meteo", "server_region": "EU"}

    apps_api = SimpleNamespace(
        calculate_skill_credits=fake_calculate_skill_credits,
        get_variable_preflight_reserved_credits=lambda *_args: 0,
        is_skill_execution_successful=lambda _result: True,
        get_variable_result_charge_items=lambda *_args: None,
        get_variable_result_usage_details=lambda *_args: {},
        resolve_skill_provider_info=resolve_provider_info,
        charge_credits_via_internal_api=fake_charge,
    )
    _patch_apps_api_module(monkeypatch, apps_api)
    monkeypatch.setattr(workflow_app_skill_adapter, "ensure_credit_headroom", fake_precheck)

    billing_context = {
        "workflow_id": "workflow-1",
        "run_id": "run-1",
        "node_id": "weather",
        "source": "workflow_test",
    }
    outputs = []
    for _ in range(2):
        outputs.append(await adapter.execute(
            "weather",
            "forecast",
            {"location": "Berlin"},
            user_id="alice",
            billing_context=billing_context,
        ))

    assert estimates == [3, 3]
    assert attributed_results == [result, result]
    assert [charge["credits"] for charge in charges] == [7, 7]
    assert charges[0]["idempotency_key"] == charges[1]["idempotency_key"]
    assert charges[0]["usage_details"] == {
        "source": "workflow_test",
        "units_processed": 1,
        "model_used": None,
        "server_provider": "Open-Meteo",
        "server_region": "EU",
        "operation_id": charges[0]["idempotency_key"],
    }
    assert charges[0]["raise_on_error"] is True
    assert [output.pop("_workflow_credit_cost") for output in outputs] == [7, 7]
    assert all("_workflow_credit_cost" not in output for output in outputs)


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.billing.skill-usage
async def test_workflow_skill_insufficient_credits_fails_before_provider_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeRegistry(response={"results": [{"temperature_max_c": 20}]}, metadata=_weather_metadata())
    adapter = WorkflowAppSkillAdapter(registry=registry)

    async def fake_calculate_skill_credits(**_kwargs: Any) -> int:
        return 3

    async def reject_precheck(**_kwargs: Any) -> None:
        raise BillingError("Insufficient credits")

    apps_api = SimpleNamespace(
        calculate_skill_credits=fake_calculate_skill_credits,
        get_variable_preflight_reserved_credits=lambda *_args: 0,
    )
    _patch_apps_api_module(monkeypatch, apps_api)
    monkeypatch.setattr(workflow_app_skill_adapter, "ensure_credit_headroom", reject_precheck)

    with pytest.raises(WorkflowSkillBillingError) as exc_info:
        await adapter.execute(
            "weather",
            "forecast",
            {"location": "Berlin"},
            user_id="alice",
            billing_context={
                "workflow_id": "workflow-1",
                "run_id": "run-1",
                "node_id": "weather",
                "source": "workflow",
            },
        )

    assert exc_info.value.code == "INSUFFICIENT_CREDITS"
    assert registry.calls == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.control.for-each
async def test_for_each_credit_allowance_rejects_expensive_skill_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeRegistry(response={"results": []}, metadata=_weather_metadata())
    adapter = WorkflowAppSkillAdapter(registry=registry)
    async def quote(**_kwargs: Any) -> int:
        return 10
    apps_api = SimpleNamespace(
        calculate_skill_credits=quote,
        get_variable_preflight_reserved_credits=lambda *_args: 0,
        VARIABLE_RESULT_BILLING_SKILLS=set(),
    )
    _patch_apps_api_module(monkeypatch, apps_api)

    with pytest.raises(WorkflowSkillBillingError) as exc_info:
        await adapter.execute("weather", "forecast", {"location": "Berlin"}, user_id="alice",
            billing_context={"workflow_id": "workflow-1", "run_id": "run-1", "node_id": "loop:0:weather:body",
                             "source": "workflow", "max_credits_remaining": 1})

    assert exc_info.value.code == "WORKFLOW_FOR_EACH_CREDITS"
    assert registry.calls == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.control.for-each
async def test_for_each_rejects_unbounded_variable_skill_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeRegistry(response={"results": []}, metadata=_weather_metadata())
    adapter = WorkflowAppSkillAdapter(registry=registry)
    async def quote(**_kwargs: Any) -> int:
        return 0
    apps_api = SimpleNamespace(
        calculate_skill_credits=quote,
        get_variable_preflight_reserved_credits=lambda *_args: 0,
        VARIABLE_RESULT_BILLING_SKILLS={("weather", "forecast")},
    )
    _patch_apps_api_module(monkeypatch, apps_api)

    with pytest.raises(WorkflowSkillBillingError) as exc_info:
        await adapter.execute("weather", "forecast", {"location": "Berlin"}, user_id="alice",
            billing_context={"workflow_id": "workflow-1", "run_id": "run-1", "node_id": "loop:0:weather:body",
                             "source": "workflow", "max_credits_remaining": 1})

    assert exc_info.value.code == "WORKFLOW_FOR_EACH_UNBOUNDED_COST"
    assert registry.calls == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.billing.skill-usage
async def test_failed_workflow_skill_result_is_not_charged(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = FakeRegistry(response={"error": "provider unavailable"}, metadata=_weather_metadata())
    adapter = WorkflowAppSkillAdapter(registry=registry)
    charges: list[dict[str, Any]] = []

    async def fake_calculate_skill_credits(**_kwargs: Any) -> int:
        return 3

    async def fake_precheck(**_kwargs: Any) -> None:
        return None

    async def fake_charge(**kwargs: Any) -> None:
        charges.append(kwargs)

    apps_api = SimpleNamespace(
        calculate_skill_credits=fake_calculate_skill_credits,
        get_variable_preflight_reserved_credits=lambda *_args: 0,
        is_skill_execution_successful=lambda _result: False,
        charge_credits_via_internal_api=fake_charge,
    )
    _patch_apps_api_module(monkeypatch, apps_api)
    monkeypatch.setattr(workflow_app_skill_adapter, "ensure_credit_headroom", fake_precheck)

    result = await adapter.execute(
        "weather",
        "forecast",
        {"location": "Berlin"},
        user_id="alice",
        billing_context={
            "workflow_id": "workflow-1",
            "run_id": "run-1",
            "node_id": "weather",
            "source": "workflow",
        },
    )

    assert result["error"] == "provider unavailable"
    assert charges == []


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_ai_ask_workflow_prompt_is_adapted_to_openai_messages_with_owner_context() -> None:
    registry = FakeRegistry()
    adapter = WorkflowAppSkillAdapter(registry=registry)

    result = await adapter.execute(
        "ai",
        "ask",
        {"prompt": "Reply with exactly: Workflow AI OK", "conversation": "e2e-local", "temperature": 0,
         "workflow_presentation_sources": ["events-search"]},
        user_id="alice",
    )

    assert registry.calls == [
        (
            "ai",
            "ask",
            {
                "messages": [{"role": "user", "content": "Reply with exactly: Workflow AI OK"}],
                "apps_enabled": False,
                "allowed_apps": [],
                "workflow_ai": True,
                "workflow_presentation_sources": ["events-search"],
                "_user_id": "alice",
                "_external_request": True,
            },
        )
    ]
    assert result["raw"] == {"choices": [{"message": {"content": "Workflow AI OK"}}]}
    assert registry.central_dispatch_active is True


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_ai_ask_preserves_only_messages_and_forces_tools_off() -> None:
    registry = FakeRegistry()
    adapter = WorkflowAppSkillAdapter(registry=registry)

    await adapter.execute(
        "ai",
        "ask",
        {"messages": [{"role": "system", "content": "Keep it short"}], "model": "auto"},
        user_id="alice",
    )

    assert registry.calls[0][2] == {
        "messages": [{"role": "system", "content": "Keep it short"}],
        "apps_enabled": False,
        "allowed_apps": [],
        "workflow_ai": True,
        "workflow_presentation_sources": [],
        "_user_id": "alice",
        "_external_request": True,
    }


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.ai-ask.execution,workflows.billing.skill-usage
async def test_ai_ask_reports_already_settled_usage_without_double_charging() -> None:
    registry = FakeRegistry(response={
        "answer": "A concise workflow answer",
        "usage": {"total_credits": 5},
    })
    adapter = WorkflowAppSkillAdapter(registry=registry)

    result = await adapter.execute(
        "ai",
        "ask",
        {"prompt": "Summarize the supplied values"},
        user_id="alice",
        billing_context={
            "workflow_id": "workflow-1",
            "run_id": "run-1",
            "node_id": "ask",
            "source": "workflow_test",
        },
    )

    assert result["answer"] == "A concise workflow answer"
    assert result["_workflow_credit_cost"] == 5


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.ai-ask.execution,workflows.billing.skill-usage
async def test_ai_ask_stream_emits_snapshots_and_uses_final_authoritative_answer(monkeypatch) -> None:
    frames = [
        {"choices": [{"delta": {"content": "Draft"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": " answer"}, "finish_reason": None}]},
        {"model": "openai/example", "choices": [{"delta": {}, "finish_reason": "stop"}],
         "full_content": "Final answer", "usage": {"total_credits": 3}},
    ]

    async def body():
        for frame in frames:
            yield f"data: {json.dumps(frame)}\n\n"
        yield "data: [DONE]\n\n"

    registry = FakeRegistry(response=StreamingResponse(body()))
    adapter = WorkflowAppSkillAdapter(registry=registry)

    async def available(_model):
        return None

    monkeypatch.setattr(adapter, "_validate_ask_model", available)
    snapshots: list[str] = []

    async def on_snapshot(value: str):
        snapshots.append(value)

    result = await adapter.stream_ask(
        {"prompt": "Say hello", "model": "openai/example"}, user_id="alice",
        billing_context={"workflow_id": "wf", "run_id": "run", "node_id": "ask", "source": "workflow_test"},
        on_snapshot=on_snapshot,
    )
    assert snapshots == ["Draft", "Draft answer", "Final answer"]
    assert result["answer"] == "Final answer"
    assert result["_workflow_credit_cost"] == 3
    assert registry.calls[0][2]["model"] == "openai/example"
    assert registry.calls[0][2]["stream"] is True
    assert registry.calls[0][2]["apps_enabled"] is False
    assert registry.calls[0][2]["_user_id"] == "alice"


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.ai-ask.execution
async def test_ai_ask_stream_provider_error_fails_without_raw_error_text() -> None:
    async def body():
        yield 'data: {"choices":[{"delta":{"content":"Error: secret diagnostic"},"finish_reason":"error"}],"usage":{"total_credits":7}}\n\n'
        yield "data: [DONE]\n\n"

    adapter = WorkflowAppSkillAdapter(registry=FakeRegistry(response=StreamingResponse(body())))
    snapshots: list[str] = []

    async def on_snapshot(value: str):
        snapshots.append(value)

    with pytest.raises(WorkflowSkillBillingError, match="could not complete") as exc:
        await adapter.stream_ask(
            {"prompt": "hello"}, user_id="alice",
            billing_context={"workflow_id": "wf", "run_id": "run", "node_id": "ask", "source": "workflow_test"},
            on_snapshot=on_snapshot,
        )
    assert exc.value.code == "WORKFLOW_AI_STREAM_FAILED"
    assert exc.value.credit_cost == 7
    assert snapshots == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.ai-ask.execution,workflows.billing.skill-usage
async def test_ai_ask_stream_empty_final_answer_retains_settled_credit_cost() -> None:
    async def body():
        yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"full_content":"   ","usage":{"total_credits":5}}\n\n'
        yield "data: [DONE]\n\n"

    adapter = WorkflowAppSkillAdapter(registry=FakeRegistry(response=StreamingResponse(body())))

    async def on_snapshot(_value: str) -> None:
        pass

    with pytest.raises(WorkflowSkillBillingError, match="returned no answer") as exc:
        await adapter.stream_ask(
            {"prompt": "hello"}, user_id="alice",
            billing_context={"workflow_id": "wf", "run_id": "run", "node_id": "ask", "source": "workflow_test"},
            on_snapshot=on_snapshot,
        )
    assert exc.value.code == "WORKFLOW_AI_STREAM_FAILED"
    assert exc.value.credit_cost == 5


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.ai-ask.execution
async def test_ai_ask_exact_model_is_checked_against_available_chat_catalog(monkeypatch) -> None:
    from backend.core.api.app.utils.config_manager import ConfigManager

    checked = []

    def get_model_pricing(self, provider, model):
        checked.append((provider, model))
        return None

    monkeypatch.setattr(ConfigManager, "get_model_pricing", get_model_pricing)
    adapter = WorkflowAppSkillAdapter(registry=FakeRegistry())
    with pytest.raises(WorkflowSkillBillingError) as exc:
        await adapter.execute("ai", "ask", {"prompt": "Hello", "model": "openai/removed"}, user_id="alice")
    assert exc.value.code == "WORKFLOW_AI_MODEL_UNAVAILABLE"
    assert checked == [("openai", "removed")]


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
def test_generic_output_normalization_exposes_artifact_and_task_ids() -> None:
    result = _normalize_skill_output("images", "generate", {"requests": [{"prompt": "blue circle"}]}, {
        "status": "processing",
        "task_ids": ["task-1"],
        "embed_ids": ["embed-1"],
        "provider": "ExampleProvider",
    })

    assert result["summary"] == "images:generate processing"
    assert result["pending"] is True
    assert result["provider"] == "ExampleProvider"
    assert result["artifact_ids"] == ["embed-1"]
    assert result["task_ids"] == ["task-1"]


@pytest.mark.parametrize(("app_id", "skill_id", "response"), [
    ("openmates", "get-docs", {"content": None, "error": "Document unavailable"}),
    ("travel", "get_flight", {"success": False, "data_source": "flightradar24", "error": "Flight unavailable"}),
])
# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_failed_document_and_flight_responses_have_no_results(
    app_id: str, skill_id: str, response: dict[str, Any],
) -> None:
    output = _normalize_skill_output(app_id, skill_id, {}, response)

    assert output["results"] == []
    assert output["result_count"] == 0
    assert output["error"] == response["error"]
    assert "completed" not in output["summary"]


@pytest.mark.anyio
@pytest.mark.parametrize(("app_id", "skill_id"), [
    ("images", "generate"),
    ("videos", "create"),
    ("openmates", "share-usecase"),
])
# contract-test: direct surface=rest_api assertions=workflows.actions.skill-contract
async def test_unsafe_workflow_contract_stops_before_dispatch_and_billing(
    monkeypatch: pytest.MonkeyPatch, app_id: str, skill_id: str,
) -> None:
    registry = FakeRegistry(metadata=None)
    adapter = WorkflowAppSkillAdapter(registry=registry)

    async def no_precheck(**_kwargs: Any) -> None:
        raise AssertionError("billing precheck must not run")

    monkeypatch.setattr(workflow_app_skill_adapter, "_precheck_workflow_skill_billing", no_precheck)
    with pytest.raises(WorkflowSkillBillingError) as exc:
        await adapter.execute(app_id, skill_id, {}, user_id="owner", billing_context={
            "workflow_id": "wf", "run_id": "run", "node_id": "step", "source": "workflow",
        })

    assert exc.value.code == "WORKFLOW_RUNTIME_UNSUPPORTED"
    assert registry.calls == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=workflows.actions.skill-contract
async def test_declared_unsafe_mode_stops_even_without_central_classification() -> None:
    registry = FakeRegistry(metadata={"skills": [{
        "id": "queued", "workflow": {"execution_mode": "async_job", "unattended": True, "approval": "never"},
    }]})
    adapter = WorkflowAppSkillAdapter(registry=registry)

    with pytest.raises(WorkflowSkillBillingError) as exc:
        await adapter.execute("example", "queued", {}, user_id="owner")

    assert exc.value.code == "WORKFLOW_RUNTIME_UNSUPPORTED"
    assert registry.calls == []


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_generic_workflow_search_output_preserves_flattened_dict_results() -> None:
    raw_output = {
        "provider": "ExampleProvider",
        "results": [
            {
                "id": "request-1",
                "results": [
                    {
                        "title": "Coffee beans",
                        "url": "https://shop.example/item?utm_source=test&size=1kg#details",
                        "price": 18.5,
                    },
                    "discard non-object result",
                ],
            }
        ],
    }

    output = _normalize_skill_output(
        "shopping",
        "search_products",
        {"requests": [{"query": "coffee beans"}]},
        raw_output,
    )

    assert output["result_count"] == 1
    assert output["results"] == [
        {
            "title": "Coffee beans",
            "url": "https://shop.example/item?utm_source=test&size=1kg#details",
            "canonical_url": "https://shop.example/item?size=1kg",
            "price": 18.5,
            "provider": "ExampleProvider",
            "source_id": "https://shop.example/item?size=1kg",
        }
    ]
    assert output["raw"] is raw_output


# contract-test: supporting surface=rest_api assertions=hosting-domains.surface-parity,hosting-domains.availability.selection,hosting-domains.quotes.truthful
def test_hosting_workflow_flattens_only_selected_domains_and_preserves_group_evidence() -> None:
    selected = {
        "domain_ascii": "example.com",
        "domain_unicode": "example.com",
        "availability": "available",
        "url": "https://shop.gandi.net/en/domain/suggest?search=example.com",
        "currency": "EUR",
        "country": "DE",
        "registration_tiers": [{"unit": "year", "price_including_tax": 14.28}],
        "renewal_tiers": [{"unit": "year", "price_including_tax": 47.60}],
    }
    used = {"domain_ascii": "example.net", "availability": "unavailable"}
    raw_output = {
        "success": True,
        "provider": "Gandi",
        "results": [
            {"id": "com", "query": "example.com", "partial": False,
             "results": [selected], "checked_results": [selected], "warnings": [], "error": None},
            {"id": 2, "query": "example.net", "partial": True,
             "results": [], "checked_results": [used],
             "warnings": ["The checked domain is unavailable"], "error": None},
            {"id": "failed", "query": "bad.example", "partial": True,
             "results": [], "checked_results": [],
             "warnings": ["Some domain checks were unavailable"],
             "error": "Domain provider unavailable"},
        ],
    }

    output = _normalize_skill_output(
        "hosting", "search_domains",
        {"requests": [{"id": "com", "query": "example.com"},
                      {"id": 2, "query": "example.net", "availability": "available_only"}]},
        raw_output,
    )

    assert output["result_count"] == 1
    assert output["provider"] == "Gandi"
    assert output["results"] == [{
        **selected,
        "provider": "Gandi",
        "canonical_url": selected["url"],
        "source_id": selected["url"],
    }]
    assert output["results"][0]["registration_tiers"][0]["price_including_tax"] == 14.28
    assert output["results"][0]["renewal_tiers"][0]["price_including_tax"] == 47.60
    assert output["raw"] is raw_output
    assert output["raw"]["results"][1]["id"] == 2
    assert output["raw"]["results"][1]["checked_results"] == [used]
    assert output["raw"]["results"][2]["error"] == "Domain provider unavailable"
    assert "error" not in output  # A failed sibling does not fail the successful Workflow step.


# contract-test: supporting surface=rest_api assertions=hosting-domains.results.partial-and-safe,hosting-domains.surface-parity
def test_hosting_workflow_total_error_keeps_safe_group_diagnostics() -> None:
    raw_output = {
        "success": False, "provider": "Gandi", "error": "Domain provider unavailable",
        "results": [{"id": "exact", "query": "example.com", "partial": True,
                     "results": [], "checked_results": [{"domain_ascii": "example.com", "availability": "unknown"}],
                     "warnings": ["Some domain availability checks were inconclusive"],
                     "error": "Domain availability could not be checked"}],
    }
    output = _normalize_skill_output("hosting", "search_domains", {}, raw_output)

    assert output["results"] == []
    assert output["result_count"] == 0
    assert output["error"] == "Domain provider unavailable"
    assert output["raw"]["results"][0]["checked_results"][0]["availability"] == "unknown"


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_travel_connection_workflow_output_preserves_real_grouped_result_fields() -> None:
    connection = {
        "type": "connection",
        "hash": "internal-deduplication-hash",
        "origin": "Berlin Hbf",
        "destination": "Hamburg Hbf",
        "departure": "2026-08-01T08:00:00+02:00",
        "arrival": "2026-08-01T09:45:00+02:00",
        "duration": "1h 45m",
        "total_price": "29.99",
        "currency": "EUR",
        "transport_method": "train",
        "booking_url": "https://booking.example/connection",
        "source_provider": "deutsche_bahn",
        "trip_type": "one_way",
        "stops": 0,
        "carriers": ["ICE"],
        "booking_provider": "Deutsche Bahn",
    }
    raw_output = {
        "provider": "travel",
        "results": [{"id": "berlin-hamburg", "results": [connection]}],
    }

    output = _normalize_skill_output(
        "travel",
        "search_connections",
        {"requests": [{"legs": [{"origin": "Berlin", "destination": "Hamburg", "date": "2026-08-01"}]}]},
        raw_output,
    )

    assert output["result_count"] == 1
    assert output["results"] == [{**connection, "provider": "travel"}]
    assert output["raw"] is raw_output


@pytest.mark.parametrize(
    ("app_id", "skill_id", "raw_output", "expected"),
    [
        (
            "finance",
            "check_accounts",
            {"account_count": 2, "transaction_count": 14, "overview": {"summaries": {"income_total": 1200}}},
            {"account_count": 2, "transaction_count": 14, "overview": {"summaries": {"income_total": 1200}}},
        ),
        ("math", "calculate", {"result": "4"}, {"result": "4"}),
        (
            "openmates",
            "share-usecase",
            {"success": True, "message": "Use case shared"},
            {"success": True, "message": "Use case shared"},
        ),
    ],
)
# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_workflow_output_contract_passthrough_fields(
    app_id: str,
    skill_id: str,
    raw_output: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    output = _normalize_skill_output(app_id, skill_id, {}, raw_output)

    assert {field: output[field] for field in expected} == expected


@pytest.mark.parametrize(
    ("app_id", "skill_id"),
    [("business", "company_financials"), ("web", "search")],
)
# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_inline_workflow_result_lists_are_preserved(app_id: str, skill_id: str) -> None:
    raw_output = {"results": [{"results": [{"title": "Result", "url": "https://example.com/result"}]}]}

    output = _normalize_skill_output(app_id, skill_id, {}, raw_output)

    assert output["result_count"] == 1
    assert output["results"] == [
        {
            "title": "Result",
            "url": "https://example.com/result",
            "canonical_url": "https://example.com/result",
            "source_id": "https://example.com/result",
        }
    ]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
async def test_workflow_strips_prompt_injection_opt_out_and_still_sanitizes_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeRegistry(response={"results": [{"description": "external workflow output"}]})
    captured_contexts: list[Any] = []

    async def fake_safety(result: dict[str, Any], context: Any) -> dict[str, Any]:
        captured_contexts.append(context)
        return result

    monkeypatch.setattr(workflow_app_skill_adapter, "sanitize_app_skill_output", fake_safety)
    secrets_manager = object()
    cache_service = object()
    adapter = WorkflowAppSkillAdapter(
        registry=registry,
        secrets_manager=secrets_manager,
        cache_service=cache_service,
    )

    await adapter.execute(
        "news",
        "search",
        {
            "requests": [{"query": "AI news"}],
            "security": {"prompt_injection_protection": "disabled"},
        },
        user_id="alice",
    )

    assert "security" not in registry.calls[0][2]
    assert captured_contexts[0].surface == "workflow"
    assert captured_contexts[0].external_data is True
    assert captured_contexts[0].secrets_manager is secrets_manager
    assert captured_contexts[0].cache_service is cache_service
    assert captured_contexts[0].request_body["security"] == {"prompt_injection_protection": "disabled"}


# contract-test: supporting surface=rest_api assertions=workflows.ai-ask.execution
def test_workflow_preview_uses_registered_child_embed_types_without_dispatch() -> None:
    registry = FakeRegistry(metadata={"embed_types": [
        {"skill_id": "search", "has_children": True, "child_frontend_type": "events-event"},
        {"skill_id": "search_connections", "has_children": True, "child_frontend_type": "travel-connection"},
    ]})
    adapter = WorkflowAppSkillAdapter(registry=registry)
    assert adapter.result_embed_type("events", "search") == "events-event"
    assert adapter.result_embed_type("travel", "search_connections") == "travel-connection"
    assert adapter.result_embed_type("events", "unknown") is None
    assert registry.calls == []
