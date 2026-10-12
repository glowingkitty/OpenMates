"""Admitted context phases preserve encrypted, scoped and fail-closed delivery."""
# contract-test-file: infrastructure
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from backend.core.api.app.services import client_context_continuation as context


class Redis:
    def __init__(self):
        self.values = {}
        self.expiry = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ex, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expiry[key] = ex
        return True

    async def eval(self, script, count, *args):
        if count == 1:
            binding, expected, replacement = args
            if binding not in self.values or self.expiry[binding] <= 0:
                return 0
            if self.values[binding] != expected:
                return -1
            self.values[binding] = replacement
            return 1
        binding, phase, value, expected = args
        assert count == 2
        if binding not in self.values:
            return 0
        if self.values[binding] != expected:
            return -1
        if phase in self.values:
            return 2
        self.values[phase] = value
        self.expiry[phase] = self.expiry[binding]
        return 1


class Vault:
    def __init__(self):
        self.sealed = {}

    async def encrypt_with_user_key(self, value, key):
        token = 'vault:v1:' + uuid.uuid4().hex
        self.sealed[token] = (key, value)
        return token, 'nonce'

    async def decrypt_with_user_key(self, value, key):
        stored_key, plaintext = self.sealed[value]
        assert stored_key == key
        return plaintext


@pytest.fixture
def setup():
    redis, vault = Redis(), Vault()
    class Cache:
        @property
        async def client(self):
            return redis
        async def get_user_vault_key_id(self, user):
            return 'key:' + user
    scope = dict(user_id='owner', chat_id='chat', turn_id='turn', message_id='message',
                 request_id=str(uuid.uuid4()), team_id=None)
    return Cache(), redis, vault, scope


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_encrypted_two_phase_delivery_hydrates_only_requested_phase(setup):
    cache, redis, vault, scope = setup
    reference = await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    request = SimpleNamespace(**scope, recovery_turn_id=scope['turn_id'], client_context_pending=True,
                              client_context_request_id=scope['request_id'], client_context_binding_ref=reference)
    routing = {'project_focus_candidates': [{'project_id': 'project', 'name': 'Private name'}]}
    details = {'custom_memory_documents': [{'id': 'memory', 'source': 'project', 'project_id': 'project',
                                           'document': 'Private body', 'item_revision': 'r1'}]}
    for phase, payload in [('routing', routing), ('details', details)]:
        assert await context.receive_client_context(cache_service=cache, encryption_service=vault,
            device_fingerprint_hash='device', phase=phase, context=payload, **scope) == 'accepted'
    assert all(value.startswith('vault:v1:') for value in redis.values.values())
    assert set(redis.expiry.values()) == {120}
    await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                            request=request, phase='routing')
    assert request.project_focus_candidates == routing['project_focus_candidates']
    assert not hasattr(request, 'custom_rule_documents') and request.client_context_pending
    await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                            request=request, phase='details')
    assert request.custom_rule_documents == details['custom_memory_documents']
    assert request.client_context_pending is False


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['user_id', 'chat_id', 'turn_id', 'message_id', 'team_id', 'device'])
async def test_other_scope_or_device_cannot_deliver(setup, changed):
    cache, redis, vault, scope = setup
    await context.register_client_context(cache_service=cache, encryption_service=vault,
                                         device_fingerprint_hash='device', **scope)
    device = 'other' if changed == 'device' else 'device'
    if changed != 'device':
        scope[changed] = 'other'
    with pytest.raises(context.ClientContextUnavailable):
        await context.receive_client_context(cache_service=cache, encryption_service=vault,
                                             device_fingerprint_hash=device, phase='routing', context={}, **scope)
    assert len(redis.values) == 1


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_duplicate_phase_idempotent_but_replacement_rejected(setup):
    cache, redis, vault, scope = setup
    await context.register_client_context(cache_service=cache, encryption_service=vault,
                                         device_fingerprint_hash='device', **scope)
    kwargs = dict(cache_service=cache, encryption_service=vault, device_fingerprint_hash='device',
                  phase='routing', context={}, **scope)
    assert await context.receive_client_context(**kwargs) == 'accepted'
    assert await context.receive_client_context(**kwargs) == 'duplicate'
    kwargs['context'] = {'project_focus_candidates': []}
    with pytest.raises(context.ClientContextUnavailable, match='Conflicting'):
        await context.receive_client_context(**kwargs)


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_missing_or_unbound_phase_never_becomes_empty_context(setup):
    cache, redis, vault, scope = setup
    reference = await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    request = SimpleNamespace(**scope, recovery_turn_id=scope['turn_id'], client_context_pending=True,
                              client_context_request_id=scope['request_id'], client_context_binding_ref=reference)
    with pytest.raises(context.ClientContextUnavailable, match='timed out'):
        await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                                 request=request, phase='routing', timeout=0)
    assert not hasattr(request, 'project_focus_candidates')
    request.client_context_binding_ref = None
    with pytest.raises(context.ClientContextUnavailable, match='binding'):
        await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                                 request=request, phase='routing', timeout=0)


@pytest.mark.parametrize('phase,payload', [
    ('routing', {'project_context_documents': []}),
    ('routing', {'project_focus_candidates': [{'project_id': 'p', 'focuses': [{'document': 'private'}]}]}),
    ('routing', {'accepted_plan_context': {'body': 'private'}}),
    ('details', {'user_id': 'other'}),
    ('details', {'project_context_documents': [{}] * 21}),
    ('routing', {'related_task_candidates': [{'summary': 'x' * 256001}]}),
])
def test_payload_allowlist_and_bounds(phase, payload):
    with pytest.raises(ValueError):
        context.validate_context(phase, payload)


@pytest.mark.asyncio
async def test_handler_rechecks_team_and_rejects_invalid_payload(setup):
    from backend.core.api.app.routes.handlers.websocket_handlers.client_context_ready_handler import handle_client_context_ready
    cache, redis, vault, scope = setup
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    directus = SimpleNamespace(team=SimpleNamespace(require_team_role=AsyncMock(side_effect=PermissionError)))
    await handle_client_context_ready(manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=vault, user_id='owner', device_fingerprint_hash='device',
        payload={key: value for key, value in scope.items() if key != 'user_id'} | {'team_id': 'team', 'phase': 'routing', 'context': {}})
    assert manager.send_personal_message.call_args.args[0]['payload']['status'] == 'rejected'
    assert redis.values == {}


@pytest.mark.parametrize("authority", ["empty", "active_project", "plan", "missing"])
def test_only_existing_empty_server_admission_can_be_completed(authority):
    snapshot = {"scope_complete": False, "active_project_id": None, "active_project_activation_id": None,
                "active_focus_id": None, "accepted_plan_ref": None, "explicit_related_task_ids": [],
                "context_revision": "server-admission-v1"}
    request = SimpleNamespace(admission_context=snapshot)
    if authority == "active_project":
        snapshot["active_project_id"] = "active"
    elif authority == "plan":
        request.accepted_plan_context = {"plan_id": "p"}
    elif authority == "missing":
        snapshot.pop("active_focus_id")
    context._complete_empty_admission_context(request)
    assert request.admission_context["scope_complete"] is (authority == "empty")


def test_core_worker_dto_roundtrip_retains_admitted_context_and_private_phase_state():
    from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as CoreRequest
    from backend.apps.ai.skills.ask_skill import AskSkillRequest as WorkerRequest
    core = CoreRequest(chat_id="chat", message_id="message", user_id="owner", user_id_hash="hash",
                       message_history=[], client_context_pending=True, client_context_request_id=str(uuid.uuid4()),
                       client_context_binding_ref="server-ref", admission_context={"scope_complete": False})
    worker = WorkerRequest.model_validate(core.model_dump())
    assert worker.client_context_pending is True
    assert worker.client_context_request_id == core.client_context_request_id
    assert worker.client_context_binding_ref == "server-ref"
    assert worker.admission_context == {"scope_complete": False}
    worker._client_context_routing_loaded = True
    assert worker._client_context_routing_loaded is True
    assert "_client_context_routing_loaded" not in worker.model_dump()


@pytest.mark.parametrize("explicit", [False, True])
def test_unrelated_project_and_task_catalogues_do_not_block_empty_scope(explicit):
    snapshot = {"scope_complete": False, "active_project_id": None, "active_project_activation_id": None,
                "active_focus_id": None, "accepted_plan_ref": None, "explicit_related_task_ids": [],
                "context_revision": "server-admission-v1"}
    request = SimpleNamespace(admission_context=snapshot,
                              project_focus_candidates=[{"project_id": "unrelated", "name": "Other"}],
                              related_task_candidates=[{"task_id": "other", "summary": "Unrelated task", "explicit_dependency": explicit}],
                              is_focus_mode_continuation=False, is_app_settings_memories_continuation=False)
    context._complete_empty_admission_context(request)
    from backend.apps.ai.processing.preprocessor import _simple_context_fast_path
    routing = {"early_decisions": {"public_decisions": {}, "needs_detailed_context": False,
                                   "needs_related_work": False},
               "selected_app_ids": [], "project_target_outcome": "none"}
    assert _simple_context_fast_path(request, routing, None) is (not explicit)


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_authenticated_exact_admission_rebind_keeps_expiry_and_phases(setup):
    cache, redis, vault, scope = setup
    kwargs = dict(cache_service=cache, encryption_service=vault, **scope)
    reference = await context.register_client_context(**kwargs, device_fingerprint_hash='old')
    await context.receive_client_context(**kwargs, device_fingerprint_hash='old', phase='routing', context={})
    key = context._key(reference)
    redis.expiry[key] = 17
    old_phase = redis.values[key + ':routing']
    assert await context.register_client_context(**kwargs, device_fingerprint_hash='new') == reference
    assert redis.expiry[key] == 17
    assert redis.values[key + ':routing'] == old_phase
    with pytest.raises(context.ClientContextUnavailable, match='mismatch'):
        await context.receive_client_context(**kwargs, device_fingerprint_hash='old', phase='details', context={})
    assert await context.receive_client_context(**kwargs, device_fingerprint_hash='new', phase='routing', context={}) == 'duplicate'
    with pytest.raises(context.ClientContextUnavailable, match='Conflicting'):
        await context.receive_client_context(**kwargs, device_fingerprint_hash='new', phase='routing', context={'project_focus_catalog': []})
    assert await context.receive_client_context(**kwargs, device_fingerprint_hash='new', phase='details', context={}) == 'accepted'
    assert redis.expiry[key + ':details'] == 17


@pytest.mark.asyncio
async def test_rebind_rejects_wrong_stored_scope_and_inflight_old_device(setup, monkeypatch):
    cache, redis, vault, scope = setup
    kwargs = dict(cache_service=cache, encryption_service=vault, **scope)
    reference = await context.register_client_context(**kwargs, device_fingerprint_hash='old')
    original_seal = context._seal
    async def race(encryption, key, record):
        sealed = await original_seal(encryption, key, record)
        if record.get('phase') == 'routing':
            await context.register_client_context(**kwargs, device_fingerprint_hash='new')
        return sealed
    monkeypatch.setattr(context, '_seal', race)
    with pytest.raises(context.ClientContextUnavailable, match='changed during delivery'):
        await context.receive_client_context(**kwargs, device_fingerprint_hash='old', phase='routing', context={})
    assert context._key(reference) + ':routing' not in redis.values
    redis.values[context._key(reference)] = await original_seal(vault, 'key:owner',
        {'scope': {**scope, 'turn_id': 'different'}, 'device': 'new'})
    with pytest.raises(context.ClientContextUnavailable, match='conflict'):
        await context.register_client_context(**kwargs, device_fingerprint_hash='third')
