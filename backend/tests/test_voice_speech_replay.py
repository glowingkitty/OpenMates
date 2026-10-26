"""Canonical call clauses replay existing assets using owner-scoped HMAC sources."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.assistant_speech.projection import project_final_voice_clauses
from backend.apps.ai.assistant_speech.streaming import _speech_source_identity
from backend.core.api.app.routes.handlers.websocket_handlers.assistant_speech_handler import (
    handle_assistant_speech_request, resolve_registered_voice_segments,
)


def rows_for(text, monkeypatch):
    monkeypatch.setattr('backend.apps.ai.assistant_speech.streaming._token_secret', lambda: b'test-only')
    return [dict(segment_id=f'clause-{i}', sequence=i, source_hash=_speech_source_identity(part),
        kind='voice_prose_clause', source_version=1, status='ready', generated_asset_id=f'asset-{i}')
        for i, part in enumerate(project_final_voice_clauses(text))]


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
@pytest.mark.asyncio
async def test_manual_replay_resolves_all_clauses_and_generate_targets_one_exact_identity(monkeypatch):
    text = 'First sentence. Read [the guide](https://example.org).\n\n```json\n{"secret":1}\n```\nLast words'
    rows = rows_for(text, monkeypatch)
    directus = SimpleNamespace(get_items=AsyncMock(return_value=rows))
    kwargs = dict(user_id='owner', chat_id='chat', assistant_message_id='message',
        segments=[dict(sequence=0, source_version=1, kind='prose_paragraph', speakable_text='whole paragraph')],
        source_markdown=text, action='request')
    resolved = await resolve_registered_voice_segments(directus, **kwargs)
    assert [s['speakable_text'] for s in resolved] == ['First sentence.', 'Read the guide.', 'Last words']
    assert [s['segment_id'] for s in resolved] == ['clause-0', 'clause-1', 'clause-2']
    filters = directus.get_items.call_args.kwargs['params']
    assert filters['filter[user_id][_eq]'] == 'owner'
    assert filters['filter[chat_id][_eq]'] == 'chat'
    assert filters['filter[assistant_message_id][_eq]'] == 'message'
    assert filters['filter[kind][_eq]'] == 'voice_prose_clause'
    kwargs.update(action='generate', segments=[dict(segment_id='clause-2', source_version=1)])
    assert [s['speakable_text'] for s in await resolve_registered_voice_segments(directus, **kwargs)] == ['Last words']


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize('source,target', [('forged text', 'clause-0'), (None, 'clause-0'), ('Safe answer.', 'foreign-id')])
async def test_forged_source_or_target_never_creates_historical_voice_assets(monkeypatch, source, target):
    directus = SimpleNamespace(get_items=AsyncMock(return_value=rows_for('Safe answer.', monkeypatch)))
    with pytest.raises(ValueError):
        await resolve_registered_voice_segments(directus, user_id='owner', chat_id='chat', assistant_message_id='message',
            segments=[dict(segment_id=target, source_version=1)], source_markdown=source, action='generate')


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
@pytest.mark.asyncio
async def test_ordinary_historical_projection_remains_unchanged():
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[]))
    assert await resolve_registered_voice_segments(directus, user_id='owner', chat_id='chat', assistant_message_id='message',
        segments=[dict(sequence=0, source_version=1, kind='prose_paragraph')], source_markdown='Historical paragraph.', action='request') is None


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.privacy
@pytest.mark.asyncio
async def test_resolution_follows_authorization_and_replaces_budget_and_dispatch_source(monkeypatch):
    text = 'First sentence. Second sentence.'
    rows = rows_for(text, monkeypatch)
    dispatch = AsyncMock(return_value=rows)
    preflight = AsyncMock(return_value=True)
    resolver = AsyncMock(return_value=[dict(row, speakable_text=part) for row, part in zip(rows, project_final_voice_clauses(text))])
    payload = dict(chat_id='chat', assistant_message_id='message', source_markdown=text,
        segments=[dict(sequence=0, source_version=1, kind='prose_paragraph', source_hash='server-verified', speakable_text=text)])
    forbidden = await handle_assistant_speech_request(user_id='other', payload=payload,
        authorize=AsyncMock(return_value={'chat_owner_id':'owner', 'message_role':'assistant'}),
        rate_limit=lambda **_:True, budget_preflight=preflight, dispatch=dispatch, resolve_segments=resolver)
    assert forbidden['error'] == 'forbidden' and not resolver.called and not dispatch.called
    result = await handle_assistant_speech_request(user_id='owner', payload=payload,
        authorize=AsyncMock(return_value={'chat_owner_id':'owner', 'message_role':'assistant'}),
        rate_limit=lambda **_:True, budget_preflight=preflight, dispatch=dispatch, resolve_segments=resolver)
    assert result['status'] == 'accepted'
    assert [call.kwargs['segment']['speakable_text'] for call in preflight.call_args_list] == ['First sentence.', 'Second sentence.']
    assert len(dispatch.call_args.kwargs['segments']) == 2
    assert 'source_markdown' not in dispatch.call_args.kwargs
    assert text not in repr(result)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
@pytest.mark.asyncio
async def test_unknown_voice_source_version_cannot_fall_back_to_historical_generation(monkeypatch):
    directus = SimpleNamespace(get_items=AsyncMock(return_value=rows_for('Safe answer.', monkeypatch)))
    with pytest.raises(ValueError):
        await resolve_registered_voice_segments(directus, user_id='owner', chat_id='chat', assistant_message_id='message',
            segments=[dict(sequence=0, source_version=2, kind='prose_paragraph')], source_markdown='Safe answer.', action='request')


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.privacy
def test_heard_context_keeps_words_without_delivery_directions():
    from backend.apps.ai.assistant_speech.voice_context import build_voice_heard_context
    boundary = SimpleNamespace(assistant_message_id='message', completed_sequences=[0],
                               active_sequence=1, active_offset_ms=120)
    source = '<!-- voice:curious -->First answer. <!-- voice:excited -->Next answer.'
    context = build_voice_heard_context(boundary, [dict(role='assistant', message_id='message', content=source)])
    assert 'First answer.' in context and 'Next answer.' in context
    assert '[curious]' not in context and '[excited]' not in context and 'voice:' not in context
    assert 'not a word timestamp' in context
