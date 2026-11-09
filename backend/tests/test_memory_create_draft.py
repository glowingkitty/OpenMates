# contract-test-file: supporting
# POST /v1/memory-suggestions/create-draft: draft validation, ownership gate and billing.
# Run: python3 -m pytest backend/tests/test_memory_create_draft.py -v
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.apps.ai.processing import memory_create_draft as draft_mod
from backend.apps.ai.processing import memory_preview_billing as billing_mod
from backend.apps.ai.processing.memory_update_preview import MemoryPreviewError
from backend.core.api.app.routes import memory_suggestions as route

GOOD = {"title": "Open source conferences in Europe", "when_to_use": "Recommending events",
        "content": "Interested in open source conferences in Europe.", "valid_until": "2027-12-31"}


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_interpret_builds_canonical_ask_first_document():
    out = draft_mod.interpret_draft(GOOD)
    assert set(out) == {"title", "when_to_use", "body"}
    assert "load_mode: ask_first" in out["body"] and "valid_until" in out["body"]


@pytest.mark.parametrize("bad", [
    None, {}, {**GOOD, "content": "api_key: abcdef123456"}, {**GOOD, "title": "token: abcdef123456"},
    {**GOOD, "valid_from": "not a date"}, {**GOOD, "content": ""},
])
# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_interpret_rejects_unusable_or_secret_drafts(bad):
    with pytest.raises(MemoryPreviewError):
        draft_mod.interpret_draft(bad)


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor
def test_run_uses_recommendation_and_chat_inputs(monkeypatch):
    seen = {}

    async def fake(**kw):
        seen.update(kw)
        return SimpleNamespace(error_message=None, arguments=GOOD, usage_telemetry={"input_tokens": 1, "output_tokens": 1})
    monkeypatch.setattr(draft_mod, "call_preprocessing_llm", fake)
    draft, telemetry = asyncio.run(draft_mod.run_memory_create_draft(
        task_id="t", model_id="m", title="Open source", summary="Europe events", user_message="Find FOSDEM",
        assistant_response="FOSDEM is in Brussels", secrets_manager=None, usage_callback=lambda _e: None))
    prompt = seen["message_history"][0]["content"]
    assert "Open source" in prompt and "Find FOSDEM" in prompt and "FOSDEM is in Brussels" in prompt
    assert seen["observability_purpose"] == "memory_create_draft"
    assert draft["title"] == GOOD["title"] and telemetry["input_tokens"] == 1


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.billing
def test_billing_purpose_is_parameterised(monkeypatch):
    monkeypatch.setattr(billing_mod, "build_model_usage_breakdown", lambda _buckets, _lookup: {
        "credits_charged": 2, "input_tokens": 10, "output_tokens": 5, "entries": []})

    class Billing:
        calls = []

        async def charge_user_credits(self, **kw):
            self.calls.append(kw)

    billing = Billing()
    buckets = billing_mod.priced_buckets({"model_id": "m", "input_tokens": 10, "output_tokens": 5})
    asyncio.run(billing_mod.charge_preview(billing, None, user_id="u", user_id_hash="h", chat_id="c", operation_id="op",
                                           buckets=buckets, purpose="memory_create_draft"))
    assert billing.calls[0]["skill_id"] == "memory_create_draft"
    assert billing.calls[0]["usage_details"]["purpose"] == "memory_create_draft"


class _Chat:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return user_id == "alice" and chat_id == "chat-1"


def _request():
    state = SimpleNamespace(directus_service=SimpleNamespace(chat=_Chat()), cache_service=None,
                            encryption_service=None, secrets_manager=None)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _body(chat_id: str) -> route.CreateDraftRequest:
    return route.CreateDraftRequest(chat_id=chat_id, title="t", summary="s", user_message="u", assistant_response="a")


# contract-test: supporting surface=rest_api assertions=app-memories.access.owner-scoped,app-memories.suggestions.billing
@pytest.mark.anyio
async def test_create_draft_rejects_foreign_chat_before_billing_or_llm(monkeypatch):
    async def fake_user(_request, _response):
        return SimpleNamespace(id="alice")

    def boom(*_a, **_k):
        raise AssertionError("billing or LLM reached for a chat the user does not own")

    monkeypatch.setattr(route, "_user", fake_user)
    monkeypatch.setattr(route, "BillingService", boom)
    monkeypatch.setattr(route, "run_memory_create_draft", boom)
    with pytest.raises(HTTPException) as exc:
        await route.create_draft.__wrapped__(_request(), None, _body("chat-of-bob"))
    assert exc.value.status_code == 404


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,app-memories.suggestions.billing
async def test_create_draft_returns_document_and_charges(monkeypatch):
    async def fake_user(_request, _response):
        return SimpleNamespace(id="alice")

    class FakeBilling:
        def __init__(self, *_a):
            pass

        async def get_authoritative_personal_balance(self, **_k):
            return 10

    charged = {}

    async def fake_run(**kw):
        kw["usage_callback"]({"input_tokens": 3, "output_tokens": 4})
        return draft_mod.interpret_draft(GOOD), None

    async def fake_charge(*_a, **kw):
        charged.update(kw)
        return 1

    monkeypatch.setattr(route, "_user", fake_user)
    monkeypatch.setattr(route, "BillingService", FakeBilling)
    monkeypatch.setattr(route, "run_memory_create_draft", fake_run)
    monkeypatch.setattr(route, "charge_preview", fake_charge)
    out = await route.create_draft.__wrapped__(_request(), None, _body("chat-1"))
    assert set(out) == {"title", "when_to_use", "body"} and "load_mode: ask_first" in out["body"]
    assert charged["purpose"] == "memory_create_draft" and charged["chat_id"] == "chat-1"
