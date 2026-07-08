"""Test helpers for Workflows V1 persistence tests.

These helpers keep unit tests independent from HashiCorp Vault while preserving
the production contract that workflow payloads are encrypted before repository
storage. Production code defaults to VaultWorkflowPayloadCipher and does not use
this module.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.api.app.services.workflow_service import WorkflowService


class FakeWorkflowPayloadCipher:
    """AES-GCM test cipher with the same JSON/checksum contract as Vault blobs."""

    requires_vault_key_id = False

    def __init__(self) -> None:
        self._aesgcm = AESGCM(b"\x42" * 32)

    def encrypt_json(self, payload: Any, vault_key_id: str | None) -> dict[str, str]:
        del vault_key_id
        plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        return {
            "ciphertext": base64.b64encode(nonce + ciphertext).decode("ascii"),
            "checksum": "sha256:" + hashlib.sha256(plaintext).hexdigest(),
            "vault_key_ref": "test-vault-key",
            "key_version": "test",
        }

    def decrypt_json(self, blob: dict[str, Any], vault_key_id: str | None) -> Any:
        del vault_key_id
        encrypted = base64.b64decode(str(blob["ciphertext"]).encode("ascii"))
        plaintext = self._aesgcm.decrypt(encrypted[:12], encrypted[12:], None)
        checksum = "sha256:" + hashlib.sha256(plaintext).hexdigest()
        if blob.get("checksum") != checksum:
            raise AssertionError("test workflow payload checksum mismatch")
        return json.loads(plaintext.decode("utf-8"))


def workflow_service(**kwargs: Any) -> WorkflowService:
    kwargs.setdefault("payload_cipher", FakeWorkflowPayloadCipher())
    return WorkflowService(**kwargs)
