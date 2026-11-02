"""Check the synthetic peer's fences and cryptographic fixture construction."""
# contract-test-file: tooling

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from recovery_server import CAPABILITY, RecoveryPeer, encrypt, hkdf, lp, seal, unurl


class RecordingSocket:
    def __init__(self):
        self.frames = []

    def send(self, kind, payload):
        self.frames.append((kind, payload))


class LifecycleSocket(RecordingSocket):
    def __init__(self, payload):
        super().__init__()
        self.incoming = iter([{"type": "native_client_lifecycle", "payload": payload}])

    def receive(self):
        return next(self.incoming, None)


class RecoveryPeerTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).with_name("fixtures") / "session-recovery.json"
        self.suite = json.loads(fixture.read_bytes())["capabilities"][CAPABILITY]
        self.peer = RecoveryPeer(self.suite, self.suite["vectors"][0], "rust").start()

    def tearDown(self):
        self.peer.close()

    def payload(self):
        protocol = self.suite["protocol"]
        return {
            "job_id": protocol["job_id"],
            "lease_token": protocol["lease_token"],
            "lease_generation": protocol["lease_generation"],
            "expected_messages_v": protocol["fresh_messages_v"],
            "encrypted_assistant_message": {
                "chat_id": self.peer.chat_id,
                "client_message_id": protocol["assistant_id"],
                "encrypted_content": encrypt(
                    protocol["sealed_content"].encode(), self.peer.key
                ),
            },
        }

    def test_active_noninteractive_lifecycle_and_exact_identity_are_required(self):
        payload = {"client_type": "rust", "is_foreground": True, "interactive": False}
        self.peer.websocket(LifecycleSocket(payload))
        self.assertEqual(self.peer.counts["admissions"], 0)
        for field, wrong in [
            ("is_foreground", False),
            ("interactive", True),
            ("client_type", "npm"),
        ]:
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.peer.websocket(LifecycleSocket({**payload, field: wrong}))
            self.assertEqual(self.peer.counts["admissions"], 0)
            self.assertEqual(self.peer.counts["persists"], 0)

    def test_peer_refuses_wrong_lease_or_version_before_canonical_commit(self):
        for field, wrong in [
            ("lease_token", "other-fixture-lease"),
            ("lease_generation", 6),
            ("expected_messages_v", 1),
        ]:
            with self.subTest(field=field):
                payload = self.payload()
                payload[field] = wrong
                with self.assertRaises(AssertionError):
                    self.peer.persist(RecordingSocket(), payload)
                self.assertEqual(self.peer.messages, [])
                self.assertNotIn("canonical-commit", self.peer.checks)

    def test_peer_authenticates_encrypted_content_and_commits_only_sealed_answer(self):
        payload = self.payload()
        payload["encrypted_assistant_message"]["encrypted_content"] = encrypt(
            b"untrusted transient preview", self.peer.key
        )
        with self.assertRaises(AssertionError):
            self.peer.persist(RecordingSocket(), payload)
        self.assertEqual(self.peer.messages, [])
        socket = RecordingSocket()
        self.peer.persist(socket, self.payload())
        self.assertIn("canonical-commit", self.peer.checks)
        self.assertEqual(socket.frames[0][0], "recovery_job_persisted")
        self.assertEqual(socket.frames[0][1]["state"], "TERMINAL")

    def test_sealed_fixture_authenticates_identity_nonce_and_ciphertext(self):
        private = X25519PrivateKey.from_private_bytes(bytes(range(33, 65)))
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        identity = [
            self.suite["account"]["owner_id"],
            self.peer.chat_id,
            "33333333-3333-4333-8333-333333333333",
            self.suite["protocol"]["job_id"],
            self.suite["protocol"]["assistant_id"],
        ]
        from recovery_server import b64url

        envelope = seal(
            b64url(public), identity, {"content": "synthetic sealed answer"}
        )
        aad = (
            b"OMCR1" + b"".join(lp(value) for value in identity) + struct.pack(">I", 1)
        )
        shared = private.exchange(
            X25519PublicKey.from_public_bytes(unurl(envelope["epk"]))
        )
        key = hkdf(
            shared,
            hashlib.sha256(b"openmates:chat-recovery-envelope:v1").digest(),
            hashlib.sha256(aad).digest(),
        )
        self.assertEqual(
            json.loads(
                AESGCM(key).decrypt(
                    unurl(envelope["nonce"]), unurl(envelope["ciphertext"]), aad
                )
            ),
            {"content": "synthetic sealed answer"},
        )
        for field in ("nonce", "ciphertext"):
            tampered = deepcopy(envelope)
            value = bytearray(unurl(tampered[field]))
            value[0] ^= 1
            tampered[field] = b64url(value)
            with self.assertRaises(InvalidTag):
                AESGCM(key).decrypt(
                    unurl(tampered["nonce"]), unurl(tampered["ciphertext"]), aad
                )
        with self.assertRaises(InvalidTag):
            AESGCM(key).decrypt(
                unurl(envelope["nonce"]),
                unurl(envelope["ciphertext"]),
                aad[:-1] + b"\x02",
            )


if __name__ == "__main__":
    unittest.main()
