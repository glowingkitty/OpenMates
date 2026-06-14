"""
Regression tests for persistence task encryption boundaries.

Directus chat history and sync cache are zero-knowledge storage surfaces. They
may only receive client-encrypted base64 payloads, never Vault/server-side
ciphertext produced by backend AI workers.
"""

import asyncio
import base64

import pytest

pytest.importorskip("celery")

from backend.core.api.app.tasks import persistence_tasks


def make_client_ciphertext() -> str:
    raw = b"OM" + bytes.fromhex("1a5b3b7c") + (b"0" * 12) + b"ciphertext-ok"
    return base64.b64encode(raw).decode("ascii")


def test_persist_new_chat_message_rejects_vault_ciphertext_before_side_effects(monkeypatch, doc_assert):
    doc_assert("chat-persistence-rejects-vault-ciphertext")
    touched_directus = False
    touched_cache = False

    class FakeDirectusService:
        def __init__(self) -> None:
            nonlocal touched_directus
            touched_directus = True

    class FakeCacheService:
        def __init__(self) -> None:
            nonlocal touched_cache
            touched_cache = True

    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(persistence_tasks, "CacheService", FakeCacheService)

    with pytest.raises(ValueError, match="client-encrypted base64"):
        asyncio.run(
            persistence_tasks._async_persist_new_chat_message_task(
                message_id="compression_bad123",
                chat_id="chat-123",
                hashed_user_id="user-hash",
                role="system",
                encrypted_content="vault:v1:not-client-ciphertext",
                created_at=1_779_399_620,
                task_id="test-task",
                user_id="user-123",
            )
        )

    assert touched_directus is False
    assert touched_cache is False


def test_persist_new_chat_message_accepts_client_encrypted_base64(doc_assert):
    doc_assert("chat-persistence-accepts-client-encrypted-base64")
    assert persistence_tasks._validate_client_encrypted_chat_payload(
        message_id="client-message-123",
        encrypted_content=make_client_ciphertext(),
    ) is None
