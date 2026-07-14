# backend/tests/test_task_update_jobs.py
#
# Red-phase protocol tests for Tasks V1 client-encrypted update jobs. The server
# may lease a vault-encrypted working copy to one authenticated device, but the
# terminal commit must contain only client-encrypted task fields and must be
# idempotent for retrying clients.

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.task_update_job_handlers import (
    TASK_EVENT_CONFIRMATION_RECOVERY_TTL_SECONDS,
    handle_task_update_job_persist,
    handle_task_update_job_event_confirmed,
    system_message_confirmation_cache_key,
)
from backend.apps.ai.processing.task_tool_executor import TASK_TOOL_JOB_CACHE_PREFIX
from backend.core.api.app.services.directus.user_task_methods import hash_id
from backend.core.api.app.services.user_task_update_job_service import (
    TaskUpdateJobConflictError,
    TaskUpdateJobNotFoundError,
    UserTaskUpdateJobService,
)


class FakeManager:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_personal_message(self, message: dict, _user_id: str, _device_hash: str) -> None:
        self.messages.append(message)


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.client_value = FakeLockClient()

    @property
    def client(self):
        return self._client()

    async def _client(self):
        return self.client_value

    async def get(self, key: str) -> object | None:
        return self.values.get(key)

    async def set(self, key: str, value: object, ttl: int | None = None) -> bool:
        self.values[key] = value
        return True


class FakeLockClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


def test_task_update_job_claim_binds_lease_to_owner_and_device() -> None:
    service = UserTaskUpdateJobService(clock=lambda: 100, lease_ttl_seconds=60, job_ttl_seconds=900)
    job = service.create_job(
        owner_id="user-1",
        task_id="TASK-123",
        chat_id="chat-1",
        working_copy_ref="vault://user-tasks/working-copies/job-1",
        expected_task_version=2,
        task_key_version=1,
    )

    claim = service.claim_job(job_id=job["job_id"], owner_id="user-1", device_hash="device-a")

    assert claim["state"] == "LEASED"
    assert claim["lease_generation"] == 1
    assert claim["lease_expires_at"] == 160
    assert claim["working_copy_ref"] == "vault://user-tasks/working-copies/job-1"

    with pytest.raises(TaskUpdateJobConflictError):
        service.claim_job(job_id=job["job_id"], owner_id="user-1", device_hash="device-b")

    with pytest.raises(TaskUpdateJobNotFoundError):
        service.claim_job(job_id=job["job_id"], owner_id="other-user", device_hash="device-a")


def test_task_update_job_persist_accepts_only_client_encrypted_payload_and_is_idempotent() -> None:
    service = UserTaskUpdateJobService(clock=lambda: 100, lease_ttl_seconds=60, job_ttl_seconds=900)
    job = service.create_job(
        owner_id="user-1",
        task_id="TASK-123",
        chat_id="chat-1",
        working_copy_ref="vault://user-tasks/working-copies/job-1",
        expected_task_version=2,
        task_key_version=1,
    )
    claim = service.claim_job(job_id=job["job_id"], owner_id="user-1", device_hash="device-a")
    encrypted_payload = {
        "encrypted_title": "cipher-title",
        "encrypted_description": "cipher-description",
        "version": 3,
    }

    committed = service.persist_job(
        job_id=job["job_id"],
        owner_id="user-1",
        device_hash="device-a",
        lease_token=claim["lease_token"],
        lease_generation=claim["lease_generation"],
        expected_task_version=2,
        encrypted_task_payload=encrypted_payload,
        encrypted_task_event_message="cipher-system-event",
    )
    retried = service.persist_job(
        job_id=job["job_id"],
        owner_id="user-1",
        device_hash="device-a",
        lease_token=claim["lease_token"],
        lease_generation=claim["lease_generation"],
        expected_task_version=2,
        encrypted_task_payload=encrypted_payload,
        encrypted_task_event_message="cipher-system-event",
    )

    assert committed["state"] == "TERMINAL"
    assert committed == retried
    stored = service.get_job(job_id=job["job_id"], owner_id="user-1")
    assert stored["client_encrypted_payload"] == encrypted_payload
    assert "Launch plan" not in str(stored)


def test_task_update_job_rejects_plaintext_or_stale_commits() -> None:
    service = UserTaskUpdateJobService(clock=lambda: 100, lease_ttl_seconds=60, job_ttl_seconds=900)
    job = service.create_job(
        owner_id="user-1",
        task_id="TASK-123",
        chat_id="chat-1",
        working_copy_ref="vault://user-tasks/working-copies/job-1",
        expected_task_version=2,
        task_key_version=1,
    )
    claim = service.claim_job(job_id=job["job_id"], owner_id="user-1", device_hash="device-a")

    with pytest.raises(ValueError, match="plaintext"):
        service.persist_job(
            job_id=job["job_id"],
            owner_id="user-1",
            device_hash="device-a",
            lease_token=claim["lease_token"],
            lease_generation=claim["lease_generation"],
            expected_task_version=2,
            encrypted_task_payload={"title": "Launch plan"},
            encrypted_task_event_message="cipher-system-event",
        )

    with pytest.raises(TaskUpdateJobConflictError):
        service.persist_job(
            job_id=job["job_id"],
            owner_id="user-1",
            device_hash="device-a",
            lease_token=claim["lease_token"],
            lease_generation=claim["lease_generation"],
            expected_task_version=1,
            encrypted_task_payload={"encrypted_title": "cipher-title"},
            encrypted_task_event_message="cipher-system-event",
        )

    with pytest.raises(TaskUpdateJobConflictError, match="committed task version"):
        service.persist_job(
            job_id=job["job_id"],
            owner_id="user-1",
            device_hash="device-a",
            lease_token=claim["lease_token"],
            lease_generation=claim["lease_generation"],
            expected_task_version=2,
            encrypted_task_payload={"encrypted_title": "cipher-title"},
            encrypted_task_event_message="cipher-system-event",
        )


@pytest.mark.asyncio
async def test_task_update_job_persist_requires_expected_task_version() -> None:
    cache = FakeCache()
    manager = FakeManager()
    job_id = "job-1"
    await cache.set(
        f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}",
        {
            "job_id": job_id,
            "owner_hash": hash_id("user-1"),
            "task_id": "task-1",
            "state": "LEASED",
            "operation": "update",
            "lease_token": "lease-1",
            "lease_generation": 1,
            "lease_device_hash": "device-a",
            "lease_expires_at": 9_999_999_999,
            "expires_at": 9_999_999_999,
        },
    )
    directus = SimpleNamespace(user_task=SimpleNamespace(update_task_if_version=AsyncMock()))

    await handle_task_update_job_persist(
        manager=manager,
        cache_service=cache,
        directus_service=directus,
        user_id="user-1",
        device_fingerprint_hash="device-a",
        payload={
            "protocol_version": 1,
            "job_id": job_id,
            "lease_token": "lease-1",
            "lease_generation": 1,
            "expected_task_version": 2,
            "encrypted_task_payload": {"encrypted_title": "cipher-title", "version": 3},
            "encrypted_task_event_message": "cipher-system-event",
        },
    )

    assert manager.messages[-1]["type"] == "error"
    assert manager.messages[-1]["payload"]["code"] == "TaskUpdateJobConflictError"
    directus.user_task.update_task_if_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_update_job_persist_requires_committed_task_version() -> None:
    cache = FakeCache()
    manager = FakeManager()
    job_id = "job-1"
    await cache.set(
        f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}",
        {
            "job_id": job_id,
            "owner_hash": hash_id("user-1"),
            "task_id": "task-1",
            "state": "LEASED",
            "operation": "update",
            "expected_task_version": 2,
            "lease_token": "lease-1",
            "lease_generation": 1,
            "lease_device_hash": "device-a",
            "lease_expires_at": 9_999_999_999,
            "expires_at": 9_999_999_999,
        },
    )
    directus = SimpleNamespace(user_task=SimpleNamespace(update_task_if_version=AsyncMock()))

    await handle_task_update_job_persist(
        manager=manager,
        cache_service=cache,
        directus_service=directus,
        user_id="user-1",
        device_fingerprint_hash="device-a",
        payload={
            "protocol_version": 1,
            "job_id": job_id,
            "lease_token": "lease-1",
            "lease_generation": 1,
            "expected_task_version": 2,
            "encrypted_task_payload": {"encrypted_title": "cipher-title"},
            "encrypted_task_event_message": "cipher-system-event",
        },
    )

    assert manager.messages[-1]["type"] == "error"
    assert manager.messages[-1]["payload"]["code"] == "TaskUpdateJobConflictError"
    directus.user_task.update_task_if_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_update_job_persist_is_idempotent_after_task_persisted() -> None:
    cache = FakeCache()
    manager = FakeManager()
    job_id = "job-1"
    encrypted_payload = {"encrypted_title": "cipher-title", "version": 3}
    await cache.set(
        f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}",
        {
            "job_id": job_id,
            "owner_hash": hash_id("user-1"),
            "task_id": "task-1",
            "state": "TASK_PERSISTED",
            "operation": "update",
            "expected_task_version": 2,
            "client_encrypted_payload": encrypted_payload,
            "encrypted_task_event_message": "cipher-system-event",
            "expires_at": 9_999_999_999,
        },
    )
    directus = SimpleNamespace(user_task=SimpleNamespace(update_task_if_version=AsyncMock()))

    await handle_task_update_job_persist(
        manager=manager,
        cache_service=cache,
        directus_service=directus,
        user_id="user-1",
        device_fingerprint_hash="device-a",
        payload={
            "protocol_version": 1,
            "job_id": job_id,
            "expected_task_version": 2,
            "encrypted_task_payload": encrypted_payload,
            "encrypted_task_event_message": "cipher-system-event",
        },
    )

    assert manager.messages[-1]["type"] == "task_update_job_persisted"
    assert manager.messages[-1]["payload"]["state"] == "TASK_PERSISTED"
    directus.user_task.update_task_if_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_update_job_persist_accepts_already_applied_task_state() -> None:
    cache = FakeCache()
    manager = FakeManager()
    job_id = "job-1"
    working_copy_ref = "vault://user-tasks/working-copies/job-1"
    encrypted_payload = {
        "encrypted_title": "cipher-title",
        "status": "todo",
        "updated_at": 123,
        "version": 2,
    }
    await cache.set(
        f"user_task_working_copy:{hash_id(working_copy_ref)}",
        {"owner_hash": hash_id("user-1"), "ref": working_copy_ref},
    )
    await cache.set(
        f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}",
        {
            "job_id": job_id,
            "owner_hash": hash_id("user-1"),
            "task_id": "task-1",
            "state": "LEASED",
            "operation": "update",
            "expected_task_version": 1,
            "working_copy_ref": working_copy_ref,
            "lease_token": "lease-1",
            "lease_generation": 1,
            "lease_device_hash": "device-a",
            "lease_expires_at": 9_999_999_999,
            "expires_at": 9_999_999_999,
        },
    )
    directus = SimpleNamespace(
        user_task=SimpleNamespace(
            update_task_if_version=AsyncMock(return_value=None),
            get_task=AsyncMock(return_value={"task_id": "task-1", **encrypted_payload, "encrypted_title": "cipher-title-randomized-retry"}),
        ),
        encryption_service=None,
    )

    await handle_task_update_job_persist(
        manager=manager,
        cache_service=cache,
        directus_service=directus,
        user_id="user-1",
        device_fingerprint_hash="device-a",
        payload={
            "protocol_version": 1,
            "job_id": job_id,
            "lease_token": "lease-1",
            "lease_generation": 1,
            "expected_task_version": 1,
            "encrypted_task_payload": encrypted_payload,
            "encrypted_task_event_message": "cipher-system-event",
        },
    )

    stored = await cache.get(f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}")
    assert manager.messages[-1]["type"] == "task_update_job_persisted"
    assert manager.messages[-1]["payload"]["state"] == "TASK_PERSISTED"
    assert stored["state"] == "TASK_PERSISTED"
    assert stored["client_encrypted_payload"] == encrypted_payload
    directus.user_task.update_task_if_version.assert_awaited_once()
    directus.user_task.get_task.assert_awaited_once_with("task-1", "user-1")


@pytest.mark.asyncio
async def test_task_update_job_event_confirm_requires_system_message_confirmation() -> None:
    cache = FakeCache()
    manager = FakeManager()
    job_id = "job-1"
    await cache.set(
        f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}",
        {
            "job_id": job_id,
            "owner_hash": hash_id("user-1"),
            "task_id": "task-1",
            "chat_id": "chat-1",
            "message_id": "source-message-1",
            "state": "TASK_PERSISTED",
            "expected_task_version": 2,
            "expires_at": 100 + TASK_EVENT_CONFIRMATION_RECOVERY_TTL_SECONDS,
        },
    )

    await handle_task_update_job_event_confirmed(
        manager=manager,
        cache_service=cache,
        user_id="user-1",
        device_fingerprint_hash="device-a",
        payload={"protocol_version": 1, "job_id": job_id, "event_system_message_id": "event-1"},
    )

    assert manager.messages[-1]["type"] == "error"
    assert manager.messages[-1]["payload"]["message"] == "Task event system message has not been confirmed"
    assert (await cache.get(f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}"))["state"] == "TASK_PERSISTED"

    await cache.set(
        system_message_confirmation_cache_key("user-1", "chat-1", "event-1"),
        {"message_id": "event-1", "user_message_id": "other-message", "task_update_job_id": job_id},
    )
    await handle_task_update_job_event_confirmed(
        manager=manager,
        cache_service=cache,
        user_id="user-1",
        device_fingerprint_hash="device-a",
        payload={"protocol_version": 1, "job_id": job_id, "event_system_message_id": "event-1"},
    )

    assert manager.messages[-1]["type"] == "error"
    assert (await cache.get(f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}"))["state"] == "TASK_PERSISTED"

    await cache.set(
        system_message_confirmation_cache_key("user-1", "chat-1", "event-1"),
        {"message_id": "event-1", "user_message_id": "source-message-1", "task_update_job_id": job_id},
    )
    await handle_task_update_job_event_confirmed(
        manager=manager,
        cache_service=cache,
        user_id="user-1",
        device_fingerprint_hash="device-a",
        payload={"protocol_version": 1, "job_id": job_id, "event_system_message_id": "event-1"},
    )

    assert manager.messages[-1]["type"] == "task_update_job_event_confirmed"
    stored = await cache.get(f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}")
    assert stored["state"] == "TERMINAL"
    assert stored["event_system_message_id"] == "event-1"
