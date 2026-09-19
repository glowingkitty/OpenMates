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

import pytest

from backend.core.api.app import routes as routes_package
from backend.core.api.app.services import workflow_app_skill_adapter
from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter, WorkflowSkillBillingError
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
        {"prompt": "Reply with exactly: Workflow AI OK", "conversation": "e2e-local", "temperature": 0},
        user_id="alice",
    )

    assert registry.calls == [
        (
            "ai",
            "ask",
            {
                "conversation": "e2e-local",
                "temperature": 0,
                "messages": [{"role": "user", "content": "Reply with exactly: Workflow AI OK"}],
                "_user_id": "alice",
                "_external_request": True,
            },
        )
    ]
    assert result["raw"] == {"choices": [{"message": {"content": "Workflow AI OK"}}]}
    assert registry.central_dispatch_active is True


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_ai_ask_preserves_openai_messages_shape() -> None:
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
        "model": "auto",
        "_user_id": "alice",
        "_external_request": True,
    }


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_generic_output_normalization_exposes_artifact_and_task_ids() -> None:
    registry = FakeRegistry(
        response={
            "status": "processing",
            "task_ids": ["task-1"],
            "embed_ids": ["embed-1"],
            "provider": "ExampleProvider",
        }
    )
    adapter = WorkflowAppSkillAdapter(registry=registry)

    result = await adapter.execute("images", "generate", {"requests": [{"prompt": "blue circle"}]})

    assert result["summary"] == "images:generate completed"
    assert result["provider"] == "ExampleProvider"
    assert result["artifact_ids"] == ["embed-1"]
    assert result["task_ids"] == ["task-1"]


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
