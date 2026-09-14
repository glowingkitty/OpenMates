"""Workflow key-boundary regression tests.

Workflow runtime payloads are intentionally Automation Vault encrypted server
execution blobs. They must not be reclassified as client-side object wrapper
rows while the unified key-wrapper architecture expands elsewhere.
"""

from datetime import date, datetime, timezone
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


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained,workflows.access.boundaries
def test_workflow_payload_cipher_requires_vault_key_reference():
    cipher = VaultWorkflowPayloadCipher(FakeEncryptionService())

    with pytest.raises(RuntimeError, match="requires a user Vault key id"):
        cipher.encrypt_json({"step": "run"}, None)

    encrypted = cipher.encrypt_json({"step": "run"}, "vault-user-key-1")

    assert encrypted["vault_key_ref"] == "vault-user-key-1"
    assert encrypted["key_version"] == "7"
    assert encrypted["ciphertext"].startswith("vault:v1:vault-user-key-1:")
    assert cipher.decrypt_json(encrypted, None) == {"step": "run"}


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained
def test_workflow_payload_cipher_serializes_dates_canonically():
    cipher = VaultWorkflowPayloadCipher(FakeEncryptionService())

    encrypted = cipher.encrypt_json(
        {
            "start_date": date(2026, 9, 14),
            "started_at": datetime(2026, 9, 14, 6, 30, tzinfo=timezone.utc),
        },
        "vault-user-key-1",
    )

    assert cipher.decrypt_json(encrypted, None) == {
        "start_date": "2026-09-14",
        "started_at": "2026-09-14T06:30:00+00:00",
    }


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained
def test_workflow_payload_cipher_rejects_unknown_python_objects():
    cipher = VaultWorkflowPayloadCipher(FakeEncryptionService())

    with pytest.raises(TypeError, match="Object of type object is not JSON serializable"):
        cipher.encrypt_json({"unexpected": object()}, "vault-user-key-1")


# contract-test: supporting surface=rest_api assertions=workflows.content.encrypted-retained
def test_workflow_blob_schema_stays_vault_not_client_wrapper():
    backend_root = Path(__file__).resolve().parents[1]
    schema = (backend_root / "core/directus/schemas/workflow_encrypted_blobs.yml").read_text()

    assert "vault_key_ref" in schema
    assert "key_version" in schema
    assert "Vault Transit encrypted JSON payload" in schema
    assert "encrypted_object_key" not in schema
    assert "key_type" not in schema
    assert "team_key_epoch" not in schema
