"""Reserved routing lane encryption and stale-turn contracts."""
# contract-test-file: infrastructure
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
async def test_snapshot_write_failure_never_returns_unusable_reference(context):
    cache, request, encryption = context
    encryption.encrypt_with_user_key.return_value = (None, None)
    with pytest.raises(RuntimeError, match="encryption"):
        await handoff.store_stage_one(cache=cache, encryption=encryption, request=request,
            task_id="task", fingerprint="fingerprint", routing={}, typing_started=False)
    assert cache.rows == {}
