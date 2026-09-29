"""A connected Project image read retains the encrypted remote bridge boundary."""

from __future__ import annotations

import pytest

from backend.core.api.app.routes.projects import ProjectRemoteAccessRequestCreate
from backend.core.api.app.services.project_remote_access_service import (
    ProjectRemoteAccessError,
    ProjectRemoteAccessService,
)
from backend.tests.test_project_remote_access_bridge import MemoryCache, binding


# contract-test: supporting surface=rest_api assertions=projects.files.no-server-decryption-authority,projects.access.explicit-context,projects.files.connected-embed-previews
@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["read_image_chunk", "read_file_chunk"])
async def test_file_chunks_use_existing_read_capability_and_opaque_bridge(operation: str) -> None:
    body = ProjectRemoteAccessRequestCreate(
        request_id="image-request", requesting_client_id="browser-1",
        operation=operation, key_epoch=1, encrypted_envelope="opaque-request",
    )
    cache = MemoryCache()
    service = ProjectRemoteAccessService(cache)
    await service.register_session(
        user_id="user-1", device_fingerprint_hash="device-cli", source_session_id="session-1",
        bindings=[binding()], confirmed_takeover=False, now=1_000,
    )
    result = await service.create_request(
        user_id="user-1", project_id="project-1", source_id="source-1",
        request_id=body.request_id, requesting_client_id=body.requesting_client_id,
        operation=body.operation, key_epoch=body.key_epoch,
        encrypted_envelope=body.encrypted_envelope, now=1_001,
    )
    assert result["status"] in {"queued", "delivered"}
    assert "opaque-request" not in str(result)

    denied_cache = MemoryCache()
    denied_service = ProjectRemoteAccessService(denied_cache)
    search_only = {**binding(), "capabilities": ["search"]}
    await denied_service.register_session(
        user_id="user-1", device_fingerprint_hash="device-cli", source_session_id="session-2",
        bindings=[search_only], confirmed_takeover=False, now=1_000,
    )
    with pytest.raises(ProjectRemoteAccessError, match="source_capability_denied"):
        await denied_service.create_request(
            user_id="user-1", project_id="project-1", source_id="source-1",
            request_id="denied-image", requesting_client_id="browser-1",
            operation=operation, key_epoch=1,
            encrypted_envelope="opaque-request", now=1_001,
        )


# contract-test: supporting surface=rest_api assertions=projects.files.connected-embed-previews
@pytest.mark.anyio
async def test_file_chunk_quota_supports_sustained_downloads_without_raising_other_request_limit() -> None:
    service = ProjectRemoteAccessService(MemoryCache())
    for _ in range(256):
        await service._consume_rate_limit("user-1", 6_000, "read_file_chunk")
    for _ in range(60):
        await service._consume_rate_limit("user-1", 6_000, "list")
    with pytest.raises(ProjectRemoteAccessError, match="request_rate_limited"):
        await service._consume_rate_limit("user-1", 6_000, "list")
    with pytest.raises(ProjectRemoteAccessError, match="request_rate_limited"):
        await service._consume_rate_limit("user-1", 6_000, "read_file_chunk")
    await service._consume_rate_limit("user-1", 6_060, "read_file_chunk")
