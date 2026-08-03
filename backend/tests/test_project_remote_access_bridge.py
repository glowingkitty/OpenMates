"""Contract tests for the encrypted Project remote-access live bridge.

The backend routes opaque envelopes between authenticated first-party clients.
It must enforce owner, Project, source, session, replay, lifecycle, and rate
boundaries without receiving filesystem paths, queries, snippets, or content.

Spec: docs/specs/cli-remote-access-live-bridge/spec.yml
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.api.app.services.project_remote_access_service import (
    ProjectRemoteAccessError,
    ProjectRemoteAccessService,
)
from backend.core.api.app.routes.handlers.websocket_handlers.project_remote_access_handlers import (
    handle_project_remote_access_heartbeat,
    handle_project_remote_access_register,
)
from backend.core.api.app.routes.projects import (
    ProjectRemoteAccessRequestCreate,
    create_project_remote_access_request,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError


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


class MemoryWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


class TeamMembershipStub:
    def __init__(self) -> None:
        self.active = True
        self.inactive_users: set[str] = set()

    async def require_team_role(self, team_id: str, user_id: str, roles: set[str]) -> dict[str, str]:
        del team_id, roles
        if not self.active or user_id in self.inactive_users:
            raise TeamPermissionError("removed")
        return {"role": "member"}


class ProjectAccessStub:
    def __init__(self) -> None:
        self.offlined_members: list[tuple[str, str]] = []

    async def get_project(self, project_id: str, user_id: str, team_id: str | None = None) -> dict[str, str]:
        del project_id, user_id, team_id
        return {"project_id": "project-1"}

    async def get_source(
        self, project_id: str, user_id: str, source_id: str, team_id: str | None = None
    ) -> dict[str, Any]:
        del project_id, source_id, team_id
        return {
            "status": "offline",
            "capabilities": ["read", "search", "import"],
            "attached_by_user_hash": ProjectRemoteAccessService._hash_identity(user_id),
        }

    async def mark_team_member_sources_offline(
        self, team_id: str, member_user_id: str, *, updated_at: int
    ) -> int:
        del updated_at
        self.offlined_members.append((team_id, member_user_id))
        return 1


class DirectusAccessStub:
    def __init__(self) -> None:
        self.team = TeamMembershipStub()
        self.project = ProjectAccessStub()


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


@pytest.mark.anyio
async def test_personal_and_team_contexts_are_independent_and_bind_both_peer_identities() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="host-1",
        team_id=None,
        device_fingerprint_hash="personal-device",
        source_session_id="personal-session",
        bindings=[binding()],
        confirmed_takeover=False,
        now=8_000,
    )
    await service.register_session(
        user_id="host-1",
        team_id="team-1",
        device_fingerprint_hash="team-device",
        source_session_id="team-session",
        bindings=[binding()],
        confirmed_takeover=False,
        now=8_000,
    )

    personal = await service.get_active_binding("host-1", "project-1", "source-1", now=8_001)
    team = await service.get_active_binding(
        "requester-1", "project-1", "source-1", team_id="team-1", now=8_001
    )
    assert personal["source_session_id"] == "personal-session"
    assert team["source_session_id"] == "team-session"

    created = await service.create_request(
        user_id="requester-1",
        team_id="team-1",
        project_id="project-1",
        source_id="source-1",
        request_id="team-request",
        requesting_client_id="request-client",
        requesting_device_fingerprint_hash="request-device",
        operation="search",
        key_epoch=1,
        encrypted_envelope="opaque-team-request",
        now=8_002,
    )
    assert created["status"] == "delivered"
    context_hash = service._hash_identity("team-1")
    assert created["routing_identity"] == {
        "context_type": "team",
        "context_id_hash": context_hash,
        "host_member_hash": service._hash_identity(
            f"{context_hash}:{service._hash_identity('host-1')}"
        ),
        "host_device_fingerprint_hash": service._hash_identity(f"{context_hash}:team-device"),
        "requester_member_hash": service._hash_identity(
            f"{context_hash}:{service._hash_identity('requester-1')}"
        ),
        "requester_device_fingerprint_hash": service._hash_identity(f"{context_hash}:request-device"),
    }
    channel, event = cache.published[-1]
    assert channel == f"user_updates::{service._hash_identity('host-1')}"
    assert event["payload"]["routing_identity"] == created["routing_identity"]

    await service.complete_request(
        user_id="host-1",
        team_id="team-1",
        device_fingerprint_hash="team-device",
        source_session_id="team-session",
        project_id="project-1",
        source_id="source-1",
        request_id="team-request",
        key_epoch=1,
        encrypted_envelope="opaque-team-result",
        now=8_003,
    )
    with pytest.raises(ProjectRemoteAccessError, match="request_not_found"):
        await service.get_request_result(
            user_id="other-member",
            team_id="team-1",
            project_id="project-1",
            source_id="source-1",
            request_id="team-request",
            requesting_client_id="request-client",
            requesting_device_fingerprint_hash="request-device",
            now=8_004,
        )
    assert await service.get_request_result(
        user_id="requester-1",
        team_id="team-1",
        project_id="project-1",
        source_id="source-1",
        request_id="team-request",
        requesting_client_id="request-client",
        requesting_device_fingerprint_hash="request-device",
        now=8_004,
    ) == {"status": "completed", "encrypted_envelope": "opaque-team-result"}


@pytest.mark.anyio
async def test_team_offboarding_revokes_host_sessions_and_pending_work() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="host-1",
        team_id="team-1",
        device_fingerprint_hash="team-device",
        source_session_id="team-session",
        bindings=[binding()],
        confirmed_takeover=False,
        now=9_000,
    )
    await service.create_request(
        user_id="requester-1",
        team_id="team-1",
        project_id="project-1",
        source_id="source-1",
        request_id="pending-request",
        requesting_client_id="request-client",
        requesting_device_fingerprint_hash="request-device",
        operation="read_text",
        key_epoch=1,
        encrypted_envelope="opaque",
        now=9_001,
    )

    assert await service.revoke_member(team_id="team-1", member_user_id="host-1") is True
    with pytest.raises(ProjectRemoteAccessError, match="source_offline"):
        await service.get_active_binding(
            "requester-1", "project-1", "source-1", team_id="team-1", now=9_002
        )
    with pytest.raises(ProjectRemoteAccessError, match="request_already_completed"):
        await service.complete_request(
            user_id="host-1",
            team_id="team-1",
            device_fingerprint_hash="team-device",
            source_session_id="team-session",
            project_id="project-1",
            source_id="source-1",
            request_id="pending-request",
            key_epoch=1,
            encrypted_envelope="stale-result",
            now=9_003,
        )


@pytest.mark.anyio
async def test_team_deletion_revokes_all_host_sessions_and_pending_work() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    for host_user_id, source_session_id, source_id in (
        ("host-1", "session-1", "source-1"),
        ("host-2", "session-2", "source-2"),
    ):
        await service.register_session(
            user_id=host_user_id,
            team_id="team-1",
            device_fingerprint_hash=f"device-{host_user_id}",
            source_session_id=source_session_id,
            bindings=[binding(source_id=source_id)],
            confirmed_takeover=False,
            now=9_100,
        )
    await service.create_request(
        user_id="requester-1",
        team_id="team-1",
        project_id="project-1",
        source_id="source-1",
        request_id="pending-team-request",
        requesting_client_id="request-client",
        operation="list",
        key_epoch=1,
        encrypted_envelope="opaque",
        now=9_101,
    )

    assert await service.revoke_team(team_id="team-1") is True
    for source_id in ("source-1", "source-2"):
        with pytest.raises(ProjectRemoteAccessError, match="source_offline"):
            await service.get_active_binding(
                "requester-1", "project-1", source_id, team_id="team-1", now=9_102
            )
    with pytest.raises(ProjectRemoteAccessError, match="request_already_completed"):
        await service.complete_request(
            user_id="host-1",
            team_id="team-1",
            device_fingerprint_hash="device-host-1",
            source_session_id="session-1",
            project_id="project-1",
            source_id="source-1",
            request_id="pending-team-request",
            key_epoch=1,
            encrypted_envelope="stale-result",
            now=9_103,
        )


@pytest.mark.anyio
async def test_team_takeover_rejects_stale_member_and_device_lifecycle_messages() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="host-1",
        team_id="team-1",
        device_fingerprint_hash="device-old",
        source_session_id="session-old",
        bindings=[binding()],
        confirmed_takeover=False,
        now=10_000,
    )
    await service.create_request(
        user_id="requester-1",
        team_id="team-1",
        project_id="project-1",
        source_id="source-1",
        request_id="old-session-request",
        requesting_client_id="request-client",
        requesting_device_fingerprint_hash="request-device",
        operation="list",
        key_epoch=1,
        encrypted_envelope="opaque",
        now=10_001,
    )
    await service.register_session(
        user_id="host-1",
        team_id="team-1",
        device_fingerprint_hash="device-new",
        source_session_id="session-new",
        bindings=[binding()],
        confirmed_takeover=True,
        now=10_002,
    )

    with pytest.raises(ProjectRemoteAccessError, match="session_scope_mismatch"):
        await service.heartbeat_session(
            user_id="host-1",
            team_id="team-1",
            device_fingerprint_hash="device-old",
            source_session_id="session-new",
            now=10_020,
        )
    assert await service.disconnect_session(
        user_id="other-member",
        team_id="team-1",
        device_fingerprint_hash="device-new",
        source_session_id="session-new",
        now=10_021,
    ) is False
    active = await service.get_active_binding(
        "host-1", "project-1", "source-1", team_id="team-1", now=10_022
    )
    assert active["source_session_id"] == "session-new"
    with pytest.raises(ProjectRemoteAccessError, match="request_already_completed"):
        await service.complete_request(
            user_id="host-1",
            team_id="team-1",
            device_fingerprint_hash="device-old",
            source_session_id="session-old",
            project_id="project-1",
            source_id="source-1",
            request_id="old-session-request",
            key_epoch=1,
            encrypted_envelope="stale-result",
            now=10_023,
        )


@pytest.mark.anyio
async def test_team_websocket_lifecycle_revalidates_membership_before_cache_mutation() -> None:
    cache = MemoryCache()
    directus = DirectusAccessStub()
    websocket = MemoryWebSocket()
    payload = {
        "team_id": "team-1",
        "source_session_id": "team-session",
        "confirmed_takeover": False,
        "bindings": [binding()],
    }
    await handle_project_remote_access_register(
        websocket=websocket,
        cache_service=cache,
        directus_service=directus,
        user_id="host-1",
        device_fingerprint_hash="device-1",
        payload=payload,
    )
    assert websocket.messages[-1]["type"] == "project_remote_access_registered"

    directus.team.active = False
    await handle_project_remote_access_heartbeat(
        websocket=websocket,
        cache_service=cache,
        directus_service=directus,
        user_id="host-1",
        device_fingerprint_hash="device-1",
        payload={"team_id": "team-1", "source_session_id": "team-session"},
    )
    assert websocket.messages[-1]["payload"]["code"] == "team_membership_required"
    service_key = ProjectRemoteAccessService._session_key("team-1", "team-session", "team")
    session = await cache.get(service_key)
    assert session is not None
    assert await cache.get(service_key) == session


@pytest.mark.anyio
async def test_team_rest_request_route_uses_team_context_and_requester_identity() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    now = int(time.time())
    await service.register_session(
        user_id="host-1",
        team_id="team-1",
        device_fingerprint_hash="host-device",
        source_session_id="team-session",
        bindings=[binding()],
        confirmed_takeover=False,
        now=now,
    )
    directus = DirectusAccessStub()
    token = "requester-refresh-token"
    token_hash = ProjectRemoteAccessService._hash_identity(token)
    cache.values["user_tokens:requester-1"] = {
        token_hash: {"connection_hash": "a" * 64}
    }
    response = await create_project_remote_access_request(
        project_id="project-1",
        source_id="source-1",
        body=ProjectRemoteAccessRequestCreate(
            request_id="route-request",
            requesting_client_id="request-client",
            operation="list",
            key_epoch=1,
            encrypted_envelope="opaque",
        ),
        request=SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(cache_service=cache)),
            cookies={"auth_refresh_token": token},
        ),
        team_id="team-1",
        current_user=SimpleNamespace(id="requester-1"),
        directus_service=directus,
    )

    assert response["status"] == "delivered"
    assert response["routing_identity"]["context_type"] == "team"
    context_hash = service._hash_identity("team-1")
    assert response["routing_identity"]["requester_device_fingerprint_hash"] == service._hash_identity(
        f"{context_hash}:{'a' * 64}"
    )
    assert cache.published[-1][1]["payload"]["requesting_client_id"] == "request-client"


def test_remote_request_rejects_client_supplied_device_fingerprint() -> None:
    with pytest.raises(ValidationError, match="requesting_device_fingerprint_hash"):
        ProjectRemoteAccessRequestCreate(
            request_id="route-request",
            requesting_client_id="request-client",
            requesting_device_fingerprint_hash="forged-request-device",
            operation="list",
            key_epoch=1,
            encrypted_envelope="opaque",
        )


@pytest.mark.anyio
async def test_team_request_revokes_stale_host_before_delivery_and_marks_sources_offline() -> None:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    now = int(time.time())
    await service.register_session(
        user_id="host-1",
        team_id="team-1",
        device_fingerprint_hash="host-device",
        source_session_id="team-session",
        bindings=[binding()],
        confirmed_takeover=False,
        now=now,
    )
    directus = DirectusAccessStub()
    directus.team.inactive_users.add("host-1")
    token = "requester-refresh-token"
    cache.values["user_tokens:requester-1"] = {
        service._hash_identity(token): {"connection_hash": "a" * 64}
    }

    with pytest.raises(Exception, match="source_offline"):
        await create_project_remote_access_request(
            project_id="project-1",
            source_id="source-1",
            body=ProjectRemoteAccessRequestCreate(
                request_id="route-request",
                requesting_client_id="request-client",
                operation="list",
                key_epoch=1,
                encrypted_envelope="opaque",
            ),
            request=SimpleNamespace(
                app=SimpleNamespace(state=SimpleNamespace(cache_service=cache)),
                cookies={"auth_refresh_token": token},
            ),
            team_id="team-1",
            current_user=SimpleNamespace(id="requester-1"),
            directus_service=directus,
        )

    assert cache.published == []
    assert directus.project.offlined_members == [("team-1", "host-1")]
    with pytest.raises(ProjectRemoteAccessError, match="source_offline"):
        await service.get_active_binding(
            "requester-1", "project-1", "source-1", team_id="team-1", now=now
        )
