"""Regression tests for human-actionable sessions.py write-claim messages.

Purpose: prevent short internal session IDs from being presented as user-facing
decisions when concurrent agents touch the same file.
Scope: imports scripts/sessions.py only; no repository session state is read.
Privacy: fixtures use synthetic task names, paths, and session IDs.
Run: python3 -m pytest scripts/tests/test_sessions_write_claim_messages.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PY = ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("sessions_write_claim_messages", SESSIONS_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["sessions_write_claim_messages"] = module
    spec.loader.exec_module(module)
    return module


def test_write_claim_conflict_message_is_actionable_not_a_naked_id() -> None:
    sessions = load_sessions_module()

    message = sessions._format_write_claim_conflict(
        "backend/tests/test_example.py",
        "e848",
        {
            "task": "Strengthen epoch-one recovery request-correlation verification",
            "last_active": sessions._now_iso(),
            "zellij_session": "recovery-worker",
            "opencode_session_id": "opencode-session-123",
        },
    )

    assert "manual WRITING claim" in message
    assert "Task: Strengthen epoch-one recovery request-correlation verification" in message
    assert "Agent next step:" in message
    assert "do not ask the user to interpret this id" in message
    assert "diagnostic id: e848" in message
    assert "Wait for that session" not in message
    assert "ownership boundary" not in message
