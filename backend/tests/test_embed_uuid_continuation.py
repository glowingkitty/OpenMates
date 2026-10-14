"""Embed pagination must honor the real Directus UUID operator restrictions."""
import json
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.directus import embed_methods

CHAT = 'a' * 64
OTHER = 'b' * 64
EMBED = 'c' * 64


def row_id(number):
    return f"00000000-0000-4000-8000-{number:012d}"


class RestrictedDirectus:
    base_url = "http://cms:8055"

    def __init__(self, rows, keys=None):
        self.rows = rows
        self.keys = keys or []
        self.requests = []

    async def get_items(self, collection, *, params, **options):
        serialized = json.dumps(params)
        assert 'filter[id][_gt]' not in serialized and 'filter[id][_lt]' not in serialized
        def reject_uuid_ranges(value):
            if isinstance(value, dict):
                if 'id' in value:
                    assert not any(op in value['id'] for op in ('_gt', '_lt'))
                for child in value.values():
                    reject_uuid_ranges(child)
            elif isinstance(value, list):
                for child in value:
                    reject_uuid_ranges(child)
        reject_uuid_ranges(params.get('filter', {}))
        assert options['raise_on_error'] is True
        rows = self.rows if collection == 'embeds' else self.keys
        chat = params.get('filter', {}).get('hashed_chat_id', {}).get('_eq') or params.get('filter[hashed_chat_id][_eq]')
        rows = [row for row in rows if row.get('hashed_chat_id') == chat]
        if params['sort'] == ['-created_at', '-id']:
            rows = sorted(rows, key=lambda row: (row['created_at'], row['id']), reverse=True)
        else:
            rows = sorted(rows, key=lambda row: row['id'])
        return rows[:params['limit']]

    async def _make_api_request(self, method, url, *, headers, json):
        assert method == 'POST' and url.endswith('/embed-version-transaction/scoped-read')
        assert headers == {'X-Internal-Service-Token': 'unit-token'}
        self.requests.append(json)
        rows = self.rows if json['operation'] in ('embed_window', 'complete_embeds') else self.keys
        rows = [row for row in rows if row.get('hashed_chat_id') == json['hashed_chat_id']]
        if json['operation'] == 'embed_window':
            cursor = (json['before_created_at'], json['before_id'])
            rows = sorted((row for row in rows if (row['created_at'], row['id']) < cursor),
                          key=lambda row: (row['created_at'], row['id']), reverse=True)[:31]
        else:
            rows = sorted((row for row in rows if row['id'] > json['after_id']), key=lambda row: row['id'])
            if json['operation'] == 'embed_key_window':
                assert json['include_master_keys'] is False and json['hashed_user_id'] is None
                rows = [row for row in rows if row['hashed_embed_id'] in json['hashed_embed_ids'] and row['key_type'] == 'chat'][:61]
            else:
                rows = rows[:20]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'data': rows})


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_uuid_tied_time_pages_are_complete_scoped_and_byte_bounded(monkeypatch):
    monkeypatch.setenv('INTERNAL_API_SHARED_TOKEN', 'unit-token')
    monkeypatch.setattr(embed_methods, 'SYNC_EMBED_PAGE_MAX_BYTES', 1400)
    rows = [{'id': row_id(n), 'embed_id': f'embed-{n}', 'created_at': 12,
             'hashed_chat_id': CHAT, 'encrypted_content': 'cipher' * 30} for n in range(75)]
    directus = RestrictedDirectus(rows + [dict(rows[0], id=row_id(999), hashed_chat_id=OTHER)])
    methods = embed_methods.EmbedMethods(directus)
    seen = []
    cursor = {}
    while True:
        page = await methods.get_embed_window_by_hashed_chat_id(CHAT, **cursor)
        assert page['payload_bytes'] <= 1400 and len(page['embeds']) <= 30
        seen.extend(row['id'] for row in page['embeds'])
        if not page['has_more_before']:
            break
        cursor = {'before_created_at': page['start_cursor']['created_at'], 'before_id': page['start_cursor']['id']}
    assert seen == [row['id'] for row in reversed(rows)]
    assert len(set(seen)) == 75 and directus.requests


# contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_oversized_uuid_cursor_skips_only_exact_selected_row(monkeypatch):
    monkeypatch.setenv('INTERNAL_API_SHARED_TOKEN', 'unit-token')
    monkeypatch.setattr(embed_methods, 'SYNC_EMBED_PAGE_MAX_BYTES', 300)
    rows = [{'id': row_id(n), 'embed_id': f'embed-{n}', 'created_at': 12,
             'hashed_chat_id': CHAT, 'encrypted_content': 'cipher'} for n in range(3)]
    rows[-1]['encrypted_content'] = 'x' * 1000
    methods = embed_methods.EmbedMethods(RestrictedDirectus(rows))
    first = await methods.get_embed_window_by_hashed_chat_id(CHAT)
    assert first['embeds'] == [] and first['oversized_embed_id'] == 'embed-2'
    cursor = first['oversized_embed_cursor']
    second = await methods.get_embed_window_by_hashed_chat_id(CHAT, before_created_at=cursor['created_at'], before_id=cursor['id'])
    assert [row['id'] for row in second['embeds']] == [row_id(1)]
    last = second['start_cursor']
    third = await methods.get_embed_window_by_hashed_chat_id(CHAT, before_created_at=last['created_at'], before_id=last['id'])
    assert [row['id'] for row in third['embeds']] == [row_id(0)]
    assert third['has_more_before'] is False


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_complete_embed_export_rejects_repeated_native_page(monkeypatch):
    monkeypatch.setenv('INTERNAL_API_SHARED_TOKEN', 'unit-token')
    rows = [{'id': row_id(n), 'embed_id': f'embed-{n}', 'created_at': 12, 'hashed_chat_id': CHAT} for n in range(42)]
    directus = RestrictedDirectus(rows)
    methods = embed_methods.EmbedMethods(directus)
    assert await methods.get_embeds_by_hashed_chat_id(CHAT) == list(reversed(rows))
    async def repeat(*args, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'data': rows[:20]})
    directus._make_api_request = repeat
    with pytest.raises(RuntimeError, match='cursor did not advance'):
        await methods.get_embeds_by_hashed_chat_id(CHAT)


# contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_uuid_key_continuation_preserves_chat_only_scope_and_oversize(monkeypatch):
    monkeypatch.setenv('INTERNAL_API_SHARED_TOKEN', 'unit-token')
    monkeypatch.setattr(embed_methods, 'SYNC_EMBED_KEY_PAGE_MAX_BYTES', 300)
    keys = [{'id': row_id(n), 'hashed_chat_id': CHAT, 'hashed_embed_id': EMBED,
             'key_type': 'chat', 'encrypted_embed_key': 'cipher'} for n in range(4)]
    keys[1]['encrypted_embed_key'] = 'x' * 1000
    methods = embed_methods.EmbedMethods(RestrictedDirectus([], keys))
    first = await methods.get_sync_embed_key_window_for_page(CHAT, '', [EMBED], include_master_keys=False)
    assert first['end_cursor'] == row_id(0) and first['has_more_after']
    oversized = await methods.get_sync_embed_key_window_for_page(CHAT, '', [EMBED], include_master_keys=False, after_key_id=first['end_cursor'])
    assert oversized['oversized_key_id'] == row_id(1) and oversized['embed_keys'] == []
    next_page = await methods.get_sync_embed_key_window_for_page(CHAT, '', [EMBED], include_master_keys=False, after_key_id=oversized['oversized_key_id'])
    assert [row['id'] for row in next_page['embed_keys']] == [row_id(2)]
