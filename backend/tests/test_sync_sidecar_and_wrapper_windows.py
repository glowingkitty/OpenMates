"""Focused cursor and authorization-scope contracts for encrypted sync pages."""

from types import SimpleNamespace

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.sync_sidecar_hydration import (
    load_sync_sidecar_window,
)
from backend.core.api.app.services.directus.chat_key_wrapper_methods import ChatKeyWrapperMethods


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_sidecar_page_has_stable_cursor_and_author_filter():
    calls = []

    async def get_items(collection, *, params, admin_required, raise_on_error):
        assert raise_on_error is True
        calls.append((collection, params, admin_required))
        return [
            {"id": f"id-{i:02d}", "updated_at": 50, "encrypted_payload": "cipher"}
            for i in range(11, 0, -1)
        ]

    directus = SimpleNamespace(get_items=get_items)
    page = await load_sync_sidecar_window(
        directus, collection="code_run_outputs", chat_id="chat-1", user_id="owner-1",
        before_updated_at=60, before_id="older-id",
    )
    assert len(page["outputs"]) == 10
    assert page["has_more_before"] is True
    assert page["start_cursor"] == {"updated_at": 50, "id": "id-02"}
    assert calls[0][1]["limit"] == 11
    assert calls[0][1]["filter"]["chat_id"] == {"_eq": "chat-1"}
    assert calls[0][1]["filter"]["author_user_id"] == {"_eq": "owner-1"}
    assert calls[0][1]["filter"]["_or"][1]["id"] == {"_lt": "older-id"}


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.anyio
async def test_oversized_sidecar_exposes_on_demand_embed_id():
    async def get_items(collection, *, params, admin_required, raise_on_error):
        assert raise_on_error is True
        return [{"id": "huge", "updated_at": 9, "embed_id": "embed-1",
                 "encrypted_payload": "x" * (129 * 1024)}]

    page = await load_sync_sidecar_window(
        SimpleNamespace(get_items=get_items), collection="code_run_outputs",
        chat_id="chat-1", user_id="owner-1",
    )
    assert page["outputs"] == []
    assert page["has_more_before"] is True
    assert page["oversized_output"] == {"id": "huge", "updated_at": 9, "embed_id": "embed-1"}


# contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized,storage.cold.discoverable-bounded
@pytest.mark.anyio
async def test_wrapper_page_scopes_principal_and_supports_exact_recovery():
    calls = []

    async def get_items(collection, *, params, no_cache, admin_required, raise_on_error):
        assert raise_on_error is True
        calls.append(params)
        return [{"id": "wrapper-2", "encrypted_chat_key": "cipher"}]

    methods = ChatKeyWrapperMethods(SimpleNamespace(get_items=get_items))
    page = await methods.get_sync_wrapper_window_for_chat(
        "hash-chat", hashed_user_id="hash-user", before_id="wrapper-3",
    )
    assert page["start_cursor"] == "wrapper-2"
    assert calls[0]["filter"] == {
        "hashed_chat_id": {"_eq": "hash-chat"},
        "hashed_user_id": {"_eq": "hash-user"},
        "id": {"_lt": "wrapper-3"},
    }
    wrapper = await methods.get_sync_wrapper_by_id(
        "hash-chat", "wrapper-2", hashed_user_id="hash-user",
    )
    assert wrapper["id"] == "wrapper-2"
    assert calls[1]["filter"]["hashed_user_id"] == {"_eq": "hash-user"}


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_sidecar_and_wrapper_reads_propagate_directus_failure():
    async def unavailable(collection, *, params, raise_on_error, **_kwargs):
        assert raise_on_error is True
        raise RuntimeError("Directus unavailable")

    directus = SimpleNamespace(get_items=unavailable)
    with pytest.raises(RuntimeError, match="Directus unavailable"):
        await load_sync_sidecar_window(
            directus, collection="code_run_outputs", chat_id="chat-1", user_id="owner-1",
        )
    wrappers = ChatKeyWrapperMethods(directus)
    with pytest.raises(RuntimeError, match="Directus unavailable"):
        await wrappers.get_sync_wrapper_window_for_chat("chat-hash", hashed_user_id="owner-hash")
    with pytest.raises(RuntimeError, match="Directus unavailable"):
        await wrappers.get_sync_wrapper_by_id("chat-hash", "wrapper-1", hashed_user_id="owner-hash")
