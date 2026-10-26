"""Offline session authority, control races, lifecycle and actual-cost accounting."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from decimal import Decimal
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from backend.core.api.app.services.web_browse_service import BrowseService, BrowseStore
from backend.shared.providers.e2b_browser import (
    BrowserAdmissionRejected,
    BrowserUnavailable,
)
from backend.shared.python_schemas.web_browse import (
    BrowseRequest,
    BrowseControl,
    charged_credits,
    session_lifecycle,
)


class MemoryStore:
    def __init__(self):
        self.records = {}
        self.results = {}
        self.cache = None
        self.locks = {}
        self.db = SimpleNamespace(get_items=AsyncMock(return_value=[]))

    @asynccontextmanager
    async def lease(self, key):
        async with self.locks.setdefault(key, asyncio.Lock()):
            yield

    async def load(self, session_id, user_id, chat_id=None):
        record = self.records.get(session_id)
        if (
            not record
            or (user_id and record["user_id"] != user_id)
            or (chat_id and record["chat_id"] != chat_id)
        ):
            raise HTTPException(404, "Unavailable")
        return deepcopy(record)

    async def save(self, record, **kwargs):
        self.records[record["session_id"]] = deepcopy(record)

    async def load_result(self, run_id, user_id):
        value = self.results.get((run_id, user_id))
        if not value:
            raise HTTPException(404, "Unavailable")
        return value.model_copy(deep=True)

    async def save_result(self, result, record):
        self.results.setdefault(
            (result.run_id, record["user_id"]), result.model_copy(deep=True)
        )
        return self.results[(result.run_id, record["user_id"])].model_copy(deep=True)


class Browser:
    def __init__(self):
        self.calls = []
        self.mode = "ai"
        self.observation = {
            "url": "https://example.com/",
            "title": "Example",
            "text": "Observed fact",
            "controls": [],
            "tables": [],
            "links": [],
            "observation_id": "fresh",
            "screenshot": None,
        }
        self.created = False
        self.fail_start = False

    async def create(self, *, on_created, **kwargs):
        self.calls.append("create")
        p = {
            "sandbox_id": "private-provider-id",
            "token": "private-token",
            "traffic_access_token": "private-ingress",
            "cpu_count": 2,
            "memory_mb": 4096,
            "running_since": time.time() - 3,
            "provider_deadline": time.time() + 120,
        }
        await on_created(p)
        self.created = True
        if self.fail_start:
            p.update(deleted=True, provider_deadline=time.time())
            await on_created(p)
            raise RuntimeError("Private provider error")
        return p

    async def rpc(self, provider, body):
        self.calls.append(deepcopy(body))
        if body["operation"] == "observe":
            return deepcopy(self.observation)
        if body["operation"] == "control":
            self.mode = body["mode"]
        if body["operation"] == "metadata":
            return {"origin": "https://example.com", "url": "https://example.com/"}
        return {"executed": True}

    async def keep_running(self, provider, *, seconds=120):
        provider["provider_deadline"] = time.time() + seconds

    async def pause(self, provider):
        self.calls.append("pause")

    async def resume(self, provider, *, on_resumed=None):
        self.calls.append("resume")
        provider.update(running_since=time.time(), provider_deadline=time.time() + 120)
        if on_resumed:
            await on_resumed(provider)

    async def kill(self, provider):
        self.calls.append("kill")


class Models:
    started = None
    proceed = None
    action = {"kind": "done"}

    def __init__(self, secrets, *, before_attempt, after_attempt, **kwargs):
        self.before = before_attempt
        self.after = after_attempt
        self.attempts = []

    async def choose(self, *args):
        call = await self.before("typesafe/jev-1.14", "typesafe", Decimal("0.0001"))
        if self.started:
            self.started.set()
            await self.proceed.wait()
        attempt = {
            "complete": True,
            "cost_usd": "0.000042",
            "usage": {"input_tokens": 1000, "output_tokens": 0},
        }
        self.attempts.append(attempt)
        await self.after(call, attempt)
        return deepcopy(self.action)

    async def verify(self, *args):
        return True

    async def generate(self, *args):
        return {"data": {"fact": "Observed fact"}}

    async def sanitize_external(self, payload, cache):
        return payload


@pytest.fixture
def service():
    browser = Browser()
    app = SimpleNamespace(
        _make_internal_api_request=AsyncMock(return_value={}),
        charge_user_credits=AsyncMock(
            side_effect=lambda **kwargs: {
                "state": "committed",
                "charged_credits": kwargs["credits_to_charge"],
            }
        ),
    )
    result = BrowseService(
        app=app,
        directus=None,
        encryption=None,
        cache=None,
        secrets_manager=None,
        driver=browser,
        models_factory=Models,
    )
    result.store = MemoryStore()
    return result


def arguments(**kwargs):
    return BrowseRequest(
        task="Read the observed fact", start_url="https://example.com/", **kwargs
    )


async def run(service, request=None, **kwargs):
    return await service.run(
        request or arguments(),
        user_id=kwargs.get("user_id", "owner"),
        chat_id=kwargs.get("chat_id", "chat"),
        message_id=kwargs.get("message_id", "message"),
        vault_key_id="vault-key",
    )


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.session-and-run,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_observed_json_is_replayable_without_new_vm_calls_or_charges(service):
    request = arguments(
        output_schema={
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
        }
    )
    result = await run(service, request)
    assert result.status == "completed"
    assert result.data == {"fact": "Observed fact"}
    assert result.sources == [{"url": "https://example.com/", "title": "Example"}]
    calls = deepcopy(service.driver.calls)
    replay = await run(service, request)
    assert replay == result
    assert service.driver.calls == calls
    assert "private-provider-id" not in result.model_dump_json()
    assert service.store.records[result.session_id]["inference_cost_usd"] == "0.000042"
    service.app.charge_user_credits.assert_not_awaited()  # Running grace is settled on confirmed pause.


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.session-and-run,web-browse.cost-accounting
@pytest.mark.asyncio
@pytest.mark.parametrize("pristine", [True, False])
async def test_pool_handoff_is_owner_bound_before_resuming_and_hidden_until_verified(
    service, monkeypatch, pristine
):
    import backend.core.api.app.services.web_browse_service as module

    monkeypatch.setattr(module, "pool_size", lambda: 3)

    class Pool:
        def __init__(self, *args):
            pass

        async def claim(self, sid, callback):
            provider = {
                "sandbox_id": "prepared-vm",
                "token": "private-token",
                "traffic_access_token": "private-ingress",
                "cpu_count": 2,
                "memory_mb": 4096,
                "created_at": time.time() - 3600,
                "running_since": None,
                "provider_deadline": time.time() - 10,
                "pool_assigned": True,
                "pool_verified": False,
            }
            await callback(provider)
            return provider

    monkeypatch.setattr(module, "BrowsePool", Pool)
    original_rpc = service.driver.rpc

    async def rpc(provider, body):
        if body.get("require_pristine"):
            assert any(
                r.get("provider", {}).get("sandbox_id") == "prepared-vm"
                for r in service.store.records.values()
            )
            return {"pristine": pristine}
        return await original_rpc(provider, body)

    service.driver.rpc = rpc
    result = await run(service)
    record = service.store.records[result.session_id]
    assert "create" not in service.driver.calls and "resume" in service.driver.calls
    assert Decimal(result.metrics["runtime_cost_usd"]) < Decimal(
        "0.01"
    )  # Platform preparation is not charged.
    if pristine:
        assert result.status == "completed" and record["provider"]["pool_verified"]
        with pytest.raises(HTTPException) as exc:
            await service.frame(result.session_id, "other-owner")
        assert exc.value.status_code == 404
    else:
        assert result.data is None and not result.observations
        assert "kill" in service.driver.calls and record["provider"] is None
        assert not any(
            isinstance(c, dict) and c["operation"] == "observe"
            for c in service.driver.calls
        )


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.budgets-and-stop,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_empty_pool_does_not_cold_start_or_hold_customer_funds(
    service, monkeypatch
):
    import backend.core.api.app.services.web_browse_service as module

    monkeypatch.setattr(module, "pool_size", lambda: 3)

    class Empty:
        def __init__(self, *args):
            pass

        async def claim(self, *args):
            return None

    monkeypatch.setattr(module, "BrowsePool", Empty)
    result = await run(service)
    record = service.store.records[result.session_id]
    assert result.status == "failed" and "capacity" in result.reason
    assert not record.get("provider") and not record.get("reservation")
    assert not record.get("accounting_pending")
    assert "create" not in service.driver.calls and "resume" not in service.driver.calls
    assert result.metrics["charged_credits"] == 0


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.exclusive-takeover
@pytest.mark.asyncio
async def test_unverified_pool_handoff_exposes_neither_frames_nor_manual_input(service):
    result = await run(service)
    record = service.store.records[result.session_id]
    record["provider"].update(pool_assigned=True, pool_verified=False)
    calls = deepcopy(service.driver.calls)
    for action in (
        service.frame(result.session_id, "owner"),
        service.control(
            result.session_id, "owner", BrowseControl(operation="take_control")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await action
        assert exc.value.status_code == 409
    assert service.driver.calls == calls


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.truthful-completion,web-browse.cost-accounting
@pytest.mark.asyncio
@pytest.mark.parametrize("repair_verified", [True, False])
async def test_one_metered_extraction_repair_still_requires_independent_verification(
    service, repair_verified
):
    contexts = []

    class RepairModels(Models):
        async def paid(self, cost):
            call = await self.before("test/model", "test", Decimal(cost))
            attempt = {"complete": True, "cost_usd": cost, "usage": {}}
            self.attempts.append(attempt)
            await self.after(call, attempt)

        async def generate(self, context):
            contexts.append(deepcopy(context))
            await self.paid("0.0001")
            return {
                "data": {
                    "fact": "Incomplete" if len(contexts) == 1 else "Observed fact"
                }
            }

        async def verify(self, task, observation, data):
            await self.paid("0.00001")
            self.verification = {"answer_coverage_score": 0.2}
            return len(contexts) == 2 and repair_verified

    service.models_factory = RepairModels
    request = arguments(
        output_schema={
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
        }
    )
    result = await run(service, request)
    assert result.status == ("completed" if repair_verified else "needs_user")
    assert result.data == ({"fact": "Observed fact"} if repair_verified else None)
    assert len(contexts) == 2
    assert contexts[1]["correction"]["previous_candidate"] == {"fact": "Incomplete"}
    assert contexts[1]["correction"]["verification"] == {"answer_coverage_score": 0.2}
    assert contexts[0]["observed_page"] == contexts[1]["observed_page"]
    assert service.store.records[result.session_id]["inference_cost_usd"] == "0.000262"
    assert not any(
        isinstance(c, dict) and c["operation"] == "act" for c in service.driver.calls
    )
    assert await run(service, request) == result
    assert len(contexts) == 2  # Replay cannot spend again or seek a different verdict.


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.truthful-completion,web-browse.sign-in
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate", [{"data": None}, {"data": {"fact": None}, "needs_user": True}]
)
async def test_missing_facts_or_explicit_human_input_do_not_trigger_extraction_repair(
    service, candidate
):
    generated = AsyncMock(return_value=candidate)

    class MissingModels(Models):
        generate = generated
        verify = AsyncMock(return_value=False)

    service.models_factory = MissingModels
    result = await run(service, arguments(output_schema={"type": "object"}))
    assert result.status == "needs_user" and result.data is None
    generated.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.truthful-completion
@pytest.mark.asyncio
async def test_unchanged_repair_cannot_seek_a_different_verification_verdict(service):
    generated = AsyncMock(return_value={"data": {"fact": "Incomplete"}})
    verified = AsyncMock(side_effect=[False, True])

    class UnchangedModels(Models):
        generate = generated
        verify = verified

    service.models_factory = UnchangedModels
    result = await run(service, arguments(output_schema={"type": "object"}))
    assert result.status == "needs_user" and result.data is None
    assert generated.await_count == 2
    verified.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.session-and-run,web-browse.private-storage-and-api
@pytest.mark.asyncio
async def test_foreign_or_different_chat_cannot_observe_resume_or_spend(service):
    result = await run(service)
    calls = deepcopy(service.driver.calls)
    for user, chat in [("stranger", "chat"), ("owner", "another-chat")]:
        with pytest.raises(HTTPException) as exc:
            await run(
                service,
                BrowseRequest(task="Continue", session_id=result.session_id),
                user_id=user,
                chat_id=chat,
                message_id="new",
            )
        assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await service.control(
            result.session_id, "stranger", BrowseControl(operation="take_control")
        )
    assert exc.value.status_code == 404
    assert service.driver.calls == calls


# contract-test: supporting surface=rest_api assertions=web-browse.budgets-and-stop,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_tighter_followup_cap_cannot_silently_spend_the_existing_larger_cap(
    service,
):
    result = await run(service)
    calls = deepcopy(service.driver.calls)
    with pytest.raises(HTTPException) as exc:
        await run(
            service,
            arguments(session_id=result.session_id, max_credits=1),
            message_id="lower-cap",
        )
    assert exc.value.status_code == 409
    assert service.driver.calls == calls


# contract-test: supporting surface=rest_api assertions=web-browse.exclusive-takeover,web-browse.control-loop
@pytest.mark.asyncio
async def test_takeover_during_inference_discards_pending_click(service):
    class DelayedModels(Models):
        started = asyncio.Event()
        proceed = asyncio.Event()
        action = {"kind": "click", "target": "0"}

    service.models_factory = DelayedModels
    task = asyncio.create_task(run(service))
    await asyncio.wait_for(DelayedModels.started.wait(), 2)
    session_id = next(iter(service.store.records))
    await service.control(session_id, "owner", BrowseControl(operation="take_control"))
    DelayedModels.proceed.set()
    result = await asyncio.wait_for(task, 2)
    assert result.status == "needs_user"
    assert service.driver.mode == "user"
    assert not any(
        isinstance(c, dict) and c["operation"] == "act" for c in service.driver.calls
    )
    assert service.store.records[session_id]["inference_cost_usd"] == "0.000042"
    assert not service.store.records[session_id]["pending_calls"]


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_pause_includes_startup_and_inference_then_costs_zero_without_waking(
    service,
):
    result = await run(service)
    await service.control(result.session_id, "owner", BrowseControl(operation="stop"))
    record = service.store.records[result.session_id]
    assert Decimal(record["runtime_cost_usd"]) >= Decimal("0.000138")
    assert record["provider"]["running_since"] is None
    assert record["reservation"] is None
    expected = charged_credits(
        Decimal(record["runtime_cost_usd"]) + Decimal("0.000042")
    )
    assert record["charged_credits"] == expected
    assert (
        service.app.charge_user_credits.await_args.kwargs["credits_to_charge"]
        == expected
    )
    before = service.total_cost(record)
    await service.state(result.session_id, "owner")
    assert service.total_cost(record) == before
    assert "resume" not in service.driver.calls


# contract-test: supporting surface=rest_api assertions=web-browse.budgets-and-stop,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_insufficient_cap_does_not_start_paid_compute(service):
    result = await run(service, arguments(max_credits=1))
    assert result.status == "budget_exceeded"
    assert "create" not in service.driver.calls
    assert not service.store.records[result.session_id]["reservation"]
    service.app.charge_user_credits.assert_not_awaited()
    release = service.app._make_internal_api_request.await_args.kwargs["payload"]
    assert release["reason"] == "definite_no_cost"


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle,web-browse.session-and-run,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_followup_reconciles_native_idle_pause_before_resuming(service):
    first = await run(service)
    record = service.store.records[first.session_id]
    record["provider"]["provider_deadline"] = time.time() - 1
    request = arguments(session_id=first.session_id)
    job = await service.run(
        request,
        user_id="owner",
        chat_id="chat",
        message_id="followup",
        vault_key_id="vault-key",
        prepare_only=True,
    )
    assert service.store.records[first.session_id]["provider"]["running_since"] is None
    result = await service.run(
        request,
        user_id="owner",
        chat_id="chat",
        message_id="followup",
        vault_key_id="vault-key",
        prepared_run_id=job.run_id,
    )
    assert result.status == "completed" and result.session_id == first.session_id
    assert service.driver.calls.count("create") == 1
    assert service.driver.calls.index("pause") < service.driver.calls.index("resume")
    assert all(
        call.args[1] != "/internal/billing/reservation/release"
        for call in service.app._make_internal_api_request.await_args_list
    )


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting
@pytest.mark.asyncio
async def test_pending_charge_keeps_same_intent_and_reservation_until_committed(
    service,
):
    result = await run(service)
    record = service.store.records[result.session_id]
    reservation = record["reservation"]
    charge = service.app.charge_user_credits
    charge.side_effect = None
    charge.return_value = {"state": "retry_scheduled", "charged_credits": 0}
    with pytest.raises(HTTPException) as exc:
        await service.pause(record)
    assert exc.value.status_code == 503
    assert record["reservation"] == reservation and record["settlement"]["delta"] > 0
    assert record["charged_credits"] == 0
    charge.return_value = {
        "state": "committed",
        "charged_credits": record["settlement"]["delta"],
    }
    await service.settle(record)
    assert record["reservation"] is None and record["charged_credits"] > 0
    assert charge.await_count == 2
    assert all(
        call.kwargs["idempotency_key"] == reservation for call in charge.await_args_list
    )
    assert all(
        call.args[1] != "/internal/billing/reservation/release"
        for call in service.app._make_internal_api_request.await_args_list
    )


# contract-test: supporting surface=rest_api assertions=web-browse.budgets-and-stop,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_boot_failure_cleans_up_recoverable_paid_handle_and_reservation(service):
    service.driver.fail_start = True
    result = await run(service)
    assert result.status == "failed"
    record = service.store.records[result.session_id]
    assert record["provider"]["deleted"]
    assert record["active_run"] is None
    assert record["reservation"] is None
    assert record["charged_credits"] > 0


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.budgets-and-stop
@pytest.mark.asyncio
async def test_missing_native_usage_cannot_be_free_success_or_release_hold(service):
    class MissingUsage(Models):
        async def choose(self, *args):
            call = await self.before("typesafe/jev-1.14", "typesafe", Decimal("0.0001"))
            await self.after(call, {"complete": False, "cost_usd": None, "usage": {}})
            return {"kind": "done"}

    service.models_factory = MissingUsage
    result = await run(service)
    assert result.status == "failed"
    record = service.store.records[result.session_id]
    assert record["status"] == "paused"
    assert record["reservation"] and record["accounting_pending"]
    assert record["pending_calls"]
    service.app.charge_user_credits.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.lifecycle
@pytest.mark.asyncio
async def test_known_resume_is_persisted_before_ingress_failure_and_can_be_settled(
    service,
):
    from backend.shared.providers.e2b_browser import BrowserRpcUnavailable

    result = await run(service)
    await service.control(result.session_id, "owner", BrowseControl(operation="stop"))
    native_resume = service.driver.resume

    async def unavailable_ingress(provider, **kwargs):
        await native_resume(provider, **kwargs)
        raise BrowserRpcUnavailable(retryable=True, status_code=502)

    service.driver.resume = unavailable_ingress
    failed = await run(
        service,
        arguments(session_id=result.session_id),
        message_id="resume-ingress-failure",
    )
    record = service.store.records[result.session_id]
    assert failed.status == "failed" and not failed.metrics["accounting_pending"]
    assert not record.get("runtime_intent") and record["reservation"] is None
    assert record["provider"]["running_since"] is None


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.lifecycle,web-browse.private-storage-and-api
@pytest.mark.asyncio
async def test_close_preserves_only_resource_billing_evidence_for_an_unknown_hold(
    service,
):
    result = await run(service)
    service.store.records[result.session_id]["accounting_pending"] = True
    service.store.records[result.session_id]["runtime_intent"] = {"kind": "resume"}
    await service.control(result.session_id, "owner", BrowseControl(operation="close"))
    record = service.store.records[result.session_id]
    assert record["provider"] is None and record["reservation"]
    receipt = record["unresolved_resource_receipt"]
    assert receipt["sandbox_id"] == "private-provider-id"
    assert not {
        "token",
        "traffic_access_token",
        "rpc_url",
        "latest_observation",
    }.intersection(receipt)
    assert "latest_observation" not in record
    service.app.charge_user_credits.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.sign-in,web-browse.private-storage-and-api
@pytest.mark.asyncio
async def test_stale_sign_in_consent_has_no_paid_or_control_side_effect(service):
    result = await run(service)
    await service.control(
        result.session_id, "owner", BrowseControl(operation="take_control")
    )
    calls = deepcopy(service.driver.calls)
    with pytest.raises(HTTPException) as exc:
        await service.control(
            result.session_id,
            "owner",
            BrowseControl(operation="sign_in", sign_in_origin="https://wrong.example"),
        )
    assert exc.value.status_code == 409
    assert service.driver.calls[len(calls) :] == [{"operation": "metadata"}]
    assert not service.store.records[result.session_id]["private_account"]


# contract-test: supporting surface=rest_api assertions=web-browse.exclusive-takeover,web-browse.private-storage-and-api
@pytest.mark.asyncio
async def test_input_is_strictly_typed_and_rejected_outside_manual_control(service):
    with pytest.raises(ValidationError):
        BrowseControl.model_validate(
            {
                "operation": "input",
                "action": {"kind": "type", "text": "secret", "operation": "observe"},
            }
        )
    result = await run(service)
    with pytest.raises(HTTPException) as exc:
        await service.control(
            result.session_id,
            "owner",
            BrowseControl(operation="input", action={"kind": "click", "x": 5, "y": 10}),
        )
    assert exc.value.status_code == 409
    assert not any(
        isinstance(c, dict) and c["operation"] == "manual" for c in service.driver.calls
    )


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle
@pytest.mark.parametrize(
    "idle,expected",
    [(119, "ai"), (120, "paused"), (86399, "paused"), (86400, "expired")],
)
def test_lifecycle_boundaries(idle, expected):
    assert (
        session_lifecycle(
            {"status": "ai", "last_activity": 100, "active_run": None}, 100 + idle
        )
        == expected
    )


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data
@pytest.mark.parametrize(
    "schema",
    [
        {"type": "not-a-type"},
        {"$ref": "https://private/schema"},
        {"type": "string"},
        {"type": "object", "properties": {"x": {"$ref": "#"}}},
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.structured-data
def test_output_schema_is_bounded_local_object_or_array(schema):
    with pytest.raises(ValidationError):
        arguments(output_schema=schema)


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting
def test_fractional_billing_is_rounded_once_for_the_accumulated_cost():
    assert charged_credits(Decimal(0)) == 0
    assert charged_credits(Decimal("0.0002")) == 1
    assert charged_credits(Decimal("0.00149")) == 2
    assert charged_credits(Decimal("0.0015")) == 3


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.session-and-run
@pytest.mark.asyncio
async def test_authoritative_store_checks_owner_before_decrypting():
    db = SimpleNamespace(get_items=AsyncMock(return_value=[]))
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock())
    store = BrowseStore(db, encryption, None)
    with pytest.raises(HTTPException) as exc:
        await store.load(str(uuid.uuid4()), "wrong-owner")
    assert exc.value.status_code == 404
    encryption.decrypt_with_user_key.assert_not_awaited()
    assert db.get_items.await_args.kwargs["no_cache"] is True
    assert db.get_items.await_args.kwargs["params"]["filter[owner_hash][_eq]"]


# contract-test: supporting surface=rest_api assertions=web-browse.session-and-run,web-browse.budgets-and-stop
@pytest.mark.asyncio
async def test_prepared_job_is_stable_and_stop_prevents_queued_compute(service):
    request = arguments()
    job = await service.run(
        request,
        user_id="owner",
        chat_id="chat",
        message_id="message",
        vault_key_id="vault-key",
        prepare_only=True,
    )
    repeated = await service.run(
        request,
        user_id="owner",
        chat_id="chat",
        message_id="message",
        vault_key_id="vault-key",
        prepare_only=True,
    )
    assert repeated == job
    assert service.driver.calls == []
    assert (await service.state(job.session_id, "owner"))["status"] == "ai"
    await service.control(job.session_id, "owner", BrowseControl(operation="stop"))
    with pytest.raises(HTTPException) as exc:
        await service.run(
            request,
            user_id="owner",
            chat_id="chat",
            message_id="message",
            vault_key_id="vault-key",
            prepared_run_id=job.run_id,
        )
    assert exc.value.status_code == 409
    assert "create" not in service.driver.calls
    assert not service.store.records[job.session_id]["reservation"]
    cancelled = await service.finish_failed_job(
        job.session_id, job.run_id, "owner", "chat"
    )
    assert cancelled.status == "cancelled"
    assert "create" not in service.driver.calls
    assert (
        await service.finish_failed_job(job.session_id, job.run_id, "owner", "chat")
        == cancelled
    )


# contract-test: supporting surface=rest_api assertions=web-browse.session-and-run,web-browse.structured-data
@pytest.mark.asyncio
async def test_distinct_followup_keeps_original_result_after_browser_close(service):
    first = await run(service)
    service.driver.observation["text"] = "A different observed fact"
    request = BrowseRequest(task="Read the next fact", session_id=first.session_id)
    second = await run(service, request, message_id="followup")
    assert second.run_id != first.run_id
    await service.control(first.session_id, "owner", BrowseControl(operation="close"))
    calls = deepcopy(service.driver.calls)
    assert await run(service) == first
    assert await run(service, request, message_id="followup") == second
    job = await service.run(
        arguments(),
        user_id="owner",
        chat_id="chat",
        message_id="message",
        vault_key_id="vault-key",
        prepare_only=True,
    )
    assert job.dispatch_required is False
    assert service.driver.calls == calls


# contract-test: supporting surface=rest_api assertions=web-browse.session-and-run,web-browse.control-loop
@pytest.mark.asyncio
async def test_admitted_worker_executes_once_and_recovers_same_result(service):
    request = arguments()
    job = await service.run(
        request,
        user_id="owner",
        chat_id="chat",
        message_id="message",
        vault_key_id="vault-key",
        prepare_only=True,
    )
    result = await service.run(
        request,
        user_id="owner",
        chat_id="chat",
        message_id="message",
        vault_key_id="vault-key",
        prepared_run_id=job.run_id,
    )
    assert result.session_id == job.session_id and result.run_id == job.run_id
    calls = deepcopy(service.driver.calls)
    again = await service.run(
        request,
        user_id="owner",
        chat_id="chat",
        message_id="message",
        vault_key_id="vault-key",
        prepared_run_id=job.run_id,
    )
    assert again == result
    assert service.driver.calls == calls


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle,web-browse.cost-accounting,web-browse.exclusive-takeover
@pytest.mark.asyncio
async def test_close_during_inference_settles_usage_after_draining_call(service):
    class DelayedModels(Models):
        started = asyncio.Event()
        proceed = asyncio.Event()
        action = {"kind": "click", "target": "0"}

    service.models_factory = DelayedModels
    task = asyncio.create_task(run(service))
    await asyncio.wait_for(DelayedModels.started.wait(), 2)
    session_id = next(iter(service.store.records))
    await service.control(session_id, "owner", BrowseControl(operation="close"))
    assert service.store.records[session_id]["reservation"]
    service.app.charge_user_credits.assert_not_awaited()
    DelayedModels.proceed.set()
    result = await asyncio.wait_for(task, 2)
    assert result.status == "cancelled"
    record = service.store.records[session_id]
    assert record["status"] == "closed" and record["provider"] is None
    assert record["inference_cost_usd"] == "0.000042"
    assert record["reservation"] is None
    assert service.app.charge_user_credits.await_count == 1
    assert not any(
        isinstance(c, dict) and c["operation"] == "act" for c in service.driver.calls
    )


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.budgets-and-stop,web-browse.session-and-run
@pytest.mark.asyncio
@pytest.mark.parametrize("known_rejection", [True, False])
async def test_creation_rejection_releases_hold_but_uncertain_creation_stays_pending(
    service, known_rejection
):
    exception = (
        BrowserAdmissionRejected("Rejected")
        if known_rejection
        else BrowserUnavailable("Unknown response")
    )
    service.driver.create = AsyncMock(side_effect=exception)
    result = await run(service)
    assert result.status == "failed"
    record = service.store.records[result.session_id]
    assert bool(record.get("accounting_pending")) is not known_rejection
    assert bool(record.get("reservation")) is not known_rejection
    service.app.charge_user_credits.assert_not_awaited()
    service.driver.create.assert_awaited_once()
    if known_rejection:
        # An opaque ID with no original browser cannot silently allocate a replacement.
        with pytest.raises(HTTPException) as exc:
            await run(
                service,
                BrowseRequest(task="Continue", session_id=result.session_id),
                message_id="next",
            )
        assert exc.value.status_code == 410
        service.driver.create.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.truthful-completion
@pytest.mark.asyncio
async def test_verified_empty_search_stays_no_results_when_schema_demands_records(
    service,
):
    class EmptyModels(Models):
        no_results = True

        async def generate(self, context):
            return {"data": []}

    service.models_factory = EmptyModels
    service.driver.observation["text"] = "No matching records."
    result = await run(
        service,
        arguments(
            output_schema={"type": "array", "minItems": 1, "items": {"type": "object"}}
        ),
    )
    assert result.status == "no_results" and result.data is None
    assert result.observations["text"] == "No matching records."
