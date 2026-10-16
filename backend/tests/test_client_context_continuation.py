"""Admitted context phases preserve encrypted, scoped and fail-closed delivery."""
# contract-test-file: infrastructure
import asyncio
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
        if count == 3:
            binding, phase, failure, value, expected = args
            if binding not in self.values or self.expiry[binding] <= 0:
                return 0
            if self.values[binding] != expected:
                return -1
            if failure in self.values:
                return -2
            if phase in self.values:
                return 2
            self.values[phase] = value
            self.expiry[phase] = self.expiry[binding]
            return 1
        assert count == 4
        binding, routing, details, failure, value, expected = args
        if binding not in self.values or self.expiry[binding] <= 0:
            return 0
        if self.values[binding] != expected:
            return -1
        if failure in self.values:
            return 2
        if routing in self.values and details in self.values:
            return 3
        self.values[failure] = value
        self.expiry[failure] = self.expiry[binding]
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
async def test_selection_details_v2_waits_for_details_before_plan_fast_path(setup):
    from backend.apps.ai.processing.preprocessor import _simple_context_fast_path

    cache, _redis, vault, scope = setup
    reference = await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    admission = {"scope_complete": False, "active_project_id": None,
                 "active_project_activation_id": None, "active_focus_id": None,
                 "accepted_plan_ref": None, "explicit_related_task_ids": [],
                 "context_revision": "server-admission-v1"}
    request = SimpleNamespace(**scope, recovery_turn_id=scope['turn_id'], client_context_pending=True,
        client_context_request_id=scope['request_id'], client_context_binding_ref=reference,
        admission_context=admission, is_focus_mode_continuation=False,
        is_app_settings_memories_continuation=False)
    routing = {'project_focus_candidates': []}
    details = {
        'related_task_candidates': [{'task_id': 'related', 'summary': 'Safe summary'}],
        'project_focus_catalog': [{'id': 'focus', 'title': 'Focus'}],
        'accepted_plan_context': {'plan_id': 'plan', 'summary': 'Approved summary'},
        'connected_account_directory': [{'app_id': 'calendar', 'connection_id': 'opaque'}],
    }
    for phase, payload in [('routing', routing), ('details', details)]:
        assert await context.receive_client_context(cache_service=cache, encryption_service=vault,
            device_fingerprint_hash='device', phase=phase, context=payload, **scope) == 'accepted'
    await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                            request=request, phase='routing')
    assert request.project_focus_candidates == []
    assert not hasattr(request, 'accepted_plan_context')
    assert not hasattr(request, 'related_task_candidates')
    assert request.client_context_pending is True
    await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                            request=request, phase='details')
    assert request.related_task_candidates == details['related_task_candidates']
    assert request.project_focus_catalog == details['project_focus_catalog']
    assert request.accepted_plan_context == details['accepted_plan_context']
    assert request.connected_account_directory == details['connected_account_directory']
    assert request.client_context_pending is False
    assert _simple_context_fast_path(request, {
        'early_decisions': {'public_decisions': {}, 'needs_detailed_context': False,
                            'needs_related_work': False},
        'selected_app_ids': [], 'project_target_outcome': 'none',
    }, None) is False


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
@pytest.mark.parametrize('first_phase', ['routing', 'details'])
async def test_cross_phase_selection_conflict_rejected(setup, first_phase):
    cache, _redis, vault, scope = setup
    await context.register_client_context(cache_service=cache, encryption_service=vault,
                                         device_fingerprint_hash='device', **scope)
    first = {'related_task_candidates': [{'task_id': 'one'}]}
    second = {'related_task_candidates': [{'task_id': 'two'}]}
    common = dict(cache_service=cache, encryption_service=vault,
                  device_fingerprint_hash='device', **scope)
    assert await context.receive_client_context(**common, phase=first_phase,
                                                context=first) == 'accepted'
    other_phase = 'details' if first_phase == 'routing' else 'routing'
    with pytest.raises(context.ClientContextUnavailable, match='cross-phase'):
        await context.receive_client_context(**common, phase=other_phase, context=second)
    assert await context.receive_client_context(**common, phase=other_phase,
                                                context=first) == 'accepted'


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_concurrent_cross_phase_conflict_cannot_override_hydrated_routing(setup):
    cache, redis, vault, scope = setup
    reference = await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    routing = {'related_task_candidates': [{'task_id': 'first'}]}
    await context.receive_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', phase='routing', context=routing, **scope)
    request = SimpleNamespace(**scope, recovery_turn_id=scope['turn_id'], client_context_pending=True,
        client_context_request_id=scope['request_id'], client_context_binding_ref=reference)
    await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                            request=request, phase='routing')
    # Simulate two opposite-phase writes that both passed their pre-write reads.
    conflicting = {'related_task_candidates': [{'task_id': 'second'}]}
    sealed = await context._seal(vault, 'key:owner', {
        'scope': scope, 'phase': 'details', 'context': conflicting,
    })
    redis.values[context._key(reference) + ':details'] = sealed
    with pytest.raises(context.ClientContextUnavailable, match='cross-phase'):
        await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                                request=request, phase='details')
    assert request.related_task_candidates == routing['related_task_candidates']
    assert request.client_context_pending is True


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


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.parametrize('phase,payload', [
    ('routing', {'project_context_documents': []}),
    ('routing', {'project_focus_candidates': [{'project_id': 'p', 'focuses': [{'document': 'private'}]}]}),
    ('routing', {'accepted_plan_context': {'body': 'private'}}),
    ('details', {'user_id': 'other'}),
    ('details', {'project_context_documents': [{}] * 21}),
    ('routing', {'related_task_candidates': [{'summary': 'x' * 256001}]}),
    ('details', {'related_task_candidates': [{'summary': {'body': 'private'}}]}),
    ('details', {'project_focus_catalog': [{'id': 'focus', 'summary': {'document': 'private'}}]}),
    ('details', {'connected_account_directory': [{'access_token': 'secret'}]}),
    ('details', {'connected_account_directory': [{'token': 'secret'}]}),
    ('details', {'connected_account_directory': [{'provider_email': 'private'}]}),
    ('details', {'accepted_plan_context': {'body': 'private'}}),
])
def test_payload_allowlist_and_bounds(phase, payload):
    with pytest.raises(ValueError):
        context.validate_context(phase, payload)


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
def test_legacy_routing_selection_fields_remain_valid():
    payload = {
        'project_focus_candidates': [],
        'related_task_candidates': [{'task_id': 'related'}],
        'project_focus_catalog': [{'id': 'focus'}],
        'accepted_plan_context': {'plan_id': 'plan'},
        'connected_account_directory': [{'app_id': 'calendar'}],
    }
    assert context.validate_context('routing', payload) == payload


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
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


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
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


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
def test_core_worker_dto_roundtrip_retains_admitted_context_and_private_phase_state():
    from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as CoreRequest
    from backend.apps.ai.skills.ask_skill import AskSkillRequest as WorkerRequest
    core = CoreRequest(chat_id="chat", message_id="message", user_id="owner", user_id_hash="hash",
                       message_history=[], client_context_pending=True, client_context_request_id=str(uuid.uuid4()),
                       client_context_binding_ref="server-ref", client_context_turn_id="admitted-turn",
                       admission_context={"scope_complete": False})
    worker = WorkerRequest.model_validate(core.model_dump())
    assert worker.client_context_pending is True
    assert worker.client_context_request_id == core.client_context_request_id
    assert worker.client_context_binding_ref == "server-ref"
    assert worker.client_context_turn_id == "admitted-turn"
    assert worker.recovery_turn_id is None
    assert worker.admission_context == {"scope_complete": False}
    worker._client_context_routing_loaded = True
    assert worker._client_context_routing_loaded is True
    assert "_client_context_routing_loaded" not in worker.model_dump()


# contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
@pytest.mark.parametrize("recovery_turn", [False, True])
async def test_core_worker_context_identity_hydrates_encrypted_legacy_and_recovery_phase(setup, recovery_turn):
    from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as CoreRequest
    from backend.apps.ai.skills.ask_skill import AskSkillRequest as WorkerRequest

    cache, _redis, vault, scope = setup
    reference = await context.register_client_context(
        cache_service=cache, encryption_service=vault,
        device_fingerprint_hash="device", **scope,
    )
    core = CoreRequest(
        chat_id=scope["chat_id"], message_id=scope["message_id"],
        user_id=scope["user_id"], user_id_hash="hash", message_history=[],
        client_context_pending=True, client_context_request_id=scope["request_id"],
        client_context_binding_ref=reference, client_context_turn_id=scope["turn_id"],
        recovery_turn_id=scope["turn_id"] if recovery_turn else None,
        team_id=scope["team_id"],
    )
    worker = WorkerRequest.model_validate(core.model_dump())
    routing = {"project_focus_candidates": [{"project_id": "project", "name": "Private name"}]}
    await context.receive_client_context(
        cache_service=cache, encryption_service=vault,
        device_fingerprint_hash="device", phase="routing", context=routing, **scope,
    )

    await context.await_client_context_phase(
        cache_service=cache, encryption_service=vault, request=worker, phase="routing",
    )

    assert worker.project_focus_candidates == routing["project_focus_candidates"]
    assert worker.client_context_turn_id == scope["turn_id"]
    assert worker.recovery_turn_id == (scope["turn_id"] if recovery_turn else None)


# contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_no_binding_skips_context_phase_without_recovery_identity(setup):
    from backend.apps.ai.skills.ask_skill import AskSkillRequest as WorkerRequest

    cache, redis, vault, scope = setup
    worker = WorkerRequest(
        chat_id=scope["chat_id"], message_id=scope["message_id"],
        user_id=scope["user_id"], user_id_hash="hash", message_history=[],
    )
    await context.await_client_context_phase(
        cache_service=cache, encryption_service=vault, request=worker, phase="routing",
    )
    assert worker.client_context_turn_id is None
    assert worker.recovery_turn_id is None
    assert redis.values == {}


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
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


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
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


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_failure_wakes_waiting_worker_before_context_timeout(setup):
    cache, redis, vault, scope = setup
    reference = await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    request = SimpleNamespace(**scope, recovery_turn_id=scope['turn_id'], client_context_pending=True,
        client_context_request_id=scope['request_id'], client_context_binding_ref=reference)
    waiter = asyncio.create_task(context.await_client_context_phase(
        cache_service=cache, encryption_service=vault, request=request, phase='routing', timeout=20))
    await asyncio.sleep(0)
    assert await context.receive_client_context_failure(
        cache_service=cache, encryption_service=vault, device_fingerprint_hash='device',
        reason='project_discovery_failed', **scope) == 'accepted'
    with pytest.raises(context.ClientContextUnavailable, match='delivery failed'):
        await asyncio.wait_for(waiter, timeout=1)
    assert not hasattr(request, 'project_focus_candidates')
    assert redis.expiry[context._key(reference) + ':failed'] == redis.expiry[context._key(reference)]
    assert all(value.startswith('vault:v1:') for value in redis.values.values())
    with pytest.raises(context.ClientContextUnavailable, match='delivery failed'):
        await context.receive_client_context(cache_service=cache, encryption_service=vault,
            device_fingerprint_hash='device', phase='routing', context={}, **scope)


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['user_id', 'chat_id', 'turn_id', 'message_id', 'request_id', 'team_id', 'device'])
async def test_failure_requires_exact_admitted_owner_device_team_and_turn(setup, changed):
    cache, redis, vault, scope = setup
    await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    attempted = dict(scope)
    device = 'other' if changed == 'device' else 'device'
    if changed == 'request_id':
        attempted[changed] = str(uuid.uuid4())
    elif changed != 'device':
        attempted[changed] = 'other'
    with pytest.raises(context.ClientContextUnavailable):
        await context.receive_client_context_failure(cache_service=cache, encryption_service=vault,
            device_fingerprint_hash=device, reason='context_preparation_failed', **attempted)
    assert len(redis.values) == 1


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_failure_after_routing_aborts_details_and_main_fallback(setup):
    cache, _redis, vault, scope = setup
    reference = await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    request = SimpleNamespace(**scope, recovery_turn_id=scope['turn_id'], client_context_pending=True,
        client_context_request_id=scope['request_id'], client_context_binding_ref=reference)
    await context.receive_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', phase='routing', context={'project_focus_candidates': []}, **scope)
    await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                            request=request, phase='routing')
    assert await context.receive_client_context_failure(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', reason='context_preparation_failed', **scope) == 'accepted'
    with pytest.raises(context.ClientContextUnavailable, match='delivery failed'):
        await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                                request=request, phase='details', timeout=0)
    with pytest.raises(context.ClientContextUnavailable, match='delivery failed'):
        await context.await_client_context_phase(cache_service=cache, encryption_service=vault,
                                                request=request, phase='routing', timeout=0)


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_finished_context_cannot_be_failed_or_replaced(setup):
    cache, redis, vault, scope = setup
    reference = await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    common = dict(cache_service=cache, encryption_service=vault, device_fingerprint_hash='device', **scope)
    await context.receive_client_context(**common, phase='routing', context={})
    await context.receive_client_context(**common, phase='details', context={})
    with pytest.raises(context.ClientContextUnavailable, match='already complete'):
        await context.receive_client_context_failure(**common, reason='context_preparation_failed')
    assert context._key(reference) + ':failed' not in redis.values

    other = dict(scope, turn_id='other-turn')
    with pytest.raises(context.ClientContextUnavailable):
        await context.receive_client_context_failure(cache_service=cache, encryption_service=vault,
            device_fingerprint_hash='device', reason='context_preparation_failed', **other)


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_failure_is_idempotent_only_for_same_allowlisted_reason(setup):
    cache, redis, vault, scope = setup
    await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    common = dict(cache_service=cache, encryption_service=vault, device_fingerprint_hash='device', **scope)
    with pytest.raises(ValueError, match='reason'):
        await context.receive_client_context_failure(**common, reason='private error text')
    assert await context.receive_client_context_failure(**common, reason='workspace_changed') == 'accepted'
    assert await context.receive_client_context_failure(**common, reason='workspace_changed') == 'duplicate'
    with pytest.raises(context.ClientContextUnavailable, match='Conflicting'):
        await context.receive_client_context_failure(**common, reason='project_discovery_failed')
    assert len(redis.values) == 2


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_failure_cannot_commit_after_device_rebind_during_seal(setup, monkeypatch):
    cache, redis, vault, scope = setup
    common = dict(cache_service=cache, encryption_service=vault, **scope)
    reference = await context.register_client_context(**common, device_fingerprint_hash='old')
    original_seal = context._seal
    async def race(encryption, key, record):
        sealed = await original_seal(encryption, key, record)
        if record.get('reason') == 'context_preparation_failed':
            await context.register_client_context(**common, device_fingerprint_hash='new')
        return sealed
    monkeypatch.setattr(context, '_seal', race)
    with pytest.raises(context.ClientContextUnavailable, match='changed during failure delivery'):
        await context.receive_client_context_failure(
            **common, device_fingerprint_hash='old', reason='context_preparation_failed')
    assert context._key(reference) + ':failed' not in redis.values


# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution
@pytest.mark.asyncio
async def test_failure_handler_rechecks_team_and_sends_correlated_ack(setup):
    from backend.core.api.app.routes.handlers.websocket_handlers.client_context_ready_handler import handle_client_context_failed
    cache, redis, vault, scope = setup
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    directus = SimpleNamespace(team=SimpleNamespace(require_team_role=AsyncMock(side_effect=PermissionError)))
    await context.register_client_context(cache_service=cache, encryption_service=vault,
        device_fingerprint_hash='device', **scope)
    frame = {key: value for key, value in scope.items() if key != 'user_id'} | {
        'reason': 'context_preparation_failed', 'team_id': 'other-team'}
    await handle_client_context_failed(manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=vault, user_id='owner', device_fingerprint_hash='device', payload=frame)
    ack = manager.send_personal_message.call_args.args[0]
    assert ack['type'] == 'chat_turn_context_failed_ack'
    assert ack['payload'] == {key: scope[key] for key in ('chat_id', 'turn_id', 'message_id', 'request_id')} | {
        'status': 'rejected'}
    assert len(redis.values) == 1
    frame['team_id'] = None
    await handle_client_context_failed(manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=vault, user_id='owner', device_fingerprint_hash='device', payload=frame)
    assert manager.send_personal_message.call_args.args[0]['payload']['status'] == 'accepted'
