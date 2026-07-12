"""
Shared immutable cryptographic vectors for chat completion recovery.

These tests pin the byte-level HKDF, X25519, associated-data, and AES-GCM
contract consumed by every OpenMates client. The fixture is intentionally
language-neutral so TypeScript, Python, and Swift can consume the same bytes.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from backend.shared.python_utils.chat_completion_recovery import (
    build_recovery_associated_data,
    derive_recovery_keypair,
    open_recovery_envelope,
    seal_recovery_payload,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chat_completion_recovery_vectors.json"


def _vectors() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["vectors"]


@pytest.mark.parametrize("vector", _vectors(), ids=lambda vector: vector["name"])
def test_shared_recovery_vector_matches_exact_bytes(vector: dict) -> None:
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
        recovery_public_key=vector["recovery_public_key"],
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

    opened = open_recovery_envelope(
        envelope,
        recovery_private_key=private_key,
        owner_id=vector["owner_id"],
        chat_id=vector["chat_id"],
        turn_id=vector["turn_id"],
        job_id=vector["job_id"],
        assistant_message_id=vector["assistant_message_id"],
        key_version=vector["key_version"],
    )
    assert opened == vector["plaintext"].encode("utf-8")


def test_recovery_derivation_is_domain_and_identity_separated() -> None:
    vector = _vectors()[0]
    baseline = derive_recovery_keypair(vector["chat_key"], vector["chat_id"], vector["key_version"])

    changed_chat = derive_recovery_keypair(
        vector["chat_key"],
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        vector["key_version"],
    )
    changed_version = derive_recovery_keypair(
        vector["chat_key"],
        vector["chat_id"],
        vector["key_version"] + 1,
    )
    changed_key = derive_recovery_keypair(
        "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
        vector["chat_id"],
        vector["key_version"],
    )

    assert baseline != changed_chat
    assert baseline != changed_version
    assert baseline != changed_key


@pytest.mark.parametrize("tampered_field", ["ciphertext", "nonce", "epk"])
def test_recovery_envelope_rejects_tampered_bytes(tampered_field: str) -> None:
    vector = _vectors()[0]
    envelope = deepcopy(vector["envelope"])
    encoded = envelope[tampered_field]
    envelope[tampered_field] = ("A" if encoded[0] != "A" else "B") + encoded[1:]

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


def test_recovery_envelope_rejects_tampered_associated_data() -> None:
    vector = _vectors()[0]

    with pytest.raises(InvalidTag):
        open_recovery_envelope(
            vector["envelope"],
            recovery_private_key=vector["recovery_private_key"],
            owner_id=vector["owner_id"],
            chat_id=vector["chat_id"],
            turn_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            job_id=vector["job_id"],
            assistant_message_id=vector["assistant_message_id"],
            key_version=vector["key_version"],
        )
