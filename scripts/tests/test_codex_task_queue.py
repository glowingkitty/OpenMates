"""CLI-independent Task intent ownership, idempotency and account scope tests.

Only private temporary snapshots and command files are used. These tests run
without an OpenMates executable or network, matching a CLI upgrade outage.
The foreground delivery processor supplies the separate encrypted API boundary.
"""
import json
import pytest
from scripts.codex_task_queue import enqueue
THREAD = '00000000-0000-0000-0000-000000000001'
OTHER = '00000000-0000-0000-0000-000000000002'


def snapshot(path, owner=THREAD):
    path.write_text(json.dumps({'account_scope': ['https://api.example', 'hashed-account', 'personal'],
        'project_id': 'project', 'connection': 'connected', 'tasks': [{'task_id': 'task', 'version': 4,
        'external_chat': {'provider': 'codex', 'id': owner, 'title': 'Landing - Header'}}]}))


def test_enqueue_survives_cli_absence_and_reuses_identity(tmp_path):
    source = tmp_path/'snapshot.json'
    snapshot(source)
    operation = {'kind': 'create', 'title': 'Review header copy'}
    first = enqueue(source, operation, 'review-header', THREAD, tmp_path)
    assert first['delivery']['state'] == 'pending'
    assert enqueue(source, operation, 'review-header', THREAD, tmp_path) == first
    with pytest.raises(ValueError, match='different work'):
        enqueue(source, {'kind': 'create', 'title': 'Something else'}, 'review-header', THREAD, tmp_path)
    files = list((tmp_path/'task-command-delivery').glob('*/*.json'))
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600


def test_foreign_owner_and_revoked_scope_cannot_enqueue(tmp_path):
    source = tmp_path/'snapshot.json'
    snapshot(source, OTHER)
    with pytest.raises(ValueError, match='Landing - Header'):
        enqueue(source, {'kind': 'complete', 'task_id': 'task'}, 'done', THREAD, tmp_path)
    data = json.loads(source.read_text()); data['connection'] = 'revoked'; source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='revoked'):
        enqueue(source, {'kind': 'create', 'title': 'Work'}, 'create', THREAD, tmp_path)
