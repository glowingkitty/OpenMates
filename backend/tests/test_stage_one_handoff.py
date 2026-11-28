"""Reserved routing lane encryption and stale-turn contracts."""
# contract-test-file: infrastructure
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import pytest

from backend.apps.ai.processing import stage_one_handoff as handoff


class Cache:
    def __init__(self):
        self.rows = {}
        self.ttls = {}
        self.active = "task"

    @property
    async def client(self):
        return self

    async def set(self, key, value, *, ex, nx):
        assert nx
        self.rows[key] = value
        self.ttls[key] = ex
        return True

    async def get(self, key):
        return self.rows.get(key)

    async def get_active_ai_task(self, chat_id):
        return self.active

    async def get_user_vault_key_id(self, user_id):
        return "vault-key"


@pytest.fixture
def context(monkeypatch):
    cache = Cache()
    request = SimpleNamespace(user_id="owner", team_id=None, chat_id="chat", message_id="message")
    encryption = SimpleNamespace(
        encrypt_with_user_key=AsyncMock(return_value=("vault:v1:ciphertext", "v1")),
        decrypt_with_user_key=AsyncMock(),
    )
    monkeypatch.setattr(handoff, "routing_admission_is_current", AsyncMock(return_value=True))
    return cache, request, encryption


@pytest.mark.asyncio
async def test_snapshot_is_ciphertext_fixed_ttl_and_bound_to_exact_request(context):
    cache, request, encryption = context
    fingerprint = handoff.request_fingerprint({"text": "private"}, {"region": "EU"})
    ref = await handoff.store_stage_one(cache=cache, encryption=encryption, request=request,
        task_id="task", fingerprint=fingerprint, routing={"early_decisions": {"category": "coding"}},
        typing_started=True)
    assert cache.rows == {handoff.KEY_PREFIX + ref: "vault:v1:ciphertext"}
    assert cache.ttls == {handoff.KEY_PREFIX + ref: 120}
    plaintext = encryption.encrypt_with_user_key.call_args.args[0]
    encryption.decrypt_with_user_key.return_value = plaintext
    args = dict(cache=cache, encryption=encryption, request=request, directus=None,
                task_id="task", fingerprint=fingerprint, reference=ref)
    result = await handoff.load_stage_one(**args)
    assert result["typing_started"] is True
    assert await handoff.load_stage_one(**{**args, "fingerprint": "changed"}) is None
    request.team_id = "other-team"
    assert await handoff.load_stage_one(**args) is None
    request.team_id = None
    cache.active = "new-turn"
    assert await handoff.load_stage_one(**args) is None


@pytest.mark.asyncio
async def test_expiry_revocation_missing_ciphertext_and_invalid_plaintext_fall_back(context, monkeypatch):
    cache, request, encryption = context
    args = dict(cache=cache, encryption=encryption, request=request, directus=None,
                task_id="task", fingerprint="fingerprint", reference="x" * 43)
    assert await handoff.load_stage_one(**args) is None
    cache.rows[handoff.KEY_PREFIX + args["reference"]] = "vault:v1:ciphertext"
    encryption.decrypt_with_user_key.return_value = "not-json"
    assert await handoff.load_stage_one(**args) is None
    encryption.decrypt_with_user_key.return_value = json.dumps({
        "version": 1, "user_id": "owner", "team_id": None, "chat_id": "chat", "message_id": "message",
        "task_id": "task", "fingerprint": "fingerprint", "routing": {}, "expires_at": 0})
    assert await handoff.load_stage_one(**args) is None
    monkeypatch.setattr(handoff, "routing_admission_is_current", AsyncMock(return_value=False))
    assert await handoff.load_stage_one(**args) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False])
async def test_snapshot_reads_overlap_only_after_verified_authority(context, monkeypatch, authorized):
    cache, request, encryption = context
    ref = await handoff.store_stage_one(
        cache=cache, encryption=encryption, request=request, task_id="task", fingerprint="digest",
        routing={"early_decisions": {"category": "coding"}}, typing_started=True,
    )
    encryption.decrypt_with_user_key.return_value = encryption.encrypt_with_user_key.call_args.args[0]
    proof_started = asyncio.Event()
    give_proof = asyncio.Event()
    lookup_started = {name: asyncio.Event() for name in ("key", "ciphertext")}
    release = asyncio.Event()

    async def proof(*_args):
        proof_started.set()
        await give_proof.wait()
        return authorized

    def lookup(name, value):
        async def read(_identity):
            lookup_started[name].set()
            await release.wait()
            return value
        return read

    monkeypatch.setattr(handoff, "routing_admission_is_current", proof)
    monkeypatch.setattr(cache, "get_user_vault_key_id", lookup("key", "vault-key"))
    monkeypatch.setattr(cache, "get", lookup("ciphertext", "vault:v1:ciphertext"))
    pending = asyncio.create_task(handoff.load_stage_one(
        cache=cache, encryption=encryption, request=request, directus=None,
        task_id="task", fingerprint="digest", reference=ref,
    ))
    try:
        await asyncio.wait_for(proof_started.wait(), 1)
        assert not any(event.is_set() for event in lookup_started.values())
        give_proof.set()
        if not authorized:
            assert await asyncio.wait_for(pending, 1) is None
            assert not any(event.is_set() for event in lookup_started.values())
            encryption.decrypt_with_user_key.assert_not_awaited()
            return
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in lookup_started.values())), 1)
        encryption.decrypt_with_user_key.assert_not_awaited()
        release.set()
        result = await asyncio.wait_for(pending, 1)
        assert result["typing_started"] is True
        encryption.decrypt_with_user_key.assert_awaited_once_with("vault:v1:ciphertext", "vault-key")
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_read", ["key", "ciphertext"])
async def test_snapshot_read_failure_cancels_and_drains_the_peer(context, monkeypatch, failing_read):
    cache, request, encryption = context
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked(_identity):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    async def failing(_identity):
        await entered.wait()
        raise RuntimeError("read unavailable")

    key_lookup, ciphertext_lookup = (failing, blocked) if failing_read == "key" else (blocked, failing)
    monkeypatch.setattr(cache, "get_user_vault_key_id", key_lookup)
    monkeypatch.setattr(cache, "get", ciphertext_lookup)
    assert await asyncio.wait_for(handoff.load_stage_one(
        cache=cache, encryption=encryption, request=request, directus=None,
        task_id="task", fingerprint="fingerprint", reference="x" * 43,
    ), 1) is None
    assert cancelled.is_set()
    encryption.decrypt_with_user_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_snapshot_write_failure_never_returns_unusable_reference(context):
    cache, request, encryption = context
    encryption.encrypt_with_user_key.return_value = (None, None)
    with pytest.raises(RuntimeError, match="encryption"):
        await handoff.store_stage_one(cache=cache, encryption=encryption, request=request,
            task_id="task", fingerprint="fingerprint", routing={}, typing_started=False)
    assert cache.rows == {}
