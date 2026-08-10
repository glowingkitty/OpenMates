#!/usr/bin/env python3
"""Verify cross-client saved-chat completion recovery without live mutation.

This harness models the protocol boundary required before the final cutover gate:
one client preflights a turn, disconnects before terminal persistence, and a
different eligible client opens the sealed recovery job, stores one encrypted
assistant row, and acknowledges deletion of recovery material. It deliberately
uses only shared deterministic crypto and in-memory state so it cannot change the
dev protocol epoch or persist private test data. It is deterministic local
contract evidence only, not evidence of a live-dev takeover.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.shared.python_utils.chat_completion_recovery import (
    derive_recovery_keypair,
    open_recovery_envelope,
)
from backend.shared.python_utils.chat_completion_recovery_job import (
    build_sealed_recovery_job_data,
)


CHAT_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
OWNER_ID = "11111111-1111-4111-8111-111111111111"
OWNER_HASH = "owner-hash"
CHAT_ID = "22222222-2222-4222-8222-222222222222"
TURN_ID = "33333333-3333-4333-8333-333333333333"
PREFLIGHT_ID = "44444444-4444-4444-8444-444444444444"
TASK_ID = "55555555-5555-4555-8555-555555555555"
CHAT_KEY_VERSION = 7
ASSISTANT_CONTENT = "Recovered hello from another client"


@dataclass
class Client:
    name: str
    chat_key: str = CHAT_KEY
    inbox: list[dict[str, Any]] = field(default_factory=list)

    @property
    def recovery_private_key(self) -> str:
        private_key, _public_key = derive_recovery_keypair(
            self.chat_key,
            CHAT_ID,
            CHAT_KEY_VERSION,
        )
        return private_key

    def decrypt_job(self, job: dict[str, Any]) -> dict[str, Any]:
        plaintext = open_recovery_envelope(
            json.loads(str(job["sealed_payload"])),
            recovery_private_key=self.recovery_private_key,
            owner_id=OWNER_ID,
            chat_id=CHAT_ID,
            turn_id=TURN_ID,
            job_id=str(job["job_id"]),
            assistant_message_id=str(job["assistant_message_id"]),
            key_version=CHAT_KEY_VERSION,
        )
        return json.loads(plaintext.decode("utf-8"))

    def persist_assistant(self, payload: dict[str, Any]) -> dict[str, str]:
        if any(message["message_id"] == payload["assistant_message_id"] for message in self.inbox):
            raise AssertionError("assistant completion was already persisted")
        encrypted_content = hashlib.sha256(
            f"{self.chat_key}:{payload['content']}".encode("utf-8")
        ).hexdigest()
        message = {
            "client": self.name,
            "message_id": payload["assistant_message_id"],
            "chat_id": payload["chat_id"],
            "encrypted_content": encrypted_content,
            "role": "assistant",
        }
        self.inbox.append(message)
        return message


@dataclass
class RecoveryBoundary:
    sealed_job: dict[str, Any] | None = None
    terminal_acknowledged: bool = False
    lease_holder: str | None = None

    def preflight(self, recovery_public_key: str) -> dict[str, str]:
        self.sealed_job = build_sealed_recovery_job_data(
            owner_id=OWNER_ID,
            owner_hash=OWNER_HASH,
            chat_id=CHAT_ID,
            turn_id=TURN_ID,
            preflight_id=PREFLIGHT_ID,
            task_id=TASK_ID,
            recovery_public_key=recovery_public_key,
            chat_key_version=CHAT_KEY_VERSION,
            content=ASSISTANT_CONTENT,
            category="ai",
            model_name="test-model",
        )
        return {"state": "PREPARED", "preflight_id": PREFLIGHT_ID}

    def claim(self, client_name: str) -> dict[str, Any]:
        if self.sealed_job is None or self.terminal_acknowledged:
            raise AssertionError("no available recovery job")
        if self.lease_holder is not None:
            raise AssertionError("recovery job is already leased")
        self.lease_holder = client_name
        return dict(self.sealed_job)

    def persist_terminal(self, client_name: str, encrypted_message: dict[str, str]) -> None:
        if self.sealed_job is None or self.terminal_acknowledged:
            raise AssertionError("recovery job was already acknowledged")
        if client_name != self.lease_holder:
            raise AssertionError("stale or missing recovery lease")
        if encrypted_message["message_id"] != self.sealed_job["assistant_message_id"]:
            raise AssertionError("persisted assistant identity changed")
        self.sealed_job = None
        self.terminal_acknowledged = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="mock", choices=("mock", "dev"))
    parser.add_argument("--origin", default="cli", choices=("cli", "web", "apple"))
    parser.add_argument("--recoverer", default="web", choices=("cli", "web", "apple"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.env != "mock":
        raise AssertionError("live dev takeover requires a deployed-client adapter; use --env mock")
    if args.origin == args.recoverer:
        raise AssertionError("origin and recoverer must be different clients")

    origin = Client(args.origin)
    recoverer = Client(args.recoverer)
    boundary = RecoveryBoundary()
    _private_key, public_key = derive_recovery_keypair(CHAT_KEY, CHAT_ID, CHAT_KEY_VERSION)

    ack = boundary.preflight(public_key)
    assert ack == {"state": "PREPARED", "preflight_id": PREFLIGHT_ID}

    origin_disconnected = True
    claimed_job = boundary.claim(recoverer.name)
    recovered_payload = recoverer.decrypt_job(claimed_job)
    reconnected_origin_payload = origin.decrypt_job(claimed_job)
    encrypted_message = recoverer.persist_assistant(recovered_payload)
    boundary.persist_terminal(recoverer.name, encrypted_message)

    origin.inbox.append(encrypted_message)
    assert origin_disconnected is True
    assert recovered_payload["content"] == ASSISTANT_CONTENT
    assert reconnected_origin_payload == recovered_payload
    assert origin.inbox == recoverer.inbox
    assert boundary.sealed_job is None
    assert boundary.terminal_acknowledged is True

    print(json.dumps({
        "boundary": "in_memory_no_live_epoch_state",
        "env": "mock",
        "evidence_scope": "deterministic_local_contract",
        "origin": origin.name,
        "recoverer": recoverer.name,
        "assistant_turns": len(recoverer.inbox),
        "both_clients_opened_same_sealed_payload": True,
        "sealed_job_deleted_after_ack": True,
        "origin_disconnected_before_persist": origin_disconnected,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
