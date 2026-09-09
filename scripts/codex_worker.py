"""Visible Codex worker dispatch through the installed app-server protocol.

Use when a remote coordinator lacks desktop create/message tools. Explicit user
approval for worker creation and Full Access remains required. Stable operation
IDs prevent duplicate launches after lost replies; uncertain intents need review.
OpenMates CLI still owns all Task writes. This command only controls Codex chats.
No background observer, transcript scan, private database edit or model override.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.codex_rpc import CodexRPC
from scripts.codex_orchestration import canonical_root, new_worker, state_path, transaction
from scripts.codex_cached_context import _save, configuration


def dispatch(rpc, record, intent, save, register):
    """Never automatically retry an invocation with an uncertain remote outcome."""
    digest = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
    if record:
        if record.get('digest') != digest:
            raise ValueError('Operation ID already belongs to different input')
        return record
    record.update(digest=digest, state='pending')
    save(record)
    permissions = {'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'dangerFullAccess'}} if intent['full_access'] else {}
    try:
        thread = intent.get('thread')
        if intent['action'] == 'create':
            args = {'cwd': intent['root'], 'ephemeral': False}
            if intent['full_access']:
                args.update(approvalPolicy='never', sandbox='danger-full-access')
            result = rpc.call('thread/start', args)
            thread = result['thread']['id']
            record.update(thread_id=thread, state='created')
            save(record)
            rpc.call('thread/name/set', {'threadId': thread, 'name': intent['title']})
            register(thread)
        else:
            record['thread_id'] = thread
        record['state'] = 'dispatching'
        save(record)
        result = rpc.call('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': intent['prompt']}], **permissions})
        record.update(state='accepted', turn_id=result['turn']['id'])
    except Exception as error:
        record.update(state='needs_review', error=str(error))
        save(record)
        raise
    save(record)
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['create', 'message', 'receipt'])
    p.add_argument('--session', required=True)
    p.add_argument('--operation', required=True, help='Stable name for this one dispatch; reuse to inspect, never duplicate')
    p.add_argument('--prompt-file', type=Path)
    p.add_argument('--thread')
    p.add_argument('--title')
    p.add_argument('--task', help='Existing OpenMates Task ID for worker registry; does not claim it')
    p.add_argument('--full-access', action='store_true', help='Only with explicit user authorization; applies to this and subsequent turns')
    a = p.parse_args()
    root = canonical_root(Path.cwd())
    directory = state_path(root, a.session).parent / 'dispatch'
    key = hashlib.sha256(a.operation.encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (key + '.json')
    import fcntl
    with (directory / (key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = json.loads(path.read_text()) if path.exists() else {}
        if a.action == 'receipt':
            print(json.dumps(record or {'state': 'not_found'})); return
        if not a.prompt_file:
            p.error('--prompt-file is required')
        owner = os.environ.get('CODEX_THREAD_ID', '')
        uuid.UUID(owner)
        if a.action == 'create' and (not a.title or not a.task):
            p.error('create requires --title and --task')
        if a.action == 'message':
            uuid.UUID(a.thread or '')
        prompt = a.prompt_file.read_text()
        if not prompt.strip():
            p.error('Prompt must not be empty')
        intent = dict(action=a.action, root=str(root), owner=owner, thread=a.thread, title=a.title, task=a.task, prompt=prompt, full_access=a.full_access)
        def register(thread):
            with transaction(state_path(root, a.session)) as state:
                if state.get('coordinator') not in (None, owner):
                    raise ValueError('Session registry belongs to another coordinator')
                state.update(coordinator=owner, enabled=True, adapter_mode='task_cache')
                state['workers'][thread] = new_worker(thread, a.task, a.title, time.time())
            config = configuration(root, owner)
            if not config or not config.get('snapshots'):
                raise ValueError('Task cache configuration is missing')
            subprocess.run([sys.executable, str(root / 'scripts/codex_cached_context.py'),
                'configure', '--repository', str(root), '--thread', owner,
                '--snapshot', config['snapshots'][0], '--session', a.session],
                check=True, capture_output=True, text=True)
        if a.action == 'create' and not configuration(root, owner):
            raise ValueError('Configure the Task cache before creating workers')
        # Check registry before remote creation; do not create an orphan on known conflict.
        registry = state_path(root, a.session)
        if registry.exists() and json.loads(registry.read_text()).get('coordinator') not in (None, owner):
            raise ValueError('Session registry belongs to another coordinator')
        with CodexRPC() as rpc:
            result = dispatch(rpc, record, intent, lambda value: _save(path, value), register)
        print(json.dumps({k: result[k] for k in ('state', 'thread_id', 'turn_id', 'error') if k in result}))
        if result.get('state') != 'accepted':
            raise SystemExit(2)


if __name__ == '__main__':
    main()
