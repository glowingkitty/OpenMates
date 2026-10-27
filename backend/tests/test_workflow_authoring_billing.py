"""Metered workflow authoring uses catalog pricing and the normal usage ledger."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
import httpx

from backend.core.api.app.services import workflow_authoring_billing as billing_module
from backend.core.api.app.services import workflow_registry_planner as planner_module
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
from backend.core.api.app.services.directus.usage import UsageMethods
from backend.core.api.app.services.workflow_gemini_authoring import WorkflowAuthoringStopped
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_input_service import WorkflowInputService
from backend.shared.python_utils.billing_utils import calculate_total_credits
from backend.tests.test_workflow_registry_planner import Author, FlatAuthor, configure, forecast_plan, two_deliveries
from backend.tests.test_workflow_authoring_preselection import Decisions
from backend.tests.test_workflows_models import rain_graph
from backend.tests.workflow_test_utils import workflow_service


ROOT = Path(__file__).resolve().parents[2]


class Catalog:
    def get_model_pricing(self, provider: str, model_id: str, **kwargs):
        path = ROOT / "backend" / "providers" / f"{provider}.yml"
        catalog = yaml.safe_load(path.read_text())
        from datetime import date
        from backend.shared.python_utils.model_pricing import resolve_model_tariff
        model = next((model for model in catalog["models"] if model["id"] == model_id), None)
        return resolve_model_tariff(model, on_date=date(2026, 10, 20), **kwargs) if model else None


@pytest.fixture
def ledger(monkeypatch):
    calls = []
    charged = {}
    prechecks = []

    async def precheck(**kwargs):
        prechecks.append(kwargs)

    async def charge(**kwargs):
        calls.append(kwargs)
        identity = kwargs["idempotency_key"]
        charged.setdefault(identity, kwargs["credits"])
        return {"charged_credits": charged[identity], "idempotent": len(calls) > len(charged)}

    monkeypatch.setattr(billing_module, "ConfigManager", Catalog)
    monkeypatch.setattr(billing_module, "ensure_credit_headroom", precheck)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.apps_api",
                        SimpleNamespace(charge_credits_via_internal_api=charge))
    return calls, charged, prechecks


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
def test_catalog_prices_jev_from_standard_formula_and_keeps_it_out_of_chat_routing():
    from backend.scripts.calculate_per_credit_unit import calculate_per_credit_unit

    jev = Catalog().get_model_pricing("typesafe", "jev-1.14")
    assert Catalog().get_model_pricing("typesafe", "jev-1.13") is not None
    assert jev["for_app_skill"] == "workflows.create-or-modify"
    assert jev["allow_auto_select"] is False
    assert jev["pricing"]["tokens"]["input"]["per_credit_unit"] == calculate_per_credit_unit(0.042)
    assert jev["pricing"]["tokens"]["output"]["per_credit_unit"] == 0
    assert calculate_total_credits(pricing_config=jev, input_tokens=7900, output_tokens=100) == 1


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_each_jev_stage_and_gemini_attempt_has_stable_private_ledger_identity(ledger):
    calls, charged, prechecks = ledger
    billing = billing_module.WorkflowAuthoringBilling(
        user_id="owner-private", session_id="session-private")

    class Jev:
        async def evaluate(self, **kwargs):
            provider = "typesafe" if "route" in kwargs["questions"] else "openrouter"
            return SimpleNamespace(provider=provider,
                                   usage=SimpleNamespace(input_tokens=7900, output_tokens=20))

    metered = billing_module.MeteredJevClient(Jev(), billing)
    await metered.evaluate(state={"request": "private instruction"}, questions={"route": {}})
    await metered.evaluate(state={"request": "private instruction"}, questions={"target": {}})
    await billing.precheck(model=billing_module.GEMINI_MODEL)
    await billing.settle(model=billing_module.GEMINI_MODEL, provider_step="gemini:0",
                         usage={"input_tokens": 450, "output_tokens": 90,
                                "estimated_cost_usd": 9999})

    assert len(prechecks) == len(calls) == len(charged) == 3
    assert [call["credits"] for call in calls] == [1, 1, 2]
    assert all(call["app_id"] == "workflows" and call["skill_id"] == "create-or-modify"
               for call in calls)
    assert all(call["user_id_hash"] == hashlib.sha256(b"owner-private").hexdigest()
               for call in calls)
    assert {call["usage_details"]["provider_step"] for call in calls} == {
        "jev:0", "jev:1", "gemini:0"}
    assert [(call["usage_details"]["server_provider"],
             call["usage_details"]["server_region"]) for call in calls] == [
        ("TypeSafe", "US"), ("OpenRouter", "global"), ("Google AI Studio", "US")]
    assert all(call["usage_details"]["source"] == "direct" for call in calls)
    assert all("private instruction" not in repr(call["usage_details"]) for call in calls)
    assert billing.usage_complete and sum(item["credits_charged"] for item in billing.entries) == 4

    # Replaying settlement of the same provider step reaches the same durable
    # charge identity; the ledger accepts it idempotently.
    replay = billing_module.WorkflowAuthoringBilling(user_id="owner-private", session_id="session-private")
    await replay.settle(model=billing_module.GEMINI_MODEL, provider_step="gemini:0",
                        usage={"input_tokens": 450, "output_tokens": 90})
    assert calls[-1]["idempotency_key"] == calls[-2]["idempotency_key"]
    assert len(charged) == 3


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_unmetered_or_unknown_usage_never_uses_cost_estimate_to_charge(ledger):
    calls, _, _ = ledger
    billing = billing_module.WorkflowAuthoringBilling(user_id="owner", session_id="session")
    await billing.settle(model=billing_module.GEMINI_MODEL, provider_step="gemini:0",
                         usage={"estimated_cost_usd": 10.0})
    await billing.settle(model=billing_module.JEV_MODEL, provider_step="jev:0",
                         usage={"input_tokens": 0, "output_tokens": 0})
    assert calls == []
    assert billing.usage_complete is False
    assert all(item["metered"] is False for item in billing.entries)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_cached_headroom_failure_prevents_paid_jev_call(monkeypatch, ledger):
    from backend.shared.python_utils.billing_utils import BillingError

    provider_calls = []

    async def denied(**kwargs):
        raise BillingError("insufficient")

    class Jev:
        async def evaluate(self, **kwargs):
            provider_calls.append(kwargs)

    monkeypatch.setattr(billing_module, "ensure_credit_headroom", denied)
    billing = billing_module.WorkflowAuthoringBilling(user_id="owner", session_id="session")
    with pytest.raises(billing_module.WorkflowAuthoringBillingError,
                       match="INSUFFICIENT_CREDITS"):
        await billing_module.MeteredJevClient(Jev(), billing).evaluate(state={}, questions={})
    assert provider_calls == [] and ledger[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 2])
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_create_batch_charges_one_gemini_attempt_for_the_request(monkeypatch, ledger, count):
    calls, _, _ = ledger
    configure(monkeypatch, count=count)
    raw = forecast_plan() if count == 1 else {
        "operations": [forecast_plan(), forecast_plan("Second forecast")]}

    class MeteredAuthor(Author):
        async def generate(self, **kwargs):
            result, _ = await super().generate(**kwargs)
            return result, {"input_tokens": 450, "output_tokens": 90,
                            "estimated_cost_usd": 0.002}

    author = MeteredAuthor(raw)
    result = await planner_module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Create forecasts", {"timezone": "Europe/Berlin", "_billing_user_id": "owner",
                             "_billing_session_id": "session"}, object(), author)
    assert result["action"] == ("batch" if count == 2 else "create_workflow")
    assert author.calls == 1 and len(calls) == 1
    assert calls[0]["usage_details"]["provider_step"] == "gemini:0"
    assert result["_authoring_metrics"]["billing"]["credits_charged"] == 2


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_real_preselection_and_generation_each_create_a_usage_entry(ledger):
    calls, _, _ = ledger

    class MeteredAuthor(Author):
        async def generate(self, **kwargs):
            result, _ = await super().generate(**kwargs)
            return result, {"input_tokens": 450, "output_tokens": 90}

    jev = Decisions()
    author = MeteredAuthor(forecast_plan())
    result = await planner_module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Daily forecast", {"timezone": "UTC", "_billing_user_id": "private-owner-987",
                           "_billing_session_id": "private-session-654"}, jev, author)
    assert result["action"] == "create_workflow"
    assert len(jev.requests) == author.calls == 1
    assert "private-owner-987" not in repr(jev.requests)
    assert "private-session-654" not in repr(jev.requests)
    assert [call["usage_details"]["provider_step"] for call in calls] == ["jev:0", "gemini:0"]
    assert result["_authoring_metrics"]["billing"]["credits_charged"] == 3


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_jev_settlement_rejection_stops_before_gemini_without_clarification(monkeypatch, ledger):
    async def rejected(**kwargs):
        response = httpx.Response(402, request=httpx.Request("POST", "http://billing.test/charge"))
        raise httpx.HTTPStatusError("insufficient", request=response.request, response=response)

    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.apps_api",
                        SimpleNamespace(charge_credits_via_internal_api=rejected))
    author = Author(forecast_plan())
    with pytest.raises(billing_module.WorkflowAuthoringBillingError,
                       match="INSUFFICIENT_CREDITS"):
        await planner_module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
            "Daily forecast", {"timezone": "UTC", "_billing_user_id": "owner",
                               "_billing_session_id": "session"}, Decisions(), author)
    assert author.calls == 0


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_validation_retry_charges_both_metered_gemini_attempts(monkeypatch, ledger):
    calls, _, _ = ledger
    configure(monkeypatch)
    bad = forecast_plan()
    bad["steps"][1]["message"][0]["ref"]["field"] = "invented_output"

    class RetryAuthor:
        calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            return deepcopy(bad if self.calls == 1 else forecast_plan()), {
                "input_tokens": 450, "output_tokens": 90,
            }

    author = RetryAuthor()
    result = await planner_module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Daily forecast", {"timezone": "UTC", "_billing_user_id": "owner",
                           "_billing_session_id": "session"}, object(), author)
    assert result["action"] == "create_workflow" and author.calls == 2
    assert [call["usage_details"]["provider_step"] for call in calls] == ["gemini:0", "gemini:1"]
    assert result["_authoring_metrics"]["billing"]["credits_charged"] == 4


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_selected_workflow_edit_bills_generation_without_exposing_owner_to_provider(monkeypatch, ledger):
    calls, _, _ = ledger
    configure(monkeypatch, operation="update")
    registry = WorkflowCapabilityRegistry()
    selection = WorkflowPreselection(
        [registry.get_capability("weather.forecast")], "create", "none", True, {}, {})
    graph = planner_module.compile_authoring_plan(forecast_plan(), selection, "UTC")["graph"]
    before = {"id": "owned-workflow", "version": 7, "title": "Daily forecast",
              "description": "Existing", "icon": "cloud-rain", "graph": graph}

    class MeteredAuthor(Author):
        async def generate(self, **kwargs):
            result, _ = await super().generate(**kwargs)
            assert "_billing_user_id" not in kwargs and "owner-private" not in repr(kwargs)
            return result, {"input_tokens": 450, "output_tokens": 90}

    author = MeteredAuthor({"operation": "update", "workflow_id": before["id"],
                            "schedule": {"type": "daily", "time": "10:00"}})
    result = await planner_module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Move this to ten", {"timezone": "UTC", "selected_workflow": before,
                             "_billing_user_id": "owner-private", "_billing_session_id": "session"},
        object(), author)
    assert result["action"] == "update_workflow" and result["expected_record_version"] == 7
    assert len(calls) == 1 and calls[0]["credits"] == 2


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.provisional-validation
async def test_independent_node_repairs_bill_every_provider_call_once(monkeypatch, ledger):
    calls, charged, _ = ledger
    configure(monkeypatch)
    good = two_deliveries()
    first_bad, second_bad = deepcopy(good), deepcopy(good)
    first_bad["workflows"][0]["nodes"][1]["message_json"] = '{'
    second_bad["workflows"][0]["nodes"][2]["message_json"] = '{'

    class MeteredAuthor(FlatAuthor):
        async def generate(self, **kwargs):
            usage = {"input_tokens": 450, "output_tokens": 90}
            try:
                result, _ = await super().generate(**kwargs)
            except ValueError as exc:
                exc.metrics = usage
                raise
            return result, usage

    author = MeteredAuthor([first_bad, second_bad, good])
    result = await planner_module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Send two forecast messages", {"timezone": "UTC", "_billing_user_id": "owner",
                                       "_billing_session_id": "per-node-session"}, object(), author)
    assert result["action"] == "create_workflow" and len(author.requests) == 3
    assert [call["usage_details"]["provider_step"] for call in calls] == ["gemini:0", "gemini:1", "gemini:2"]
    assert len(charged) == 3 and [call["credits"] for call in calls] == [2, 2, 2]
    assert result["_authoring_metrics"]["billing"]["credits_charged"] == 6


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_stopped_metered_stream_is_charged_and_unmetered_fallback_is_not(monkeypatch, ledger):
    calls, _, _ = ledger
    configure(monkeypatch, unavailable=True)

    class StoppedAuthor:
        calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            raise WorkflowAuthoringStopped(
                "Workflow authoring was stopped", {"input_tokens": 450, "output_tokens": 90})

    author = StoppedAuthor()
    result = await planner_module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Daily forecast", {"timezone": "UTC", "_billing_user_id": "owner",
                           "_billing_session_id": "session"}, object(), author)
    assert result["action"] == "partial" and result["reason"] == "stopped"
    assert author.calls == 1 and len(calls) == 1
    assert result["_authoring_metrics"]["billing"]["credits_charged"] == 2

    billing = billing_module.WorkflowAuthoringBilling(user_id="owner", session_id="another-session")
    await billing.settle(model=billing_module.JEV_MODEL, provider_step="jev:0", usage=None)
    assert len(calls) == 1 and billing.usage_complete is False


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_authoring_usage_survives_existing_settings_and_cli_history_format():
    class Cipher:
        async def encrypt_with_user_key(self, *, key_id, plaintext):
            return f"encrypted:{plaintext}", None

        async def decrypt_with_user_key(self, ciphertext, key_id):
            return ciphertext.removeprefix("encrypted:")

    class SDK:
        rows = []

        async def get_items(self, collection, *, params, no_cache):
            return self.rows

    sdk = SDK()
    usage = UsageMethods(sdk, Cipher())
    row = await usage.create_usage_entry(
        user_id_hash="owner-hash", app_id="workflows", skill_id="create-or-modify",
        usage_type="skill_execution", timestamp=123, credits_charged=2,
        user_vault_key_id="vault-key", model_used=billing_module.GEMINI_MODEL,
        source="direct", actual_input_tokens=450, actual_output_tokens=90,
        server_provider="Google AI Studio", server_region="US", build_only=True,
    )
    assert row["app_id"] == "workflows" and row["skill_id"] == "create-or-modify"
    assert row["encrypted_input_tokens"] == "encrypted:450"
    assert row["encrypted_output_tokens"] == "encrypted:90"
    sdk.rows = [{**row, "id": "usage-row"}]
    history = await usage.get_user_usage_entries(
        user_id_hash="owner-hash", user_vault_key_id="vault-key", limit=10)
    assert history == [{"id": "usage-row", "type": "skill_execution", "source": "direct",
                        "created_at": 123, "updated_at": 123, "app_id": "workflows",
                        "skill_id": "create-or-modify", "chat_id": None, "message_id": None,
                        "api_key_hash": None, "device_hash": None,
                        "tool_inference_iterations": None, "credits": 2,
                        "input_tokens": 450, "output_tokens": 90,
                        "model_used": billing_module.GEMINI_MODEL,
                        "server_provider": "Google AI Studio", "server_region": "US"}]


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
def test_billing_failure_after_preview_fails_session_without_saving_draft():
    class Planner:
        atomic_authoring = True
        requires_workflow_overview = False

        def plan(self, *, text, context):
            assert context["_billing_user_id"] == "owner"
            assert context["_billing_session_id"]
            context["_on_checkpoint"]({"workflow_index": 0, "operation": "create",
                                       "accepted_node_count": len(rain_graph()["nodes"]),
                                       "graph": rain_graph(), "metadata": {"title": "Draft"}})
            raise billing_module.WorkflowAuthoringBillingError("WORKFLOW_AUTHORING_BILLING_UNAVAILABLE")

    workflows = workflow_service()
    result = WorkflowInputService(workflow_service=workflows, planner=Planner()).start(
        user_id="owner", text="Make a rain workflow")
    assert result.status == "failed"
    assert result.error_code == "WORKFLOW_AUTHORING_BILLING_UNAVAILABLE"
    assert workflows.list_workflows("owner") == []


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_mercury_primary_and_gemini_fallback_settle_actual_models_once(monkeypatch, ledger):
    from backend.core.api.app.services.workflow_gemini_authoring import WorkflowAuthoringProviderError
    calls, charged, _ = ledger
    configure(monkeypatch)

    class Mercury:
        model_id = billing_module.MERCURY_MODEL
        async def generate(self, **kwargs):
            raise WorkflowAuthoringProviderError('Workflow provider transport failed',
                {'input_tokens': 100, 'output_tokens': 20}, is_availability_failure=True)

    class Gemini(Author):
        model_id = billing_module.GEMINI_MODEL
        async def generate(self, **kwargs):
            raw, _ = await super().generate(**kwargs)
            return raw, {'input_tokens': 450, 'output_tokens': 90}

    for _ in range(2):
        result = await planner_module.WorkflowRegistryPlanner(secrets_manager=None,
            fallback_author=Gemini(forecast_plan()))._plan('Forecast', {
                'timezone': 'UTC', '_billing_user_id': 'owner', '_billing_session_id': 'stable-session',
            }, object(), Mercury())
        assert result['action'] == 'create_workflow'
    assert len(charged) == 2  # Stable identities across replay of the same session.
    assert [call['credits'] for call in calls] == [1, 2, 1, 2]
    assert [call['usage_details']['provider_step'] for call in calls] == [
        'mercury:0', 'gemini:1', 'mercury:0', 'gemini:1']
    assert [call['usage_details']['server_provider'] for call in calls[:2]] == ['Inception', 'Google AI Studio']
    assert [call['usage_details']['model_used'] for call in calls[:2]] == [
        billing_module.MERCURY_MODEL, billing_module.GEMINI_MODEL]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_three_profile_recovery_bills_actual_attempts_once_and_retains_profiles(monkeypatch, ledger):
    from backend.tests.test_workflow_mercury_authoring import flat_forecast, invalid_delivery
    calls, charged, prechecks = ledger
    configure(monkeypatch)

    class MeteredAuthor(FlatAuthor):
        def __init__(self, response, model, profile):
            super().__init__([response])
            self.model_id, self.reasoning_effort = model, profile

        async def generate(self, **kwargs):
            measured = {'input_tokens': 100, 'output_tokens': 20,
                        'cache_read_input_tokens': 50, 'usage_source': 'provider_reported'}
            try:
                raw, _ = await super().generate(**kwargs)
            except ValueError as exc:
                exc.metrics = measured
                raise
            return raw, measured

    for _ in range(2):
        primary = MeteredAuthor(invalid_delivery(), billing_module.MERCURY_MODEL, 'instant')
        recovery = MeteredAuthor(invalid_delivery(), billing_module.MERCURY_MODEL, 'low')
        fallback = MeteredAuthor(flat_forecast(), billing_module.GEMINI_MODEL, 'low')
        result = await planner_module.WorkflowRegistryPlanner(secrets_manager=None,
            recovery_author=recovery, fallback_author=fallback)._plan('Forecast', {
                'timezone': 'UTC', '_billing_user_id': 'owner', '_billing_session_id': 'three-profiles',
            }, object(), primary)
        assert result['action'] == 'create_workflow'
    assert len(calls) == len(prechecks) == 6 and len(charged) == 3
    assert [c['usage_details']['provider_step'] for c in calls[:3]] == ['mercury:0', 'mercury:1', 'gemini:2']
    assert [c['usage_details']['model_used'] for c in calls[:3]] == [
        billing_module.MERCURY_MODEL, billing_module.MERCURY_MODEL, billing_module.GEMINI_MODEL]
    assert [c['usage_details']['reasoning_effort'] for c in calls[:3]] == ['instant', 'low', 'low']
    assert [c['usage_details']['server_provider'] for c in calls[:3]] == ['Inception', 'Inception', 'Google AI Studio']
    assert all(c['usage_details']['input_tokens'] == 100 and c['usage_details']['output_tokens'] == 20 for c in calls)
    assert calls[0]['usage_details']['cache_read_input_tokens'] == 50


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_cancelled_mercury_attempt_settles_observed_usage_without_recovery(monkeypatch, ledger):
    from backend.tests.test_workflow_mercury_authoring import ProfileAuthor, flat_forecast
    calls, charged, _ = ledger
    configure(monkeypatch)
    cancelled = asyncio.CancelledError()
    cancelled.metrics = {'input_tokens': 100, 'output_tokens': 20}
    primary = ProfileAuthor(cancelled)
    recovery = ProfileAuthor(flat_forecast(), 'low')
    fallback = ProfileAuthor(flat_forecast(), 'low', billing_module.GEMINI_MODEL)
    with pytest.raises(asyncio.CancelledError):
        await planner_module.WorkflowRegistryPlanner(secrets_manager=None, recovery_author=recovery,
            fallback_author=fallback)._plan('Forecast', {
                'timezone': 'UTC', '_billing_user_id': 'owner', '_billing_session_id': 'cancelled',
            }, object(), primary)
    assert len(calls) == len(charged) == 1
    assert calls[0]['usage_details']['model_used'] == billing_module.MERCURY_MODEL
    assert calls[0]['usage_details']['reasoning_effort'] == 'instant'
    assert not recovery.requests and not fallback.requests


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_mercury_uses_host_scoped_launch_tariff_and_preserves_missing_usage(ledger):
    calls, _, _ = ledger
    billing = billing_module.WorkflowAuthoringBilling(user_id='owner', session_id='session')
    prices = billing._pricing(billing_module.MERCURY_MODEL)['tokens']
    assert prices['input']['per_credit_unit'] == 3300
    assert prices['output']['per_credit_unit'] == 950
    await billing.settle(model=billing_module.MERCURY_MODEL, provider_step='mercury:0', usage=None)
    assert calls == [] and billing.usage_complete is False
    assert billing.entries[0]['metered'] is False
    await billing.settle(model=billing_module.MERCURY_MODEL, provider_step='mercury:1',
                         usage={'input_tokens': 3300, 'output_tokens': 950})
    assert calls[0]['credits'] == 2
    assert calls[0]['usage_details']['server_provider'] == 'Inception'


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_mercury_workflow_cache_discount_is_subset_of_inclusive_input(ledger):
    calls, _, _ = ledger
    billing = billing_module.WorkflowAuthoringBilling(user_id='owner', session_id='cached-session')
    await billing.precheck(model=billing_module.MERCURY_MODEL)
    await billing.settle(model=billing_module.MERCURY_MODEL, provider_step='mercury:0',
                         usage={'input_tokens': 33000, 'output_tokens': 950, 'cache_read_input_tokens': 29700})
    assert calls[0]['credits'] == 2  # floor(3300/3300 + 29700/33000 + 950/950)
    details = calls[0]['usage_details']
    assert details['input_tokens'] == 33000
    assert details['uncached_input_tokens'] == 3300
    assert details['cache_read_input_tokens'] == 29700
    assert details['billing_mode'] == 'cache_aware'
    assert details['pricing_version']

    await billing.settle(model=billing_module.MERCURY_MODEL, provider_step='mercury:1',
                         usage={'input_tokens': 33000, 'output_tokens': 950})
    assert calls[1]['credits'] == 11
    assert calls[1]['usage_details']['cache_read_input_tokens'] is None
    assert calls[1]['usage_details']['billing_mode'] == 'ordinary_input'
    for invalid in (33001, -1, True):
        with pytest.raises(billing_module.WorkflowAuthoringBillingError):
            await billing.settle(model=billing_module.MERCURY_MODEL, provider_step='mercury:2',
                                 usage={'input_tokens': 33000, 'output_tokens': 950, 'cache_read_input_tokens': invalid})
    assert len(calls) == 2


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge,workflows.authoring.compact-plan
async def test_mercury_workflow_attempt_retains_its_admitted_cache_tariff(ledger):
    calls, _, _ = ledger
    billing = billing_module.WorkflowAuthoringBilling(user_id='owner', session_id='snapshot-session')
    await billing.precheck(model=billing_module.MERCURY_MODEL)

    class RepricedCatalog:
        def get_model_pricing(self, *args, **kwargs):
            raise AssertionError('Settlement must use the already admitted tariff')

    billing.config_manager = RepricedCatalog()
    await billing.settle(model=billing_module.MERCURY_MODEL, provider_step='mercury:0',
                         usage={'input_tokens': 33000, 'output_tokens': 950, 'cache_read_input_tokens': 29700})
    assert calls[0]['credits'] == 2
