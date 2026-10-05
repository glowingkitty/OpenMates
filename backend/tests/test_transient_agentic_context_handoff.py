"""Private documents never cross persistent queue/cache boundaries as plaintext."""
# contract-test-file: infrastructure
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.python_utils.recent_work_summary_cache import TransientContextHandoffStore
from backend.shared.python_utils.recent_work_summary_client import seal_private_context_payload, restore_private_context_payload
from backend.apps.ai.skills.ask_skill import AskSkillRequest


class Encryption:
    def __init__(self):
        self.values = {}

    async def encrypt_with_user_key(self, text, key):
        ciphertext = 'vault:v1:' + str(len(self.values))
        self.values[ciphertext] = text
        return ciphertext, 'v1'

    async def decrypt_with_user_key(self, ciphertext, key):
        return self.values[ciphertext]


@pytest.mark.asyncio
async def test_handoff_is_ciphertext_only_owner_turn_request_bound_and_nonrenewing():
    now = [100.0]
    store = TransientContextHandoffStore(clock=lambda: now[0])
    encryption = Encryption()
    args = dict(owner_id='owner', chat_id='chat', turn_id='turn', request_id='request',
                encryption=encryption, vault_key_id='key')
    fields = {'related_task_candidates': [{'id': 'task', 'summary': 'private sentinel'}]}
    reference = await store.seal(**args, fields=fields)
    assert reference and 'private sentinel' not in repr(vars(store))
    for field in ('owner_id', 'chat_id', 'turn_id', 'request_id', 'vault_key_id'):
        assert await store.open(reference, **{**args, field: 'wrong'}) is None
    now[0] = 1299
    assert await store.open(reference, **args) == fields
    now[0] = 1300
    assert await store.open(reference, **args) is None
    assert not store._entries


@pytest.mark.asyncio
async def test_revoke_fences_decryption_and_rejects_unknown_or_oversized_fields():
    store, encryption = TransientContextHandoffStore(), Encryption()
    args = dict(owner_id='owner', chat_id='chat', turn_id='turn', request_id='request',
                encryption=encryption, vault_key_id='key')
    assert await store.seal(**args, fields={'unapproved': 'secret'}) is None
    assert await store.seal(**args, fields={'related_task_candidates': ['x' * 200001]}) is None
    reference = await store.seal(**args, fields={'custom_rule_documents': [{'document': 'private'}]})
    original = encryption.decrypt_with_user_key
    async def revoke(ciphertext, key):
        store.revoke(owner_id='owner')
        return await original(ciphertext, key)
    encryption.decrypt_with_user_key = revoke
    assert await store.open(reference, **args) is None


@pytest.mark.asyncio
async def test_queue_payload_contains_only_opaque_reference_and_misses_drop_private_fields():
    payload = {'user_id': 'owner', 'chat_id': 'chat', 'message_id': 'turn',
               'related_task_candidates': [{'summary': 'private sentinel'}], 'project_focus_documents': []}
    client = SimpleNamespace(seal_context=AsyncMock(return_value='opaque'), open_context=AsyncMock(return_value=None))
    sealed = await seal_private_context_payload(payload, request_id='request', client=client)
    assert 'private sentinel' not in repr(sealed)
    assert sealed['agentic_context_ref'] == 'opaque'
    assert 'project_focus_documents' not in sealed
    assert 'related_task_candidates' not in await restore_private_context_payload(sealed, client=client)
    client.seal_context.return_value = None
    with pytest.raises(RuntimeError, match='handoff unavailable'):
        await seal_private_context_payload(payload, request_id='request', client=client)


def test_worker_request_serialization_excludes_all_private_bodies_but_keeps_reference():
    request = AskSkillRequest(chat_id='chat', message_id='turn', user_id='owner', user_id_hash='hash',
                              message_history=[], related_task_candidates=[{'summary': 'private sentinel'}],
                              agentic_context_ref='opaque', agentic_context_request_id='request')
    dumped = request.model_dump()
    assert 'private sentinel' not in repr(dumped)
    assert dumped['agentic_context_ref'] == 'opaque'


@pytest.mark.asyncio
async def test_handoff_keeps_original_project_activation_fence():
    store, encryption = TransientContextHandoffStore(), Encryption()
    reference = await store.seal(owner_id='owner', chat_id='chat', turn_id='turn', request_id='request',
        fields={'project_focus_documents': [{'document': 'private'}]}, encryption=encryption, vault_key_id='key',
        project_binding=('project', 'activation-original'))
    assert store.project_binding(reference) == ('project', 'activation-original')
    store.revoke(owner_id='owner', chat_id='chat')
    assert store.project_binding(reference) is None
