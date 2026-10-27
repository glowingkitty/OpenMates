"""Live context retries preserve immutable queue identity without retaining plaintext."""
# contract-test-file: infrastructure

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.python_utils.recent_work_summary_cache import TransientContextHandoffStore


def arguments(**overrides):
    values = dict(owner_id="owner", chat_id="chat", turn_id="turn", request_id="request",
                  fields={"custom_rule_documents": [{"id": "rule", "content": "private sentinel"}]},
                  encryption=SimpleNamespace(encrypt_with_user_key=AsyncMock(
                      return_value=("vault:v1:ciphertext", "v1"))), vault_key_id="vault-key",
                  project_binding=("project", "activation"))
    return {**values, **overrides}


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.context.memory-only-summary
@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [{}, {"custom_rule_documents": [{"id": "rule", "content": "private sentinel"}]}])
async def test_identical_context_reuses_random_reference_without_renewing_expiry(fields):
    now = [1000.0]
    store = TransientContextHandoffStore(clock=lambda: now[0])
    args = arguments(fields=fields)
    try:
        first = await store.seal(**args)
        expiry = store._entries[first].expires_at
        now[0] += 100
        assert await store.seal(**args) == first
        assert store._entries[first].expires_at == expiry
        args["encryption"].encrypt_with_user_key.assert_awaited_once()
        assert "private sentinel" not in repr(vars(store))
        assert store._entries[first].fingerprint not in first.encode()
    finally:
        store.revoke(owner_id="owner")


@pytest.mark.asyncio
async def test_context_dictionary_order_does_not_change_retry_identity():
    store = TransientContextHandoffStore()
    args = arguments()
    try:
        first = await store.seal(**args)
        assert await store.seal(**{**args, "fields": {
            "custom_rule_documents": [{"content": "private sentinel", "id": "rule"}],
        }}) == first
    finally:
        store.revoke(owner_id="owner")


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.context.memory-only-summary
@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [
    {"owner_id": "other"}, {"chat_id": "other"}, {"turn_id": "other"},
    {"request_id": "other"}, {"vault_key_id": "other"},
    {"project_binding": ("project", "other-activation")}, {"project_binding": None},
    {"fields": {"custom_rule_documents": [{"content": "changed private context"}]}},
])
async def test_changed_context_or_authority_never_reuses_reference(changed):
    store = TransientContextHandoffStore()
    args = arguments()
    try:
        first = await store.seal(**args)
        assert await store.seal(**{**args, **changed}) != first
    finally:
        store.revoke(owner_id="owner")
        store.revoke(owner_id="other")


@pytest.mark.asyncio
@pytest.mark.parametrize("removal", ["expiry", "release", "revoke"])
async def test_removed_context_reference_cannot_be_resurrected(removal):
    now = [1000.0]
    store = TransientContextHandoffStore(clock=lambda: now[0])
    args = arguments()
    try:
        first = await store.seal(**args)
        if removal == "expiry":
            now[0] = store._entries[first].expires_at
        elif removal == "release":
            assert store.release(first, **{key: args[key] for key in (
                "owner_id", "chat_id", "turn_id", "request_id",
            )})
        else:
            store.revoke(owner_id="owner")
        assert await store.seal(**args) != first
        assert first not in store._entries
    finally:
        store.revoke(owner_id="owner")


@pytest.mark.asyncio
async def test_identical_concurrent_context_seals_converge_after_encryption():
    store = TransientContextHandoffStore()
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0

    async def encrypt(_text, _key):
        nonlocal count
        count += 1
        if count == 12:
            entered.set()
        await release.wait()
        return "vault:v1:ciphertext", "v1"

    args = arguments(encryption=SimpleNamespace(encrypt_with_user_key=encrypt))
    tasks = [asyncio.create_task(store.seal(**args)) for _ in range(12)]
    try:
        await asyncio.wait_for(entered.wait(), 1)
        release.set()
        references = await asyncio.gather(*tasks)
        assert references[0] is not None
        assert len(set(references)) == len(store._entries) == 1
    finally:
        release.set()
        await asyncio.gather(*tasks)
        store.revoke(owner_id="owner")


@pytest.mark.asyncio
async def test_revocation_during_encryption_still_fences_context_insertion():
    store = TransientContextHandoffStore()

    async def encrypt(_text, _key):
        store.revoke(owner_id="owner")
        return "vault:v1:ciphertext", "v1"

    assert await store.seal(**arguments(encryption=SimpleNamespace(
        encrypt_with_user_key=encrypt))) is None
    assert not store._entries
