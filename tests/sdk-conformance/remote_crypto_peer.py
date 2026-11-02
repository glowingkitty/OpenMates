"""Independent synthetic Python cryptography peer; never imports an OpenMates SDK."""

# contract-test-file: tooling
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def decode(value):
    if (
        not isinstance(value, str)
        or not value
        or any(
            c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for c in value
        )
    ):
        raise ValueError("canonical wire bytes required")
    raw = base64.urlsafe_b64decode(value + "=" * ((-len(value)) % 4))
    if encode(raw) != value:
        raise ValueError("canonical wire bytes required")
    return raw


def transcript(identity, label, suffix):
    team = identity.get("contextType") == "team"
    version = 2 if team else 1
    names = (
        [
            "ownerId",
            "contextType",
            "contextId",
            "projectId",
            "sourceId",
            "sourceSessionId",
            "requestingClientId",
            "hostMemberId",
            "hostDeviceId",
            "requesterMemberId",
            "requesterDeviceId",
        ]
        if team
        else [
            "ownerId",
            "projectId",
            "sourceId",
            "sourceSessionId",
            "requestingClientId",
        ]
    )
    values = [
        f"OMRA-{label}-{version}",
        *[identity[name] for name in names],
        identity["keyEpoch"],
        *suffix,
    ]
    return json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()


class IndependentPeer:
    """Only this harness party owns a private ephemeral. SDK private keys stay opaque."""

    def __init__(self, key, identity, role, private=None):
        self.project_key = key
        self.identity = identity
        self.role = role
        self.version = 2 if identity.get("contextType") == "team" else 1
        self.private = (
            X25519PrivateKey.generate()
            if private is None
            else X25519PrivateKey.from_private_bytes(private)
        )
        public = encode(
            self.private.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        )
        tag = hmac.digest(
            key, transcript(identity, "HANDSHAKE", [role, public]), "sha256"
        )
        self.handshake = {
            "version": self.version,
            "role": role,
            "publicKey": public,
            "authenticationTag": encode(tag),
        }
        self.key = None
        self.received = set()
        self.sent = set()

    def accept(self, remote):
        opposite = "source" if self.role == "requester" else "requester"
        if (
            set(remote) != {"version", "role", "publicKey", "authenticationTag"}
            or remote["version"] != self.version
            or remote["role"] != opposite
        ):
            raise ValueError("peer wire role/version mismatch")
        public = decode(remote["publicKey"])
        tag = decode(remote["authenticationTag"])
        expected = hmac.digest(
            self.project_key,
            transcript(self.identity, "HANDSHAKE", [opposite, remote["publicKey"]]),
            "sha256",
        )
        if (
            len(public) != 32
            or len(tag) != 32
            or not hmac.compare_digest(expected, tag)
        ):
            raise ValueError("peer handshake authentication mismatch")
        requester = (
            remote["publicKey"]
            if self.role == "source"
            else self.handshake["publicKey"]
        )
        source = (
            self.handshake["publicKey"]
            if self.role == "source"
            else remote["publicKey"]
        )
        shared = self.private.exchange(X25519PublicKey.from_public_bytes(public))
        info = hashlib.sha256(
            transcript(self.identity, "TRANSCRIPT", [requester, source])
        ).digest()
        self.key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=f"openmates:project-remote-access:v{self.version}".encode(),
            info=info,
        ).derive(shared)

    def seal(self, request_id, plaintext, nonce=None):
        nonce = os.urandom(12) if nonce is None else nonce
        if nonce in self.sent:
            raise ValueError("peer outbound nonce reused")
        self.sent.add(nonce)
        direction = "request" if self.role == "requester" else "result"
        ciphertext = AESGCM(self.key).encrypt(
            nonce,
            plaintext,
            transcript(self.identity, "ENVELOPE", [request_id, direction]),
        )
        return {
            "version": self.version,
            "nonce": encode(nonce),
            "ciphertext": encode(ciphertext),
        }

    def open(self, request_id, envelope):
        if (
            set(envelope) != {"version", "nonce", "ciphertext"}
            or envelope["version"] != self.version
        ):
            raise ValueError("peer envelope shape/version mismatch")
        nonce = decode(envelope["nonce"])
        if len(nonce) != 12 or nonce in self.received:
            raise ValueError("peer replay or nonce mismatch")
        direction = "result" if self.role == "requester" else "request"
        value = AESGCM(self.key).decrypt(
            nonce,
            decode(envelope["ciphertext"]),
            transcript(self.identity, "ENVELOPE", [request_id, direction]),
        )
        self.received.add(nonce)
        return value
