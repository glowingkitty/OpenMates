#!/usr/bin/env python3
"""Canonicalize and sign the reviewed domain-security policy.

The Ed25519 private seed is accepted only through an environment variable and
is never printed or written. The command emits a detached signature and the
matching public key as review artifacts for the protected release workflow.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.core.api.app.services.domain_security import DomainSecurityService


PRIVATE_KEY_ENV = "DOMAIN_SECURITY_SIGNING_PRIVATE_KEY_B64"


def sign_policy(policy_path: Path, signature_path: Path, public_key_path: Path) -> None:
    encoded_private_key = os.environ.get(PRIVATE_KEY_ENV, "")
    try:
        private_key_bytes = base64.b64decode(encoded_private_key, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"{PRIVATE_KEY_ENV} must be canonical base64") from exc
    if len(private_key_bytes) != 32:
        raise ValueError(f"{PRIVATE_KEY_ENV} must encode a 32-byte Ed25519 seed")

    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    DomainSecurityService()._apply_policy(policy)
    canonical = DomainSecurityService._canonical_policy_bytes(policy)
    policy_path.write_bytes(canonical)
    signature_path.write_text(
        base64.b64encode(private_key.sign(canonical)).decode("ascii") + "\n",
        encoding="ascii",
    )
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key_path.write_text(base64.b64encode(public_key).decode("ascii") + "\n", encoding="ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    args = parser.parse_args()
    sign_policy(args.policy, args.signature, args.public_key)
    print("Domain-security policy canonicalized and signed; review artifacts are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
