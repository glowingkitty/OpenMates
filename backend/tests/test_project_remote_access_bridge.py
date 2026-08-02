"""Contract tests for the encrypted Project remote-access live bridge.

The backend routes opaque envelopes between authenticated first-party clients.
It must enforce owner, Project, source, session, replay, lifecycle, and rate
boundaries without receiving filesystem paths, queries, snippets, or content.

Spec: docs/specs/cli-remote-access-live-bridge/spec.yml
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.services.project_remote_access_service import (
    ProjectRemoteAccessError,
    ProjectRemoteAccessService,
)


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        self.values[key] = value
        return True

    async def delete(self, key: str) -> bool:
        self.values.pop(key, None)
        return True

    async def publish_event(self, channel: str, event: dict[str, Any]) -> bool:
        self.published.append((channel, event))
        return True


class FailingPublishCache(MemoryCache):
    async def publish_event(self, channel: str, event: dict[str, Any]) -> bool:
        return False


def binding(project_id: str = "project-1", source_id: str = "source-1") -> dict[str, Any]:
    return {
        "project_id": project_id,
        "source_id": source_id,
        "capabilities": ["read", "search", "import"],
        "key_epoch": 1,
    }


@pytest.mark.anyio
async def test_register_heartbeat_disconnect_and_stale_takeover_are_session_scoped() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)

    registered = await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-1",
        source_session_id="session-1",
        bindings=[binding()],
        confirmed_takeover=False,
        now=1_000,
    )
    assert registered["deadline_at"] == 1_045
    assert registered["heartbeat_interval_seconds"] == 15

    with pytest.raises(ProjectRemoteAccessError, match="takeover_confirmation_required"):
        await service.register_session(
            user_id="user-1",
            device_fingerprint_hash="device-2",
            source_session_id="session-2",
            bindings=[binding()],
            confirmed_takeover=False,
            now=1_001,
        )

    replacement = await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-2",
        source_session_id="session-2",
        bindings=[binding()],
        confirmed_takeover=True,
        now=1_002,
    )
    assert replacement["replaced_session_id"] == "session-1"

    stale_disconnect = await service.disconnect_session(
        user_id="user-1", source_session_id="session-1", now=1_003
    )
    assert stale_disconnect is False
    active = await service.get_active_binding("user-1", "project-1", "source-1", now=1_003)
    assert active["source_session_id"] == "session-2"

    with pytest.raises(ProjectRemoteAccessError, match="heartbeat_too_early"):
        await service.heartbeat_session(
            user_id="user-1", source_session_id="session-2", now=1_004
        )
    assert await service.disconnect_session(
        user_id="user-1", source_session_id="session-2", now=1_020
    ) is True
    with pytest.raises(ProjectRemoteAccessError, match="source_offline"):
        await service.get_active_binding("user-1", "project-1", "source-1", now=1_020)


@pytest.mark.anyio
async def test_create_request_routes_only_opaque_envelope_to_exact_device() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-cli",
        source_session_id="session-1",
        bindings=[binding()],
        confirmed_takeover=False,
        now=2_000,
    )

    created = await service.create_request(
        user_id="user-1",
        project_id="project-1",
        source_id="source-1",
        request_id="request-1",
        requesting_client_id="browser-1",
        operation="search",
        key_epoch=1,
        encrypted_envelope="opaque-request-ciphertext",
        now=2_001,
    )

    assert created == {"request_id": "request-1", "status": "delivered"}
    channel, event = cache.published[-1]
    assert channel.startswith("user_updates::")
    assert event["target_device_fingerprint_hash"] == "device-cli"
    assert event["event_for_client"] == "project_remote_access_request"
    assert event["payload"]["encrypted_envelope"] == "opaque-request-ciphertext"
    assert event["payload"]["requesting_client_id"] == "browser-1"
    serialized = repr(cache.values) + repr(cache.published)
    for forbidden in ("/workspace/private", "billing query", "file contents"):
        assert forbidden not in serialized


@pytest.mark.anyio
async def test_completion_rejects_wrong_scope_replay_and_old_key_epoch() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-cli",
        source_session_id="session-1",
        bindings=[binding()],
        confirmed_takeover=False,
        now=3_000,
    )
    await service.create_request(
        user_id="user-1",
        project_id="project-1",
        source_id="source-1",
        request_id="request-1",
        requesting_client_id="browser-1",
        operation="read_text",
        key_epoch=1,
        encrypted_envelope="opaque-request",
        now=3_001,
    )

    with pytest.raises(ProjectRemoteAccessError, match="request_scope_mismatch"):
        await service.complete_request(
            user_id="user-1",
            device_fingerprint_hash="wrong-device",
            source_session_id="session-1",
            project_id="project-1",
            source_id="source-1",
            request_id="request-1",
            key_epoch=1,
            encrypted_envelope="opaque-result",
            now=3_002,
        )
    with pytest.raises(ProjectRemoteAccessError, match="request_scope_mismatch"):
        await service.complete_request(
            user_id="user-1",
            device_fingerprint_hash="device-cli",
            source_session_id="session-1",
            project_id="project-1",
            source_id="source-1",
            request_id="request-1",
            key_epoch=2,
            encrypted_envelope="opaque-result",
            now=3_002,
        )

    completed = await service.complete_request(
        user_id="user-1",
        device_fingerprint_hash="device-cli",
        source_session_id="session-1",
        project_id="project-1",
        source_id="source-1",
        request_id="request-1",
        key_epoch=1,
        encrypted_envelope="opaque-result",
        now=3_002,
    )
    assert completed is True
    assert await service.get_request_result(
        user_id="user-1",
        project_id="project-1",
        source_id="source-1",
        request_id="request-1",
        requesting_client_id="browser-1",
        now=3_003,
    ) == {"status": "completed", "encrypted_envelope": "opaque-result"}

    with pytest.raises(ProjectRemoteAccessError, match="request_already_completed"):
        await service.complete_request(
            user_id="user-1",
            device_fingerprint_hash="device-cli",
            source_session_id="session-1",
            project_id="project-1",
            source_id="source-1",
            request_id="request-1",
            key_epoch=1,
            encrypted_envelope="replayed-result",
            now=3_004,
        )


@pytest.mark.anyio
async def test_cross_user_project_and_expired_session_requests_fail_closed() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-cli",
        source_session_id="session-1",
        bindings=[binding()],
        confirmed_takeover=False,
        now=4_000,
    )

    for user_id, project_id in (("user-2", "project-1"), ("user-1", "project-2")):
        with pytest.raises(ProjectRemoteAccessError, match="source_offline"):
            await service.create_request(
                user_id=user_id,
                project_id=project_id,
                source_id="source-1",
                request_id=f"request-{user_id}-{project_id}",
                requesting_client_id="browser-1",
                operation="list",
                key_epoch=1,
                encrypted_envelope="opaque",
                now=4_001,
            )

    with pytest.raises(ProjectRemoteAccessError, match="source_offline"):
        await service.create_request(
            user_id="user-1",
            project_id="project-1",
            source_id="source-1",
            request_id="request-expired",
            requesting_client_id="browser-1",
            operation="list",
            key_epoch=1,
            encrypted_envelope="opaque",
            now=4_046,
        )


@pytest.mark.anyio
async def test_rate_queue_and_payload_limits_reject_before_delivery() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-cli",
        source_session_id="session-1",
        bindings=[binding()],
        confirmed_takeover=False,
        now=5_000,
    )

    with pytest.raises(ProjectRemoteAccessError, match="payload_too_large"):
        await service.create_request(
            user_id="user-1",
            project_id="project-1",
            source_id="source-1",
            request_id="oversized",
            requesting_client_id="browser-1",
            operation="search",
            key_epoch=1,
            encrypted_envelope="x" * (256 * 1024 + 1),
            now=5_001,
        )
    assert cache.published == []

    for index in range(20):
        result = await service.create_request(
            user_id="user-1",
            project_id="project-1",
            source_id="source-1",
            request_id=f"request-{index}",
            requesting_client_id="browser-1",
            operation="search",
            key_epoch=1,
            encrypted_envelope="opaque",
            now=5_001,
        )
        assert result["status"] == ("delivered" if index < 4 else "queued")

    with pytest.raises(ProjectRemoteAccessError, match="source_queue_full"):
        await service.create_request(
            user_id="user-1",
            project_id="project-1",
            source_id="source-1",
            request_id="request-21",
            requesting_client_id="browser-1",
            operation="search",
            key_epoch=1,
            encrypted_envelope="opaque",
            now=5_001,
        )


@pytest.mark.anyio
async def test_service_instances_for_one_cache_serialize_state_mutations() -> None:
    cache = MemoryCache()
    first = ProjectRemoteAccessService(cache)
    second = ProjectRemoteAccessService(cache)

    assert first._lock is second._lock


@pytest.mark.anyio
async def test_takeover_clears_non_overlapping_bindings_from_replaced_session() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-1",
        source_session_id="session-1",
        bindings=[binding(), binding("project-2", "source-2")],
        confirmed_takeover=False,
        now=5_500,
    )
    await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-2",
        source_session_id="session-2",
        bindings=[binding()],
        confirmed_takeover=True,
        now=5_501,
    )

    with pytest.raises(ProjectRemoteAccessError, match="source_offline"):
        await service.get_active_binding("user-1", "project-2", "source-2", now=5_502)


@pytest.mark.anyio
async def test_expired_requests_release_capacity_and_cannot_be_replayed() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-cli",
        source_session_id="session-1",
        bindings=[binding()],
        confirmed_takeover=False,
        now=6_000,
    )
    for index in range(4):
        await service.create_request(
            user_id="user-1",
            project_id="project-1",
            source_id="source-1",
            request_id=f"expired-{index}",
            requesting_client_id="browser-1",
            operation="list",
            key_epoch=1,
            encrypted_envelope="opaque",
            now=6_001,
        )
    await service.heartbeat_session(user_id="user-1", source_session_id="session-1", now=6_040)

    created = await service.create_request(
        user_id="user-1",
        project_id="project-1",
        source_id="source-1",
        request_id="replacement",
        requesting_client_id="browser-1",
        operation="list",
        key_epoch=1,
        encrypted_envelope="opaque",
        now=6_047,
    )
    assert created["status"] == "delivered"
    with pytest.raises(ProjectRemoteAccessError, match="duplicate_request_id"):
        await service.create_request(
            user_id="user-1",
            project_id="project-1",
            source_id="source-1",
            request_id="expired-0",
            requesting_client_id="browser-1",
            operation="list",
            key_epoch=1,
            encrypted_envelope="opaque",
            now=6_047,
        )


@pytest.mark.anyio
async def test_publish_failure_rolls_back_request_and_capacity() -> None:
    cache = FailingPublishCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="user-1",
        device_fingerprint_hash="device-cli",
        source_session_id="session-1",
        bindings=[binding()],
        confirmed_takeover=False,
        now=7_000,
    )
    with pytest.raises(ProjectRemoteAccessError, match="request_delivery_unavailable"):
        await service.create_request(
            user_id="user-1",
            project_id="project-1",
            source_id="source-1",
            request_id="request-1",
            requesting_client_id="browser-1",
            operation="list",
            key_epoch=1,
            encrypted_envelope="opaque",
            now=7_001,
        )
    assert await cache.get(service._request_key("user-1", "request-1")) is None
    session = await cache.get(service._session_key("user-1", "session-1"))
    assert session["in_flight"] == []
