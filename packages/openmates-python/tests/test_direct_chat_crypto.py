"""OMDM1 direct-chat crypto, including browser/Node and Python byte interop.

The Node cases execute the shared TypeScript helper in the existing repository
runtime. No network, API account, or persistent identity is used by this file.
"""

import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from openmates.direct_chats import (
    DirectChatIdentity,
    direct_chat_key_id,
    generate_identity,
    open_direct_chat_key,
    recover_identity,
    seal_direct_chat_key,
    validate_public_chat_key,
)


CHAT_KEY = bytes(range(1, 33))
RECIPIENT_HASH = "b" * 64


def _identity(key_id: str, **overrides: str) -> DirectChatIdentity:
    values = {"team_id": "team-one", "chat_id": "chat-one",
              "recipient_hash": RECIPIENT_HASH, "key_id": key_id}
    values.update(overrides)
    return DirectChatIdentity(**values)


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _wire(envelope: str) -> dict:
    return json.loads(_decode(envelope.removeprefix("OMDM1.")).decode("utf-8"))


def _node_root() -> Path:
    if not shutil.which("node"):
        pytest.skip("Node is required for cross-language direct-chat interop")
    for root in Path(__file__).resolve().parents:
        source = root / "frontend/packages/pairing-crypto/src/directChatCrypto.ts"
        dependency = root / "frontend/packages/pairing-crypto/node_modules/tweetnacl"
        if source.is_file() and dependency.exists():
            return root
    pytest.skip("Shared TypeScript direct-chat helper dependencies are unavailable")


def _node(script: str, payload: dict | None = None) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        input=json.dumps(payload) if payload is not None else "",
        text=True, capture_output=True, check=True, cwd=_node_root(), timeout=20,
    )
    return json.loads(result.stdout)


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange

def test_two_recipient_roundtrip_fresh_ephemerals_and_exact_binding():
    alice = generate_identity()
    bob = generate_identity()
    alice_binding = _identity(alice.key_id, recipient_hash="a" * 64)
    bob_binding = _identity(bob.key_id)
    first = seal_direct_chat_key(CHAT_KEY, alice_binding, alice.public_key)
    second = seal_direct_chat_key(CHAT_KEY, alice_binding, alice.public_key)
    bob_envelope = seal_direct_chat_key(CHAT_KEY, bob_binding, bob.public_key)

    assert first.startswith("OMDM1.") and bob_envelope.startswith("OMDM1.")
    assert first != second
    assert _wire(first)["ephemeral_public_key"] != _wire(second)["ephemeral_public_key"]
    assert _wire(first)["nonce"] != _wire(second)["nonce"]
    assert open_direct_chat_key(first, alice_binding, alice.private_key) == CHAT_KEY
    assert open_direct_chat_key(bob_envelope, bob_binding, bob.private_key) == CHAT_KEY
    for changed in (
        _identity(alice.key_id, team_id="other-team", recipient_hash="a" * 64),
        _identity(alice.key_id, chat_id="other-chat", recipient_hash="a" * 64),
        _identity(alice.key_id, recipient_hash="c" * 64),
    ):
        with pytest.raises(ValueError, match="binding"):
            open_direct_chat_key(first, changed, alice.private_key)
    with pytest.raises(ValueError, match="private key ID"):
        open_direct_chat_key(first, alice_binding, bob.private_key)
    with pytest.raises(ValueError, match="recipient key ID"):
        seal_direct_chat_key(CHAT_KEY, alice_binding, bob.public_key)


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange

def test_public_directory_and_backup_recovery_reject_mismatch_and_weak_keys():
    pair = generate_identity()
    assert direct_chat_key_id(pair.public_key) == pair.key_id
    assert validate_public_chat_key({"key_id": pair.key_id, "public_key": pair.public_key,
                                     "untrusted_extra": "ignored"}) == {
        "key_id": pair.key_id, "public_key": pair.public_key,
    }
    assert recover_identity(pair.public_key, pair.key_id, pair.private_key) == pair
    with pytest.raises(ValueError, match="ID mismatch"):
        validate_public_chat_key({"key_id": "a" * 64, "public_key": pair.public_key})
    with pytest.raises(ValueError, match="pair mismatch"):
        recover_identity(pair.public_key, pair.key_id, generate_identity().private_key)
    for weak in (bytes(32), b"\x01" + bytes(31)):
        with pytest.raises(ValueError, match="public key"):
            direct_chat_key_id(_encode(weak))
    with pytest.raises(ValueError, match="chat key"):
        seal_direct_chat_key(bytes(32), _identity(pair.key_id), pair.public_key)


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange

def test_malformed_envelope_is_rejected_without_fallback():
    pair = generate_identity()
    expected = _identity(pair.key_id)
    envelope = seal_direct_chat_key(CHAT_KEY, expected, pair.public_key)
    outer = _wire(envelope)
    altered = []
    for variant in (
        {**outer, "v": 2},
        {**outer, "v": True},
        {**outer, "extra": "forbidden"},
        {**outer, "nonce": "AA="},
        {**outer, "ephemeral_public_key": _encode(bytes(32))},
        {**outer, "ciphertext": "AA"},
    ):
        altered.append("OMDM1." + _encode(json.dumps(variant, separators=(",", ":")).encode()))
    altered.extend(("not-an-envelope", "OMDM1.abc=", "OMDM1." + "x" * 3000,
                    "OMDM1." + _encode(b"\xff")))
    for invalid in altered:
        with pytest.raises(ValueError):
            open_direct_chat_key(invalid, expected, pair.private_key)
    with pytest.raises(ValueError, match="private key"):
        open_direct_chat_key(envelope, expected, _encode(bytes(32)))


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange

def test_typescript_seal_opens_in_python():
    source = """
import {generateIdentity, sealDirectChatKey} from './frontend/packages/pairing-crypto/src/directChatCrypto.ts';
const pair = await generateIdentity();
const raw = Uint8Array.from({length: 32}, (_, i) => i + 1);
const expected = {teamId: 'team-one', chatId: 'chat-one', recipientHash: 'b'.repeat(64), keyId: pair.keyId};
const envelope = await sealDirectChatKey(raw, expected, pair.publicKey);
process.stdout.write(JSON.stringify({pair, expected, envelope, keyHex: Buffer.from(raw).toString('hex')}));
"""
    fixture = _node(source)
    pair = fixture["pair"]
    expected = fixture["expected"]
    binding = DirectChatIdentity(expected["teamId"], expected["chatId"],
                                 expected["recipientHash"], expected["keyId"])
    assert direct_chat_key_id(pair["publicKey"]) == pair["keyId"]
    assert open_direct_chat_key(fixture["envelope"], binding, pair["privateKey"]).hex() == fixture["keyHex"]


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange

def test_python_seal_opens_in_typescript():
    pair = generate_identity()
    binding = _identity(pair.key_id)
    envelope = seal_direct_chat_key(CHAT_KEY, binding, pair.public_key)
    source = """
import {readFileSync} from 'node:fs';
import {directChatKeyId, openDirectChatKey} from './frontend/packages/pairing-crypto/src/directChatCrypto.ts';
const input = JSON.parse(readFileSync(0, 'utf8'));
const key = await openDirectChatKey(input.envelope, input.binding, input.privateKey);
process.stdout.write(JSON.stringify({keyHex: Buffer.from(key).toString('hex'), keyId: await directChatKeyId(input.publicKey)}));
"""
    result = _node(source, {"envelope": envelope, "privateKey": pair.private_key,
                            "publicKey": pair.public_key,
                            "binding": {"teamId": binding.team_id, "chatId": binding.chat_id,
                                        "recipientHash": binding.recipient_hash,
                                        "keyId": binding.key_id}})
    assert result == {"keyHex": CHAT_KEY.hex(), "keyId": hashlib.sha256(_decode(pair.public_key)).hexdigest()}
