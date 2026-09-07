"""Repository-scope policy regression evidence with isolated Linux fixtures.

No test connects to the Mac or deletes a Mac file. Fixtures prove realpath
boundaries, protected originals, root/origin verification and policy history.
Native enforcement is separately queried without attempting outside deletion.
The explicit v1 transition must never become a general acknowledgement flag.
"""
# contract-test-file: tooling
import json

import pytest


@pytest.fixture(autouse=True)
def policy_module(isolate_apple_stop_state):
    global policy
    import _apple_repository_policy as policy


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / 'openmates-marketing'
    (root / '.git').mkdir(parents=True)
    (root / '.git/config').write_text('[remote "origin"]\nurl = ' + policy.ORIGINS['openmates-marketing'])
    project = root / 'videos/remotion'
    (project / 'input-media/originals').mkdir(parents=True)
    (project / 'input-media/originals/clip.mov').write_text('original')
    return root, project


def test_verified_roots_and_absent_clone_target(checkout):
    root, project = checkout
    scope = policy.workspace(project)
    assert scope['roots'] == [root]
    assert scope['app'] == root.parent / 'OpenMates'


@pytest.mark.parametrize('target', ['.', '..', '../openmates-marketing-extra/file', 'videos/remotion/input-media/originals/clip.mov'])
def test_roots_parents_prefix_collisions_and_originals_refused(checkout, target):
    root, project = checkout
    scope = policy.workspace(project)
    with pytest.raises(policy.ScopeError):
        policy.require_descendant(root / target, scope['roots'], scope['protected'])


def test_symlink_escape_and_recursive_path_refused(checkout, tmp_path):
    root, project = checkout
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'file').write_text('outside')
    (root / 'escape').symlink_to(outside, target_is_directory=True)
    scope = policy.workspace(project)
    with pytest.raises(policy.ScopeError):
        policy.require_descendant(root / 'escape/file', scope['roots'], scope['protected'])
    assert policy.require_descendant(root / 'generated/cache/file', scope['roots']) == root / 'generated/cache/file'


def test_wrong_origin_or_symlink_checkout_is_not_authorized(checkout):
    root, project = checkout
    app = root.parent / 'OpenMates'
    app.symlink_to(root, target_is_directory=True)
    with pytest.raises(policy.ScopeError):
        policy.workspace(project)
    (root / '.git/config').write_text('[remote "origin"]\nurl = https://github.com/other/repo.git')
    with pytest.raises(policy.ScopeError):
        policy.verify_checkout(root, 'openmates-marketing')


def test_profile_denies_outside_and_roots_but_not_all_unlinks(checkout):
    root, project = checkout
    scope = policy.workspace(project)
    profile = policy.profile(scope['roots'], scope['protected'])
    assert '(require-not (require-any (subpath ' in profile
    assert '(literal ' + json.dumps(str(root)) + ')' in profile
    assert '(deny file-write*' in profile
    assert '(with send-signal SIGKILL)' in profile


def test_named_policy_transition_preserves_original_record_and_new_stop(tmp_path):
    import apple_no_delete_guard as guard
    store = guard.StopStore(tmp_path / 'history.sqlite3')
    old = {'id': policy.SUPERSEDED_STOP, 'task': policy.SUPERSEDED_TASK, 'reason': 'legacy browser stop',
           'status': 'awaiting_trusted_human_response'}
    with store.connect() as db:
        db.execute('INSERT INTO stops VALUES (?, ?)', (policy.SUPERSEDED_TASK, json.dumps(old)))
    assert store.active(policy.SUPERSEDED_TASK) is None
    with store.connect() as db:
        assert json.loads(db.execute('SELECT record FROM stops WHERE task=?', (policy.SUPERSEDED_TASK,)).fetchone()[0]) == old
        transition = json.loads(db.execute('SELECT record FROM policy_transitions').fetchone()[0])
        assert transition['authority']['manual_deletion_performed'] is False
    new = store.block(policy.SUPERSEDED_TASK, 'outside v2 roots')
    assert new['policy_version'] == policy.POLICY_VERSION
    assert store.active(policy.SUPERSEDED_TASK)['id'] == new['id']


def test_other_legacy_stops_not_implicitly_cleared(tmp_path):
    import apple_no_delete_guard as guard
    store = guard.StopStore(tmp_path / 'stops.sqlite3')
    old = {'id': 'other-stop', 'task': 'other-task', 'reason': 'outside', 'status': 'awaiting_trusted_human_response'}
    with store.connect() as db:
        db.execute('INSERT INTO stops VALUES (?, ?)', ('other-task', json.dumps(old)))
    assert store.active('other-task') == old


def test_named_diagnostic_reads_without_clearing_or_admitting_render(monkeypatch):
    import apple_no_delete_guard as guard
    record = {'id': '0ba26b6a94cd43c3a189c2150e52430c', 'reason': 'unexplained native signal'}
    monkeypatch.setattr(guard, 'active_stop', lambda: record)
    monkeypatch.setattr(guard, 'task_identity', lambda: policy.SUPERSEDED_TASK)
    guard.require_safe_operation('render-diagnostic')
    guard.require_safe_command(guard.diagnostic_command())
    assert '(deny file-write*)' in guard.diagnostic_command()
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command(guard.remotion_command())
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_command(guard.diagnostic_command() + ' extra')
    record['id'] = 'another-stop'
    with pytest.raises(guard.MacDeletionStop):
        guard.require_safe_operation('render-diagnostic')
