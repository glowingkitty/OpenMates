"""
Cross-runtime cryptographic vectors for the OpenMates Python SDK.

The SDK consumes the same immutable fixture as the backend, CLI, browser, and
Apple clients. Exact byte matching prevents silent recovery incompatibilities
between independently released clients.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from openmates.chat_completion_recovery import (
    build_recovery_associated_data,
    derive_recovery_keypair,
    open_recovery_envelope,
    seal_recovery_payload,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "tests"
    / "fixtures"
    / "chat_completion_recovery_vectors.json"
)


def _vectors() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["vectors"]


@pytest.mark.parametrize("vector", _vectors(), ids=lambda vector: vector["name"])
def test_python_sdk_matches_shared_recovery_vector(vector: dict) -> None:
    private_key, public_key = derive_recovery_keypair(
        vector["chat_key"],
        vector["chat_id"],
        vector["key_version"],
    )
    assert private_key == vector["recovery_private_key"]
    assert public_key == vector["recovery_public_key"]
    assert build_recovery_associated_data(vector) == vector["associated_data"]

    envelope = seal_recovery_payload(
        vector["plaintext"].encode("utf-8"),
        recovery_public_key=public_key,
        owner_id=vector["owner_id"],
        chat_id=vector["chat_id"],
        turn_id=vector["turn_id"],
        job_id=vector["job_id"],
        assistant_message_id=vector["assistant_message_id"],
        key_version=vector["key_version"],
        ephemeral_private_key=vector["ephemeral_private_key"],
        nonce=vector["nonce"],
    )
    assert envelope == vector["envelope"]
    assert open_recovery_envelope(
        envelope,
        recovery_private_key=private_key,
        owner_id=vector["owner_id"],
        chat_id=vector["chat_id"],
        turn_id=vector["turn_id"],
        job_id=vector["job_id"],
        assistant_message_id=vector["assistant_message_id"],
        key_version=vector["key_version"],
    ) == vector["plaintext"].encode("utf-8")


@pytest.mark.parametrize("field", ["ciphertext", "nonce", "epk"])
def test_python_sdk_rejects_shared_tamper_cases(field: str) -> None:
    vector = _vectors()[0]
    envelope = deepcopy(vector["envelope"])
    encoded = envelope[field]
    envelope[field] = ("A" if encoded[0] != "A" else "B") + encoded[1:]

    with pytest.raises((InvalidTag, ValueError)):
        open_recovery_envelope(
            envelope,
            recovery_private_key=vector["recovery_private_key"],
            owner_id=vector["owner_id"],
            chat_id=vector["chat_id"],
            turn_id=vector["turn_id"],
            job_id=vector["job_id"],
            assistant_message_id=vector["assistant_message_id"],
            key_version=vector["key_version"],
        )
