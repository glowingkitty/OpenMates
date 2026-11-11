# contract-test-file: supporting
# Ownership gate of POST /v1/memory-suggestions/update-preview.
# Run: python3 -m pytest backend/tests/test_memory_suggestions_route.py -v
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import memory_suggestions as route


class _Chat:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return user_id == "alice" and chat_id == "chat-1"


def _body(chat_id: str) -> route.UpdatePreviewRequest:
    return route.UpdatePreviewRequest(
        chat_id=chat_id, memory_id="m1", memory_markdown="---\ntitle: x\n---\nbody",
        messages=[route.PreviewMessage(role="user", text="hi")],
    )


def _request():
    state = SimpleNamespace(directus_service=SimpleNamespace(chat=_Chat()), cache_service=None,
                            encryption_service=None, secrets_manager=None)
    return SimpleNamespace(app=SimpleNamespace(state=state))


# contract-test: supporting surface=rest_api assertions=app-memories.access.owner-scoped,app-memories.suggestions.billing
@pytest.mark.anyio
async def test_update_preview_rejects_foreign_chat_before_billing_or_llm(monkeypatch):
    async def fake_user(_request, _response):
        return SimpleNamespace(id="alice")

    def boom(*_a, **_k):
        raise AssertionError("billing or LLM reached for a chat the user does not own")

    monkeypatch.setattr(route, "_user", fake_user)
    monkeypatch.setattr(route, "BillingService", boom)
    monkeypatch.setattr(route, "run_memory_update_preview", boom)
    handler = route.update_preview.__wrapped__
    with pytest.raises(HTTPException) as exc:
        await handler(_request(), None, _body("chat-of-bob"))
    assert exc.value.status_code == 404


class _Redis:
    def __init__(self):
        self.keys = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = (value, ex)
        return True

    async def delete(self, key):
        self.keys.pop(key, None)


class _Cache:
    def __init__(self):
        self.redis = _Redis()

    @property
    async def client(self):
        return self.redis


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.billing
@pytest.mark.anyio
async def test_second_delivery_of_one_request_id_is_refused_before_llm_or_charge():
    cache = _Cache()
    request_id = "0b0e7c4e-2f4b-4c1d-9a56-3f1c2d4e5a6b"
    assert await route._claim_request(cache, "hash-alice", request_id) == request_id
    with pytest.raises(HTTPException) as exc:
        await route._claim_request(cache, "hash-alice", request_id)
    assert exc.value.status_code == 409
    # Another user's identical id is independent; only the id is kept, with an expiry.
    assert await route._claim_request(cache, "hash-bob", request_id) == request_id
    assert all(value == ("1", route.REQUEST_CLAIM_TTL_SECONDS) for value in cache.redis.keys.values())


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.billing
@pytest.mark.anyio
async def test_request_without_id_gets_a_fresh_operation_and_malformed_ids_are_rejected():
    assert await route._claim_request(None, "hash-alice", None) != await route._claim_request(None, "hash-alice", None)
    with pytest.raises(ValueError):
        route.CreateDraftRequest(chat_id="c", title="t", summary="s", user_message="u", assistant_response="a", request_id="x")


REQUEST_ID = "0b0e7c4e-2f4b-4c1d-9a56-3f1c2d4e5a6b"


class _Balance:
    def __init__(self, *_a):
        pass

    async def get_authoritative_personal_balance(self, **_k):
        return 10


def _billed_request(cache):
    state = SimpleNamespace(directus_service=SimpleNamespace(chat=_Chat()), cache_service=cache,
                            encryption_service=None, secrets_manager=None, discovered_apps_metadata={})
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _draft_body(**extra):
    return route.CreateDraftRequest(chat_id="chat-1", title="t", summary="s", user_message="u",
                                    assistant_response="a", request_id=REQUEST_ID, **extra)


def _preview_body(**extra):
    return route.UpdatePreviewRequest(
        chat_id="chat-1", memory_id="m1", memory_markdown="---\ntitle: x\n---\nbody",
        messages=[route.PreviewMessage(role="user", text="hi")], request_id=REQUEST_ID, **extra)


def _patch_route(monkeypatch, charges, *, usage):
    async def fake_user(_request, _response):
        return SimpleNamespace(id="alice")

    async def failing_run(**kw):
        if usage:
            kw["usage_callback"]({"input_tokens": 3, "output_tokens": 4})
        raise route.MemoryPreviewError("unusable model output")

    async def fake_charge(*_a, **kw):
        charges.append(kw)
        return 1

    monkeypatch.setattr(route, "_user", fake_user)
    monkeypatch.setattr(route, "BillingService", _Balance)
    monkeypatch.setattr(route, "run_memory_create_draft", failing_run)
    monkeypatch.setattr(route, "run_memory_update_preview", failing_run)
    monkeypatch.setattr(route, "charge_preview", fake_charge)


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.billing
@pytest.mark.anyio
@pytest.mark.parametrize("endpoint", ["create_draft", "update_preview"])
async def test_unbilled_failure_releases_the_request_id_for_a_retry(monkeypatch, endpoint):
    charges = []
    _patch_route(monkeypatch, charges, usage=False)
    cache = _Cache()
    handler = getattr(route, endpoint).__wrapped__
    body = _draft_body() if endpoint == "create_draft" else _preview_body()
    for _ in range(2):  # The retry with the same request_id reaches the model again, not a 409.
        with pytest.raises(HTTPException) as exc:
            await handler(_billed_request(cache), None, body)
        assert exc.value.status_code == 502
        assert cache.redis.keys == {}
    assert charges == []


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.billing
@pytest.mark.anyio
@pytest.mark.parametrize("endpoint", ["create_draft", "update_preview"])
async def test_charged_failure_keeps_the_claim_so_one_request_id_is_billed_once(monkeypatch, endpoint):
    charges = []
    _patch_route(monkeypatch, charges, usage=True)
    cache = _Cache()
    handler = getattr(route, endpoint).__wrapped__
    body = (_draft_body(message_id="chat-1-turn") if endpoint == "create_draft"
            else _preview_body(message_id="chat-1-turn"))
    with pytest.raises(HTTPException) as exc:
        await handler(_billed_request(cache), None, body)
    assert exc.value.status_code == 502
    assert len(charges) == 1 and charges[0]["chat_id"] == "chat-1" and charges[0]["message_id"] == "chat-1-turn"
    with pytest.raises(HTTPException) as retry:
        await handler(_billed_request(cache), None, body)
    assert retry.value.status_code == 409 and len(charges) == 1


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.billing
def test_message_id_is_optional_bounded_and_stored_where_a_chat_turn_stores_it(monkeypatch):
    import asyncio
    from backend.apps.ai.processing import memory_preview_billing as billing_mod

    assert _draft_body().message_id is None and _preview_body().message_id is None
    for invalid in ("", "m" * (route.MESSAGE_ID_MAX_LENGTH + 1)):
        with pytest.raises(ValueError):
            _draft_body(message_id=invalid)
        with pytest.raises(ValueError):
            _preview_body(message_id=invalid)

    class Billing:
        calls = []

        async def charge_user_credits(self, **kw):
            self.calls.append(kw)

    monkeypatch.setattr(billing_mod, "build_model_usage_breakdown", lambda _b, _l: {
        "credits_charged": 2, "input_tokens": 10, "output_tokens": 5, "entries": []})
    buckets = billing_mod.priced_buckets({"model_id": "m", "input_tokens": 10, "output_tokens": 5})
    for message_id in ("chat-1-turn", None):
        asyncio.run(billing_mod.charge_preview(Billing(), None, user_id="u", user_id_hash="h", chat_id="chat-1",
                                               operation_id="op", buckets=buckets, message_id=message_id))
    assert Billing.calls[0]["usage_details"]["message_id"] == "chat-1-turn"
    assert "message_id" not in Billing.calls[1]["usage_details"]


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.billing
@pytest.mark.anyio
@pytest.mark.parametrize("skill_id", ["memory_create_draft", "memory_update_preview"])
async def test_memory_suggestion_usage_rows_keep_their_token_counts(skill_id):
    from backend.core.api.app.services.directus.usage import UsageMethods

    class Cipher:
        async def encrypt_with_user_key(self, *, key_id, plaintext):
            return f"encrypted:{plaintext}", None

    row = await UsageMethods(SimpleNamespace(), Cipher()).create_usage_entry(
        user_id_hash="owner-hash", app_id="ai", skill_id=skill_id, usage_type="skill_execution",
        timestamp=123, credits_charged=2, user_vault_key_id="vault-key", chat_id="chat-1",
        message_id="chat-1-turn", source="chat", actual_input_tokens=450, actual_output_tokens=90,
        build_only=True,
    )
    assert row["encrypted_input_tokens"] == "encrypted:450"
    assert row["encrypted_output_tokens"] == "encrypted:90"
    assert (row["chat_id"], row["message_id"], row["source"]) == ("chat-1", "chat-1-turn", "chat")
