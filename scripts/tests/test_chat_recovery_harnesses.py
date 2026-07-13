#!/usr/bin/env python3
"""Regression tests for the deterministic chat-recovery evidence harnesses.

These tests keep the local evidence scripts honest: recovery must require a
lease and remove the sealed job only after terminal acknowledgement, while the
latency harness must preserve the preflight-before-enqueue ordering contract.
All fixtures are synthetic and never contact a deployment.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.measure_chat_preflight_latency import InMemoryDurableBoundary, nearest_rank_p95
from scripts.test_cross_client_chat_recovery import (
    ASSISTANT_CONTENT,
    CHAT_ID,
    CHAT_KEY,
    CHAT_KEY_VERSION,
    Client,
    RecoveryBoundary,
    derive_recovery_keypair,
)


ROOT = Path(__file__).resolve().parents[2]
TAKEOVER_SCRIPT = ROOT / "scripts" / "test_cross_client_chat_recovery.py"
LATENCY_SCRIPT = ROOT / "scripts" / "measure_chat_preflight_latency.py"


def test_cross_client_recovery_persists_once_then_removes_sealed_job() -> None:
    origin = Client("cli")
    recoverer = Client("web")
    boundary = RecoveryBoundary()
    _private_key, public_key = derive_recovery_keypair(CHAT_KEY, CHAT_ID, CHAT_KEY_VERSION)

    boundary.preflight(public_key)
    job = boundary.claim(recoverer.name)
    payload = recoverer.decrypt_job(job)
    encrypted_message = recoverer.persist_assistant(payload)
    boundary.persist_terminal(recoverer.name, encrypted_message)
    origin.inbox.append(encrypted_message)

    assert payload["content"] == ASSISTANT_CONTENT
    assert origin.inbox == recoverer.inbox
    assert boundary.sealed_job is None
    assert boundary.terminal_acknowledged is True
    with pytest.raises(AssertionError, match="no available recovery job"):
        boundary.claim("apple")


def test_cross_client_recovery_rejects_terminal_write_without_lease() -> None:
    boundary = RecoveryBoundary()
    _private_key, public_key = derive_recovery_keypair(CHAT_KEY, CHAT_ID, CHAT_KEY_VERSION)
    boundary.preflight(public_key)

    with pytest.raises(AssertionError, match="stale or missing recovery lease"):
        boundary.persist_terminal("web", {"message_id": "not-the-claimed-job"})


def test_cross_client_recovery_rejects_duplicate_claim_and_persistence() -> None:
    recoverer = Client("web")
    boundary = RecoveryBoundary()
    _private_key, public_key = derive_recovery_keypair(CHAT_KEY, CHAT_ID, CHAT_KEY_VERSION)
    boundary.preflight(public_key)
    job = boundary.claim(recoverer.name)

    with pytest.raises(AssertionError, match="already leased"):
        boundary.claim("apple")

    payload = recoverer.decrypt_job(job)
    recoverer.persist_assistant(payload)
    with pytest.raises(AssertionError, match="already persisted"):
        recoverer.persist_assistant(payload)


def test_latency_boundary_rejects_enqueue_before_preflight() -> None:
    boundary = InMemoryDurableBoundary()
    turn_id = "33333333-3333-4333-8333-333333333333"

    with pytest.raises(AssertionError, match="cannot enqueue before preflight"):
        boundary.enqueue_inference(turn_id)

    boundary.prepare_preflight(turn_id)
    boundary.enqueue_inference(turn_id)
    assert len(boundary.outbox) == 1


def test_nearest_rank_p95_uses_the_ninety_fifth_observation() -> None:
    assert nearest_rank_p95([float(index) for index in range(1, 21)]) == 19.0


def test_mock_latency_harness_rejects_nonserial_concurrency() -> None:
    result = subprocess.run(
        [sys.executable, str(LATENCY_SCRIPT), "--env", "mock", "--concurrency", "2"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "runs serially" in result.stderr


@pytest.mark.parametrize("script", [TAKEOVER_SCRIPT, LATENCY_SCRIPT])
def test_harnesses_reject_dev_evidence_without_a_live_adapter(script: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(script), "--env", "dev"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "requires a deployed" in result.stderr
