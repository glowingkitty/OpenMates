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

    async def resume(self, provider):
        self.calls.append("resume")
        provider.update(running_since=time.time(), provider_deadline=time.time() + 120)

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
