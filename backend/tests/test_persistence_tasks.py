"""
Regression tests for persistence task encryption boundaries.

Directus chat history and sync cache are zero-knowledge storage surfaces. They
may only receive client-encrypted base64 payloads, never Vault/server-side
ciphertext produced by backend AI workers.
"""

import asyncio
import base64
import json
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


# contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted
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


# contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted
def test_persist_new_chat_message_accepts_client_encrypted_base64(doc_assert):
    doc_assert("chat-persistence-accepts-client-encrypted-base64")
    assert persistence_tasks._validate_client_encrypted_chat_payload(
        message_id="client-message-123",
        encrypted_content=make_client_ciphertext(),
    ) is None


@pytest.mark.parametrize(
    ("encrypted_pii_mappings", "expected_persisted"),
    [
        ("123e4567-e89b-12d3-a456-426614174000", False),
        (make_client_ciphertext(), True),
    ],
)
# contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
def test_persist_new_chat_message_sanitizes_optional_encrypted_pii_mappings(
    monkeypatch,
    encrypted_pii_mappings: str,
    expected_persisted: bool,
):
    cached_messages: list[dict] = []
    directus_messages: list[dict] = []

    class FakeCacheService:
        async def append_sync_message_to_history(
            self,
            *,
            user_id: str,
            chat_id: str,
            encrypted_message_json: str,
            ttl: int,
        ) -> None:
            cached_messages.append(json.loads(encrypted_message_json))

        async def close(self) -> None:
            return None

    class FakeChatService:
        async def get_chat_metadata(self, chat_id: str) -> dict:
            return {"id": chat_id}

        async def message_exists_by_client_message_id(self, message_id: str) -> bool:
            return False

        async def create_message_in_directus(self, message_data: dict) -> dict:
            directus_messages.append(dict(message_data))
            return {"id": message_data["id"]}

        async def update_chat_fields_in_directus(
            self,
            *,
            chat_id: str,
            fields_to_update: dict,
        ) -> dict:
            return {"id": chat_id, **fields_to_update}

    class FakeDirectusService:
        def __init__(self) -> None:
            self.chat = FakeChatService()

        async def ensure_auth_token(self) -> None:
            return None

    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(cache_service_module, "CacheService", FakeCacheService)

    asyncio.run(
        persistence_tasks._async_persist_new_chat_message_task(
            message_id="message-123",
            chat_id="chat-123",
            hashed_user_id="user-hash",
            role="user",
            encrypted_content=make_client_ciphertext(),
            created_at=1_779_399_620,
            task_id="test-task",
            user_id="user-123",
            encrypted_pii_mappings=encrypted_pii_mappings,
        )
    )

    assert len(cached_messages) == 1
    assert len(directus_messages) == 1
    assert ("encrypted_pii_mappings" in cached_messages[0]) is expected_persisted
    assert ("encrypted_pii_mappings" in directus_messages[0]) is expected_persisted
    if expected_persisted:
        assert cached_messages[0]["encrypted_pii_mappings"] == encrypted_pii_mappings
        assert directus_messages[0]["encrypted_pii_mappings"] == encrypted_pii_mappings


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
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
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
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
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
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

    with pytest.raises(ValueError, match="missing encrypted_content"):
        await persistence_tasks._async_persist_ai_response_to_directus(
            user_id="user-123",
            user_id_hash="user-hash",
            message_data={"message_id": "message-123", "chat_id": "chat-123"},
            task_id="task-123",
        )

    acknowledge.assert_not_awaited()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
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
# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
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
# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
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
