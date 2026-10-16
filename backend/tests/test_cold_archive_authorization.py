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


class ListingDirectus(Directus):
    def __init__(self, role: str | None = None) -> None:
        super().__init__(role)
        self.filters = None

    async def get_items(self, collection, params, **_kwargs):
        assert collection == "cold_archive_manifests"
        self.filters = params["filter"]
        return []


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


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,teams.membership.role-gated
@pytest.mark.asyncio
async def test_archive_index_keeps_personal_and_team_scopes_disjoint() -> None:
    directus = ListingDirectus("member")
    service = ColdArchiveService(directus_service=directus, s3_service=object())

    await service.list_archives(user_id="alice", resource_type="chat")
    personal_filters = directus.filters["_and"]
    assert {"hashed_user_id": {"_eq": hashlib.sha256(b"alice").hexdigest()}} in personal_filters
    assert {"hashed_team_id": {"_null": True}} in personal_filters

    await service.list_archives(user_id="alice", resource_type="chat", team_id="team-1")
    team_filters = directus.filters["_and"]
    assert {"hashed_team_id": {"_eq": hashlib.sha256(b"team-1").hexdigest()}} in team_filters
    assert {"hashed_team_id": {"_null": True}} not in team_filters


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.versions.metadata-and-payload,storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_legacy_full_graph_migration_is_held_before_claim_or_metadata_deletion():
    from unittest.mock import AsyncMock
    from backend.core.api.app.services.cold_archive_service import ColdArchiveConflictError
    directus = AsyncMock()
    service = ColdArchiveService(directus_service=directus, s3_service=object())
    with pytest.raises(ColdArchiveConflictError, match="FULL_GRAPH_PRUNING_POLICY_PENDING"):
        await service.archive_chat("chat")
    with pytest.raises(ColdArchiveConflictError, match="FULL_GRAPH_PRUNING_POLICY_PENDING"):
        await service._delete_hot_graph({"embeds": [{"id": "current-head"}], "chats": [{"id": "root"}, {"id": "child"}]})
    directus.update_item_if_version.assert_not_awaited()
    directus.delete_item.assert_not_awaited()
