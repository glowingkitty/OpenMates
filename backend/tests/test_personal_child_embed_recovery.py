"""Bounded Personal ciphertext recovery security on the exact production candidate."""
import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException

CHAT = '11111111-1111-1111-1111-111111111111'
PARENT = '22222222-2222-2222-2222-222222222222'
CHILD = '33333333-3333-3333-3333-333333333333'
OWNER = 'owner'
hash_value = lambda value: hashlib.sha256(value.encode()).hexdigest()


def route():
    root = Path(__file__).resolve().parents[2]
    source = root / 'backend/core/api/app/routes/embeds_api.py'
    tree = ast.parse(source.read_text())
    node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == 'get_personal_child_embed')
    node.decorator_list = []
    node.args.defaults = []
    namespace = dict(UUID=UUID, HTTPException=HTTPException, _hash_value=hash_value,
                     Request=object, User=object, DirectusService=object,
                     EMBED_ALL_FIELDS="*", EMBED_KEY_ALL_FIELDS="*")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['get_personal_child_embed']


def fixture():
    chat = {'id': CHAT, 'hashed_user_id': hash_value(OWNER), 'hashed_team_id': None}
    base = {'status': 'finished', 'hashed_user_id': hash_value(OWNER),
            'hashed_chat_id': hash_value(CHAT), 'encrypted_content': 'ciphertext'}
    embeds = {PARENT: {'embed_id': PARENT, **base},
              CHILD: {'embed_id': CHILD, 'parent_embed_id': PARENT, **base}}
    keys = [{'hashed_embed_id': hash_value(PARENT), 'hashed_user_id': hash_value(OWNER),
             'key_type': 'master', 'hashed_chat_id': None, 'encrypted_embed_key': 'wrapped'}]
    calls = []

    async def get_items(collection, params, **kwargs):
        calls.append((collection, params, kwargs))
        if collection == 'chats': return [chat]
        if collection == 'embeds':
            row = embeds.get(params['filter[embed_id][_eq]'])
            return [row] if row else []
        return keys

    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value=chat)),
                               get_items=get_items)
    return chat, embeds, keys, calls, directus


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
@pytest.mark.asyncio
async def test_returns_exact_child_and_existing_parent_keys_with_bounded_owner_queries():
    _, _, keys, calls, directus = fixture()
    result = await route()(CHAT, CHILD, SimpleNamespace(query_params={}), SimpleNamespace(id=OWNER), directus)
    assert result['embed']['embed_id'] == CHILD
    assert result['parent_embed_id'] == PARENT
    assert result['embed_keys'] == keys
    assert [call[1]['limit'] for call in calls] == [1, 1, 1, 3, 1]
    assert all(call[2]['no_cache'] and call[2]['admin_required'] for call in calls)
    assert calls[3][1]['filter']['_and'][1] == {'hashed_user_id': {'_eq': hash_value(OWNER)}}
    assert len([call for call in calls if call[0] == 'chats']) == 2
    assert all(call[2]['raise_on_error'] for call in calls)


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['wrong-owner', 'team-chat', 'wrong-source', 'wrong-parent-owner',
                                  'cyclic-parent', 'nested-parent', 'wrong-key-owner', 'other-chat-key',
                                  'project-key', 'too-many-keys', 'unfinished-child', 'vault-child'])
async def test_fails_closed_without_returning_ciphertext(fault):
    chat, embeds, keys, _, directus = fixture()
    if fault == 'wrong-owner': chat['hashed_user_id'] = 'other'
    elif fault == 'team-chat': chat['hashed_team_id'] = 'team'
    elif fault == 'wrong-source': embeds[CHILD]['hashed_chat_id'] = 'other'
    elif fault == 'wrong-parent-owner': embeds[PARENT]['hashed_user_id'] = 'other'
    elif fault == 'cyclic-parent': embeds[CHILD]['parent_embed_id'] = CHILD
    elif fault == 'nested-parent': embeds[PARENT]['parent_embed_id'] = CHILD
    elif fault == 'wrong-key-owner': keys[0]['hashed_user_id'] = 'other'
    elif fault == 'other-chat-key': keys[0].update(key_type='chat', hashed_chat_id='other')
    elif fault == 'project-key': keys[0]['hashed_project_id'] = 'other'
    elif fault == 'too-many-keys': keys.extend([keys[0], keys[0]])
    elif fault == 'unfinished-child': embeds[CHILD]['status'] = 'processing'
    elif fault == 'vault-child': embeds[CHILD]['encryption_mode'] = 'vault'
    with pytest.raises(HTTPException) as error:
        await route()(CHAT, CHILD, SimpleNamespace(query_params={}), SimpleNamespace(id=OWNER), directus)
    assert error.value.status_code == 404


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
@pytest.mark.asyncio
async def test_malformed_ids_and_explicit_team_scope_do_not_query_storage():
    _, _, _, calls, directus = fixture()
    for chat, child, query in [(CHAT, 'malformed', {}), ('malformed', CHILD, {}), (CHAT, CHILD, {'team_id': 'team'})]:
        with pytest.raises(HTTPException):
            await route()(chat, child, SimpleNamespace(query_params=query), SimpleNamespace(id=OWNER), directus)
    assert calls == []
    directus.chat.get_chat_metadata.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
@pytest.mark.asyncio
@pytest.mark.parametrize('collection', ['chats', 'embeds', 'embed_keys'])
@pytest.mark.parametrize('failure', ['exception', 'none-response'])
async def test_transient_storage_failure_is_503_not_absence(collection, failure):
    _, _, _, _, directus = fixture()
    original = directus.get_items
    async def failing_read(selected_collection, params, **kwargs):
        if selected_collection == collection:
            if failure == 'exception': raise RuntimeError('Transient CMS failure')
            return None
        return await original(selected_collection, params, **kwargs)
    directus.get_items = failing_read
    with pytest.raises(HTTPException) as error:
        await route()(CHAT, CHILD, SimpleNamespace(query_params={}), SimpleNamespace(id=OWNER), directus)
    assert error.value.status_code == 503


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
@pytest.mark.asyncio
async def test_missing_live_chat_remains_404():
    _, _, _, _, directus = fixture()
    directus.get_items = AsyncMock(return_value=[])
    with pytest.raises(HTTPException) as error:
        await route()(CHAT, CHILD, SimpleNamespace(query_params={}), SimpleNamespace(id=OWNER), directus)
    assert error.value.status_code == 404
