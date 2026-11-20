"""Isolate Apple remote safety tests from real agent state.

Existing Apple tests import the transport dynamically and may inject only the
runner. Every Apple transport test must also receive local temporary stop
storage and a synthetic task identity. This prevents a fake transport test from
latching a real chat. It does not add an environment bypass to production code.
"""
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_claude_conversation_identity(monkeypatch):
    """Keep the running Claude conversation ID out of tests that set their own identity."""
    for name in ('CLAUDE_CODE_SESSION_ID', 'CLAUDE_SESSION_ID'):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolate_chat_lifecycle_state(tmp_path, monkeypatch):
    """Real-test runners take the dev test lock (dev_test_lock.py); keep it and waiters out of real state."""
    monkeypatch.setenv('OPENMATES_CHAT_LIFECYCLE_DIR', str(tmp_path / 'chat-lifecycle'))
    import sys
    lock = sys.modules.get('dev_test_lock')
    if lock is not None:
        monkeypatch.setattr(lock, '_held', {})


@pytest.fixture(autouse=True)
def isolate_apple_stop_state(request, tmp_path, monkeypatch):
    name = request.node.path.name
    if not (name.startswith('test_apple_remote') or name == 'test_apple_no_delete_guard.py'):
        return
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    import apple_no_delete_guard
    monkeypatch.setattr(apple_no_delete_guard, 'STATE_PATH', tmp_path / 'apple-stops.sqlite3')
    monkeypatch.setenv('CODEX_THREAD_ID', 'isolated-apple-test')
    monkeypatch.setenv('CODEX_SESSION_ID', 'isolated-apple-test')
