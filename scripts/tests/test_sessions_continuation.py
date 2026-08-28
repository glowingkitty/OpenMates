#!/usr/bin/env python3
"""Tests for durable, idempotent OpenCode operation continuations."""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_continuation", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def state():
    return {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_test",
                "modified_files": [],
            }
        }
    }


def install_mutator(monkeypatch, sessions, data):
    def mutate(callback):
        return callback(data)
    monkeypatch.setattr(sessions, "_mutate_sessions", mutate)


def test_record_claim_and_ack_are_idempotent(monkeypatch):
    sessions = load_sessions_module()
    data = state()
    install_mutator(monkeypatch, sessions, data)

    first = sessions._record_session_continuation(
        "ses_test",
        operation_type="deployment_ready",
        operation_key="commit-a",
        next_action="Verify exact commit.",
    )
    repeated = sessions._record_session_continuation(
        "ses_test",
        operation_type="deployment_ready",
        operation_key="commit-a",
        next_action="Verify exact commit.",
    )
    claimed = sessions._claim_session_continuation("ses_test")
    duplicate_claim = sessions._claim_session_continuation("ses_test")
    acknowledged = sessions._finish_session_continuation("ses_test", delivered=True)

    assert first == repeated
    assert claimed["message_id"].startswith("msg_")
    assert duplicate_claim is None
    assert acknowledged["status"] == "delivered"
    assert sessions._claim_session_continuation("ses_test") is None


def test_automatic_message_ids_preserve_opencode_chronological_order(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions.time, "time_ns", lambda: 1_787_947_100_000_000_000)

    message_id = sessions._opencode_ascending_message_id(entropy="stable-operation")

    assert len(message_id) == 30
    assert int(message_id[4:16], 16) == (1_787_947_100_000 * 0x1000 + 1) & ((1 << 48) - 1)
    assert message_id < sessions._opencode_ascending_message_id(
        timestamp_ms=1_787_947_100_001,
        entropy="later-operation",
    )


def test_transport_failure_retries_once_with_new_generation(monkeypatch):
    sessions = load_sessions_module()
    data = state()
    install_mutator(monkeypatch, sessions, data)
    sessions._record_session_continuation(
        "abcd",
        operation_type="health_ready",
        operation_key="health-a",
        next_action="Retry verification.",
    )

    first = sessions._claim_session_continuation("abcd")
    sessions._finish_session_continuation("abcd", delivered=False)
    second = sessions._claim_session_continuation("abcd")
    sessions._finish_session_continuation("abcd", delivered=False)

    assert first["message_id"] != second["message_id"]
    assert sessions._claim_session_continuation("abcd") is None
    assert data["sessions"]["abcd"]["continuation"]["status"] == "failed"


def test_new_tool_can_cancel_only_ready_continuation(monkeypatch):
    sessions = load_sessions_module()
    data = state()
    install_mutator(monkeypatch, sessions, data)
    sessions._record_session_continuation(
        "abcd",
        operation_type="resource_ready",
        operation_key="vercel",
        next_action="Continue deploy.",
    )

    assert sessions._cancel_session_continuation("abcd") is True
    assert sessions._cancel_session_continuation("abcd") is False
    assert data["sessions"]["abcd"]["continuation"]["status"] == "cancelled"
