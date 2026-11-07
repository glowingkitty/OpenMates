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
