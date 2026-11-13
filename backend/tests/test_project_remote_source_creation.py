# contract-test-file: infrastructure
"""Contract tests for host-created Projects: placeholder sources and create_source relay.

A brand-new Project has no source, so the backend creates a placeholder bound to
one connected host device. The host discovers it, answers a single-use
``create_source`` request and completes the placeholder into a normal source.

Spec: docs/specs/cli-remote-access-live-bridge/spec.yml
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.core.api.app.routes.projects import (
    ProjectRemoteAccessRequestCreate,
    ProjectSourceCreateRequest,
    ProjectSourceCreationCompleteRequest,
    complete_project_source_creation,
    create_project_remote_access_request,
    create_project_source,
    delete_project_source,
    list_pending_source_creations,
    list_project_sources,
    update_project_source_capabilities,
    ProjectSourceCapabilitiesUpdateRequest,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.project_remote_access_service import (
    ALLOWED_OPERATIONS,
    SINGLE_USE_OPERATIONS,
    WRITE_OPERATIONS,
    ProjectRemoteAccessError,
    ProjectRemoteAccessService,
)
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
)
from backend.core.api.app.routes.projects import hash_id
from backend.tests.test_project_remote_access_bridge import (
    DIGEST_RUN,
    MemoryCache,
    _ConsumableCache,
    _command_authorizer,
)

OWNER = "user-1"
HOST_DEVICE = "a" * 64
OTHER_DEVICE = "b" * 64
PROJECT = "project-1"


class _Team:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    async def require_team_role(self, team_id: str, user_id: str, roles: set[str]) -> dict[str, str]:
        del team_id, user_id, roles
        if not self.allowed:
            raise TeamPermissionError("denied")
        return {"role": "member"}


class _Project:
    def __init__(self, project_exists: bool = True, write_mode: str | None = "always_ask") -> None:
        self.project_exists = project_exists
        self.write_mode = write_mode
        self.sources: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []

    async def get_project(self, project_id: str, user_id: str, team_id: str | None = None) -> Any:
        del user_id, team_id
        return {"project_id": project_id} if self.project_exists else None

    async def get_project_settings(self, project_id: str, user_id: str, team_id: str | None = None) -> Any:
        del project_id, user_id, team_id
        return {"write_mode": self.write_mode} if self.write_mode else None

    async def create_source(self, project_id: str, user_id: str, payload: dict[str, Any], team_id: str | None = None) -> Any:
        del project_id, team_id
        row = {**payload, "attached_by_user_hash": hash_id(user_id)}
        self.sources[payload["source_id"]] = row
        return row

    async def get_source(self, project_id: str, user_id: str, source_id: str, team_id: str | None = None) -> Any:
        del project_id, user_id, team_id
        return self.sources.get(source_id)

    async def list_sources(self, project_id: str, user_id: str, team_id: str | None = None) -> list[dict[str, Any]]:
        del project_id, user_id, team_id
        return list(self.sources.values())

    async def delete_source(self, project_id: str, user_id: str, source_id: str, team_id: str | None = None) -> bool:
        del project_id, user_id, team_id
        self.deleted.append(source_id)
        return self.sources.pop(source_id, None) is not None

    async def list_creation_pending_sources(self, user_id: str, device_hash: str) -> list[dict[str, Any]]:
        return [
            row for row in self.sources.values()
            if row["status"] == "creation_pending" and row["host_device_hash"] == device_hash
            and row["attached_by_user_hash"] == hash_id(user_id)
        ]

    async def complete_source_creation(self, project_id: str, user_id: str, source_id: str, **fields: Any) -> Any:
        del project_id, user_id
        fields.pop("team_id", None)
        row = self.sources[source_id]
        row.update(fields, status="offline", host_device_hash=None)
        return row


class _Directus:
    def __init__(self, devices: list[str] | None = None, **project_kwargs: Any) -> None:
        self.project = _Project(**project_kwargs)
        self.team = _Team()
        self._devices = [HOST_DEVICE] if devices is None else devices

    async def get_user_fields_direct(self, user_id: str, fields: list[str], no_cache: bool = False) -> dict[str, Any]:
        del fields, no_cache
        return {"id": user_id, "connected_devices": [{"hash": value} for value in self._devices]}


def _request(device: str = HOST_DEVICE, cache: Any = None) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(cache_service=cache or MemoryCache())),
        cookies={}, state=SimpleNamespace(auth_info={"device_hash": device}),
    )


def _create_body(device: str = HOST_DEVICE) -> ProjectSourceCreateRequest:
    return ProjectSourceCreateRequest(
        create_on_host_device=device, source_type="local_folder",
        encrypted_display_name="cipher-name", encrypted_metadata="cipher-meta",
        created_at=1, updated_at=1,
    )


async def _placeholder(directus: _Directus) -> str:
    result = await create_project_source(
        request=_request(), project_id=PROJECT, body=_create_body(), team_id=None,
        current_user=SimpleNamespace(id=OWNER), directus_service=directus,
    )
    return result["source"]["source_id"]


def _complete_body() -> ProjectSourceCreationCompleteRequest:
    return ProjectSourceCreationCompleteRequest(
        source_type="local_git_repository", encrypted_display_name="cipher-real",
        encrypted_metadata="cipher-path", capabilities=["read", "search", "write_request"],
        updated_at=5,
    )


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_placeholder_is_backend_identified_and_bound_to_one_device() -> None:
    directus = _Directus()
    source_id = await _placeholder(directus)
    row = directus.project.sources[source_id]
    assert source_id.startswith("src_")
    assert row["status"] == "creation_pending"
    assert row["capabilities"] == ["create_source"]
    assert row["source_type"] == "local_folder"
    assert row["host_device_hash"] == HOST_DEVICE


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_placeholder_refuses_unknown_device_missing_project_and_denied_member() -> None:
    kwargs: dict[str, Any] = dict(
        request=_request(), project_id=PROJECT, body=_create_body(OTHER_DEVICE), team_id=None,
        current_user=SimpleNamespace(id=OWNER),
    )
    with pytest.raises(HTTPException) as foreign:
        await create_project_source(directus_service=_Directus(), **kwargs)
    assert (foreign.value.status_code, foreign.value.detail) == (403, "HOST_DEVICE_NOT_CONNECTED")

    with pytest.raises(HTTPException) as missing:
        await create_project_source(directus_service=_Directus(project_exists=False), **{**kwargs, "body": _create_body()})
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as no_mode:
        await create_project_source(directus_service=_Directus(write_mode=None), **{**kwargs, "body": _create_body()})
    assert no_mode.value.detail == "PROJECT_WRITE_MODE_REQUIRED"

    denied = _Directus()
    denied.team.allowed = False
    with pytest.raises(HTTPException) as viewer:
        await create_project_source(directus_service=denied, **{**kwargs, "body": _create_body(), "team_id": "team-1"})
    assert viewer.value.status_code == 403


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
def test_placeholder_mode_rejects_client_chosen_identity_and_plain_mode_needs_one() -> None:
    with pytest.raises(ValidationError):
        ProjectSourceCreateRequest(
            create_on_host_device=HOST_DEVICE, source_id="mine", source_type="local_folder",
            encrypted_display_name="n", encrypted_metadata="m", created_at=1, updated_at=1,
        )
    with pytest.raises(ValidationError):
        ProjectSourceCreateRequest(
            source_type="local_folder", encrypted_display_name="n", encrypted_metadata="m",
            created_at=1, updated_at=1,
        )
    with pytest.raises(ValidationError):
        ProjectSourceCreateRequest(
            source_id="s", source_type="local_folder", encrypted_display_name="n",
            encrypted_metadata="m", capabilities=["create_source"], created_at=1, updated_at=1,
        )


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_only_the_bound_device_discovers_and_completes_the_placeholder() -> None:
    directus = _Directus()
    source_id = await _placeholder(directus)
    mine = await list_pending_source_creations(
        request=_request(), current_user=SimpleNamespace(id=OWNER), directus_service=directus,
    )
    assert [row["source_id"] for row in mine["sources"]] == [source_id]
    elsewhere = await list_pending_source_creations(
        request=_request(OTHER_DEVICE), current_user=SimpleNamespace(id=OWNER), directus_service=directus,
    )
    assert elsewhere["sources"] == []

    common = dict(project_id=PROJECT, source_id=source_id, body=_complete_body(), team_id=None, directus_service=directus)
    with pytest.raises(HTTPException) as wrong_device:
        await complete_project_source_creation(request=_request(OTHER_DEVICE), current_user=SimpleNamespace(id=OWNER), **common)
    assert wrong_device.value.detail == "SOURCE_HOST_DEVICE_MISMATCH"
    with pytest.raises(HTTPException) as wrong_user:
        await complete_project_source_creation(request=_request(), current_user=SimpleNamespace(id="user-2"), **common)
    assert wrong_user.value.status_code == 403

    done = await complete_project_source_creation(request=_request(), current_user=SimpleNamespace(id=OWNER), **common)
    assert done["source"]["status"] == "offline"
    assert done["source"]["host_device_hash"] is None
    assert "create_source" not in done["source"]["capabilities"]
    with pytest.raises(HTTPException) as again:
        await complete_project_source_creation(request=_request(), current_user=SimpleNamespace(id=OWNER), **common)
    assert again.value.detail == "SOURCE_NOT_CREATION_PENDING"
    with pytest.raises(ValidationError):
        ProjectSourceCreationCompleteRequest(
            source_type="local_folder", encrypted_display_name="n", encrypted_metadata="m",
            capabilities=["create_source"], updated_at=1,
        )


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_refused_creation_leaves_a_placeholder_deletable_without_the_host() -> None:
    directus = _Directus()
    source_id = await _placeholder(directus)
    with pytest.raises(HTTPException) as patched:
        await update_project_source_capabilities(
            request=_request(), project_id=PROJECT, source_id=source_id,
            body=ProjectSourceCapabilitiesUpdateRequest(capabilities=["read"], updated_at=2),
            team_id=None, current_user=SimpleNamespace(id=OWNER), directus_service=directus,
        )
    assert patched.value.detail == "SOURCE_CREATION_PENDING"
    # No host session is registered at all; deletion must still work.
    deleted = await delete_project_source(
        request=_request(), project_id=PROJECT, source_id=source_id, confirmation_source_id=source_id,
        team_id=None, current_user=SimpleNamespace(id=OWNER), directus_service=directus,
    )
    assert deleted == {"deleted": True}
    assert source_id not in directus.project.sources


async def _host_service(source_id: str, capabilities: list[str], device: str = HOST_DEVICE) -> tuple[ProjectRemoteAccessService, MemoryCache]:
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id=OWNER, device_fingerprint_hash="connection", stable_device_fingerprint_hash=device,
        source_session_id="host-session",
        bindings=[{"project_id": PROJECT, "source_id": source_id, "capabilities": capabilities, "key_epoch": 1}],
        confirmed_takeover=False, now=2_000,
    )
    return service, cache


def _create_request_args(**extra: Any) -> dict[str, Any]:
    return dict(
        user_id=OWNER, project_id=PROJECT, source_id="src_x", request_id="req-1",
        requesting_client_id="chat-client", operation="create_source", key_epoch=1,
        encrypted_envelope="opaque", now=2_001, **extra,
    )


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_capability_allowlist_and_operation_class() -> None:
    assert "create_source" in ALLOWED_OPERATIONS
    assert {"create_source"} <= WRITE_OPERATIONS & SINGLE_USE_OPERATIONS
    service, _ = await _host_service("src_x", ["create_source"])
    active = await service.get_active_binding(OWNER, PROJECT, "src_x", now=2_001)
    assert active["capabilities"] == ["create_source"]
    with pytest.raises(ProjectRemoteAccessError, match="invalid_source_capabilities"):
        await _host_service("src_x", ["create_sources"])
    ProjectRemoteAccessRequestCreate(
        request_id="r", requesting_client_id="c", operation="create_source", key_epoch=1,
        encrypted_envelope="opaque", chat_id="c1", operation_id="o1", proposal_digest=DIGEST_RUN,
    )
    with pytest.raises(ValidationError):
        ProjectRemoteAccessRequestCreate(
            request_id="r", requesting_client_id="c", operation="create_source", key_epoch=1,
            encrypted_envelope="opaque",
        )


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_create_source_relay_needs_write_context_and_the_create_source_capability() -> None:
    service, cache = await _host_service("src_x", ["create_source"])
    with pytest.raises(ProjectRemoteAccessError, match="write_context_required"):
        await service.create_request(**_create_request_args())
    await service.create_request(
        chat_id="sub-1", operation_id="op-new-1", proposal_digest=DIGEST_RUN,
        workspace_chat_id="root-1", **_create_request_args(),
    )
    payload = cache.published[-1][1]["payload"]
    assert (payload["operation"], payload["operation_id"], payload["workspace_chat_id"]) == (
        "create_source", "op-new-1", "root-1",
    )
    delivery = await service.require_remote_write_request(
        host_user_id=OWNER, project_id=PROJECT, source_id="src_x", source_session_id="host-session",
        request_id="req-1", stable_device_fingerprint_hash=HOST_DEVICE, now=2_002,
    )
    assert delivery["operation"] == "create_source"
    with pytest.raises(ProjectRemoteAccessError, match="write_request_unavailable"):
        await service.require_remote_write_request(
            host_user_id=OWNER, project_id=PROJECT, source_id="src_x", source_session_id="host-session",
            request_id="req-1", stable_device_fingerprint_hash=OTHER_DEVICE, now=2_002,
        )
    # write_request alone must not stand in for create_source.
    plain, _ = await _host_service("src_x", ["write_request"])
    with pytest.raises(ProjectRemoteAccessError, match="source_capability_denied"):
        await plain.create_request(
            chat_id="c", operation_id="o", proposal_digest=DIGEST_RUN, **_create_request_args(),
        )


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_create_source_approval_is_single_use() -> None:
    authorizer = _command_authorizer(_ConsumableCache(), "always_ask")
    await authorizer.approve_write(
        user_id="user-1", chat_id="chat-1", project_id="project-1",
        operation_id="op-new-1", proposal_digest=DIGEST_RUN,
    )
    kwargs = dict(
        requester_user_id="user-1", chat_id="chat-1", project_id="project-1",
        operation_id="op-new-1", proposal_digest=DIGEST_RUN, consume_approval=True,
        single_use="create_source" in SINGLE_USE_OPERATIONS,
    )
    assert (await authorizer.require_write_authorization(**kwargs))["approval"] == "consumed"
    with pytest.raises(ProjectWriteAuthorizationError) as reused:
        await authorizer.require_write_authorization(**kwargs)
    assert reused.value.code == "PROJECT_OPERATION_ALREADY_USED"


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_relay_route_separates_placeholders_from_ordinary_sources() -> None:
    directus = _Directus()
    placeholder_id = await _placeholder(directus)
    directus.project.sources["real"] = {
        "source_id": "real", "status": "offline", "capabilities": ["read"],
        "attached_by_user_hash": hash_id(OWNER),
    }

    def body(operation: str) -> ProjectRemoteAccessRequestCreate:
        extra = dict(chat_id="c1", operation_id="o1", proposal_digest=DIGEST_RUN) if operation == "create_source" else {}
        return ProjectRemoteAccessRequestCreate(
            request_id="r1", requesting_client_id="c", operation=operation, key_epoch=1,
            encrypted_envelope="opaque", **extra,
        )

    for source_id, operation, detail in (
        (placeholder_id, "list", "SOURCE_CREATION_PENDING"),
        ("real", "create_source", "SOURCE_NOT_CREATION_PENDING"),
    ):
        with pytest.raises(HTTPException) as refused:
            await create_project_remote_access_request(
                project_id=PROJECT, source_id=source_id, body=body(operation), request=_request(),
                team_id=None, current_user=SimpleNamespace(id=OWNER), directus_service=directus,
            )
        assert (refused.value.status_code, refused.value.detail) == (409, detail)


async def _list(directus: _Directus, cache: Any) -> dict[str, Any]:
    result = await list_project_sources(
        request=_request(cache=cache), project_id=PROJECT, team_id=None,
        current_user=SimpleNamespace(id=OWNER), directus_service=directus,
    )
    return result["sources"][0]


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_registered_placeholder_lists_session_and_key_epoch() -> None:
    import time

    directus = _Directus()
    source_id = await _placeholder(directus)
    cache = MemoryCache()
    await ProjectRemoteAccessService(cache).register_session(
        user_id=OWNER, device_fingerprint_hash="session-device",
        stable_device_fingerprint_hash=HOST_DEVICE, source_session_id="session-1",
        bindings=[{
            "project_id": PROJECT, "source_id": source_id,
            "capabilities": ["create_source"], "key_epoch": 3,
        }],
        confirmed_takeover=False, now=int(time.time()),
    )
    row = await _list(directus, cache)
    assert (row["status"], row["source_session_id"], row["key_epoch"], row["host_device_hash"]) == (
        "creation_pending", "session-1", 3, HOST_DEVICE,
    )


# contract-test: supporting surface=rest_api assertions=projects.creation.machine-folder
@pytest.mark.anyio
async def test_unregistered_placeholder_lists_without_session() -> None:
    directus = _Directus()
    await _placeholder(directus)
    row = await _list(directus, MemoryCache())
    assert (row["status"], row["source_session_id"], row["key_epoch"], row["host_device_hash"]) == (
        "creation_pending", None, None, HOST_DEVICE,
    )
