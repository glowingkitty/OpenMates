"""Combined queued turns retain response identity and fresh memory-bound authority."""
# contract-test-file: infrastructure
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.apps.ai.processing import main_processor as main
from backend.apps.ai.processing.chat_direction import DirectionAuthority
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.core.api.app.routes import recent_work_internal
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService
from backend.shared.python_utils.recent_work_summary_cache import TransientContextHandoffStore
from backend.shared.python_utils.recent_work_summary_client import (
    RecentWorkSummaryClient, authoritative_context_turn_id, bind_restored_context_turn,
    mark_response_summary_active, mint_response_summary_completion,
    restore_private_context_payload, seal_private_context_payload,
)
from backend.tests.test_recent_work_summary_cache import runtime_app
from backend.tests.test_project_authoring_response_availability import _publish_project_authoring_availability


@pytest.mark.asyncio
async def test_two_queued_turns_use_validated_latest_source_without_changing_response_identity(monkeypatch):
    app, _tasks, _owned, _encryption = runtime_app(monkeypatch)
    monkeypatch.setattr(recent_work_internal, 'transient_context_handoff_store', TransientContextHandoffStore())
    monkeypatch.setattr(ProjectWriteAuthorizationService, 'get_active_focus', AsyncMock(return_value=None))
    latest = ['last-user-turn']
    cache = app.state.cache_service
    cache.get = AsyncMock(side_effect=lambda key: {'project_id': 'project', 'team_id': None}
                         if 'focus' in key else latest[0])
    cache.set = AsyncMock(return_value=True)
    cache.publish_event = AsyncMock()
    ipc = RecentWorkSummaryClient(base_url='http://runtime', token='service-token', transport=httpx.ASGITransport(app=app))
    # Even a turn with no optional documents gets an owner/chat/source-bound opaque handle.
    queued = await seal_private_context_payload({'user_id': 'owner', 'chat_id': 'current',
        'message_id': 'last-user-turn'}, request_id='last-user-turn', client=ipc, ensure_turn_binding=True)
    request = AskSkillRequest(user_id='owner', user_id_hash='hash', chat_id='current',
        message_id='first-user-turn', current_user_content='Fix the API\nAlso preserve privacy',
        message_history=[{'message_id': 'first-user-turn', 'role': 'user', 'content': 'Fix the API', 'created_at': 1},
                         {'message_id': 'last-user-turn', 'role': 'user', 'content': 'Also preserve privacy', 'created_at': 2}],
        active_project_focus={'project_id': 'project'}, **{k: v for k, v in queued.items() if k.startswith('agentic_context_')})
    restored = await restore_private_context_payload(request.model_dump(), client=ipc)
    bind_restored_context_turn(request, restored)
    assert request.message_id == 'first-user-turn'
    assert authoritative_context_turn_id(request) == 'last-user-turn'
    assert '_authoritative_context_turn_id' not in request.model_dump()
    assert await mark_response_summary_active(request, 'task-current', client=ipc)
    await mint_response_summary_completion(request, 'task-current', client=ipc)
    permit = recent_work_internal.recent_work_summary_cache._completion_permits[request._recent_summary_completion_ticket]
    assert permit.turn_id == 'last-user-turn'
    authority = DirectionAuthority('owner', 'current', 'last-user-turn', main.agentic_context.goal_revision(request.message_history))
    assert await main._direction_authority_current(request=request, authority=authority, task_id='task-current',
                                                  cache=cache, directus=object())
    async def evaluate(_script, _count, *args):
        return int(args[-2] == latest[0])
    redis = SimpleNamespace(eval=AsyncMock(side_effect=evaluate))
    async def redis_client():
        return redis
    cache.client = redis_client()
    cache._get_active_task_key = lambda chat: 'active-task:' + chat
    instructions = []
    receipt = await main._deliver_direction_instruction(request=request, task_id='task-current', authority=authority,
        cache=cache, instruction='Return to the API goal with privacy preserved', fingerprint='two-queued', append=instructions.append)
    assert receipt.accepted and len(instructions) == 1
    assert redis.eval.await_args.args[-2] == 'last-user-turn'
    monkeypatch.setattr(ProjectWriteAuthorizationService, '_require_chat_access', AsyncMock())
    monkeypatch.setattr(ProjectWriteAuthorizationService, '_require_project_access', AsyncMock())
    assert await _publish_project_authoring_availability(request, 'task-current', cache, object())
    assert cache.set.await_args.args[0].endswith(':last-user-turn')
    assert cache.publish_event.await_args.args[1]['payload'] == {
        'chat_id': 'current', 'project_id': 'project', 'user_message_id': 'last-user-turn', 'assistant_message_id': 'task-current'}
    latest[0] = 'newer-user-turn'
    assert not await mark_response_summary_active(request, 'task-current', client=ipc)
    assert not await main._direction_authority_current(request=request, authority=authority, task_id='task-current', cache=cache, directus=object())
    assert not await _publish_project_authoring_availability(request, 'task-current', cache, object())
    stale = await restore_private_context_payload(request.model_dump(), client=ipc)
    bind_restored_context_turn(request, stale)
    assert authoritative_context_turn_id(request) == 'first-user-turn'
    del request._recent_summary_completion_ticket
    await mint_response_summary_completion(request, 'task-current', client=ipc)
    assert not getattr(request, '_recent_summary_completion_ticket', None)
    assert request.message_id == 'first-user-turn'


@pytest.mark.asyncio
async def test_client_source_turn_and_injected_runtime_marker_cannot_grant_authority():
    request = AskSkillRequest(user_id='owner', user_id_hash='hash', chat_id='chat', message_id='first',
                              agentic_context_turn_id='last', message_history=[], _authoritative_context_turn_id='last')
    assert authoritative_context_turn_id(request) == 'first'
    restored = await restore_private_context_payload({**request.model_dump(), '_authoritative_context_turn_id': 'last'})
    bind_restored_context_turn(request, restored)
    assert authoritative_context_turn_id(request) == 'first'
