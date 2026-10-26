"""Bootstrap the real cleanup schema through the reviewed setup contract."""
# contract-test-file: infrastructure
from pathlib import Path

import yaml
from backend.core.directus.setup import setup_schemas as setup


def schema():
    path = Path(__file__).parents[1] / 'core/directus/schemas/chat_call_cleanup_candidates.yml'
    return yaml.safe_load(path.read_text())['chat_call_cleanup_candidates']


def test_empty_call_cleanup_schema_has_reviewed_accountability():
    assert setup.configured_accountability('chat_call_cleanup_candidates', schema()) == (True, None)


def test_empty_call_cleanup_schema_creates_its_string_primary_and_temporal_fields(monkeypatch):
    posted = []
    monkeypatch.setattr(setup, 'collection_exists', lambda *_args: False)
    monkeypatch.setattr(setup, 'field_exists', lambda *_args: False)
    monkeypatch.setattr(setup, 'settle', lambda _delay: None)

    class Response:
        status_code = 200
        text = ''
        def raise_for_status(self):
            return None

    def post(url, *, json, headers):
        assert headers == {'Authorization': 'Bearer test-token'}
        posted.append((url, json))
        return Response()

    monkeypatch.setattr(setup.requests, 'post', post)
    assert setup.create_collection_from_config('test-token', 'chat_call_cleanup_candidates', schema()) == (True, True)
    primary = posted[0][1]['fields'][0]
    assert primary['type'] == 'string'
    assert primary['meta']['special'] == []
    assert primary['schema']['is_primary_key'] is True
    assert posted[0][1]['meta']['accountability'] is None
    fields = {item['field']: item for _url, item in posted[1:]}
    assert set(fields) == set(schema()['fields']) - {'id'}
    assert fields['created_at']['type'] == 'dateTime'
    assert fields['created_at']['schema']['data_type'] == 'timestamp with time zone'
    assert fields['attempt_id']['type'] == 'uuid'
    assert fields['expected_messages_v']['type'] == 'integer'
