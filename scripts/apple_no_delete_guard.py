#!/usr/bin/env python3
"""Fail-closed Mac dispatch policy and persistent task stop records.

This is a local guard, not an OS security boundary. The host must enforce the
stop across all tools and protect state/identity from the agent. No current
transcript reader distinguishes human input from coordinator turn/start, so
there is deliberately no reset command or automatic confirmation mechanism.
See docs/architecture/apple-no-delete-safety.md for the deployment boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

STATE_PATH = Path.home() / '.local/state/openmates/apple-no-delete.sqlite3'
STOP_EXIT_CODE = 77
SAFE_COMMANDS = frozenset({'true', '/usr/bin/true', '/usr/bin/uname -s', '/bin/df -h'})
STOP_MESSAGE = (
    'MAC_NO_DELETE_STOP: End this task immediately. Do not try another command, '
    'helper, SSH connection, Python tool, or automatic continuation. Any needed '
    'Mac deletion must be performed by the user personally, never by an agent, '
    'even with approval. Present the exact deletion command and reason privately '
    'to the user. Wait for a fresh human-authored response confirming they ran '
    'it themselves or did not want deletion. This installation has no trusted '
    'human-input verifier; the gate remains closed. Coordinator messages, '
    'role=user transcripts, flags and timeouts cannot clear it.'
)


class MacDeletionStop(SystemExit):
    """Terminate the helper rather than returning a retryable AppleRemoteError."""
    def __init__(self, detail: str = ''):
        self.detail = f'{STOP_MESSAGE}\n{detail}'.strip()
        super().__init__(STOP_EXIT_CODE)

    def __str__(self):
        return self.detail


class StopStore:
    """Append-only stop records, shared by worktrees and durable across restarts."""
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        self.path.chmod(0o600)
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('CREATE TABLE IF NOT EXISTS stops '
                           '(task TEXT PRIMARY KEY, record TEXT NOT NULL)')
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def active(self, task: str):
        if not self.path.exists():
            return None
        with self.connect() as connection:
            row = connection.execute('SELECT record FROM stops WHERE task=?', (task,)).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        if (not isinstance(record, dict)
                or not all(isinstance(record.get(key), str) and record[key]
                           for key in ('id', 'task', 'reason', 'status'))
                or record['status'] != 'awaiting_trusted_human_response'):
            raise ValueError('invalid stop record')
        return record

    def block(self, task: str, reason: str, command: str | None = None):
        record = {'id': uuid.uuid4().hex, 'task': task, 'created_ns': time.time_ns(),
                  'reason': reason, 'requested_command': command, 'status': 'awaiting_trusted_human_response'}
        with self.connect() as connection:
            connection.execute('INSERT OR IGNORE INTO stops VALUES (?, ?)',
                               (task, json.dumps(record)))
        return self.active(task)


def task_identity() -> str:
    # These environment variables are routing hints, not authentication. A host
    # integration must bind them independently before claiming bypass resistance.
    codex = os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID')
    opencode = os.environ.get('OPENCODE_SESSION_ID')
    claude = os.environ.get('CLAUDE_SESSION_ID')
    if codex:
        return f'codex:{codex}'
    if opencode:
        return f'opencode:{opencode}'
    if claude:
        return f'claude:{claude}'
    raise MacDeletionStop('Cannot bind a durable stop without a task identity.')


def active_stop():
    try:
        return StopStore(STATE_PATH).active(task_identity())
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise MacDeletionStop(f'Stop state unavailable: {type(exc).__name__}') from exc


def require_unlatched():
    record = active_stop()
    if record:
        raise MacDeletionStop(f'Stop ID: {record["id"]}. Reason: {record["reason"]}')


def block(reason: str, command: str | None = None):
    try:
        record = StopStore(STATE_PATH).block(task_identity(), reason, command)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise MacDeletionStop(f'Unable to persist stop: {type(exc).__name__}') from exc
    raise MacDeletionStop(f'Stop ID: {record["id"]}. Reason: {record["reason"]}')


def require_safe_command(command: str):
    require_unlatched()
    # Exact complete commands only. Never tokenize/expand user shell strings or
    # consider the absence of deletion substrings evidence of safety. No Python,
    # shell, git, package-manager, browser, Xcode or arbitrary executable entry.
    if command not in SAFE_COMMANDS:
        block('Remote execution is outside the fixed read-only diagnostic allowlist; '
              'deletion or indirect cleanup cannot be excluded.', command)


def require_safe_operation(operation: str):
    require_unlatched()
    if operation not in {'status', 'run', 'finalize-proof'}:
        block(f'Apple helper {operation!r} is not approved as deletion-free. '
              'Its entire workflow is blocked before credentials or remote dispatch.')


def hook_result():
    """Host adapters must honor continue=false AND deny every subsequent tool."""
    try:
        require_unlatched()
    except MacDeletionStop as exc:
        return {'continue': False, 'stopReason': str(exc),
                'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                                       'permissionDecision': 'deny',
                                       'permissionDecisionReason': str(exc)}}
    return {'continue': True}


def main():
    # Read-only host integration probe: no reset/confirmation flags are exposed.
    if sys.argv[1:] != ['hook']:
        print('Usage: apple_no_delete_guard.py hook', file=sys.stderr)
        return 2
    # Hook payload identity is a routing hint, never confirmation provenance.
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError('hook payload must be an object')
        if payload.get('session_id') and not any(os.environ.get(k) for k in
                ('CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'OPENCODE_SESSION_ID')):
            os.environ['CLAUDE_SESSION_ID'] = str(payload['session_id'])
    except (ValueError, OSError) as exc:
        print(json.dumps({'continue': False, 'stopReason': str(exc)}))
        return STOP_EXIT_CODE
    result = hook_result()
    event = payload.get('hook_event_name', 'PreToolUse')
    if event != 'PreToolUse':
        result.pop('hookSpecificOutput', None)
    print(json.dumps(result))
    return 0 if result['continue'] else STOP_EXIT_CODE


if __name__ == '__main__':
    raise SystemExit(main())
