"""Human app presence gates both completion channels before broker submission."""
# contract-test-file: infrastructure
import sys
import ast
import json
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.core.api.app.services import notification_presence as presence
from backend.core.api.app.services import chat_email_notification_service as email
from backend.tests.test_notification_presence import CacheService
from backend.tests.test_push_notification_preview import completion_dispatch

from backend.tests.test_chat_email_notification_service import fixture as delivery_fixture  # noqa: F401


# contract-test: supporting surface=rest_api assertions=notifications.delivery.foreground-chat-suppression
@pytest.mark.parametrize('client_type', ['web', 'cli'])
@pytest.mark.parametrize('chat_id', ['new-chat-without-active-selection', 'follow-up-chat'])
@pytest.mark.parametrize('state', ['foreground', 'background', 'closed', 'expired', 'headless', 'other-user', 'rotated'])
@pytest.mark.asyncio
async def test_completion_email_and_push_use_same_fresh_human_gate(delivery_fixture, monkeypatch, client_type, chat_id, state):  # noqa: F811
    cache = CacheService()
    now = 100
    owner = 'another-user' if state == 'other-user' else 'user-a'
    await presence.report_presence(cache, owner, 'old-socket', client_type, True,
                                   interactive=state != 'headless', chat_id=None, now=now)
    if state == 'background':
        await presence.report_presence(cache, owner, 'old-socket', client_type, False, now=101)
    elif state == 'closed':
        await presence.clear_presence(cache, owner, 'old-socket')
    elif state == 'expired':
        now += presence.LEASE_SECONDS
    elif state == 'rotated':
        # An old authenticated socket's cleanup cannot erase the successor lease.
        await presence.report_presence(cache, owner, 'new-socket', client_type, True,
                                       interactive=True, now=101)
        await presence.clear_presence(cache, owner, 'old-socket')
    evaluator = presence.has_active_human
    async def active(_cache, user_id, _chat_id):
        return await evaluator(cache, user_id, _chat_id, now=now)
    monkeypatch.setattr(email, 'has_active_human', active)
    # Preserve the real lease evaluator while injecting a deterministic clock into
    # the production push coroutine's imported gate.
    async def push_active(_cache, user_id, selected_chat):
        return await evaluator(cache, user_id, selected_chat, now=now)
    monkeypatch.setattr(presence, 'has_active_human', push_active)
    broker = SimpleNamespace(send_task=Mock())
    monkeypatch.setitem(sys.modules, 'backend.core.api.app.tasks.celery_config', SimpleNamespace(app=broker))
    push_cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={
        'push_notification_enabled': True, 'push_notification_subscription': '{}',
        'push_notification_preferences': {'aiResponses': True},
    }))
    suppressed = state in {'foreground', 'rotated'} or (state == 'headless' and client_type == 'web')
    assert await email.enqueue_chat_email(cache_service=delivery_fixture.cache, directus_service=delivery_fixture.directus,
        encryption_service=delivery_fixture.encryption, user_id='user-a', chat_id=chat_id,
        message_id='response') is not suppressed
    assert await completion_dispatch()(SimpleNamespace(state=SimpleNamespace(cache_service=push_cache)),
        'user-a', chat_id, 'Response') is not suppressed
    assert broker.send_task.call_count == (0 if suppressed else 2)
    if suppressed:
        assert delivery_fixture.cache.redis.values == {}


# contract-test: supporting surface=rest_api assertions=notifications.delivery.foreground-chat-suppression
@pytest.mark.asyncio
async def test_foreground_return_during_push_profile_lookup_suppresses_enqueue(monkeypatch):
    broker = SimpleNamespace(send_task=Mock())
    monkeypatch.setitem(sys.modules, 'backend.core.api.app.tasks.celery_config', SimpleNamespace(app=broker))
    monkeypatch.setattr(presence, 'has_active_human', AsyncMock(side_effect=[False, True]))
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={
        'push_notification_enabled': True, 'push_notification_subscription': '{}',
        'push_notification_preferences': {'aiResponses': True},
    }))
    assert not await completion_dispatch()(SimpleNamespace(state=SimpleNamespace(cache_service=cache)),
        'user-a', 'chat', 'Response')
    broker.send_task.assert_not_called()


# contract-test: supporting surface=rest_api assertions=notifications.delivery.foreground-chat-suppression
@pytest.mark.parametrize('category', ['OPENMATES_CHAT_MESSAGE', 'OPENMATES_WORKFLOW_COMPLETED', 'REMINDER'])
@pytest.mark.parametrize('active', [True, False])
def test_delayed_push_transport_rechecks_only_chat_presence(category, active):
    source = Path(__file__).resolve().parents[1] / 'core/api/app/tasks/push_notification_task.py'
    node = next(n for n in ast.parse(source.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == 'send_push_notification')
    node.decorator_list = []
    transport = Mock(return_value=True)
    active_gate = AsyncMock(return_value=active)
    namespace = dict(Optional=__import__('typing').Optional, asyncio=asyncio,
        logger=logging.getLogger(__name__), _can_dispatch_subscription=lambda _: True,
        _direct_chat_push_access=AsyncMock(return_value=True),
        _chat_has_active_human=active_gate,
        push_notification_service=SimpleNamespace(send_push_notification=transport))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), 'exec'), namespace)
    suppressed = active and category == 'OPENMATES_CHAT_MESSAGE'
    assert namespace['send_push_notification'](None, '{}', 'Title', 'Body',
        chat_id='chat', user_id='user', category=category) is not suppressed
    assert transport.call_count == (0 if suppressed else 1)
    assert active_gate.await_count == (1 if category == 'OPENMATES_CHAT_MESSAGE' else 0)


# contract-test: supporting surface=rest_api assertions=notifications.delivery.foreground-chat-suppression
@pytest.mark.asyncio
async def test_foreground_return_during_email_preparation_suppresses_enqueue(delivery_fixture, monkeypatch):  # noqa: F811
    monkeypatch.setattr(email, 'has_active_human', AsyncMock(side_effect=[False, True]))
    assert not await email.enqueue_chat_email(cache_service=delivery_fixture.cache,
        directus_service=delivery_fixture.directus, encryption_service=delivery_fixture.encryption,
        user_id='user-a', chat_id='chat-a', message_id='response')
    assert delivery_fixture.cache.redis.values == {}
    assert delivery_fixture.broker == []


def offline_email_coroutine(enqueue):
    """Execute the production completion-email coroutine with real view marking."""
    source = Path(__file__).resolve().parents[1] / 'core/api/app/routes/websockets.py'
    node = next(n for n in ast.parse(source.read_text()).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == '_send_offline_email_notification')
    namespace = {'FastAPI': object, 'enqueue_chat_email': enqueue,
                 'mark_message_viewed': presence.mark_message_viewed}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), 'exec'), namespace)
    return namespace[node.name]


# A noninteractive `openmates chats send` (npm or Rust CLI) announces
# client_type=cli, is_foreground=true, interactive=false and selects the chat it
# is awaiting. It holds no human presence lease, but it received this exact
# completion on a live foreground socket, so the initiator's email must not send.
# contract-test: supporting surface=rest_api assertions=notifications.delivery.foreground-chat-suppression
@pytest.mark.parametrize('state,expected', [
    ('cli-awaiting-reply', 'viewed'),
    ('cli-disconnected-no-wait', 'sent'),
    ('cli-other-chat', 'sent'),
    ('background-socket', 'sent'),
    ('retained-in-grace', 'sent'),
])
@pytest.mark.asyncio
async def test_completion_delivered_to_awaiting_cli_socket_suppresses_initiator_email(
    delivery_fixture, monkeypatch, state, expected,  # noqa: F811
):
    from starlette.websockets import WebSocketState
    from backend.core.api.app.routes.connection_manager import ConnectionManager
    from backend.core.api.app.services import team_chat_notification_service as team

    manager = ConnectionManager()
    user, device, chat, message = 'user-a', 'cli-device', 'chat-a', 'message-a'
    if state != 'cli-disconnected-no-wait':
        manager.active_connections[user] = {device: SimpleNamespace(application_state=WebSocketState.CONNECTED)}
        manager.connection_foreground_state[(user, device)] = state != 'background-socket'
        manager.active_chat_per_connection[(user, device)] = 'chat-b' if state == 'cli-other-chat' else chat
        if state == 'retained-in-grace':
            manager.grace_period_tasks[(user, device)] = SimpleNamespace(done=lambda: False)
    # The noninteractive CLI never holds an account-wide human lease.
    view_cache = CacheService()
    await presence.report_presence(view_cache, user, 'cli-socket', 'cli', True, interactive=False, chat_id=chat)
    assert not await presence.has_active_human(view_cache, user, chat)

    monkeypatch.setattr(team, 'queue_completed_team_mate_response', AsyncMock(return_value=False))
    async def viewed(_cache, user_id, chat_id, message_id):
        return await presence.is_message_viewed(view_cache, user_id, chat_id, message_id)
    monkeypatch.setattr(email, 'is_message_viewed', viewed)

    async def enqueue(**kwargs):
        kwargs.update(cache_service=delivery_fixture.cache, directus_service=delivery_fixture.directus,
                      encryption_service=delivery_fixture.encryption)
        return await email.enqueue_chat_email(**kwargs)
    app = SimpleNamespace(state=SimpleNamespace(cache_service=view_cache, directus_service=delivery_fixture.directus,
                                                encryption_service=delivery_fixture.encryption))
    await offline_email_coroutine(enqueue)(
        app, user, chat, 'Response', message_id=message,
        # The listener records actual final delivery to a selected-chat
        # foreground socket; mirror that capability check here.
        viewing_connection=manager.has_foreground_connection_for_chat(user, chat),
    )
    key = email.candidate_key(user, chat, message)
    candidate = json.loads(delivery_fixture.cache.redis.values[key])
    candidate['not_before'] = 0
    delivery_fixture.cache.redis.values[key] = json.dumps(candidate)
    guard = sys.modules['backend.core.api.app.services.email_delivery_guard']
    async def send_once(**kwargs):
        return (True, 'sent') if await kwargs['before_send']() else (False, 'suppressed')
    monkeypatch.setattr(guard, 'send_email_once', send_once)
    assert await email.dispatch_chat_email(delivery_fixture.task, user_id=user, chat_id=chat, message_id=message) == expected
