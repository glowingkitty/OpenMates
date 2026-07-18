"""IdeaBucket processing-window cache contract tests.

These tests pin the privacy-critical storage rule for IdeaBucket scheduled
processing: server-processable payloads live only in Redis/cache, use latest
version replacement, and are never represented through Directus persistence.
"""

import pytest

from backend.core.api.app.services.cache import CacheService


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, int] = {}

    async def eval(self, script, _numkeys, key, *args):
        if "processing_started_at" in script:
            now = int(args[0])
            lock_token = str(args[1])
            ttl = int(args[2])
            payload = self.store.get(key)
            if not payload:
                return []
            if payload.get("status") == "sent":
                return self._hgetall_list(key)
            if payload.get("status") not in {"active", "failed"}:
                return []
            if int(payload.get("scheduled_send_at") or 0) > now:
                return []
            payload["status"] = "processing"
            payload["processing_started_at"] = str(now)
            payload["lock_token"] = lock_token
            self.ttls[key] = ttl
            return self._hgetall_list(key)

        if "user_message_id" in script:
            lock_token = str(args[0])
            payload = self.store.get(key)
            if payload and payload.get("status") == "sent":
                return 1
            if not payload or payload.get("status") != "processing" or payload.get("lock_token") != lock_token:
                return 0
            payload["status"] = "sent"
            payload["user_message_id"] = str(args[1])
            payload["system_event_id"] = str(args[2])
            payload["sent_at"] = str(args[3])
            payload.pop("lock_token", None)
            self.ttls[key] = int(args[4])
            return 1

        if "failed_at" in script:
            lock_token = str(args[0])
            payload = self.store.get(key)
            if not payload or payload.get("status") != "processing" or payload.get("lock_token") != lock_token:
                return 0
            payload["status"] = "failed"
            payload["failed_at"] = str(args[1])
            payload["error_code"] = str(args[2])
            payload.pop("lock_token", None)
            self.ttls[key] = int(args[3])
            return 1

        version = int(args[0])
        current_version = int(self.store.get(key, {}).get("version") or 0)
        if current_version and version <= current_version:
            return 0

        fields = list(args[1:-1])
        ttl = int(args[-1])
        payload = {str(fields[index]): str(fields[index + 1]) for index in range(0, len(fields), 2)}
        self.store[key] = payload
        self.ttls[key] = ttl
        return 1

    async def hgetall(self, key):
        return {
            field.encode("utf-8"): value.encode("utf-8")
            for field, value in self.store.get(key, {}).items()
        }

    def _hgetall_list(self, key):
        values = []
        for field, value in self.store.get(key, {}).items():
            values.extend([field.encode("utf-8"), value.encode("utf-8")])
        return values


@pytest.mark.anyio
async def test_ideabucket_processing_window_replaces_latest_payload_without_directus() -> None:
    service = CacheService()
    fake = _FakeRedis()
    service._client = fake

    first = await service.replace_ideabucket_processing_window_in_cache(
        "user-1",
        "window-1",
        version=1,
        chat_id="chat-1",
        scheduled_send_at=123,
        server_vault_encrypted_processing_payload="server-cipher-v1",
        client_encrypted_future_user_message="client-cipher-v1",
        client_encrypted_ideabucket_system_event="system-cipher-v1",
        payload_hash="hash-v1",
    )
    second = await service.replace_ideabucket_processing_window_in_cache(
        "user-1",
        "window-1",
        version=2,
        chat_id="chat-1",
        scheduled_send_at=123,
        server_vault_encrypted_processing_payload="server-cipher-v2",
        client_encrypted_future_user_message="client-cipher-v2",
        client_encrypted_ideabucket_system_event="system-cipher-v2",
        payload_hash="hash-v2",
    )

    cached = await service.get_ideabucket_processing_window_from_cache("user-1", "window-1")

    assert first is True
    assert second is True
    assert cached == {
        "processing_window_id": "window-1",
        "chat_id": "chat-1",
        "version": 2,
        "scheduled_send_at": 123,
        "status": "active",
        "server_vault_encrypted_processing_payload": "server-cipher-v2",
        "client_encrypted_future_user_message": "client-cipher-v2",
        "client_encrypted_ideabucket_system_event": "system-cipher-v2",
        "payload_hash": "hash-v2",
    }
    assert "server-cipher-v1" not in str(fake.store)


@pytest.mark.anyio
async def test_ideabucket_processing_window_rejects_stale_versions() -> None:
    service = CacheService()
    fake = _FakeRedis()
    service._client = fake

    assert await service.replace_ideabucket_processing_window_in_cache(
        "user-1",
        "window-1",
        version=3,
        chat_id="chat-1",
        scheduled_send_at=123,
        server_vault_encrypted_processing_payload="server-cipher-v3",
        client_encrypted_future_user_message="client-cipher-v3",
        client_encrypted_ideabucket_system_event="system-cipher-v3",
        payload_hash="hash-v3",
    ) is True

    assert await service.replace_ideabucket_processing_window_in_cache(
        "user-1",
        "window-1",
        version=2,
        chat_id="chat-1",
        scheduled_send_at=123,
        server_vault_encrypted_processing_payload="server-cipher-v2",
        client_encrypted_future_user_message="client-cipher-v2",
        client_encrypted_ideabucket_system_event="system-cipher-v2",
        payload_hash="hash-v2",
    ) is False

    cached = await service.get_ideabucket_processing_window_from_cache("user-1", "window-1")

    assert cached["version"] == 3
    assert cached["server_vault_encrypted_processing_payload"] == "server-cipher-v3"
    assert cached["client_encrypted_future_user_message"] == "client-cipher-v3"


@pytest.mark.anyio
async def test_ideabucket_processing_window_locks_only_due_payload() -> None:
    service = CacheService()
    fake = _FakeRedis()
    service._client = fake

    await service.replace_ideabucket_processing_window_in_cache(
        "user-1",
        "window-1",
        version=1,
        chat_id="chat-1",
        scheduled_send_at=200,
        server_vault_encrypted_processing_payload="server-cipher-v1",
        client_encrypted_future_user_message="client-cipher-v1",
        client_encrypted_ideabucket_system_event="system-cipher-v1",
        payload_hash="hash-v1",
    )

    assert await service.lock_due_ideabucket_processing_window_in_cache(
        "user-1",
        "window-1",
        now=199,
        lock_token="lock-1",
    ) is None

    locked = await service.lock_due_ideabucket_processing_window_in_cache(
        "user-1",
        "window-1",
        now=200,
        lock_token="lock-1",
    )

    assert locked["status"] == "processing"
    assert locked["version"] == 1
    assert locked["processing_started_at"] == 200


@pytest.mark.anyio
async def test_ideabucket_processing_window_tombstones_sent_payload() -> None:
    service = CacheService()
    fake = _FakeRedis()
    service._client = fake

    await service.replace_ideabucket_processing_window_in_cache(
        "user-1",
        "window-1",
        version=1,
        chat_id="chat-1",
        scheduled_send_at=123,
        server_vault_encrypted_processing_payload="server-cipher-v1",
        client_encrypted_future_user_message="client-cipher-v1",
        client_encrypted_ideabucket_system_event="system-cipher-v1",
        payload_hash="hash-v1",
    )
    await service.lock_due_ideabucket_processing_window_in_cache(
        "user-1",
        "window-1",
        now=123,
        lock_token="lock-1",
    )

    assert await service.mark_ideabucket_processing_window_sent_in_cache(
        "user-1",
        "window-1",
        lock_token="lock-1",
        user_message_id="user-message-1",
        system_event_id="system-event-1",
        sent_at=124,
    ) is True
    cached = await service.get_ideabucket_processing_window_from_cache("user-1", "window-1")

    assert cached["status"] == "sent"
    assert cached["user_message_id"] == "user-message-1"
    assert cached["system_event_id"] == "system-event-1"
    assert "lock_token" not in cached
