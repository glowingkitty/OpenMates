"""IdeaBucket encrypted route guardrail tests.

Purpose: ensure IdeaBucket endpoints reject private cleartext fields.
Architecture: docs/specs/ideabucket-mvp/spec.yml.
Security: encrypted add routes must never accept idea text, prompts,
transcripts, markdown, or server-processable plaintext payloads.
Run: docker exec api pytest /app/backend/tests/test_ideabucket_encrypted_routes.py
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.core.api.app.routes.ideabucket import (
    IdeaBucketEncryptedAddRequest,
    reject_ideabucket_cleartext_payload,
)


def _valid_encrypted_add_payload() -> dict[str, object]:
    return {
        "chat_id": "chat-1",
        "encrypted_draft_md": "cipher-draft",
        "encrypted_draft_preview": "cipher-preview",
        "ideabucket": True,
        "ideabucket_processing_window_id": "2026-07-18",
        "ideabucket_processing_version": 1,
        "encrypted_chat_key": "cipher-chat-key",
        "scheduled_send_at": 1,
        "server_vault_encrypted_processing_payload": "cipher-processing",
        "client_encrypted_future_user_message": "cipher-user-message",
        "client_encrypted_ideabucket_system_event": "cipher-system-event",
        "payload_hash": "hash",
    }


def test_ideabucket_cleartext_guard_rejects_private_fields():
    with pytest.raises(HTTPException) as exc_info:
        reject_ideabucket_cleartext_payload({"text": "secret idea", "prompt": "private prompt"})

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "ideabucket_cleartext_rejected"
    assert exc_info.value.detail["fields"] == ["prompt", "text"]


def test_ideabucket_encrypted_add_schema_forbids_cleartext_extras():
    payload = {**_valid_encrypted_add_payload(), "markdown": "secret draft"}

    with pytest.raises(ValidationError):
        IdeaBucketEncryptedAddRequest(**payload)


def test_ideabucket_encrypted_add_schema_accepts_ciphertext_only_payload():
    request = IdeaBucketEncryptedAddRequest(**_valid_encrypted_add_payload())

    assert request.chat_id == "chat-1"
    assert request.encrypted_chat_key == "cipher-chat-key"
    assert request.ideabucket_processing_window_id == "2026-07-18"
