"""Encrypted summary intent checkpoint and internal REST ownership contract."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.core.api.app.services.team_billing_service import (
    TeamBillingService,
    frozen_summary_billing_intent,
)
from backend.tests.test_usage_entries import RoundTripEncryption, _llm_receipt


USER = "22222222-2222-4222-8222-222222222222"
TEAM = "33333333-3333-4333-8333-333333333333"
CHAT = "44444444-4444-4444-8444-444444444444"
SUMMARY = "55555555-5555-4555-8555-555555555555"
CHARGE = "ai-ask:task-one:summary"


def summary_receipt() -> dict:
    receipt = _llm_receipt()
    receipt["entries"][0]["purpose"] = "summary"
    receipt["entries"][0]["model_id"] = "google/gemini-3.5-flash-lite"
    receipt["entries"][0]["inference_host"] = "google_ai_studio"
    receipt["settlement_state"] = "pending"
    return receipt


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown,billing.credits.idempotent-charge
def test_summary_intent_accepts_only_pending_numeric_summary_receipt() -> None:
    receipt = summary_receipt()
    serialized, digest = frozen_summary_billing_intent(
        charge_id=CHARGE, chat_id=CHAT, message_id="message-1",
        summary_message_id=SUMMARY, llm_usage_breakdown=receipt,
    )
    assert hashlib.sha256(serialized.encode()).hexdigest() == digest
    assert json.loads(serialized)["state"] == "response_recorded"
    assert json.loads(serialized)["llm_usage_breakdown"] == receipt
    assert "summary_content" not in serialized
    fallback = summary_receipt()
    fallback["entries"][0].update(model_id="openai/gpt-oss-120b", inference_host="cerebras")
    frozen_summary_billing_intent(
        charge_id=CHARGE, chat_id=CHAT, message_id="message-1",
        summary_message_id=SUMMARY, llm_usage_breakdown=fallback,
    )
    fallback["entries"][0]["inference_host"] = "google_ai_studio"
    with pytest.raises(ValueError):
        frozen_summary_billing_intent(
            charge_id=CHARGE, chat_id=CHAT, message_id="message-1",
            summary_message_id=SUMMARY, llm_usage_breakdown=fallback,
        )
    private = summary_receipt()
    private["supplier_cost_usd"] = "0.001"
    with pytest.raises(ValueError):
        frozen_summary_billing_intent(
            charge_id=CHARGE, chat_id=CHAT, message_id="message-1",
            summary_message_id=SUMMARY, llm_usage_breakdown=private,
        )
    receipt["entries"][0].pop("purpose")
    with pytest.raises(ValueError):
        frozen_summary_billing_intent(
            charge_id=CHARGE, chat_id=CHAT, message_id="message-1",
            summary_message_id=SUMMARY, llm_usage_breakdown=receipt,
        )
    receipt = summary_receipt()
    receipt["entries"][0]["model_id"] = "private prompt text"
    with pytest.raises(ValueError):
        frozen_summary_billing_intent(
            charge_id=CHARGE, chat_id=CHAT, message_id="message-1",
            summary_message_id=SUMMARY, llm_usage_breakdown=receipt,
        )


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary,billing.usage.receipt-token-breakdown
@pytest.mark.anyio
async def test_team_summary_intent_authorizes_member_and_encrypts_with_actor_key(monkeypatch) -> None:
    calls = []
    encryption = RoundTripEncryption()

    class Directus:
        usage = SimpleNamespace(encryption_service=encryption)

        def __init__(self):
            self.team = SimpleNamespace(require_team_role=AsyncMock())

        async def get_user_fields_direct(self, user_id, fields, no_cache=False):
            assert (user_id, fields, no_cache) == (USER, ["id", "vault_key_id"], True)
            return {"id": USER, "vault_key_id": "actor-vault-key"}

    async def execute(_self, operation, body):
        calls.append((operation, body))
        return {"state": "response_recorded", "charge_id": CHARGE, "idempotent": False}

    from backend.core.api.app.services import team_billing_service

    monkeypatch.setattr(team_billing_service.SubChatOrchestrationService, "execute", execute)
    directus = Directus()
    service = TeamBillingService(directus)
    result = await service.record_summary_billing_intent(
        team_id=TEAM, actor_user_id=USER, charge_id=CHARGE, chat_id=CHAT,
        message_id="message-1", summary_message_id=SUMMARY,
        llm_usage_breakdown=summary_receipt(),
    )
    assert result["state"] == "response_recorded"
    directus.team.require_team_role.assert_awaited_once_with(TEAM, USER, {"owner", "admin", "member"})
    operation, body = calls[0]
    assert operation == "record_billing_reservation_intent"
    assert body["subject_kind"] == "team"
    assert body["subject_hash"] == hash_id(TEAM)
    assert body["actor_user_hash"] == hash_id(USER)
    assert body["intent_vault_key_id"] == "actor-vault-key"
    assert body["receipt_credits"] == 1
    assert body["encrypted_intent"].startswith("enc:actor-vault-key:")
    directus.team.require_team_role.side_effect = TeamPermissionError("not a member")
    with pytest.raises(TeamPermissionError):
        await service.record_summary_billing_intent(
            team_id=TEAM, actor_user_id=USER, charge_id=CHARGE, chat_id=CHAT,
            message_id="message-1", summary_message_id=SUMMARY,
            llm_usage_breakdown=summary_receipt(),
        )
    assert len(calls) == 1


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown,billing.credits.idempotent-charge
@pytest.mark.anyio
async def test_personal_summary_intent_uses_owner_vault_key(monkeypatch) -> None:
    pytest.importorskip("redis", reason="BillingService imports cache runtime")
    pytest.importorskip("celery", reason="BillingService imports worker runtime")
    from backend.core.api.app.services import billing_service

    calls = []

    async def execute(_self, operation, body):
        calls.append((operation, body))
        return {"state": "response_recorded", "charge_id": CHARGE, "idempotent": False}

    monkeypatch.setattr(billing_service.SubChatOrchestrationService, "execute", execute)
    directus = SimpleNamespace(get_user_fields_direct=AsyncMock(
        return_value={"id": USER, "vault_key_id": "owner-vault-key"},
    ))
    service = billing_service.BillingService(
        cache_service=object(), directus_service=directus,
        encryption_service=RoundTripEncryption(),
    )
    result = await service.record_summary_billing_intent(
        user_id=USER, user_id_hash=hash_id(USER), charge_id=CHARGE,
        chat_id=CHAT, message_id="message-1", summary_message_id=SUMMARY,
        llm_usage_breakdown=summary_receipt(),
    )
    assert result["state"] == "response_recorded"
    directus.get_user_fields_direct.assert_awaited_once_with(USER, ["id", "vault_key_id"], no_cache=True)
    assert calls[0][1]["subject_hash"] == hash_id(USER)
    assert calls[0][1]["intent_vault_key_id"] == "owner-vault-key"
    assert calls[0][1]["receipt_credits"] == 1
    assert calls[0][1]["encrypted_intent"].startswith("enc:owner-vault-key:")


# contract-test: direct surface=rest_api assertions=billing.access.authenticated-first-party,billing.credits.idempotent-charge
@pytest.mark.anyio
async def test_internal_summary_intent_rest_auth_scope_and_payload(monkeypatch) -> None:
    pytest.importorskip("redis", reason="internal API imports cache runtime")
    pytest.importorskip("celery", reason="internal API imports worker runtime")
    from backend.core.api.app.routes import internal_api
    from backend.core.api.app.utils import internal_auth

    monkeypatch.setattr(internal_auth, "INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    personal = SimpleNamespace(record_summary_billing_intent=AsyncMock(return_value={
        "state": "response_recorded", "charge_id": CHARGE, "idempotent": False,
    }))
    team = SimpleNamespace(record_summary_billing_intent=AsyncMock(return_value={
        "state": "response_recorded", "charge_id": CHARGE, "idempotent": False,
    }))
    app = FastAPI()
    app.include_router(internal_api.router)
    app.dependency_overrides[internal_api.get_billing_service] = lambda: personal
    app.dependency_overrides[internal_api.get_team_billing_service] = lambda: team
    payload = {
        "charge_id": CHARGE, "user_id": USER, "user_id_hash": hash_id(USER),
        "app_id": "ai", "skill_id": "ask", "chat_id": CHAT, "message_id": "message-1",
        "summary_message_id": SUMMARY, "llm_usage_breakdown": summary_receipt(),
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path = "/internal/billing/reservation/record-intent"
        assert (await client.post(path, json=payload)).status_code == 401
        headers = {"X-Internal-Service-Token": "test-internal-token"}
        response = await client.post(path, json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"state": "response_recorded", "charge_id": CHARGE, "idempotent": False}
        assert personal.record_summary_billing_intent.await_count == 1
        assert (await client.post(path, json={**payload, "team_id": TEAM}, headers=headers)).status_code == 200
        assert team.record_summary_billing_intent.await_count == 1
        assert (await client.post(path, json={**payload, "user_id_hash": "0" * 64}, headers=headers)).status_code == 409
        assert (await client.post(path, json={**payload, "summary_content": "private"}, headers=headers)).status_code == 422
        team.record_summary_billing_intent.side_effect = TeamPermissionError("not a member")
        assert (await client.post(path, json={**payload, "team_id": TEAM}, headers=headers)).status_code == 403
