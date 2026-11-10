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
