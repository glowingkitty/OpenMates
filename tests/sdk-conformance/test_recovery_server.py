"""Validate canonical sealed main-completion data in the shared recovery peer.

Exercise the real claim and encryption helpers with a recording socket only.
Independently decrypt synthetic envelopes and require nullable metadata fields.
Keep lease-generation, identity, tamper, terminal and cancellation cases intact.
Never bind a listener, create a product client or invoke a real SDK operation.
"""

# contract-test-file: tooling
from __future__ import annotations

import base64
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

import recovery_server as recovery


class RecordingSocket:
    def __init__(self):
        self.frames = []

    def send(self, kind, payload):
        self.frames.append((kind, payload))


class MainCompletionFixtureTests(unittest.TestCase):
    def setUp(self):
        raw = (
            Path(recovery.__file__).parent / "fixtures/session-recovery.json"
        ).read_bytes()
        self.suite = json.loads(raw)["capabilities"][recovery.CAPABILITY]
        self.private = X25519PrivateKey.from_private_bytes(bytes([77]) * 32)

    def peer(self, mode):
        # Exercise the actual claim/seal algorithm, without constructing an HTTP
        # server, binding a socket, spawning threads or invoking an SDK.
        peer = recovery.RecoveryPeer.__new__(recovery.RecoveryPeer)
        peer.suite = self.suite
        peer.account = self.suite["account"]
        peer.protocol = self.suite["protocol"]
        peer.vector = {"mode": mode}
        peer.counts = {"claims": 0}
        peer.checks = set()
        peer.chat_id = peer.protocol["initial_chat_id"]
        peer.key = base64.b64decode(peer.protocol["initial_chat_key"])
        public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        peer.admission = {
            "turn_id": "33333333-3333-4333-8333-333333333333",
            "recovery_public_key": recovery.b64url(public),
        }
        return peer

    def claim(self, peer):
        socket = RecordingSocket()
        peer.claim(
            socket,
            {
                "protocol_version": 1,
                "job_id": peer.protocol["job_id"],
                "request_id": "66666666-6666-4666-8666-666666666666",
            },
        )
        return socket.frames

    def plaintext(self, peer, payload):
        outer = json.loads(payload["sealed_payload"])
        identity = [
            peer.account["owner_id"],
            peer.chat_id,
            peer.admission["turn_id"],
            peer.protocol["job_id"],
            peer.protocol["assistant_id"],
        ]
        aad = (
            b"OMCR1"
            + b"".join(
                struct.pack(">I", len(value.encode())) + value.encode()
                for value in identity
            )
            + struct.pack(">I", 1)
        )
        shared = self.private.exchange(
            X25519PublicKey.from_public_bytes(recovery.unurl(outer["epk"]))
        )
        key = recovery.hkdf(
            shared,
            hashlib.sha256(b"openmates:chat-recovery-envelope:v1").digest(),
            hashlib.sha256(aad).digest(),
        )
        return json.loads(
            AESGCM(key).decrypt(
                recovery.unurl(outer["nonce"]), recovery.unurl(outer["ciphertext"]), aad
            )
        )

    def test_all_leased_modes_include_canonical_nullable_metadata_in_sealed_plaintext(
        self,
    ):
        modes = [
            "leased",
            "lost_ack",
            "bad_lease",
            "bad_identity",
            "bad_key",
            "bad_version",
            "persist_error",
        ]
        for mode in modes:
            with self.subTest(mode=mode):
                peer = self.peer(mode)
                frames = self.claim(peer)
                self.assertEqual(len(frames), 1)
                kind, payload = frames[0]
                self.assertEqual(kind, "recovery_job_claimed")
                opened = self.plaintext(peer, payload)
                self.assertEqual(
                    set(opened),
                    {
                        "assistant_message_id",
                        "category",
                        "chat_id",
                        "content",
                        "job_id",
                        "key_version",
                        "model_name",
                        "turn_id",
                    },
                )
                self.assertIsNone(opened["category"])
                self.assertIsNone(opened["model_name"])
                self.assertEqual(opened["content"], peer.protocol["sealed_content"])
                self.assertEqual(opened["turn_id"], peer.admission["turn_id"])
                self.assertEqual(peer.counts["claims"], 1)
                self.assertNotIn(
                    peer.protocol["sealed_content"], payload["sealed_payload"]
                )
                if mode == "bad_lease":
                    self.assertEqual(payload["lease_generation"], 0)
                if mode == "bad_identity":
                    self.assertNotEqual(payload["turn_id"], peer.admission["turn_id"])

    def test_tamper_still_rejects_and_terminal_cancel_contracts_are_unchanged(self):
        peer = self.peer("bad_envelope")
        with self.assertRaises(InvalidTag):
            self.plaintext(peer, self.claim(peer)[0][1])
        peer = self.peer("terminal")
        terminal = self.claim(peer)[0][1]
        self.assertEqual(terminal["state"], "TERMINAL")
        self.assertNotIn("sealed_payload", terminal)
        self.assertEqual(len(peer.messages), 1)
        peer = self.peer("cancel")
        self.assertEqual(self.claim(peer), [])
        self.assertEqual(peer.counts["claims"], 1)


if __name__ == "__main__":
    unittest.main()
