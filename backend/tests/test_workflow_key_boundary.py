"""Workflow key-boundary regression tests.

Workflow runtime payloads are intentionally Automation Vault encrypted server
execution blobs. They must not be reclassified as client-side object wrapper
rows while the unified key-wrapper architecture expands elsewhere.
"""

from pathlib import Path

import pytest

from backend.core.api.app.services.workflow_service import VaultWorkflowPayloadCipher


class FakeEncryptionService:
    async def encrypt_with_user_key(self, plaintext: str, vault_key_id: str):
        return f"vault:v1:{vault_key_id}:{plaintext}", "7"

    async def decrypt_with_user_key(self, ciphertext: str, vault_key_id: str):
        prefix = f"vault:v1:{vault_key_id}:"
        if not ciphertext.startswith(prefix):
            return None
        return ciphertext.removeprefix(prefix)


def test_workflow_payload_cipher_requires_vault_key_reference():
    cipher = VaultWorkflowPayloadCipher(FakeEncryptionService())

    with pytest.raises(RuntimeError, match="requires a user Vault key id"):
        cipher.encrypt_json({"step": "run"}, None)

    encrypted = cipher.encrypt_json({"step": "run"}, "vault-user-key-1")

    assert encrypted["vault_key_ref"] == "vault-user-key-1"
    assert encrypted["key_version"] == "7"
    assert encrypted["ciphertext"].startswith("vault:v1:vault-user-key-1:")
    assert cipher.decrypt_json(encrypted, None) == {"step": "run"}


def test_workflow_blob_schema_stays_vault_not_client_wrapper():
    schema = Path("backend/core/directus/schemas/workflow_encrypted_blobs.yml").read_text()

    assert "vault_key_ref" in schema
    assert "key_version" in schema
    assert "Vault Transit encrypted JSON payload" in schema
    assert "encrypted_object_key" not in schema
    assert "key_type" not in schema
    assert "team_key_epoch" not in schema
