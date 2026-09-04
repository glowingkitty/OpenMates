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


# contract-test: supporting surface=rest_api assertions=code-run.artifacts.chat-bound-versioned,chats.message.identity-idempotent
def test_embed_fallback_requires_persisting_a_newer_cached_version() -> None:
    assert persistence_tasks._persisted_embed_snapshot_is_current(
        {"version_number": 1},
        {"version_number": 2},
    ) is False
    assert persistence_tasks._persisted_embed_snapshot_is_current(
        {"version_number": 2},
        {"version_number": 2},
    ) is True


# contract-test: supporting surface=rest_api assertions=code-run.artifacts.chat-bound-versioned,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_embed_fallback_resends_newer_cached_version(monkeypatch) -> None:
    published: list[tuple[str, dict]] = []
    cached_embed = {
        "embed_id": "embed-1",
        "type": "application",
        "status": "finished",
        "chat_id": "chat-1",
        "message_id": "message-1",
        "user_id": "user-1",
        "hashed_user_id": "user-hash",
        "vault_key_id": "vault-1",
        "encrypted_content": "vault-ciphertext",
        "version_number": 2,
    }

    class FakeRedis:
        async def get(self, key: str):
            assert key == "embed:embed-1"
            return json.dumps(cached_embed)

        async def publish(self, channel: str, message: str):
            published.append((channel, json.loads(message)))
            return 1

    class FakeCacheService:
        @property
        def client(self):
            async def get_client():
                return FakeRedis()

            return get_client()

        async def close(self) -> None:
            return None

    class FakeDirectusService:
        def __init__(self):
            self.embed = SimpleNamespace(get_embed_by_id=AsyncMock(return_value={"version_number": 1}))

        async def ensure_auth_token(self):
            return True

    class FakeEncryptionService:
        def __init__(self, **_kwargs):
            pass

        async def decrypt_with_user_key(self, _ciphertext: str, _vault_key_id: str):
            return "type: application"

    monkeypatch.setattr(persistence_tasks, "CacheService", FakeCacheService)
    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(persistence_tasks, "EncryptionService", FakeEncryptionService)

    await persistence_tasks._async_persist_embed_fallback("embed-1", "task-1")

    assert published[0][0] == "websocket:user:user-hash"
    assert published[0][1]["payload"]["version_number"] == 2


# contract-test: infrastructure
def test_pending_embed_safety_net_is_time_bounded_and_messages_expire() -> None:
    task = persistence_tasks.process_pending_embeds_task
    schedule = persistence_tasks.app.conf.beat_schedule["process-pending-embeds"]
    interval_seconds = schedule["schedule"].total_seconds()

    assert task.soft_time_limit == persistence_tasks.PENDING_EMBED_SOFT_TIME_LIMIT_SECONDS
    assert task.time_limit == persistence_tasks.PENDING_EMBED_HARD_TIME_LIMIT_SECONDS
    assert task.soft_time_limit < task.time_limit < interval_seconds
    assert schedule["options"]["expires"] == task.time_limit
    assert (
        persistence_tasks.PENDING_EMBED_SINGLE_FLIGHT_TTL_SECONDS
        == persistence_tasks.PENDING_EMBED_HARD_TIME_LIMIT_SECONDS
    )


# contract-test: infrastructure
def test_pending_embed_user_selection_is_bounded_and_round_robin() -> None:
    user_ids = [f"user-{index:02d}" for index in range(25)]

    first_batch = persistence_tasks._select_round_robin(
        user_ids,
        None,
        persistence_tasks.PENDING_EMBED_MAX_USERS_PER_RUN,
    )
    second_batch = persistence_tasks._select_round_robin(
        user_ids,
        first_batch[-1],
        persistence_tasks.PENDING_EMBED_MAX_USERS_PER_RUN,
    )

    assert first_batch == user_ids[:persistence_tasks.PENDING_EMBED_MAX_USERS_PER_RUN]
    assert second_batch[:5] == user_ids[20:]
    assert second_batch[5:] == user_ids[:15]


# contract-test: infrastructure
def test_pending_embed_safety_net_coalesces_duplicate_runs(monkeypatch) -> None:
    class FakeRedis:
        async def set(self, key: str, value: str, **kwargs):
            assert key == persistence_tasks.PENDING_EMBED_SINGLE_FLIGHT_KEY
            assert kwargs == {
                "nx": True,
                "ex": persistence_tasks.PENDING_EMBED_SINGLE_FLIGHT_TTL_SECONDS,
            }
            return False

    class FakeCacheService:
        @property
        def client(self):
            async def get_client():
                return FakeRedis()

            return get_client()

        async def get_all_users_with_pending_embeds(self):
            raise AssertionError("duplicate run must stop before scanning pending users")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(persistence_tasks, "CacheService", FakeCacheService)

    asyncio.run(persistence_tasks._async_process_pending_embeds("duplicate-task"))


# contract-test: infrastructure
def test_pending_embed_safety_net_bounds_each_user_batch(monkeypatch) -> None:
    pending_ids = [f"embed-{index}" for index in range(12)]
    removed_ids: list[str] = []

    class FakeRedis:
        async def set(self, key: str, value: str, **kwargs):
            return True

        async def get(self, key: str):
            return None

    class FakeCacheService:
        def __init__(self) -> None:
            self.redis = FakeRedis()

        @property
        def client(self):
            async def get_client():
                return self.redis

            return get_client()

        async def get_all_users_with_pending_embeds(self) -> list[str]:
            return ["user-1"]

        async def get_pending_embed_ids(self, user_id: str) -> list[str]:
            return pending_ids

        async def remove_pending_embed(self, user_id: str, embed_id: str) -> bool:
            removed_ids.append(embed_id)
            return True

        async def close(self) -> None:
            return None

    class FakeEmbedMethods:
        async def get_embed_by_id(self, embed_id: str):
            return None

    class FakeDirectusService:
        def __init__(self) -> None:
            self.embed = FakeEmbedMethods()

        async def ensure_auth_token(self) -> None:
            return None

    class FakeEncryptionService:
        def __init__(self, cache_service) -> None:
            pass

    monkeypatch.setattr(persistence_tasks, "CacheService", FakeCacheService)
    monkeypatch.setattr(persistence_tasks, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(persistence_tasks, "EncryptionService", FakeEncryptionService)

    asyncio.run(persistence_tasks._async_process_pending_embeds("task-1"))

    expected = persistence_tasks._select_round_robin(
        pending_ids,
        None,
        persistence_tasks.PENDING_EMBED_BATCH_SIZE_PER_USER,
    )
    assert removed_ids == expected


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
