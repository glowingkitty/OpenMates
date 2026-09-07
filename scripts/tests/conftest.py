"""Isolate Apple remote safety tests from real agent state.

Existing Apple tests import the transport dynamically and may inject only the
runner. Every Apple transport test must also receive local temporary stop
storage and a synthetic task identity. This prevents a fake transport test from
latching a real chat. It does not add an environment bypass to production code.
"""
from pathlib import Path

import pytest


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
    monkeypatch.delenv('OPENCODE_SESSION_ID', raising=False)
