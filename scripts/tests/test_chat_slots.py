# contract-test-file: tooling
"""Slot rules: daemon spares hold no slot (2026-11-23: waking them created empty chats)."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import claude_idle_chats as lc  # noqa: E402  (path set above)


def test_daemon_spares_hold_no_slot(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    pid = os.getpid()
    (sessions / f"{pid}.json").write_text(json.dumps({
        "pid": pid, "sessionId": "spare1", "procStart": lc._proc_start(pid), "status": "idle", "kind": "bg",
        "spare": True}))
    assert lc.live_chats(tmp_path, dict(lc.DEFAULTS), waiters={}) == []
