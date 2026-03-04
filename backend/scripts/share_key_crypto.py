"""
Share Key Cryptography Utilities for Inspection Scripts

Provides Python implementations of the client-side share URL key blob
decryption and AES-GCM content decryption, matching the TypeScript
implementations in:
  - frontend/packages/ui/src/services/shareEncryption.ts
  - frontend/packages/ui/src/services/embedShareEncryption.ts
  - frontend/packages/ui/src/services/cryptoService.ts

Architecture context: See docs/architecture/share_chat.md
                      See docs/architecture/zero-knowledge-storage.md

This module is used by inspect_chat.py and inspect_embed.py to decrypt
client-side encrypted content using a share URL or raw key blob.
"""

import base64
import re
from typing import Optional, Tuple
from urllib.parse import parse_qs, unquote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# --- Constants ---
PBKDF2_ITERATIONS = 100_000
PBKDF2_KEY_LENGTH = 32  # 256 bits
AES_IV_LENGTH = 12  # 12 bytes for GCM mode
SHARE_SALT = b'openmates-share-v1'
PASSWORD_SALT_PREFIX = 'openmates-pwd-'

# Share URL patterns
# Format: https://<domain>/share/chat/<chatId>#key=<encryptedBlob>
# Format: https://<domain>/share/embed/<embedId>#key=<encryptedBlob>
CHAT_SHARE_URL_PATTERN = re.compile(
    r'(?:https?://[^/]+)?/share/chat/([a-f0-9-]+)#key=(.*)',
    re.IGNORECASE
)
EMBED_SHARE_URL_PATTERN = re.compile(
    r'(?:https?://[^/]+)?/share/embed/([a-f0-9-]+)#key=(.*)',
    re.IGNORECASE
)


def base64url_decode(s: str) -> bytes:
    """
    Decode a base64 URL-safe string (as produced by the frontend).

    Matches the frontend's base64UrlDecode exactly:
      replace '-' -> '+', '_' -> '/', then pad with '=' until len % 4 == 0.

    Args:
        s: Base64 URL-safe encoded string

    Returns:
        Decoded bytes
    """
    s = s.replace('-', '+').replace('_', '/')
    while len(s) % 4:
        s += '='
    return base64.b64decode(s)


def _derive_key_from_id(entity_id: str) -> bytes:
    """
    Derive an AES-256 key from an entity ID (chat ID or embed ID)
    using PBKDF2-HMAC-SHA256, matching the frontend's deriveKeyFromChatId /
    deriveKeyFromEmbedId.

    PBKDF2 params:
      - password: entity_id (UTF-8)
      - salt: 'openmates-share-v1' (UTF-8)
      - iterations: 100,000
      - hash: SHA-256
      - key length: 32 bytes (256 bits)

    Args:
        entity_id: Chat ID or embed ID string

    Returns:
        32-byte derived key
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=PBKDF2_KEY_LENGTH,
        salt=SHARE_SALT,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(entity_id.encode('utf-8'))


def _derive_key_from_password(password: str, entity_id: str) -> bytes:
    """
    Derive an AES-256 key from a password, using the entity ID as part of
    the salt. Matches the frontend's deriveKeyFromPassword.

    PBKDF2 params:
      - password: password (UTF-8)
      - salt: 'openmates-pwd-{entity_id}' (UTF-8)
      - iterations: 100,000
      - hash: SHA-256
      - key length: 32 bytes (256 bits)

    Args:
        password: User-provided password
        entity_id: Chat ID or embed ID

    Returns:
        32-byte derived key
    """
    salt = f'{PASSWORD_SALT_PREFIX}{entity_id}'.encode('utf-8')
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=PBKDF2_KEY_LENGTH,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode('utf-8'))


def _aes_gcm_decrypt(raw_bytes: bytes, key: bytes) -> bytes:
    """
    Decrypt AES-256-GCM data in the format: IV (12 bytes) || ciphertext || tag (16 bytes).

    This matches the Web Crypto API output where the GCM tag is appended
    to the ciphertext. Python's AESGCM.decrypt() expects the same format
    (ciphertext + tag concatenated).

    Args:
        raw_bytes: IV + ciphertext + tag
        key: 32-byte AES key

    Returns:
        Decrypted plaintext bytes

    Raises:
        ValueError: If raw_bytes is too short
        cryptography.exceptions.InvalidTag: If authentication fails
    """
    if len(raw_bytes) < AES_IV_LENGTH + 16:
        raise ValueError(
            f"Encrypted data too short: {len(raw_bytes)} bytes "
            f"(need at least {AES_IV_LENGTH + 16} for IV + GCM tag)"
        )
    iv = raw_bytes[:AES_IV_LENGTH]
    ciphertext_with_tag = raw_bytes[AES_IV_LENGTH:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext_with_tag, None)



def parse_share_url(url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse a share URL to extract the entity type, entity ID, and key blob.

    Supports both full URLs and path-only formats:
      - https://app.example.org/share/chat/<id>#key=<blob>
      - /share/chat/<id>#key=<blob>
      - https://app.example.org/share/embed/<id>#key=<blob>

    Args:
        url: The share URL string

    Returns:
        Tuple of (entity_type, entity_id, key_blob) where entity_type is
        'chat' or 'embed'. Returns (None, None, None) if the URL doesn't
        match any known pattern.
    """
    # Try chat pattern
    match = CHAT_SHARE_URL_PATTERN.search(url)
    if match:
        return 'chat', match.group(1), match.group(2)

    # Try embed pattern
    match = EMBED_SHARE_URL_PATTERN.search(url)
    if match:
        return 'embed', match.group(1), match.group(2)

    return None, None, None


def decrypt_share_key_blob(
    entity_id: str,
    encrypted_blob: str,
    key_field_name: str = 'chat_encryption_key',
    password: Optional[str] = None,
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Decrypt a share key blob and extract the raw AES encryption key.

    This reimplements the frontend's decryptShareKeyBlob / decryptEmbedShareKeyBlob
    in Python.

    Steps:
    1. Derive a key from the entity ID using PBKDF2
    2. Base64-URL-safe decode the encrypted blob
    3. AES-GCM decrypt with the ID-derived key to get the serialised blob
    4. Parse URL-encoded parameters
    5. If pwd=1, decrypt the encryption key with password-derived key
    6. Return the raw 32-byte AES key

    Args:
        entity_id: Chat ID or embed ID
        encrypted_blob: Base64 URL-safe encoded encrypted blob from URL fragment
        key_field_name: Field name in the blob ('chat_encryption_key' or 'embed_encryption_key')
        password: Optional password if the share link is password-protected

    Returns:
        Tuple of (raw_key_bytes, error_message). On success, error is None.
        raw_key_bytes is the 32-byte AES key for decrypting content.
    """
    try:
        # Some share URLs are passed with percent-encoding intact (%2B, %2F, %3D).
        # Normalize to raw base64/base64url characters before decoding.
        encrypted_blob = unquote(encrypted_blob).strip()

        # Step 1: Derive key from entity ID
        id_key = _derive_key_from_id(entity_id)

        # Step 2: Decode the blob from base64 URL-safe / base64
        raw_encrypted = base64url_decode(encrypted_blob)

        # Step 3: AES-GCM decrypt to get the serialised parameter string.
        # Matches the frontend's decryptAESGCM: iv = first 12 bytes, rest = ciphertext+tag.
        try:
            serialised = _aes_gcm_decrypt(raw_encrypted, id_key)
            serialised_str = serialised.decode('utf-8')
        except Exception as e:
            return None, f"AES-GCM decryption failed: {type(e).__name__}: {e}"

        # Step 4: Parse URL-encoded parameters
        params = parse_qs(serialised_str, keep_blank_values=True)

        encryption_key_value = params.get(key_field_name, [''])[0]
        pwd_flag = params.get('pwd', ['0'])[0]
        # Note: We skip expiration checks — for debugging, we always want to decrypt

        if not encryption_key_value:
            return None, f"Blob is missing '{key_field_name}' field"

        # Step 5: If password-protected, decrypt the key with password
        if pwd_flag == '1':
            if not password:
                return None, (
                    "Share link is password-protected (pwd=1). "
                    "Provide the password with --share-password"
                )
            pwd_key = _derive_key_from_password(password, entity_id)
            raw_key_encrypted = base64url_decode(encryption_key_value)
            key_base64_bytes = _aes_gcm_decrypt(raw_key_encrypted, pwd_key)
            encryption_key_value = key_base64_bytes.decode('utf-8')

        # Step 6: Decode the standard base64 key to raw bytes
        raw_key = base64.b64decode(encryption_key_value)
        if len(raw_key) != 32:
            return None, (
                f"Decoded key is {len(raw_key)} bytes, expected 32 bytes (AES-256)"
            )

        return raw_key, None

    except Exception as e:
        return None, f"Failed to decrypt share key blob: {e}"


def decrypt_client_aes_content(
    encrypted_base64: str,
    raw_key: bytes,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Decrypt client-side AES-GCM encrypted content.

    The frontend encrypts message content and embed content as:
      standard_base64( IV[12 bytes] || AES-GCM-ciphertext || tag[16 bytes] )

    This function decodes and decrypts that format.

    Args:
        encrypted_base64: Standard base64 encoded string (IV + ciphertext + tag)
        raw_key: 32-byte AES-256 key (chat key or embed key)

    Returns:
        Tuple of (plaintext_string, error_message). On success, error is None.
    """
    if not encrypted_base64:
        return None, "Empty encrypted content"

    try:
        raw_bytes = base64.b64decode(encrypted_base64)
        plaintext_bytes = _aes_gcm_decrypt(raw_bytes, raw_key)
        return plaintext_bytes.decode('utf-8'), None
    except Exception as e:
        return None, f"AES-GCM decryption failed: {e}"
