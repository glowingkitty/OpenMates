"""SDK-only binary/AAD legacy IV collisions still require AES-GCM authentication."""

# contract-test-file: tooling
import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from openmates import sdk


def test_legacy_om_binary_and_associated_data_remain_authenticated():
    key = bytes([7]) * 32
    aad = "synthetic:expected-context"
    for marker in (
        bytes.fromhex("deadbeef"),
        sdk._key_fingerprint(key),
        bytes([1, 0, 0, 0]),
    ):
        iv = b"OM" + marker + bytes(range(6, 12))
        binary = bytes(range(256))
        combined = iv + AESGCM(key).encrypt(iv, binary, None)
        assert (
            sdk._decrypt_aes_gcm_bytes(base64.b64encode(combined).decode(), key)
            == binary
        )
        text = "Synthetic AAD payload ✓"
        raw = iv + AESGCM(key).encrypt(iv, text.encode(), aad.encode())
        for combined in (raw, b"OM" + sdk._key_fingerprint(key) + raw):
            encoded = base64.b64encode(combined).decode()
            assert sdk._decrypt_aes_gcm_text(encoded, key, aad) == text
            assert sdk._decrypt_aes_gcm_text(encoded, key, "wrong-context") is None
            assert sdk._decrypt_aes_gcm_text(encoded, key) is None
            tamper = bytearray(combined)
            tamper[-1] ^= 1
            assert (
                sdk._decrypt_aes_gcm_text(base64.b64encode(tamper).decode(), key, aad)
                is None
            )


def test_unauthenticated_headers_and_truncated_tags_are_rejected():
    key = bytes([7]) * 32
    for marker in (
        sdk._key_fingerprint(key),
        bytes([1, 0, 0, 0]),
        bytes.fromhex("deadbeef"),
    ):
        encoded = base64.b64encode(b"OM" + marker + bytes(28)).decode()
        assert sdk._decrypt_aes_gcm_bytes(encoded, key) is None
        assert sdk._decrypt_aes_gcm_text(encoded, key) is None
    for size in range(28):
        assert (
            sdk._decrypt_aes_gcm_bytes(base64.b64encode(bytes(size)).decode(), key)
            is None
        )
