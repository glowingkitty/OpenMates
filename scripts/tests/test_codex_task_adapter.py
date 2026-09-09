"""Task event routing contracts using isolated snapshots and a synthetic daemon.

No live thread or account is created. Lost acceptance must never become a second
start, and routine Task activity must never become a coordinator wakeup.
Real app-server behavior remains an explicit opt-in runtime pilot gate.
"""
import json
import pytest
from scripts import codex_task_adapter as adapter
from scripts import codex_orchestration as legacy

OWNER = '00000000-0000-0000-0000-000000000001'
PARENT = '00000000-0000-0000-0000-000000000002'


def task(status='blocked', version=1):
    return {'task_id': 'task', 'title': 'Header', 'status': status, 'version': version,
            'blocked_reason_code': 'external_dependency' if status == 'blocked' else None, 'blocked_reason': '',
            'external_chat': {'provider': 'codex', 'id': OWNER}, 'scope': ['api', 'account', 'personal'],
            'dependencies': [{'target_kind': 'task', 'target_status': 'done'}]}


class RPC:
    def __init__(self, active=False, lost=False):
        self.calls = []; self.active = active; self.lost = lost
    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/read':
            return {'thread': {'status': {'type': 'active' if self.active else 'idle'}}}
        if method == 'thread/items/list':
            return {'data': [], 'nextCursor': None}
        if self.lost: raise TimeoutError('response lost')
        return {'turn': {'id': 'accepted-turn'}}


def ready_state():
    state = adapter.empty_state()
    adapter.observe_tasks(state, {'key': task()}, {OWNER})
    tasks = {'key': task('todo', 2)}
    adapter.observe_tasks(state, tasks, {OWNER})
    return state, tasks


def test_routine_activity_is_silent_and_ready_event_is_owner_bound_and_deduplicated():
    state, tasks = ready_state()
    adapter.observe_tasks(state, tasks, {OWNER})
    assert len(state['deliveries']) == 1
    event = next(iter(state['deliveries'].values()))
    assert event['owner'] == OWNER and event['kind'] == 'dependency_ready'
    tasks['key']['latest_activity'] = 'still reviewing'
    adapter.observe_tasks(state, tasks, {OWNER})
    assert len(state['deliveries']) == 1


def test_active_or_paused_worker_does_not_start_another_turn():
    state, tasks = ready_state()
    rpc = RPC(active=True)
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert [method for method, _ in rpc.calls] == ['thread/read']
    state['threads'][OWNER]['paused'] = True
    rpc.calls.clear()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert rpc.calls == []


def test_lost_start_response_is_reconciled_without_retrying_start():
    state, tasks = ready_state()
    rpc = RPC(lost=True)
    saved = []
    with pytest.raises(TimeoutError):
        adapter.deliver(state, rpc, {OWNER}, True, lambda: saved.append(json.loads(json.dumps(state))), tasks)
    assert next(iter(saved[-1]['deliveries'].values()))['state'] == 'uncertain'
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert len([m for m, _ in rpc.calls if m == 'turn/start']) == 1
    assert next(iter(state['deliveries'].values()))['state'] == 'needs_review'


def test_superseded_ownership_or_status_cannot_resume_old_work():
    state, tasks = ready_state()
    tasks['key']['status'] = 'done'
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert rpc.calls == []
    assert next(iter(state['deliveries'].values()))['state'] == 'superseded'


def test_parent_only_receives_completed_work_not_each_worker_turn():
    state = adapter.empty_state()
    message = {'method': 'turn/completed', 'params': {'threadId': OWNER, 'turn': {'id': 'turn', 'status': 'completed'}}}
    adapter.observe_notification(state, message, {OWNER, PARENT}, {OWNER: PARENT}, {'key': task('in_progress')})
    assert not state['deliveries']
    adapter.observe_notification(state, message, {OWNER, PARENT}, {OWNER: PARENT}, {'key': task('done')})
    assert next(iter(state['deliveries'].values()))['owner'] == PARENT


def test_only_confirmed_delete_of_registered_chat_enqueues_unlink():
    state = adapter.empty_state(); adapter.observe_tasks(state, {'key': task()}, {OWNER})
    for method in ['thread/archived', 'thread/unloaded', 'thread/status/changed']:
        adapter.observe_notification(state, {'method': method, 'params': {'threadId': OWNER}}, {OWNER}, {}, {})
    assert not state['deliveries']
    adapter.observe_notification(state, {'method': 'thread/deleted', 'params': {'threadId': PARENT}}, {OWNER}, {}, {})
    assert not state['deliveries']
    adapter.observe_notification(state, {'method': 'thread/deleted', 'params': {'threadId': OWNER}}, {OWNER}, {}, {})
    assert next(iter(state['deliveries'].values()))['kind'] == 'chat_deleted'
    assert state['threads'][OWNER]['paused']


def test_migrated_old_observer_cannot_read_or_start_threads(tmp_path):
    path = tmp_path/'state.json'
    with legacy.transaction(path) as state:
        state.update(enabled=True, adapter_mode='task_cache', coordinator=PARENT)
    rpc = RPC()
    legacy.observe_tick(path, rpc)
    legacy.deliver(path, rpc)
    assert rpc.calls == []


def test_all_chat_context_does_not_let_another_device_execute_the_same_task(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter.socket, "gethostname", lambda: "dev-server")
    path=tmp_path/'.claude/sessions.json'; path.parent.mkdir()
    path.write_text(json.dumps({'sessions': {
        'local': {'codex_task_id': OWNER, 'codex_host': 'dev-server', 'worktree': {'path': str(tmp_path/'worker'), 'status': 'active'}},
        'remote': {'codex_task_id': PARENT, 'codex_host': 'laptop', 'worktree': {'path': str(tmp_path/'other'), 'status': 'active'}}}}))
    assert adapter.execution_threads(tmp_path, {'all_threads': True}) == {OWNER}
    assert adapter.execution_threads(tmp_path, {}) == set()


def test_parent_completion_survives_task_sync_arriving_after_turn_event():
    state=adapter.empty_state()
    message={'method': 'turn/completed', 'params': {'threadId': OWNER, 'turn': {'id': 'turn', 'status': 'completed'}}}
    adapter.observe_notification(state, message, {OWNER,PARENT}, {OWNER:PARENT}, {'key':task('in_progress')})
    assert not state['deliveries']
    tasks={'key':task('done',2)}
    adapter.observe_worker_completion(state, {OWNER:PARENT}, tasks, {OWNER,PARENT})
    assert len(state['deliveries']) == 1
    tasks['key']['title']='Minor title edit'; tasks['key']['version']=3
    adapter.observe_worker_completion(state, {OWNER:PARENT}, tasks, {OWNER,PARENT})
    assert len(state['deliveries']) == 1


def test_subscription_batches_metadata_and_recovers_interruption_without_inference():
    class ResumeRPC:
        def __init__(self): self.calls=[]
        def call(self, method, params):
            self.calls.append((method,params))
            return {'thread': {'status': {'type':'idle'}}, 'initialTurnsPage': {'data':[{'id':'turn','status':'interrupted','completedAt':100}]}}
    rpc=ResumeRPC(); state=adapter.empty_state()
    adapter.subscribe_thread(rpc,state,OWNER)
    assert [method for method,_ in rpc.calls] == ['thread/resume']
    assert rpc.calls[0][1]['excludeTurns'] is True
    assert rpc.calls[0][1]['initialTurnsPage']['itemsView'] == 'notLoaded'
    assert state['threads'][OWNER]['paused']



def test_new_active_turn_cannot_reuse_previous_completion_to_wake_parent():
    state=adapter.empty_state()
    adapter.observe_notification(state, {'method':'turn/completed','params':{'threadId':OWNER,'turn':{'id':'old','status':'completed'}}}, {OWNER,PARENT}, {OWNER:PARENT}, {'key':task('in_progress')})
    adapter.observe_notification(state, {'method':'thread/status/changed','params':{'threadId':OWNER,'status':{'type':'active'}}}, {OWNER,PARENT}, {OWNER:PARENT}, {})
    adapter.observe_worker_completion(state, {OWNER:PARENT}, {'key':task('done',2)}, {OWNER,PARENT})
    assert not state['deliveries']


def test_title_edit_does_not_discard_still_ready_dependency():
    state,tasks=ready_state()
    tasks['key']['version'] += 1
    tasks['key']['title']='Clearer title'
    rpc=RPC()
    adapter.deliver(state,rpc,{OWNER},True,lambda:None,tasks)
    assert len([method for method,_ in rpc.calls if method=='turn/start']) == 1
