"""Guard against placeholder workflow payload encryption.

Workflow definitions and run content are server-executed sensitive data. The
production path must use the existing Vault Transit encryption service, not a
local hardcoded key, XOR transform, or base64-only obfuscation.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_SERVICE = REPO_ROOT / "backend/core/api/app/services/workflow_service.py"


def test_workflow_service_does_not_use_placeholder_encryption() -> None:
    source = WORKFLOW_SERVICE.read_text(encoding="utf-8")

    forbidden = [
        "openmates-workflows-dev-vault-v1",
        "bytes(byte ^",
        "base64.b64encode(ciphertext)",
        "def _encrypt_payload",
        "def _decrypt_payload",
    ]
    for pattern in forbidden:
        assert pattern not in source

    assert "EncryptionService" in source
    assert "encrypt_with_user_key" in source
    assert "decrypt_with_user_key" in source
