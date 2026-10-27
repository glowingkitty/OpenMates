"""Fund website creator shares only from committed internal billing receipts."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from backend.core.api.app.services.creators import paid_web_read_income as paid
from backend.core.api.app.services.creators.revenue_service import CreatorRevenueService
from backend.tests.test_web_read_billing import _helpers, _success


@pytest.fixture
def funded(monkeypatch):
    from backend.core.api.app.services import cache, directus
    from backend.core.api.app.utils import encryption

    entries = {}
    attempts = []
    encrypt = AsyncMock(return_value=("encrypted-ten",))

    class Database:
        async def create_item(self, *, collection, payload):
            assert collection == "creator_income"
            attempts.append(payload)
            if payload.get("id") in entries:
                return False, {"error": "duplicate primary key"}
            entries[payload.get("id")] = payload
            return True, payload

    database = Database()
    monkeypatch.setattr(paid, "is_payment_enabled", lambda: True)
    monkeypatch.setattr(cache, "CacheService", lambda: None)
    monkeypatch.setattr(encryption, "EncryptionService", lambda **_: SimpleNamespace(encrypt=encrypt))
    monkeypatch.setattr(directus, "DirectusService", lambda **_: database)
    return SimpleNamespace(entries=entries, attempts=attempts, encrypt=encrypt, database=database)


def _receipt(**updates):
    return {"status": "success", "state": "committed", "charged_credits": 20,
            "charge_id": "web-read-paid-operation", **updates}


# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.asyncio
async def test_committed_charge_reserves_ten_once_and_hashes_identifiers(funded):
    group = _success()
    assert await paid.record_paid_web_read_income(group, _receipt()) is True
    assert await paid.record_paid_web_read_income(group, _receipt()) is False
    assert len(funded.entries) == 1
    assert funded.attempts[0]["id"] == funded.attempts[1]["id"]
    assert UUID(funded.attempts[0]["id"]).version == 5
    entry = funded.attempts[0]
    assert entry["content_type"] == "website"
    assert entry["income_source"] == "skill_usage"
    assert all(len(entry[key]) == 64 for key in ("hashed_owner_id", "hashed_content_id", "hashed_app_id", "hashed_skill_id"))
    assert "https://example.com" not in repr(entry)
    assert all(call.kwargs["plaintext"] == "10" for call in funded.encrypt.await_args_list)
    assert await paid.record_paid_web_read_income(group, _receipt(charge_id="another-paid-operation")) is True
    assert len(funded.entries) == 2


@pytest.mark.parametrize("receipt", [
    None, {}, _receipt(status="pending"), _receipt(state="retry_scheduled"),
    _receipt(state="reserved"), _receipt(charged_credits=19), _receipt(charged_credits=True),
    _receipt(charged_credits="20"), _receipt(charge_id=None), _receipt(charge_id=""),
    {"status": "finalized", "actual_credits": 20, "charge_id": "anonymous-hold"},
])
# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.asyncio
async def test_unconfirmed_or_underfunded_receipts_never_create_income(funded, receipt):
    assert await paid.record_paid_web_read_income(_success(), receipt) is False
    assert funded.attempts == []


@pytest.mark.parametrize("group", [
    None, {}, {**_success(), "error": "blocked"}, {**_success(), "usage": {"credits_charged": 0}},
    {**_success(), "results": []}, {**_success(), "results": [{"markdown": " ", "url": "https://example.com"}]},
    {**_success(), "results": [{"markdown": "text", "url": "file:///private"}]},
    {**_success(), "results": [{"markdown": "text", "url": "https://user:secret@example.com"}]},
    {**_success(), "results": _success()["results"] * 2},
])
# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.asyncio
async def test_failed_or_unusable_groups_never_create_income(funded, group):
    assert await paid.record_paid_web_read_income(group, _receipt()) is False
    assert funded.attempts == []


# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.asyncio
async def test_payment_disabled_or_creator_outage_does_not_raise(funded, monkeypatch):
    monkeypatch.setattr(paid, "is_payment_enabled", lambda: False)
    assert await paid.record_paid_web_read_income(_success(), _receipt()) is False
    assert funded.attempts == []
    monkeypatch.setattr(paid, "is_payment_enabled", lambda: True)
    funded.encrypt.side_effect = RuntimeError("creator encryption offline")
    assert await paid.record_paid_web_read_income(_success(), _receipt()) is False
    assert funded.attempts == []


# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.asyncio
async def test_optional_income_id_leaves_legacy_default_unchanged(funded):
    service = CreatorRevenueService(funded.database, SimpleNamespace(encrypt=funded.encrypt))
    assert await service.create_income_entry("example.com", "https://example.com", "website", "web", "read", 10)
    assert "id" not in funded.attempts[0]
    assert not await service.create_income_entry("example.com", "https://example.com", "website", "web", "read", 10, entry_id="not-a-uuid")
    assert len(funded.attempts) == 1


@pytest.mark.parametrize("receipt,http_error", [(_receipt(), False), (_receipt(status="pending", state="retry_scheduled"), False), (_receipt(), True)])
# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.asyncio
async def test_rest_calls_payout_only_after_billing_acknowledgement(funded, receipt, http_error):
    rest = _helpers("backend/core/api/app/routes/apps_api.py", ["charge_credits_via_internal_api"])
    events = []

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def post(self, url, **kwargs):
            events.append("debit")
            assert "server_result_group" not in kwargs["json"]
            assert "https://example.com" not in repr(kwargs["json"])
            return httpx.Response(503 if http_error else 200, json=receipt, request=httpx.Request("POST", url))

    rest.charge_credits_via_internal_api.__globals__.update(
        httpx=SimpleNamespace(AsyncClient=Client, HTTPStatusError=httpx.HTTPStatusError),
        INTERNAL_API_BASE_URL="https://billing.invalid", INTERNAL_API_SHARED_TOKEN="",
    )
    result = await rest.charge_credits_via_internal_api("user", "hashed", 20, "web", "read",
                                                      idempotency_key="stable", server_result_group=_success())
    assert events == ["debit"]
    if http_error:
        assert result is None
    else:
        assert result == receipt
    assert len(funded.entries) == (1 if not http_error and receipt["state"] == "committed" else 0)


# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.asyncio
async def test_workflow_passes_actual_success_group_outside_usage_metadata(monkeypatch):
    import hashlib
    import sys
    from backend.core.api.app import routes
    from backend.core.api.app.utils import config_manager

    workflow = _helpers("backend/core/api/app/services/workflow_app_skill_adapter.py", ["_charge_workflow_skill_result"])
    charged = AsyncMock(return_value=_receipt())
    fake_api = SimpleNamespace(
        is_skill_execution_successful=lambda _: True,
        calculate_skill_credits=AsyncMock(return_value=20),
        get_variable_result_charge_items=lambda *_: [(1, 20)],
        resolve_skill_provider_info=lambda *_: {"model_used": None, "server_provider": None, "server_region": None},
        get_variable_result_usage_details=lambda *_: {"web_read_credits_charged": 20},
        charge_credits_via_internal_api=charged,
    )
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.apps_api", fake_api)
    monkeypatch.setattr(routes, "apps_api", fake_api, raising=False)
    monkeypatch.setattr(config_manager, "ConfigManager", lambda: None)
    workflow._charge_workflow_skill_result.__globals__.update(
        hashlib=hashlib, _workflow_credit_allowance=lambda _: None,
        _find_skill_definition=lambda *_: object(), _workflow_usage_source=lambda _: "workflow",
        _workflow_billing_identity=lambda **_: "stable-workflow-operation",
    )
    group = _success()
    total = await workflow._charge_workflow_skill_result(
        app_id="web", skill_id="read", request={"requests": [{"url": "https://example.com"}] * 2},
        result={"results": [{"error": "blocked", "results": []}, group]},
        user_id="test", metadata=object(), billing_context={},
    )
    assert total == 20
    assert charged.await_args.kwargs["server_result_group"] is group
    assert "https://example.com" not in repr(charged.await_args.kwargs["usage_details"])
