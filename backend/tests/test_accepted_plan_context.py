"""Accepted Plan drift references require durable approval and fresh real linkage."""
# contract-test-file: infrastructure
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import hashlib
import json

import pytest

from backend.apps.ai.processing.accepted_plan_context import bounded_accepted_plan_snapshot, validate_accepted_plan_context
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as CoreAskSkillRequest
from backend.shared.python_utils.recent_work_summary_client import seal_private_context_payload, restore_private_context_payload

OWNER_HASH = hashlib.sha256(b'owner').hexdigest()


def fixtures(**snapshot_updates):
    snapshot = {'plan_id': 'plan', 'version': 7, 'approved_revision_id': 'revision', 'summary': 'Fix the API with the accepted scope.'}
    snapshot.update(snapshot_updates)
    plan = {'plan_id': 'plan', 'version': 7, 'status': 'active', 'primary_chat_id': 'chat',
            'hashed_user_id': OWNER_HASH, 'hashed_team_id': None, 'approval_state': 'approved',
            'submitted_revision_id': 'revision', 'approved_revision_id': 'revision'}
    revision = {'plan_id': 'plan', 'revision_id': 'revision', 'hashed_user_id': OWNER_HASH,
                'hashed_team_id': None, 'approval_state': 'approved', 'fingerprint': 'fingerprint'}
    task = {'task_id': 'task', 'plan_id': 'plan', 'primary_chat_id': 'chat', 'status': 'in_progress',
            'hashed_user_id': OWNER_HASH, 'hashed_team_id': None}
    records = {'user_plans': [plan], 'user_plan_revisions': [revision], 'user_tasks': [task]}
    async def get_items(collection, params, **kwargs):
        assert kwargs == {'no_cache': True}
        assert 'encrypted_' not in params['fields']
        assert params['filter[hashed_user_id][_eq]'] == OWNER_HASH
        assert params['filter[hashed_team_id][_null]'] is True
        if collection == 'user_plan_revisions':
            assert params['filter[encrypted_snapshot][_nnull]'] is True
            assert params['filter[encrypted_snapshot][_neq]'] == ''
        return deepcopy(records[collection])
    directus = SimpleNamespace(get_items=AsyncMock(side_effect=get_items))
    request = SimpleNamespace(user_id='owner', chat_id='chat', team_id=None, accepted_plan_context=snapshot)
    return request, directus, records


@pytest.mark.asyncio
async def test_only_current_durable_approval_is_used_without_reading_private_ciphertext():
    request, directus, _records = fixtures()
    context = json.loads(await validate_accepted_plan_context(request, directus))
    assert context == {'source': 'authorized_current_approved_plan', 'plan_id': 'plan', 'version': 7,
                       'approved_revision_id': 'revision', 'summary': request.accepted_plan_context['summary']}
    assert [call.args[0] for call in directus.get_items.await_args_list] == ['user_plans', 'user_plan_revisions', 'user_plans']


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('version', 8), ('approval_state', 'awaiting_review'),
    ('approved_revision_id', 'old'), ('submitted_revision_id', 'new'), ('hashed_user_id', 'another-owner'),
    ('hashed_team_id', 'another-team'), ('status', 'draft'), ('status', 'completed'), ('primary_chat_id', 'other-chat')])
async def test_stale_unapproved_wrong_owner_unlinked_plan_is_omitted(field, value):
    request, directus, records = fixtures()
    records['user_plans'][0][field] = value
    assert await validate_accepted_plan_context(request, directus) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('revision_id', 'other'), ('approval_state', 'submitted'),
    ('fingerprint', ''), ('hashed_user_id', 'other-owner'), ('plan_id', 'other')])
async def test_metadata_approval_without_matching_durable_revision_is_omitted(field, value):
    request, directus, records = fixtures()
    records['user_plan_revisions'][0][field] = value
    assert await validate_accepted_plan_context(request, directus) is None


@pytest.mark.asyncio
async def test_owned_open_task_can_link_plan_to_chat_and_closed_or_unlinked_task_cannot():
    request, directus, records = fixtures(linked_task_id='task')
    records['user_plans'][0]['primary_chat_id'] = 'plan-original-chat'
    assert await validate_accepted_plan_context(request, directus)
    for field, value in [('status', 'done'), ('primary_chat_id', 'other-chat'), ('plan_id', 'other-plan'), ('hashed_user_id', 'other-owner')]:
        original = records['user_tasks'][0][field]
        records['user_tasks'][0][field] = value
        assert await validate_accepted_plan_context(request, directus) is None
        records['user_tasks'][0][field] = original


@pytest.mark.asyncio
async def test_material_version_change_during_metadata_reads_and_team_revocation_fail_closed():
    request, directus, records = fixtures()
    original = directus.get_items.side_effect
    async def changing(collection, params, **kwargs):
        result = await original(collection, params, **kwargs)
        if collection == 'user_plan_revisions':
            records['user_plans'][0]['version'] += 1
        return result
    directus.get_items.side_effect = changing
    assert await validate_accepted_plan_context(request, directus) is None
    request.team_id = 'team'
    directus.team = SimpleNamespace(require_team_role=AsyncMock(side_effect=PermissionError()))
    assert await validate_accepted_plan_context(request, directus) is None


@pytest.mark.asyncio
async def test_snapshot_stays_ephemeral_across_core_worker_and_opaque_queue_transport():
    request, _directus, _records = fixtures()
    fields = dict(user_id='owner', user_id_hash=OWNER_HASH, chat_id='chat', message_id='turn', message_history=[],
                  accepted_plan_context=request.accepted_plan_context)
    core = CoreAskSkillRequest(**fields)
    worker = AskSkillRequest(**core.model_dump())
    assert worker.accepted_plan_context == request.accepted_plan_context
    assert 'accepted_plan_context' not in worker.model_dump()
    client = SimpleNamespace(seal_context=AsyncMock(return_value='opaque'),
                             open_context=AsyncMock(return_value={'accepted_plan_context': request.accepted_plan_context}))
    payload = await seal_private_context_payload(core.model_dump(), request_id='request', client=client)
    assert 'Fix the API' not in repr(payload)
    assert payload['agentic_context_ref'] == 'opaque'
    restored = await restore_private_context_payload(payload, client=client)
    assert restored['accepted_plan_context'] == request.accepted_plan_context
    client.open_context.return_value = None
    assert 'accepted_plan_context' not in await restore_private_context_payload(payload, client=client)


@pytest.mark.parametrize('value', [None, [], {'approved': True}, {'plan_id': 'plan', 'version': True,
    'approved_revision_id': 'revision', 'summary': 'test'}, {'plan_id': 'plan', 'version': 7,
    'approved_revision_id': 'revision', 'summary': 'x' * 4001}])
def test_unknown_malformed_or_oversized_snapshot_is_omitted(value):
    assert bounded_accepted_plan_snapshot(value) is None


@pytest.mark.asyncio
async def test_plan_change_while_generative_reviewer_awaits_prevents_correction_delivery():
    from backend.apps.ai.processing.main_processor import _direction_authority_current
    from backend.apps.ai.processing import agentic_context
    from backend.apps.ai.processing.chat_direction import (
        DirectionAuthority, DirectionAssessment, CorrectionReview,
        ChatDirectionCorrectionCoordinator, assemble_direction_context,
    )
    request, directus, records = fixtures()
    request.message_id = 'turn'
    request.message_history = [{'role': 'user', 'content': 'Fix the API'}]
    authority = DirectionAuthority('owner', 'chat', 'turn', agentic_context.goal_revision(request.message_history))
    plan = await validate_accepted_plan_context(request, directus)
    context = assemble_direction_context(authority=authority, message_history=request.message_history,
        accepted_plan_summary=plan, recent_actions=[{'summary': 'Unrelated cookbook'}])
    cache = SimpleNamespace(get_active_ai_task=AsyncMock(return_value='task'), get=AsyncMock(return_value='turn'))
    async def current(binding):
        return await _direction_authority_current(request=request, authority=binding, task_id='task',
                                                  cache=cache, directus=directus, expected_plan_summary=plan)
    async def review(_context, _assessment):
        records['user_plans'][0]['approved_revision_id'] = 'changed-revision'
        return CorrectionReview(True, 'Return to accepted API scope.', 'real-reviewer')
    delivered = AsyncMock()
    result = await ChatDirectionCorrectionCoordinator().review_and_deliver(context=context,
        assessment=DirectionAssessment('material_drift', context.fingerprint), review=review,
        still_current=current, deliver=delivered)
    assert result is None
    delivered.assert_not_awaited()


@pytest.mark.asyncio
async def test_absent_plan_keeps_actual_goal_baseline_and_queue_binding_uses_latest_original_source_turn():
    from backend.apps.ai.processing.main_processor import _direction_authority_current
    from backend.apps.ai.processing import agentic_context
    from backend.apps.ai.processing.chat_direction import DirectionAuthority
    request, directus, _records = fixtures()
    request.accepted_plan_context = None
    request.message_id = 'turn'
    request.message_history = [{'role': 'user', 'content': 'Fix the API'}]
    cache = SimpleNamespace(get_active_ai_task=AsyncMock(return_value='task'), get=AsyncMock(return_value='turn'))
    authority = DirectionAuthority('owner', 'chat', 'turn', agentic_context.goal_revision(request.message_history))
    assert await _direction_authority_current(request=request, authority=authority, task_id='task', cache=cache,
                                              directus=directus, expected_plan_summary=None)
    directus.get_items.assert_not_awaited()
    client = SimpleNamespace(open_context=AsyncMock(return_value={'accepted_plan_context': fixtures()[0].accepted_plan_context}))
    restored = await restore_private_context_payload({'user_id': 'owner', 'chat_id': 'chat', 'message_id': 'first-batch-turn',
        'agentic_context_ref': 'opaque', 'agentic_context_request_id': 'last-queued-turn',
        'agentic_context_turn_id': 'last-queued-turn'}, client=client)
    assert restored['accepted_plan_context']
    assert client.open_context.await_args.kwargs['turn_id'] == 'last-queued-turn'
