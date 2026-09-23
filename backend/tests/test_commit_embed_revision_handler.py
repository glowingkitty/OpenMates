"""Focused WebSocket contract tests for atomic hosted Project revisions."""

import sys
import types

import pytest

redis_stub = types.ModuleType("redis")
redis_asyncio_stub = types.ModuleType("redis.asyncio")
redis_asyncio_stub.Redis = object
redis_stub.asyncio = redis_asyncio_stub
redis_stub.exceptions = types.SimpleNamespace(RedisError=Exception, ConnectionError=Exception)
sys.modules.setdefault("redis", redis_stub)
sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)

cache_module_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_module_stub.CacheService = object
directus_module_stub = types.ModuleType("backend.core.api.app.services.directus.directus")
directus_module_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_module_stub)
sys.modules.setdefault("backend.core.api.app.services.directus.directus", directus_module_stub)

from backend.core.api.app.routes.handlers.websocket_handlers import (  # noqa: E402
    commit_embed_revision_handler as handler,
)


class FakeManager:
    def __init__(self):
        self.personal = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device_hash):
        self.personal.append((message, user_id, device_hash))

    async def broadcast_to_user(self, message, user_id, exclude_device_hash):
        self.broadcasts.append((message, user_id, exclude_device_hash))


def commit_payload():
    return {
        "request_id": "request-1",
        "operation_id": "operation-1",
        "embed_id": "embed-1",
        "project_id": "project-1",
        "chat_id": "chat-1",
        "proposal_digest": "a" * 64,
        "expected_revision": 1,
        "head": {"encrypted_content": "cipher-head-v2"},
        "history_rows": [{
            "version_number": 2,
            "encrypted_snapshot": None,
            "encrypted_patch": "cipher-patch-v2",
            "created_at": 2,
        }],
    }


# contract-test: direct surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.files.chat-focus-required,projects.files.write-policy-enforcement
@pytest.mark.asyncio
async def test_commit_runs_fresh_shared_authorization_then_atomic_transaction(monkeypatch):
    manager = FakeManager()
    calls = []

    class FakeAuthorization:
        def __init__(self, directus_service, cache_service):
            calls.append(("authorization_init", directus_service, cache_service))

        async def require_write_authorization(self, **kwargs):
            calls.append(("authorize", kwargs))
            return {"authorized": True}

    class FakeTransaction:
        def __init__(self, directus_service):
            calls.append(("transaction_init", directus_service))

        async def commit(self, data, *, user_id):
            calls.append(("commit", data, user_id))
            return {"status": "committed", "current_revision": 2, "idempotent": False}

    monkeypatch.setattr(handler, "ProjectWriteAuthorizationService", FakeAuthorization)
    monkeypatch.setattr(handler, "EmbedVersionTransactionService", FakeTransaction)
    payload = commit_payload()

    await handler.handle_commit_embed_revision(
        manager=manager,
        cache_service="cache",
        directus_service="directus",
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload=payload,
    )

    assert calls[1][0] == "transaction_init"
    assert calls[2][0] == "authorize"
    assert calls[2][1]["consume_approval"] is True
    assert calls[3][0] == "commit"
    assert "request_id" not in calls[3][1]
    assert calls[3][2] == "user-1"
    assert manager.personal[0][0] == {
        "type": "commit_embed_revision_result",
        "payload": {
            "request_id": "request-1",
            "operation_id": "operation-1",
            "embed_id": "embed-1",
            "status": "committed",
            "current_revision": 2,
        },
    }
    assert len(manager.broadcasts) == 1


# contract-test: supporting surface=rest_api assertions=projects.files.chat-focus-required,projects.files.write-policy-enforcement
@pytest.mark.asyncio
async def test_commit_rejects_when_fresh_project_focus_authorization_fails(monkeypatch):
    manager = FakeManager()

    class FakeAuthorization:
        def __init__(self, directus_service, cache_service):
            pass

        async def require_write_authorization(self, **kwargs):
            raise handler.ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUIRED")

    class NeverTransaction:
        def __init__(self, directus_service):
            pass

        async def commit(self, data, *, user_id):
            raise AssertionError("unauthorized commit reached transaction")

    monkeypatch.setattr(handler, "ProjectWriteAuthorizationService", FakeAuthorization)
    monkeypatch.setattr(handler, "EmbedVersionTransactionService", NeverTransaction)

    await handler.handle_commit_embed_revision(
        manager=manager,
        cache_service="cache",
        directus_service="directus",
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload=commit_payload(),
    )

    assert manager.personal[0][0]["payload"]["status"] == "rejected"
    assert manager.personal[0][0]["payload"]["code"] == "PROJECT_FOCUS_REQUIRED"
    assert manager.broadcasts == []
