"""Current authorization and ciphertext-boundary tests for cold archives.

Archive identifiers never replace live owner or Team authorization. Metadata and
parts expose client ciphertext plus safe routing fields, never private plaintext.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import hashlib

import pytest

from backend.core.api.app.services.cold_archive_service import ColdArchiveAuthorizationError, ColdArchiveService


class TeamService:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def require_team_role(self, _team_id, _user_id, allowed_roles):
        if self.role not in allowed_roles:
            raise RuntimeError("TEAM_PERMISSION_DENIED")


class Directus:
    def __init__(self, role: str | None = None) -> None:
        self.team = TeamService(role)


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_personal_owner_reads_only_their_archive() -> None:
    service = ColdArchiveService(directus_service=Directus(), s3_service=object())
    manifest = {"hashed_user_id": hashlib.sha256(b"alice").hexdigest(), "hashed_team_id": None}

    await service.authorize_manifest(manifest, user_id="alice", team_id=None, mutation=False)
    with pytest.raises(ColdArchiveAuthorizationError):
        await service.authorize_manifest(manifest, user_id="bob", team_id=None, mutation=False)


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,teams.membership.role-gated
@pytest.mark.asyncio
async def test_team_viewer_reads_but_cannot_promote_and_removed_member_gets_nothing() -> None:
    manifest = {"hashed_user_id": None, "hashed_team_id": hashlib.sha256(b"team-1").hexdigest()}
    viewer = ColdArchiveService(directus_service=Directus("viewer"), s3_service=object())
    removed = ColdArchiveService(directus_service=Directus(None), s3_service=object())

    await viewer.authorize_manifest(manifest, user_id="alice", team_id="team-1", mutation=False)
    with pytest.raises(ColdArchiveAuthorizationError):
        await viewer.authorize_manifest(manifest, user_id="alice", team_id="team-1", mutation=True)
    with pytest.raises(ColdArchiveAuthorizationError):
        await removed.authorize_manifest(manifest, user_id="alice", team_id="team-1", mutation=False)


# contract-test: direct surface=rest_api assertions=storage.privacy.ciphertext-boundary
def test_public_manifest_projection_excludes_graph_and_storage_routing() -> None:
    service = ColdArchiveService(directus_service=Directus(), s3_service=object())
    manifest = {
        "archive_id": "archive-1",
        "resource_type": "chat",
        "resource_id": "chat-1",
        "encrypted_listing_metadata": "cipher-listing",
        "active_generation": 1,
        "archived_at": 10,
        "object_key": "private/path",
        "graph": {"messages": [{"content": "plaintext"}]},
    }

    assert service.public_manifest(manifest) == {
        "archive_id": "archive-1",
        "resource_type": "chat",
        "resource_id": "chat-1",
        "encrypted_listing_metadata": "cipher-listing",
        "active_generation": 1,
        "archived_at": 10,
        "source": "cold",
    }
