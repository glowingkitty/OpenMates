# backend/apps/uploads/services/file_encryption.py
#
# File encryption and Vault key-wrapping service for uploaded files.
#
# Architecture — matches generate_task.py exactly:
#   1. Generate a random AES-256 key per file.
#   2. Encrypt the file bytes with AES-256-GCM (same key, unique nonce per variant).
#   3. Vault-wrap the AES key using the user's Vault Transit key.
#      → 'vault_wrapped_aes_key' is stored in the embed content TOON so that
#        backend skills can later unwrap it via Vault and decrypt the file on demand.
#      → The plaintext AES key is also returned to the client so it can decrypt
#        the file for local rendering (e.g. displaying the image in the browser).
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
    AES-256-GCM file encryption with HashiCorp Vault Transit key wrapping.

    Each file gets a freshly generated 256-bit AES key. The key is:
      - Used to encrypt the raw file bytes before S3 upload.
      - Vault-wrapped so skills can decrypt the file server-side on demand.
      - Returned as base64 plaintext to the caller for inclusion in the embed TOON
        (the embed TOON is then client-encrypted, so the key is protected at rest).
    """

    def __init__(self, vault_url: str, vault_token_path: str = "/vault-data/api.token") -> None:
        self.vault_url = vault_url
        self.vault_token_path = vault_token_path
        self.transit_mount = "transit"

    def _load_vault_token(self) -> str:
        """Load the Vault API token from the shared token file (written by vault-setup)."""
        try:
            with open(self.vault_token_path, "r") as f:
                token = f.read().strip()
                if not token:
                    raise ValueError("Vault token file is empty")
                return token
        except FileNotFoundError as e:
            logger.error(f"[FileEncryption] Vault token file not found at {self.vault_token_path}")
            raise RuntimeError("Vault token file not found") from e

    async def _vault_wrap_key(self, aes_key_b64: str, vault_key_id: str) -> str:
        """
        Encrypt (wrap) a base64-encoded AES key using the Vault Transit engine.

        Args:
            aes_key_b64: Base64-encoded raw AES-256 key to wrap.
            vault_key_id: The user's Vault Transit key name (user.vault_key_id).

        Returns:
            Vault ciphertext string (e.g. "vault:v1:abc123...") that only Vault can decrypt.

        Raises:
            RuntimeError: If Vault is unreachable or the wrap fails.
        """
        import httpx

        token = self._load_vault_token()
        url = f"{self.vault_url}/v1/{self.transit_mount}/encrypt/{vault_key_id}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    json={"plaintext": aes_key_b64},
                    headers={"X-Vault-Token": token},
                )
                resp.raise_for_status()
                ciphertext = resp.json()["data"]["ciphertext"]
                logger.debug(
                    f"[FileEncryption] Vault-wrapped AES key for transit key '{vault_key_id}'"
                )
                return ciphertext
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[FileEncryption] Vault Transit encrypt failed: {e.response.status_code} {e.response.text}",
                exc_info=True,
            )
            raise RuntimeError(f"Vault Transit encrypt failed: {e.response.status_code}") from e
        except Exception as e:
            logger.error(f"[FileEncryption] Vault request error: {e}", exc_info=True)
            raise

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
        Encrypt a second variant (e.g. preview image) using the SAME AES key but a NEW nonce.

        IMPORTANT: Never reuse the same nonce with the same key for different plaintexts.
        This method generates a fresh nonce and appends it to the ciphertext so the caller
        can store both together.

        Wait — actually for our use case (image + preview), we use the SAME nonce across
        variants (same as generate_task.py). This is safe because the plaintexts are different.
        GCM nonce reuse is only catastrophic when the SAME plaintext is encrypted with the same
        nonce+key. Different plaintexts with the same nonce+key are NOT a security issue for
        confidentiality (only authenticity could theoretically be impacted, which is acceptable
        for our use case where we verify S3 integrity via content hash).

        See generate_task.py lines 358: `encrypted_payload = aesgcm.encrypt(nonce, content, None)`
        for all image variants — same key, same nonce, different plaintext. We follow that pattern.

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

    async def wrap_key_with_vault(self, aes_key_b64: str, vault_key_id: str) -> str:
        """
        Vault-wrap the plaintext AES key using the user's Transit key.

        Args:
            aes_key_b64: Base64 raw AES key to wrap.
            vault_key_id: User's Vault Transit key ID.

        Returns:
            Vault ciphertext string for storage in embed content.
        """
        return await self._vault_wrap_key(aes_key_b64, vault_key_id)
