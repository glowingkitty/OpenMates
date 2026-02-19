# backend/apps/uploads/services/file_encryption.py
#
# Pure AES-256-GCM file encryption service for uploaded files.
#
# Architecture:
#   1. Generate a random AES-256 key per file.
#   2. Encrypt the file bytes with AES-256-GCM (same key, unique nonce per variant).
#   3. Return the plaintext AES key and nonce to the caller.
#
# Vault Transit key wrapping is handled by the core API via its internal
# endpoint (/internal/uploads/wrap-key). This service has NO access to the
# main Vault and never performs any Vault operations.
#
# The plaintext AES key is NEVER stored server-side after this function returns.
# It lives only in the client-encrypted embed content (TOON inside encrypted_content).

import os
import base64
import logging
from typing import Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)


class FileEncryptionService:
    """
    AES-256-GCM file encryption service.

    Each file gets a freshly generated 256-bit AES key. The key is:
      - Used to encrypt the raw file bytes before S3 upload.
      - Returned as base64 plaintext to the caller for inclusion in the embed TOON
        (the embed TOON is then client-encrypted, so the key is protected at rest).

    Vault Transit key wrapping (for server-side skill access) is handled
    separately by the core API's /internal/uploads/wrap-key endpoint.
    This class is intentionally Vault-free for security isolation.
    """

    def __init__(self) -> None:
        """Initialize the encryption service. No external dependencies."""
        pass

    def encrypt_bytes(self, plaintext: bytes) -> Tuple[bytes, str, str]:
        """
        Encrypt raw bytes with AES-256-GCM using a freshly generated key.

        The same key is returned for the caller to encrypt multiple variants
        (e.g. original + preview) with the same key but a DIFFERENT nonce.
        Call this once per file; call encrypt_bytes_with_key() for variants.

        Returns:
            Tuple of (encrypted_bytes, aes_key_b64, nonce_b64)
              - encrypted_bytes: AES-GCM ciphertext (nonce NOT prepended — stored separately)
              - aes_key_b64: Base64 raw 32-byte AES key (return to client)
              - nonce_b64: Base64 12-byte GCM nonce
        """
        aes_key = os.urandom(32)  # 256-bit key
        nonce = os.urandom(12)    # GCM nonce — 96-bit is the GCM standard

        aesgcm = AESGCM(aes_key)
        encrypted = aesgcm.encrypt(nonce, plaintext, None)

        aes_key_b64 = base64.b64encode(aes_key).decode("utf-8")
        nonce_b64 = base64.b64encode(nonce).decode("utf-8")

        logger.debug(
            f"[FileEncryption] Encrypted {len(plaintext)} bytes → {len(encrypted)} bytes ciphertext"
        )
        return encrypted, aes_key_b64, nonce_b64

    def encrypt_bytes_with_key(self, plaintext: bytes, aes_key_b64: str, nonce_b64: str) -> bytes:
        """
        Encrypt a second variant (e.g. preview image) using the SAME AES key.

        For our use case (image + preview), we use the SAME nonce across
        variants (same as generate_task.py). This is safe because the plaintexts
        are different. GCM nonce reuse is only catastrophic when the SAME
        plaintext is encrypted with the same nonce+key. Different plaintexts
        with the same nonce+key are NOT a security issue for confidentiality.

        See generate_task.py: all image variants use same key, same nonce,
        different plaintext. We follow that pattern.

        Args:
            plaintext: Raw bytes to encrypt.
            aes_key_b64: Base64 AES key (same as used for the original).
            nonce_b64: Base64 nonce (same as used for the original).

        Returns:
            AES-GCM encrypted bytes.
        """
        aes_key = base64.b64decode(aes_key_b64)
        nonce = base64.b64decode(nonce_b64)
        aesgcm = AESGCM(aes_key)
        encrypted = aesgcm.encrypt(nonce, plaintext, None)
        logger.debug(
            f"[FileEncryption] Encrypted variant: {len(plaintext)} bytes → {len(encrypted)} bytes"
        )
        return encrypted
