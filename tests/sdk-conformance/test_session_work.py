"""Independently validate the shared synthetic encrypted-work peer."""

# contract-test-file: tooling
from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from recovery_server import encrypt
from session_work_server import CAPABILITY, WorkPeer


def peer(team=False):
    suite = json.loads(
        (Path(__file__).with_name("fixtures") / "session-work.json").read_bytes()
    )["capabilities"][CAPABILITY]
    vector = next(
        v
        for v in suite["vectors"]
        if v.get("family") == "tasks" and v.get("team") is team
    )
    return WorkPeer(suite, vector, "rust")


def task_payload(target):
    key = bytes(range(64, 96))
    wrapping = target.team if target.vector.get("team") else target.master
    payload = {
        "task_id": "11111111-1111-4111-8111-111111111111",
        "encrypted_task_key": encrypt(key, wrapping),
        "encrypted_title": encrypt(b"Synthetic private Task", key),
        "encrypted_description": encrypt(b"Synthetic client-only description", key),
        "encrypted_labels": encrypt(b'["private"]', key),
        "due_at": 2000000000,
        "assignee_type": "user",
    }
    if target.vector.get("team"):
        import hashlib

        payload["key_wrappers"] = [
            {
                "key_type": "team",
                "team_key_epoch": 1,
                "hashed_team_id": hashlib.sha256(
                    target.suite["team"]["team_id"].encode()
                ).hexdigest(),
                "encrypted_task_key": payload["encrypted_task_key"],
            }
        ]
    return payload


def test_peer_rejects_plaintext_and_wrong_scope_before_accepting_create():
    for team in (False, True):
        target = peer(team)
        try:
            payload = task_payload(target)
            altered = deepcopy(payload)
            altered["title"] = "Synthetic private Task"
            with pytest.raises(AssertionError):
                target.validate_create("tasks", altered, json.dumps(altered))
            if team:
                altered = deepcopy(payload)
                altered["key_wrappers"][0]["hashed_team_id"] = "0" * 64
                with pytest.raises(AssertionError):
                    target.validate_create("tasks", altered, json.dumps(altered))
            target.validate_create("tasks", payload, json.dumps(payload))
            assert "encrypted-private-fields" in target.checks
        finally:
            target.server.server_close()


def test_peer_authenticates_payload_ciphertext_and_independent_key_wrapping():
    target = peer()
    try:
        payload = task_payload(target)
        key = base64.b64decode(target.suite["account"]["master_key"])
        payload["encrypted_title"] = encrypt(b"Synthetic private Task", key)
        with pytest.raises(AssertionError, match="ciphertext fingerprint"):
            target.validate_create("tasks", payload, json.dumps(payload))
        raw = bytearray(
            base64.b64decode(encrypt(b"Synthetic private Task", bytes(range(64, 96))))
        )
        raw[-1] ^= 1
        payload["encrypted_title"] = base64.b64encode(raw).decode()
        with pytest.raises(InvalidTag):
            target.validate_create("tasks", payload, json.dumps(payload))
        assert "encrypted-private-fields" not in target.checks
    finally:
        target.server.server_close()
