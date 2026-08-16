"""Structural validation for client-encrypted chat payloads.

OpenMates clients encode AES-GCM envelopes as base64 containing a 12-byte nonce,
at least one ciphertext byte, and a 16-byte authentication tag. This validation
does not decrypt content; it only rejects obvious plaintext or malformed blobs.
"""

import base64
import binascii


MIN_CLIENT_ENCRYPTED_PAYLOAD_BYTES = 29


def is_client_encrypted_base64(value: str) -> bool:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(decoded) >= MIN_CLIENT_ENCRYPTED_PAYLOAD_BYTES


def validate_client_encrypted_chat_payload(message_id: str, encrypted_content: str) -> None:
    if not encrypted_content:
        raise ValueError(f"Message {message_id} is missing client-encrypted base64 content.")
    if not is_client_encrypted_base64(encrypted_content):
        raise ValueError(f"Message {message_id} must contain a valid client-encrypted base64 envelope.")
