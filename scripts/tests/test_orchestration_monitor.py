"""Regression checks for real orchestration stop and restart failures.

Use a fake clock and in-memory session state, with no live chat prompts.
Exercise due-time and existing continuation interaction through sessions.py.
These tests never alter shared runtime or user Tasks.
"""
# contract-test-file: tooling
import json
from argparse import Namespace

import pytest
from test_sessions_continuation import load_sessions_module, install_mutator, state


def setup(monkeypatch, now='2026-09-07T14:00:00Z'):
    sessions = load_sessions_module()
    data = state()
    install_mutator(monkeypatch, sessions, data)
    monkeypatch.setattr(sessions, '_load_sessions', lambda: data)
    monkeypatch.setattr(sessions, '_now_iso', lambda: now)
    return sessions, data, data['sessions']['abcd']


def register(sessions, owner, worker='ses_worker', start='2026-09-07T14:00:00Z'):
    return sessions.orchestration_monitor.register(owner, worker, start, '2026-09-07T23:00:00Z', start)


def test_due_cadence_independent_workers_and_no_early_prompt(monkeypatch):
    s, _, owner = setup(monkeypatch)
    register(s, owner)
    register(s, owner, 'ses_later', '2026-09-07T14:03:00Z')
    assert s.orchestration_monitor.prepare(owner, '2026-09-07T14:04:59Z') is None
    record = s.orchestration_monitor.prepare(owner, '2026-09-07T14:05:00Z')
    assert list(record['monitor_workers']) == ['ses_worker']
    for now, expected in [('14:05', '14:10'), ('14:10', '14:15'), ('14:15', '14:20'), ('14:20', '14:40'), ('14:40', '15:00')]:
        item = owner['orchestration_monitor']['workers']['ses_worker']
        s.orchestration_monitor.acknowledge(owner, {'monitor_workers': {'ses_worker': item['next_due']}}, f'2026-09-07T{now}:00Z')
        assert item['next_due'] == f'2026-09-07T{expected}:00Z'


def test_restart_retains_schedule_and_coalesces_missed_checks(monkeypatch):
    s, _, owner = setup(monkeypatch)
    register(s, owner)
    recovered = json.loads(json.dumps(owner))
    record = s.orchestration_monitor.prepare(recovered, '2026-09-07T14:57:00Z')
    assert record is not None
    assert s.orchestration_monitor.prepare(recovered, '2026-09-07T14:57:00Z') is None
    s.orchestration_monitor.acknowledge(recovered, record, '2026-09-07T14:57:00Z')
    assert recovered['orchestration_monitor']['workers']['ses_worker']['next_due'] == '2026-09-07T15:00:00Z'


def test_user_turn_cancel_does_not_remove_future_schedule(monkeypatch):
    s, _, owner = setup(monkeypatch)
    register(s, owner)
    s.orchestration_monitor.prepare(owner, '2026-09-07T14:05:00Z')
    assert s._cancel_session_continuation('abcd')
    assert s.orchestration_monitor.active(owner, '2026-09-07T14:06:00Z')
    assert s.orchestration_monitor.prepare(owner, '2026-09-07T14:06:00Z')


@pytest.mark.parametrize('stop', [True, False])
def test_explicit_stop_and_nightly_expiry_cancel_pending_delivery(monkeypatch, stop):
    s, _, owner = setup(monkeypatch)
    register(s, owner)
    s.orchestration_monitor.prepare(owner, '2026-09-07T14:05:00Z')
    if stop:
        s.orchestration_monitor.stop(owner)
    assert s.orchestration_monitor.prepare(owner, '2026-09-07T23:00:00Z') is None
    assert owner['continuation']['status'] == 'cancelled'


def test_other_continuation_is_not_overwritten(monkeypatch):
    s, _, owner = setup(monkeypatch)
    register(s, owner)
    owner['continuation'] = {'operation_type': 'task_ready', 'status': 'ready'}
    assert s.orchestration_monitor.prepare(owner, '2026-09-07T14:05:00Z') is None
    assert owner['continuation']['operation_type'] == 'task_ready'


def test_monitor_retry_keeps_message_id_and_ack_advances_once(monkeypatch):
    s, _, owner = setup(monkeypatch, '2026-09-07T14:05:00Z')
    register(s, owner)
    s.orchestration_monitor.prepare(owner, s._now_iso())
    first = s._claim_session_continuation('abcd')
    assert s._claim_session_continuation('abcd') is None
    s._finish_session_continuation('abcd', delivered=False)
    second = s._claim_session_continuation('abcd')
    assert first['message_id'] == second['message_id']
    s._finish_session_continuation('abcd', delivered=True)
    s._finish_session_continuation('abcd', delivered=True)
    assert owner['orchestration_monitor']['workers']['ses_worker']['next_due'] == '2026-09-07T14:10:00Z'


def test_uncertain_delivery_survives_restart(monkeypatch):
    s, _, owner = setup(monkeypatch, '2026-09-07T14:05:00Z')
    register(s, owner)
    s.orchestration_monitor.prepare(owner, s._now_iso())
    first = s._claim_session_continuation('abcd')
    monkeypatch.setattr(s, '_now_iso', lambda: '2026-09-07T14:06:01Z')
    second = s._claim_session_continuation('abcd')
    assert first['message_id'] == second['message_id']


def test_idempotent_registration_does_not_reset_cadence(monkeypatch):
    s, _, owner = setup(monkeypatch)
    register(s, owner)
    owner['orchestration_monitor']['workers']['ses_worker']['next_due'] = '2026-09-07T14:40:00Z'
    register(s, owner)
    assert owner['orchestration_monitor']['workers']['ses_worker']['next_due'] == '2026-09-07T14:40:00Z'


def test_rejects_unbounded_or_ambiguous_schedule(monkeypatch):
    s, _, owner = setup(monkeypatch)
    with pytest.raises(RuntimeError):
        s.orchestration_monitor.register(owner, 'ses_worker', '2026-09-07T14:00:00', '2026-09-07T23:00:00Z', s._now_iso())
    with pytest.raises(RuntimeError):
        s.orchestration_monitor.register(owner, 'ses_worker', s._now_iso(), '2026-10-07T23:00:00Z', s._now_iso())


def test_active_coordinator_cannot_be_blocked_or_finished(monkeypatch):
    s, _, owner = setup(monkeypatch)
    register(s, owner)
    for payload in [{'action': 'block'}, {'action': 'done'}, {'action': 'edit', 'status': 'blocked'}]:
        with pytest.raises(RuntimeError, match='Coordinator monitoring is active'):
            s._openmates_task_tool('ses_test', payload, cli_runner=lambda _: pytest.fail('No mutation allowed'))


def test_new_day_registration_discards_expired_workers(monkeypatch):
    s, _, owner = setup(monkeypatch)
    register(s, owner)
    s.orchestration_monitor.register(owner, 'ses_today', '2026-09-08T09:00:00Z',
        '2026-09-08T23:00:00Z', '2026-09-08T09:00:00Z')
    assert list(owner['orchestration_monitor']['workers']) == ['ses_today']


def test_removing_worker_cancels_stale_pending_checkpoint(monkeypatch, capsys):
    s, _, owner = setup(monkeypatch, '2026-09-07T14:05:00Z')
    register(s, owner)
    register(s, owner, 'ses_other')
    s.orchestration_monitor.prepare(owner, s._now_iso())
    s.cmd_monitor(Namespace(session='abcd', monitor_action='remove', worker='ses_worker'))
    record = s.orchestration_monitor.prepare(owner, s._now_iso())
    assert list(record['monitor_workers']) == ['ses_other']


def test_managed_restart_holds_wakeups_until_resume_verified(monkeypatch, tmp_path):
    s, _, owner = setup(monkeypatch, '2026-09-07T14:05:00Z')
    register(s, owner)
    s.orchestration_monitor.prepare(owner, s._now_iso())
    monkeypatch.setattr(s, '_opencode_api_json', lambda _: {})
    manifest = tmp_path / 'restart.json'
    s.capture_opencode_restart_manifest(manifest)
    assert owner['orchestration_monitor']['restart_manifest'] == str(manifest)
    assert s._claim_session_continuation('abcd') is None
    s.resume_opencode_restart_manifest(manifest)
    assert 'restart_manifest' not in owner['orchestration_monitor']
    assert s._claim_session_continuation('abcd') is not None
