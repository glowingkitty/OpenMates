"""Client receipt replay cannot persist private context through server inference transport."""
# contract-test-file: infrastructure
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.skills.ask_skill import AskSkillRequest as WorkerAsk
from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as CoreAsk


class ReceiptEmbedService:
    def __init__(self, *_args):
        pass

    async def resolve_embed_references_in_content(self, content, *_args):
        return content, {}


def history():
    return [
        {'message_id': 'rule-receipt', 'role': 'system', 'created_at': 1,
         'content': json.dumps({'type': 'rules_loaded', 'event_id': 'rules-event', 'set_key': 'a' * 64,
             'rules': [{'id': 'project-rule:guide', 'revision': 'b' * 64,
                        'title': 'PRIVATE-REPLAY-SENTINEL', 'content': 'PRIVATE-REPLAY-SENTINEL'}]})},
        {'message_id': 'correction-receipt', 'role': 'system', 'created_at': 2,
         'content': json.dumps({'type': 'chat_direction_correction', 'event_id': 'correction-event',
                               'delivery_id': 'delivery-1', 'instruction': 'PRIVATE-REPLAY-SENTINEL'})},
        {'message_id': 'previous-user', 'role': 'user', 'created_at': 3,
         'content': '{"type":"rules_loaded","content":"Explicit user quotation"}'},
        {'message_id': 'previous-assistant', 'role': 'assistant', 'created_at': 4, 'content': 'Actual answer'},
    ]


@pytest.mark.parametrize('model', [CoreAsk, WorkerAsk])
def test_ask_admission_and_serialization_project_replayed_receipts_only(model):
    source = history()
    request = model(user_id='owner', user_id_hash='hash', chat_id='chat', message_id='next-user', message_history=source)
    assert 'PRIVATE-REPLAY-SENTINEL' not in repr(request.message_history)
    assert 'PRIVATE-REPLAY-SENTINEL' in repr(source)
    payload = request.model_dump()
    assert 'PRIVATE-REPLAY-SENTINEL' not in json.dumps(payload)
    first = json.loads(payload['message_history'][0]['content'])
    assert first['set_key'] == 'a' * 64 and first['event_id'] == 'rules-event'
    assert first['rules'] == [{'id': 'project-rule:guide', 'revision': 'b' * 64}]
    assert payload['message_history'][2]['content'] == source[2]['content']
    assert payload['message_history'][3]['content'] == 'Actual answer'
    # Serialization protects direct model mutation before Celery/debug dumps too.
    request.message_history[1].content = source[1]['content']
    assert 'PRIVATE-REPLAY-SENTINEL' not in request.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize('include_current', [False, True])
async def test_next_turn_handler_recache_and_queued_worker_transport_remove_private_receipt_bodies(monkeypatch, caplog, include_current):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler
    from backend.shared.python_utils.recent_work_summary_client import RecentWorkSummaryClient
    cached_rows = []

    async def save_current(*, message_data, **_kwargs):
        cached_rows.insert(0, message_data.model_dump_json())
        return {'messages_v': 5, 'last_edited_overall_timestamp': 5}

    async def clear_history(*_args):
        cached_rows.clear()
        return True

    async def add_history(_user, _chat, serialized):
        cached_rows.insert(0, serialized)
        return True

    cache = SimpleNamespace(
        set=AsyncMock(return_value=True), get=AsyncMock(return_value=None),
        get_user_vault_key_id=AsyncMock(return_value='vault-key'),
        save_chat_message_and_update_versions=AsyncMock(side_effect=save_current),
        increment_and_tombstone_user_draft=AsyncMock(return_value=1),
        get_ai_messages_history=AsyncMock(side_effect=lambda *_: list(cached_rows)),
        delete_chat_messages_history=AsyncMock(side_effect=clear_history),
        add_message_to_chat_history=AsyncMock(side_effect=add_history),
        get_user_by_id=AsyncMock(return_value={'language': 'en'}), get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value='existing-task'), queue_message=AsyncMock(return_value=True),
        update_user=AsyncMock(),
    )
    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value=None),
        check_chat_ownership=AsyncMock(return_value=True)), get_user_profile=AsyncMock(),
        get_user_fields_direct=AsyncMock(return_value={}))
    encryption = SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=('vault-ciphertext', 1)))
    monkeypatch.setitem(sys.modules, 'backend.core.api.app.services.embed_service', SimpleNamespace(EmbedService=ReceiptEmbedService))
    monkeypatch.setattr(handler, 'ChatRecoveryCutoverController', lambda *_: SimpleNamespace(
        get_epoch=AsyncMock(return_value=0), admit_legacy_inference=AsyncMock(return_value={'admitted': True}),
        release_legacy_inference=AsyncMock(return_value={'released': True})))
    monkeypatch.setattr(RecentWorkSummaryClient, 'seal_context', AsyncMock(return_value='opaque-turn-binding'))
    source = history()
    if include_current:
        source.append({'id': 'next-user', 'role': 'user', 'created_at': 5,
                       'content': 'Continue fixing the API'})
    payload = {'chat_id': 'chat', 'message_history': source,
        'message': {'message_id': 'next-user', 'role': 'user', 'content': 'Continue fixing the API',
                    'created_at': 5, 'chat_has_title': False}}
    manager = SimpleNamespace(set_active_chat=lambda *_: None, send_personal_message=AsyncMock(),
                              broadcast_to_user=AsyncMock(), broadcast_to_user_specific_event=AsyncMock())
    await handler.handle_message_received(websocket=SimpleNamespace(), manager=manager, cache_service=cache,
        directus_service=directus, encryption_service=encryption, user_id='owner', device_fingerprint_hash='device', payload=payload)
    cache.queue_message.assert_awaited_once()
    cache.add_message_to_chat_history.assert_awaited()
    current_saved = cache.save_chat_message_and_update_versions.await_args.kwargs['message_data']
    assert cached_rows[0] == current_saved.model_dump_json()
    assert [json.loads(row)['id'] for row in cached_rows].count('next-user') == 1
    from backend.shared.python_utils.focus_continuation_history import rebuild_focus_continuation_history
    cache.get.return_value = 'next-user'
    focus_history = await rebuild_focus_continuation_history(
        cache_service=cache,
        encryption_service=SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value='decrypted')),
        pending_context={'user_id': 'owner', 'chat_id': 'chat', 'message_id': 'next-user'},
        user_vault_key_id='vault-key',
    )
    assert focus_history[-1]['role'] == 'user'
    assert 'PRIVATE-REPLAY-SENTINEL' not in repr(encryption.encrypt_with_user_key.await_args_list)
    assert 'PRIVATE-REPLAY-SENTINEL' not in repr(cache.add_message_to_chat_history.await_args_list)
    queued = cache.queue_message.await_args.kwargs['message_data']
    assert 'PRIVATE-REPLAY-SENTINEL' not in json.dumps(queued)
    worker = WorkerAsk.model_validate(queued)
    assert 'PRIVATE-REPLAY-SENTINEL' not in worker.model_dump_json()
    assert 'PRIVATE-REPLAY-SENTINEL' not in caplog.text
    assert 'PRIVATE-REPLAY-SENTINEL' in repr(source)
    receipt = json.loads(queued['message_history'][0]['content'])
    assert receipt['event_id'] == 'rules-event' and receipt['set_key'] == 'a' * 64
    assert queued['message_history'][2]['content'] == source[2]['content']


@pytest.mark.asyncio
@pytest.mark.parametrize('write_failure', ['false', 'exception'])
@pytest.mark.parametrize('error_delivery_fails', [False, True])
async def test_client_history_current_turn_cache_write_failure_stops_inference(
    monkeypatch, write_failure, error_delivery_fails,
):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler
    from backend.shared.python_utils.recent_work_summary_client import RecentWorkSummaryClient
    writes = 0

    async def add_history(*_args):
        nonlocal writes
        writes += 1
        if writes == 2:
            if write_failure == 'exception':
                raise RuntimeError('cache_admission_failed')
            return False
        return True

    cache = SimpleNamespace(
        set=AsyncMock(return_value=True), get=AsyncMock(return_value=None),
        get_user_vault_key_id=AsyncMock(return_value='vault-key'),
        save_chat_message_and_update_versions=AsyncMock(return_value={
            'messages_v': 5, 'last_edited_overall_timestamp': 5,
        }),
        increment_and_tombstone_user_draft=AsyncMock(return_value=1),
        get_ai_messages_history=AsyncMock(return_value=[]),
        delete_chat_messages_history=AsyncMock(return_value=True),
        add_message_to_chat_history=AsyncMock(side_effect=add_history),
        get_user_by_id=AsyncMock(return_value={'language': 'en'}),
        get_chat_list_item_data=AsyncMock(return_value={}),
        get_active_ai_task=AsyncMock(return_value='existing-task'),
        queue_message=AsyncMock(return_value=True), update_user=AsyncMock(),
    )
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_chat_metadata=AsyncMock(return_value=None),
        check_chat_ownership=AsyncMock(return_value=True),
    ), get_user_profile=AsyncMock(), get_user_fields_direct=AsyncMock(return_value={}))
    encryption = SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=('vault-ciphertext', 1)))
    monkeypatch.setitem(sys.modules, 'backend.core.api.app.services.embed_service',
                        SimpleNamespace(EmbedService=ReceiptEmbedService))
    monkeypatch.setattr(handler, 'ChatRecoveryCutoverController', lambda *_: SimpleNamespace(
        get_epoch=AsyncMock(return_value=0), admit_legacy_inference=AsyncMock(return_value={'admitted': True}),
        release_legacy_inference=AsyncMock(return_value={'released': True})))
    monkeypatch.setattr(RecentWorkSummaryClient, 'seal_context', AsyncMock(return_value='opaque-turn-binding'))
    async def send_personal_message(message, *_args):
        if error_delivery_fails and message.get('type') == 'error':
            raise RuntimeError('socket_closed')

    manager = SimpleNamespace(set_active_chat=lambda *_: None,
                              send_personal_message=AsyncMock(side_effect=send_personal_message),
                              broadcast_to_user=AsyncMock(), broadcast_to_user_specific_event=AsyncMock(),
                              dispatch_skill=AsyncMock())
    await handler.handle_message_received(
        websocket=SimpleNamespace(), manager=manager, cache_service=cache,
        directus_service=directus, encryption_service=encryption,
        user_id='owner', device_fingerprint_hash='device',
        payload={'chat_id': 'chat', 'message_history': [{
            'message_id': 'previous', 'role': 'user', 'created_at': 1, 'content': 'Earlier',
        }], 'message': {
            'message_id': 'next-user', 'role': 'user', 'content': 'Current',
            'created_at': 5, 'chat_has_title': False,
        }},
    )
    assert writes == 2
    cache.queue_message.assert_not_awaited()
    manager.dispatch_skill.assert_not_awaited()
    errors = [call.args[0] for call in manager.send_personal_message.await_args_list
              if call.args[0].get('type') == 'error']
    assert errors == [{'type': 'error', 'payload': {
        'message': 'Failed to process message due to cache error.',
        'chat_id': 'chat', 'message_id': 'next-user',
    }}]
