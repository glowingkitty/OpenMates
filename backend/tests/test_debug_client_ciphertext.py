# contract-test-file: infrastructure
"""Debug tooling decrypts the current web client ciphertext format.

The web client prefixes AES-GCM ciphertext with "OM" + a 4-byte key
fingerprint. Without header support every message of a shared chat failed to
decrypt during issue forensics (issues 4VXWM, 8V7RB, BMKRJ, XDE6G, S7ZNB).
"""
import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import debug_utils  # noqa: E402 - scripts directory is not a package


def _encrypt(key: bytes, plaintext: str, *, header: bool, fingerprint: bytes | None = None) -> str:
    iv = os.urandom(12)
    body = iv + AESGCM(key).encrypt(iv, plaintext.encode(), None)
    if header:
        body = b"OM" + (fingerprint or debug_utils._client_key_fingerprint(key)) + body
    return base64.b64encode(body).decode()


def test_fingerprint_matches_web_fnv1a_reference() -> None:
    # Reference value computed with MessageEncryptor.computeKeyFingerprint4Bytes.
    assert debug_utils._client_key_fingerprint(b"") == bytes.fromhex("811c9dc5")
    assert debug_utils._client_key_fingerprint(b"a") == bytes.fromhex("e40c292c")


def test_decrypts_headered_and_legacy_client_ciphertext() -> None:
    key = AESGCM.generate_key(bit_length=256)
    for header in (True, False):
        plaintext, error = debug_utils.decrypt_client_aes_content(_encrypt(key, "hello", header=header), key)
        assert (plaintext, error) == ("hello", None)


def test_reports_key_fingerprint_mismatch() -> None:
    key = AESGCM.generate_key(bit_length=256)
    encrypted = _encrypt(key, "hello", header=True, fingerprint=b"\x00\x00\x00\x00")
    plaintext, error = debug_utils.decrypt_client_aes_content(encrypted, key)
    assert plaintext is None
    assert "fingerprint mismatch" in error
