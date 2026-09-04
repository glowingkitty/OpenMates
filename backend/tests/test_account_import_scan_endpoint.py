"""Account Import V1 scan endpoint contract tests.

The route may receive selected plaintext normalized chats for transient scanning,
but it must return sanitized output without writing plaintext Directus records.
"""

from __future__ import annotations

import sys
import types
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

if "redis" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedisClient:
        pass

    redis_asyncio_module.Redis = FakeRedisClient
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

from backend.core.api.app.routes import account_imports
from backend.core.api.app.services.account_import_service import (
    AccountImportService,
    DirectusImportJobStore,
    InMemoryImportLock,
    InMemoryImportJobStore,
)


class FakeImportService:
    def __init__(self) -> None:
        self.directus = SimpleNamespace(create_item=AsyncMock(), update_item=AsyncMock())

    async def scan_selected_chats(self, *, user_id: str, import_id: str, chats: list[dict]) -> dict:
        assert user_id == "user-1"
        assert import_id == "import-1"
        assert chats[0]["messages"][0]["content"] == "Synthetic plaintext selected for scan."
        return {
            "chats": [
                {
                    **chats[0],
                    "messages": [{"role": "user", "content": "Synthetic sanitized content.", "source_message_id": "msg-1"}],
                }
            ],
            "credits_reserved": 1,
            "messages_blocked": [],
            "failures": [],
        }

    @asynccontextmanager
    async def lock_operation(self, **_: object):
        yield

    async def validate_encrypted_persistence(self, **_: object) -> None:
        return None

    async def record_encrypted_persistence(self, **_: object) -> None:
        return None


class FakeChatDirectus:
    def __init__(self) -> None:
        self.created_chats = []
        self.created_messages = []

    async def create_chat_in_directus(self, payload: dict):
        self.created_chats.append(payload)
        return payload, False

    async def create_message_in_directus(self, payload: dict):
        self.created_messages.append(payload)
        return payload

    async def delete_all_messages_for_chat(self, chat_id: str) -> bool:
        self.created_messages = [message for message in self.created_messages if message["chat_id"] != chat_id]
        return True

    async def persist_delete_chat(self, chat_id: str) -> bool:
        self.created_chats = [chat for chat in self.created_chats if chat["id"] != chat_id]
        return True


def _client(service: object, *, credits: int = 0) -> TestClient:
    app = FastAPI()
    app.include_router(account_imports.router)
    app.state.directus_service = SimpleNamespace(chat=FakeChatDirectus())
    app.dependency_overrides[account_imports.get_account_import_service] = lambda: service
    app.dependency_overrides[account_imports.get_current_user_info] = lambda: {
        "user_id": "user-1",
        "credits": credits,
    }
    return TestClient(app)


# contract-test: supporting surface=rest_api assertions=account-import.persistence.client-encrypted,account-import.review.confirmed-results
def test_production_service_factory_wires_scanner_compressor_and_durable_metadata() -> None:
    directus = SimpleNamespace()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        directus_service=directus,
        secrets_manager=SimpleNamespace(),
        cache_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(),
        config_manager=SimpleNamespace(get_model_pricing=lambda *_: {"pricing": {"tokens": {}}}),
        billing_service=SimpleNamespace(cache_service=SimpleNamespace()),
    )))

    service = account_imports.get_account_import_service(request)

    assert service.scanner is not None
    assert service.compressor is not None
    assert service.billing is not None
    assert isinstance(service.job_store, DirectusImportJobStore)
    assert service.require_billing_for_paid is True


# contract-test: direct surface=rest_api assertions=account-import.persistence.client-encrypted,account-import.review.confirmed-results
def test_scan_endpoint_returns_sanitized_messages_without_directus_plaintext_writes() -> None:
    service = FakeImportService()
    response = _client(service).post(
        "/v1/account-imports/import-1/scan",
        json={
            "chats": [
                {
                    "provider": "claude",
                    "source_chat_id": "claude-chat-1",
                    "source_fingerprint": "fingerprint-1",
                    "messages": [{"role": "user", "content": "Synthetic plaintext selected for scan.", "source_message_id": "msg-1"}],
                    "embeds": [],
                    "uploads": [],
                }
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["credits_reserved"] == 1
    assert body["messages_blocked"] == []
    assert body["chats"][0]["messages"][0]["content"] == "Synthetic sanitized content."
    service.directus.create_item.assert_not_awaited()
    service.directus.update_item.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=account-import.review.confirmed-results,account-import.persistence.client-encrypted
def test_real_service_route_flow_preview_confirm_scan_compress_persist_complete() -> None:
    service = AccountImportService(
        scanner=lambda content, **_: {
            "content": f"sanitized:{content}",
            "usage": {"model_id": "provider/scanner", "input_tokens": 1, "output_tokens": 1},
        },
        compressor=AsyncMock(),
        usage_pricer=lambda *_: 0,
        job_store=InMemoryImportJobStore(),
        import_lock=InMemoryImportLock(),
        require_billing_for_paid=True,
    )
    client = _client(service)
    preview = client.post(
        "/v1/account-imports/preview",
        json={
            "source": "claude",
            "chat_count": 1,
            "source_fingerprints": ["fp-1"],
            "estimated_tokens_by_chat": [10],
        },
    )
    assert preview.status_code == 200
    import_id = preview.json()["import_id"]

    confirmation = client.post(
        f"/v1/account-imports/{import_id}/confirm",
        json={"selected_fingerprints": ["fp-1"]},
    )
    assert confirmation.status_code == 200
    scan = client.post(
        f"/v1/account-imports/{import_id}/scan",
        json={
            "batch_id": "scan-0",
            "sequence": 0,
            "final_batch": True,
            "chats": [{
                "source_fingerprint": "fp-1",
                "messages": [{"role": "user", "content": "plaintext"}],
            }],
        },
    )
    assert scan.status_code == 200
    sanitized_messages = scan.json()["chats"][0]["messages"]
    compression = client.post(
        f"/v1/account-imports/{import_id}/compress",
        json={
            "batch_id": "compress-0",
            "sequence": 0,
            "final_batch": True,
            "scan_sequence": 0,
            "source_fingerprint": "fp-1",
            "sanitized_messages": sanitized_messages,
        },
    )
    assert compression.status_code == 200
    persisted = client.post(
        f"/v1/account-imports/{import_id}/persist-encrypted",
        json={"chats": [{
            "chat_id": "chat-1",
            "encrypted_title": "encrypted-title",
            "encrypted_chat_key": "encrypted-key",
            "created_at": 100,
            "updated_at": 101,
            "source_fingerprint": "fp-1",
            "messages": [{
                "message_id": "message-1",
                "role": "user",
                "encrypted_content": "encrypted-content",
                "created_at": 100,
            }],
        }]},
    )
    assert persisted.status_code == 200
    completed = client.post(
        f"/v1/account-imports/{import_id}/complete",
        json={
            "imported_chat_ids": ["chat-1"],
            "source_fingerprints": ["fp-1"],
            "encrypted_record_counts": {"chats": 1, "messages": 1},
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "complete"
    assert "plaintext" not in repr(service.job_store.records)


# contract-test: direct surface=rest_api assertions=account-import.source.explicit-selection
def test_preview_accepts_other_selected_source() -> None:
    response = _client(AccountImportService()).post(
        "/v1/account-imports/preview",
        json={
            "source": "other",
            "chat_count": 1,
            "source_fingerprints": ["fp-1"],
            "estimated_tokens_by_chat": [1],
        },
    )

    assert response.status_code == 200


# contract-test: direct surface=rest_api assertions=account-import.persistence.client-encrypted
def test_persist_encrypted_endpoint_writes_only_client_encrypted_fields() -> None:
    service = FakeImportService()
    client = _client(service)
    directus = client.app.state.directus_service

    response = client.post(
        "/v1/account-imports/import-1/persist-encrypted",
        json={
            "chats": [
                {
                    "chat_id": "chat-1",
                    "encrypted_title": "client-encrypted-title",
                    "encrypted_chat_key": "client-encrypted-key",
                    "created_at": 100,
                    "updated_at": 110,
                    "source_fingerprint": "fingerprint-1",
                    "messages": [
                        {
                            "message_id": "message-1",
                            "role": "assistant",
                            "encrypted_content": "client-encrypted-content",
                            "encrypted_sender_name": "client-encrypted-sender",
                            "encrypted_category": "client-encrypted-category",
                            "encrypted_model_name": "client-encrypted-model",
                            "created_at": 100,
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "complete"
    assert directus.chat.created_chats[0]["encrypted_title"] == "client-encrypted-title"
    assert "title" not in directus.chat.created_chats[0]
    assert directus.chat.created_messages[0]["encrypted_content"] == "client-encrypted-content"
    assert directus.chat.created_messages[0]["encrypted_category"] == "client-encrypted-category"
    assert directus.chat.created_messages[0]["encrypted_model_name"] == "client-encrypted-model"
    assert "content" not in directus.chat.created_messages[0]


# contract-test: direct surface=rest_api assertions=account-import.review.confirmed-results,account-import.persistence.client-encrypted
def test_persist_encrypted_rolls_back_chat_when_any_message_write_fails() -> None:
    service = FakeImportService()
    client = _client(service)
    directus = client.app.state.directus_service
    directus.chat.create_message_in_directus = AsyncMock(side_effect=[{"id": "message-1"}, None])
    service.validate_encrypted_persistence = AsyncMock(return_value=None)
    service.record_encrypted_persistence = AsyncMock(return_value=None)
    client.app.dependency_overrides[account_imports.get_account_import_service] = lambda: service

    response = client.post(
        "/v1/account-imports/import-1/persist-encrypted",
        json={"chats": [{
            "chat_id": "chat-1", "encrypted_title": "encrypted", "encrypted_chat_key": "key",
            "created_at": 100, "updated_at": 101, "source_fingerprint": "fp-1",
            "messages": [
                {"message_id": "message-1", "role": "user", "encrypted_content": "one", "created_at": 100},
                {"message_id": "message-2", "role": "assistant", "encrypted_content": "two", "created_at": 101},
            ],
        }]},
    )

    assert response.status_code == 200
    assert response.json()["imported_chat_ids"] == []
    assert response.json()["encrypted_record_counts"] == {"chats": 0, "messages": 0}
    assert response.json()["failures"][0]["reason"] == "message_create_failed"


# contract-test: direct surface=rest_api assertions=account-import.review.confirmed-results,account-import.persistence.client-encrypted
def test_persist_encrypted_rolls_back_request_when_metadata_acknowledgement_fails() -> None:
    service = FakeImportService()
    service.record_encrypted_persistence = AsyncMock(side_effect=RuntimeError("metadata unavailable"))
    client = _client(service)
    directus = client.app.state.directus_service

    response = client.post(
        "/v1/account-imports/import-1/persist-encrypted",
        json={"chats": [
            {
                "chat_id": "chat-1", "encrypted_title": "encrypted-1", "encrypted_chat_key": "key-1",
                "created_at": 100, "updated_at": 101, "source_fingerprint": "fp-1", "messages": [],
            },
            {
                "chat_id": "chat-2", "encrypted_title": "encrypted-2", "encrypted_chat_key": "key-2",
                "created_at": 102, "updated_at": 103, "source_fingerprint": "fp-2", "messages": [],
            },
        ]},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Encrypted import metadata acknowledgement failed; persisted chats were rolled back"
    assert directus.chat.created_chats == []
    assert directus.chat.created_messages == []


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["openmates", "chatgpt", "claude", "gemini", "opencode", "other"])
# contract-test: direct surface=rest_api assertions=account-import.source.explicit-selection,account-import.persistence.client-encrypted
async def test_all_roles_and_sources_are_scanned_message_by_message(source: str) -> None:
    calls: list[tuple[str, str]] = []

    async def scanner(content: str, *, role: str, **_: object) -> dict:
        calls.append((role, content))
        return {"content": f"sanitized:{content}", "usage": {"credits": 1}}

    service = AccountImportService(scanner=scanner, job_store=InMemoryImportJobStore())
    result = await service.scan_import_batch(
        user_id="user-1",
        import_id=f"import-{source}",
        batch_id="batch-0",
        sequence=0,
        final_batch=True,
        chats=[{
            "provider": source,
            "messages": [
                {"role": "user", "content": "user text"},
                {"role": "assistant", "content": "assistant text"},
                {"role": "system", "content": "system text"},
                {"role": "assistant", "content": "   "},
            ],
        }],
    )

    assert calls == [("user", "user text"), ("assistant", "assistant text"), ("system", "system text")]
    assert [message["content"] for message in result["chats"][0]["messages"]] == [
        "sanitized:user text", "sanitized:assistant text", "sanitized:system text", "   ",
    ]
    assert result["status"] == "acknowledged"
    assert result["usage"]["credits"] == 3
