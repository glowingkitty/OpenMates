"""Independent peer checks against retained original CLI/Rust vectors; no SDK import."""

# contract-test-file: tooling
from __future__ import annotations
import json
from pathlib import Path
import unittest
from remote_crypto_peer import IndependentPeer, decode, encode, transcript

ROOT = Path(__file__).resolve().parents[2]


class IndependentPeerTests(unittest.TestCase):
    def vectors(self):
        return json.loads(
            (
                ROOT
                / "packages/openmates-rust/tests/fixtures/remote_access_vectors.json"
            ).read_bytes()
        )

    def test_original_fixed_personal_team_vectors_both_directions(self):
        for vector in self.vectors():
            for role, outgoing, incoming, text in [
                ("requester", "request", "result", "requestText"),
                ("source", "result", "request", "resultText"),
            ]:
                opposite = "source" if role == "requester" else "requester"
                peer = IndependentPeer(
                    decode(vector["projectKey"]),
                    vector["identity"],
                    role,
                    decode(vector[role]["privateKey"]),
                )
                self.assertEqual(peer.handshake, vector[role]["handshake"])
                peer.accept(vector[opposite]["handshake"])
                self.assertEqual(encode(peer.key), vector["sessionKey"])
                actual = peer.seal(
                    vector["requestId"],
                    vector[text].encode(),
                    decode(vector[outgoing]["nonce"]),
                )
                self.assertEqual(actual, vector[outgoing])
                self.assertEqual(
                    peer.open(vector["requestId"], vector[incoming]),
                    vector[
                        "requestText" if incoming == "request" else "resultText"
                    ].encode(),
                )

    def test_independent_hmac_rejects_identity_and_key_changes(self):
        for vector in self.vectors():
            for key, identity in [
                (bytes(32), vector["identity"]),
                (
                    decode(vector["projectKey"]),
                    {**vector["identity"], "ownerId": "wrong"},
                ),
            ]:
                peer = IndependentPeer(key, identity, "source")
                with self.assertRaises(ValueError):
                    peer.accept(vector["requester"]["handshake"])

    def test_independent_peer_replay_and_direction_are_real_auth_checks(self):
        vector = self.vectors()[0]
        peer = IndependentPeer(
            decode(vector["projectKey"]),
            vector["identity"],
            "source",
            decode(vector["source"]["privateKey"]),
        )
        peer.accept(vector["requester"]["handshake"])
        with self.assertRaises(Exception):
            peer.open("wrong-request", vector["request"])
        with self.assertRaises(Exception):
            peer.open(vector["requestId"], vector["result"])
        self.assertEqual(
            peer.open(vector["requestId"], vector["request"]),
            vector["requestText"].encode(),
        )
        with self.assertRaises(ValueError):
            peer.open(vector["requestId"], vector["request"])

    def test_canonical_public_encoding_refuses_padding_and_noncanonical_bits(self):
        for value in ["AA=", "bad+base64", "A", "AB", ""]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode(value)

    def test_personal_transcript_ignores_unbound_legacy_team_fields(self):
        identity = self.vectors()[0]["identity"]
        extra = {
            **identity,
            "contextType": "personal",
            "contextId": "unbound",
            "hostMemberId": "unbound",
        }
        self.assertEqual(
            transcript(identity, "TRANSCRIPT", ["a", "b"]),
            transcript(extra, "TRANSCRIPT", ["a", "b"]),
        )


if __name__ == "__main__":
    unittest.main()
