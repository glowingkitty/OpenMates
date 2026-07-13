"""
Regression tests for persistence task encryption boundaries.

Directus chat history and sync cache are zero-knowledge storage surfaces. They
may only receive client-encrypted base64 payloads, never Vault/server-side
ciphertext produced by backend AI workers.
"""

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("celery")

from backend.core.api.app.tasks import persistence_tasks
from backend.core.api.app.services import cache as cache_service_module
from backend.core.api.app.services import chat_recovery_service


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
    monkeypatch.setattr(cache_service_module, "CacheService", FakeCacheService)

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


@pytest.mark.anyio
async def test_existing_ai_response_acknowledges_legacy_persistence(monkeypatch) -> None:
    get_message_by_id = AsyncMock(return_value={"id": "message-123"})
    acknowledge = AsyncMock(return_value={"acknowledged": True})

    class FakeDirectusService:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(get_message_by_id=get_message_by_id)

        async def ensure_auth_token(self) -> None:
            return None

    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(
        chat_recovery_service,
        "ChatRecoveryService",
        lambda _directus: SimpleNamespace(execute=acknowledge),
    )

    await persistence_tasks._async_persist_ai_response_to_directus(
        user_id="user-123",
        user_id_hash="user-hash",
        message_data={
            "message_id": "message-123",
            "chat_id": "chat-123",
            "encrypted_content": "client-ciphertext",
        },
        task_id="task-123",
    )

    acknowledge.assert_awaited_once_with(
        "acknowledge_legacy_persistence",
        {"protocol_version": 1, "task_identity": "message-123"},
    )


@pytest.mark.anyio
async def test_existing_ai_response_retries_transient_legacy_acknowledgment_failure(
    monkeypatch,
) -> None:
    get_message_by_id = AsyncMock(return_value={"id": "message-123"})
    acknowledge = AsyncMock(
        side_effect=[RuntimeError("transient acknowledgment failure"), {"acknowledged": True}]
    )

    class FakeDirectusService:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(get_message_by_id=get_message_by_id)

        async def ensure_auth_token(self) -> None:
            return None

    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(
        chat_recovery_service,
        "ChatRecoveryService",
        lambda _directus: SimpleNamespace(execute=acknowledge),
    )
    message_data = {
        "message_id": "message-123",
        "chat_id": "chat-123",
        "encrypted_content": "client-ciphertext",
    }

    with pytest.raises(RuntimeError, match="transient acknowledgment failure"):
        await persistence_tasks._async_persist_ai_response_to_directus(
            user_id="user-123",
            user_id_hash="user-hash",
            message_data=message_data,
            task_id="task-123",
        )

    await persistence_tasks._async_persist_ai_response_to_directus(
        user_id="user-123",
        user_id_hash="user-hash",
        message_data=message_data,
        task_id="task-123",
    )

    assert get_message_by_id.await_count == 2
    assert acknowledge.await_count == 2


@pytest.mark.anyio
async def test_missing_ai_response_ciphertext_does_not_acknowledge_legacy_persistence(
    monkeypatch,
) -> None:
    acknowledge = AsyncMock(return_value={"acknowledged": True})

    class FakeDirectusService:
        async def ensure_auth_token(self) -> None:
            return None

    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(
        chat_recovery_service,
        "ChatRecoveryService",
        lambda _directus: SimpleNamespace(execute=acknowledge),
    )

    await persistence_tasks._async_persist_ai_response_to_directus(
        user_id="user-123",
        user_id_hash="user-hash",
        message_data={"message_id": "message-123", "chat_id": "chat-123"},
        task_id="task-123",
    )

    acknowledge.assert_not_awaited()


@pytest.mark.anyio
async def test_falsy_ai_response_create_result_raises_for_wrapper_retry(monkeypatch) -> None:
    acknowledge = AsyncMock(return_value={"acknowledged": True})

    class FakeDirectusService:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                get_message_by_id=AsyncMock(return_value=None),
                create_message_in_directus=AsyncMock(return_value=None),
            )

        async def ensure_auth_token(self) -> None:
            return None

    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(
        chat_recovery_service,
        "ChatRecoveryService",
        lambda _directus: SimpleNamespace(execute=acknowledge),
    )

    with pytest.raises(RuntimeError, match="did not confirm persistence"):
        await persistence_tasks._async_persist_ai_response_to_directus(
            user_id="user-123",
            user_id_hash="user-hash",
            message_data={
                "message_id": "message-123",
                "chat_id": "chat-123",
                "role": "assistant",
                "encrypted_content": make_client_ciphertext(),
            },
            task_id="task-123",
        )

    acknowledge.assert_not_awaited()


@pytest.mark.anyio
async def test_created_ai_response_acknowledges_legacy_persistence(monkeypatch) -> None:
    acknowledge = AsyncMock(return_value={"acknowledged": True})

    class FakeDirectusService:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                get_message_by_id=AsyncMock(return_value=None),
                create_message_in_directus=AsyncMock(return_value={"id": "message-123"}),
            )

        async def ensure_auth_token(self) -> None:
            return None

    class FakeCacheService:
        async def append_sync_message_to_history(self, **_kwargs) -> None:
            return None

        async def close(self) -> None:
            return None

    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(persistence_tasks, "CacheService", FakeCacheService)
    monkeypatch.setattr(
        chat_recovery_service,
        "ChatRecoveryService",
        lambda _directus: SimpleNamespace(execute=acknowledge),
    )

    await persistence_tasks._async_persist_ai_response_to_directus(
        user_id="user-123",
        user_id_hash="user-hash",
        message_data={
            "message_id": "message-123",
            "chat_id": "chat-123",
            "role": "assistant",
            "encrypted_content": make_client_ciphertext(),
        },
        task_id="task-123",
    )

    acknowledge.assert_awaited_once_with(
        "acknowledge_legacy_persistence",
        {"protocol_version": 1, "task_identity": "message-123"},
    )


@pytest.mark.anyio
async def test_duplicate_ai_response_acknowledges_legacy_persistence(monkeypatch) -> None:
    acknowledge = AsyncMock(return_value={"acknowledged": True})

    class FakeDirectusService:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                get_message_by_id=AsyncMock(return_value=None),
                create_message_in_directus=AsyncMock(
                    side_effect=RuntimeError("duplicate key")
                ),
            )

        async def ensure_auth_token(self) -> None:
            return None

    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(
        chat_recovery_service,
        "ChatRecoveryService",
        lambda _directus: SimpleNamespace(execute=acknowledge),
    )

    await persistence_tasks._async_persist_ai_response_to_directus(
        user_id="user-123",
        user_id_hash="user-hash",
        message_data={
            "message_id": "message-123",
            "chat_id": "chat-123",
            "role": "assistant",
            "encrypted_content": make_client_ciphertext(),
        },
        task_id="task-123",
    )

    acknowledge.assert_awaited_once_with(
        "acknowledge_legacy_persistence",
        {"protocol_version": 1, "task_identity": "message-123"},
    )
