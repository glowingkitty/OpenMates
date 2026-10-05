"""Teams V1 data portability tests.

Team export/import must behave like personal export in privacy posture while
remaining strictly team-scoped: owner/admin only, no viewer exports, no personal
rows, no team-key or connected-account secret leakage, and destination-team-only
imports after rewrap.
"""

import base64
from copy import deepcopy
import hashlib

import pytest

from backend.core.api.app.services.directus.team_methods import TeamMethods, TeamPermissionError, hash_id
from backend.core.api.app.services.team_data_portability_service import TeamDataPortabilityError, TeamDataPortabilityService
from backend.tests.test_teams_lifecycle import FakeDirectus, team_payload


async def _seed_export_data() -> tuple[FakeDirectus, TeamDataPortabilityService]:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    directus.team = methods
    await methods.create_team("alice", team_payload())
    directus.rows["user_app_settings_and_memories"].append({
        "id": "team-memory",
        "owner_context": "team",
        "hashed_team_id": hash_id("team-1"),
        "hashed_user_id": None,
        "encrypted_item_json": "cipher-team-memory",
    })
    directus.rows["user_app_settings_and_memories"].append({
        "id": "personal-memory",
        "owner_context": "personal",
        "hashed_team_id": None,
        "hashed_user_id": hash_id("alice"),
        "encrypted_item_json": "cipher-personal-memory",
    })
    directus.rows["connected_accounts"].append({
        "id": "team-account",
        "owner_context": "team",
        "hashed_team_id": hash_id("team-1"),
        "encrypted_refresh_token_bundle": "cipher-secret-token",
    })
    directus.rows["connected_accounts"].append({
        "id": "other-team-account",
        "owner_context": "team",
        "hashed_team_id": hash_id("team-2"),
        "encrypted_refresh_token_bundle": "cipher-other-secret",
    })
    return directus, TeamDataPortabilityService(directus)


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local,teams.connected-accounts.team-owned-isolation,storage.privacy.ciphertext-boundary
async def test_owner_export_includes_only_selected_team_rows_and_redacts_secrets() -> None:
    directus, service = await _seed_export_data()

    result = await service.export_team_data("team-1", "alice", export_id="export-1", created_at=200)

    artifact = result["artifact"]
    memories = artifact["collections"]["user_app_settings_and_memories"]
    accounts = artifact["collections"]["connected_accounts"]
    assert [row["id"] for row in memories] == ["team-memory"]
    assert [row["id"] for row in accounts] == ["team-account"]
    assert accounts[0]["encrypted_refresh_token_bundle"] == "<redacted>"
    serialized = repr(artifact)
    assert "personal-memory" not in serialized
    assert "other-team-account" not in serialized
    assert "cipher-secret-token" not in serialized
    assert directus.rows["team_data_exports"][0]["export_id"] == "export-1"


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated
async def test_viewer_export_is_denied() -> None:
    directus, service = await _seed_export_data()
    methods = directus.team
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-viewer", "role": "viewer", "created_at": 110})
    request = await methods.accept_invite("invite-viewer", "vera", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-vera", approved_at=130)

    with pytest.raises(TeamPermissionError):
        await service.export_team_data("team-1", "vera")


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
async def test_import_requires_destination_rewrap_and_writes_team_rows_only() -> None:
    directus, service = await _seed_export_data()
    await directus.team.create_team("alice", team_payload(team_id="team-2", slug="team-two"))
    export = await service.export_team_data("team-1", "alice", export_id="export-1", created_at=200)

    with pytest.raises(TeamDataPortabilityError):
        await service.import_team_data("team-2", "alice", export["artifact"], imported_at=300)

    artifact = {
        **export["artifact"], "rewrapped_with_destination_team_key": True,
        "collections": {key: export["artifact"]["collections"][key] for key in (
            "user_app_settings_and_memories", "connected_accounts", "team_connected_account_grants",
        )},
    }
    result = await service.import_team_data("team-2", "alice", artifact, imported_at=300)

    assert result["success"] is True
    assert result["hashed_team_id"] == hash_id("team-2")
    imported_memories = [row for row in directus.rows["user_app_settings_and_memories"] if row.get("hashed_team_id") == hash_id("team-2")]
    assert imported_memories
    assert all(row["owner_context"] == "team" for row in imported_memories)


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.chat-billing.team-credit-boundary
@pytest.mark.parametrize("actor_role", ["owner", "admin"])
@pytest.mark.parametrize("collection", ["team_memberships", "team_invites", "team_credit_accounts", "team_credit_events", "team_usage_events"])
async def test_import_rejects_authority_records_before_any_metadata_or_ledger_write(actor_role, collection) -> None:
    directus, service = await _seed_export_data()
    actor = "alice"
    if actor_role == "admin":
        actor = "bob"
        directus.rows["team_memberships"].append({
            "id": "admin-membership", "hashed_team_id": hash_id("team-1"),
            "hashed_user_id": hash_id(actor), "role": "admin", "status": "active",
        })
    forged = {
        "hashed_team_id": hash_id("team-1"), "hashed_user_id": hash_id("new-owner"),
        "role": "owner", "status": "active", "balance_credits": 1000000,
        "event_type": "purchase", "amount": 1000000, "credit_amount": -1000000,
    }
    artifact = {
        "schema": "openmates.team_export.v1", "rewrapped_with_destination_team_key": True,
        "collections": {
            # This valid row is ordered first to prove complete preflight.
            "user_app_settings_and_memories": [{
                "owner_context": "team", "hashed_team_id": hash_id("team-1"), "encrypted_item_json": "cipher-import",
            }],
            collection: [forged],
        },
    }
    before_rows = deepcopy(directus.rows)
    before_created = deepcopy(directus.created)
    with pytest.raises(TeamDataPortabilityError, match=rf"Server-controlled Team records cannot be imported \({collection}\).*no rows were imported"):
        await service.import_team_data("team-1", actor, artifact)
    assert directus.rows == before_rows
    assert directus.created == before_created
    with pytest.raises(TeamPermissionError):
        await directus.team.require_team_role("team-1", "new-owner", {"owner"})


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.chat-billing.team-credit-boundary
async def test_full_team_export_cannot_be_replayed_to_restore_balances_or_memberships() -> None:
    directus, service = await _seed_export_data()
    artifact = (await service.export_team_data("team-1", "alice"))["artifact"]
    artifact["rewrapped_with_destination_team_key"] = True
    before_rows = deepcopy(directus.rows)
    before_created = deepcopy(directus.created)
    with pytest.raises(TeamDataPortabilityError, match="Server-controlled Team records cannot be imported"):
        await service.import_team_data("team-1", "alice", artifact)
    assert directus.rows == before_rows
    assert directus.created == before_created


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local
async def test_import_rejects_personal_rows_before_persistence() -> None:
    directus, service = await _seed_export_data()
    artifact = {
        "schema": "openmates.team_export.v1",
        "rewrapped_with_destination_team_key": True,
        "collections": {
            "user_app_settings_and_memories": [{"owner_context": "personal", "hashed_user_id": hash_id("alice")}],
        },
    }

    with pytest.raises(TeamDataPortabilityError):
        await service.import_team_data("team-1", "alice", artifact, imported_at=300)


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,storage.export.persisted-bounded-complete
@pytest.mark.parametrize("collection", ["chats", "chat_message_archive_pages", "embeds", "embed_diffs", "cold_archives"])
async def test_import_rejects_unsupported_content_before_any_metadata_writes(collection) -> None:
    directus, service = await _seed_export_data()
    created_before = list(directus.created)
    artifact = {
        "schema": "openmates.team_export.v1",
        "rewrapped_with_destination_team_key": True,
        "collections": {
            "user_app_settings_and_memories": [{"owner_context": "team", "hashed_team_id": hash_id("team-1"), "encrypted_item_json": "cipher-memory"}],
            collection: [{"id": "unsupported-content"}],
        },
    }
    with pytest.raises(TeamDataPortabilityError, match="restore is unsupported.*no rows were imported"):
        await service.import_team_data("team-1", "alice", artifact)
    assert directus.created == created_before
    assert len(directus.rows["user_app_settings_and_memories"]) == 2


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.context.full-switch-local,teams.connected-accounts.team-owned-isolation
async def test_import_preflights_invalid_late_metadata_row_before_writes() -> None:
    directus, service = await _seed_export_data()
    created_before = list(directus.created)
    artifact = {
        "schema": "openmates.team_export.v1", "rewrapped_with_destination_team_key": True,
        "collections": {
            "user_app_settings_and_memories": [{"owner_context": "team", "hashed_team_id": hash_id("team-1")}],
            "connected_accounts": [{"owner_context": "personal", "hashed_user_id": hash_id("alice")}],
        },
    }
    with pytest.raises(TeamDataPortabilityError, match="Personal-context"):
        await service.import_team_data("team-1", "alice", artifact)
    assert directus.created == created_before


class ArchiveS3:
    def __init__(self, content: bytes):
        self.content = content
        self.reads = []

    async def get_replicated_file_stream(self, **kwargs):
        self.reads.append(kwargs)
        yield self.content


def seed_cold_archive(directus, *, owner_hash=None):
    content = b"immutable-compressed-client-ciphertext"
    directus.rows["cold_archive_manifests"].append({
        "id": "manifest-1", "archive_id": "archive-1", "resource_type": "chat", "resource_id": "cold-chat",
        "hashed_team_id": owner_hash or hash_id("team-1"), "hashed_user_id": hash_id("alice"),
        "active_generation": 2, "part_count": 1, "state": "cold", "graph_checksum": "f" * 64,
        "encrypted_listing_metadata": {"encrypted_title": "cipher-title"}, "archived_at": 200,
    })
    directus.rows["cold_archive_parts"].append({
        "id": "part-row", "archive_id": "archive-1", "part_id": "part-00001", "part_number": 1, "generation": 2,
        "logical_bucket": "cold_archives", "object_key": "private/team/object", "size_bytes": len(content),
        "checksum": hashlib.sha256(content).hexdigest(), "regional_states": {"nbg1": "verified", "fsn1": "pending"},
    })
    return content


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
async def test_team_export_contains_verified_cold_ciphertext_without_storage_routing() -> None:
    directus, _ = await _seed_export_data()
    content = seed_cold_archive(directus)
    s3 = ArchiveS3(content)
    result = await TeamDataPortabilityService(directus, s3_service=s3).export_team_data("team-1", "alice")
    archives = result["artifact"]["collections"]["cold_archives"]
    assert len(archives) == 1
    part = archives[0]["parts"][0]
    assert base64.b64decode(part["ciphertext"]) == content
    assert part["generation"] == 2
    assert s3.reads[0]["regions"] == ("nbg1",)
    assert "private/team/object" not in repr(archives)
    assert "regional_states" not in repr(archives)
    assert directus.rows["cold_archive_parts"][0]["object_key"] == "private/team/object"


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
@pytest.mark.parametrize("failure", ["missing", "checksum", "size", "generation", "number", "no_storage", "no_regions"])
async def test_team_export_fails_without_ready_record_when_cold_parts_unverified(failure) -> None:
    directus, _ = await _seed_export_data()
    content = seed_cold_archive(directus)
    part = directus.rows["cold_archive_parts"][0]
    if failure == "missing":
        directus.rows["cold_archive_parts"].clear()
    elif failure == "checksum":
        part["checksum"] = "0" * 64
    elif failure == "size":
        part["size_bytes"] = 4 * 1024 * 1024 + 1
    elif failure == "generation":
        part["generation"] = 3
    elif failure == "number":
        part["part_number"] = 2
    elif failure == "no_regions":
        part["regional_states"] = {"nbg1": "pending"}
    s3 = None if failure == "no_storage" else ArchiveS3(content)
    with pytest.raises(TeamDataPortabilityError, match="cold archive"):
        await TeamDataPortabilityService(directus, s3_service=s3).export_team_data("team-1", "alice")
    assert directus.rows["team_data_exports"] == []
    if s3 and failure in {"size", "no_regions", "missing", "generation", "number"}:
        assert s3.reads == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.export.persisted-bounded-complete
async def test_team_export_does_not_read_another_teams_cold_ciphertext() -> None:
    directus, _ = await _seed_export_data()
    s3 = ArchiveS3(seed_cold_archive(directus, owner_hash=hash_id("team-2")))
    result = await TeamDataPortabilityService(directus, s3_service=s3).export_team_data("team-1", "alice")
    assert result["artifact"]["collections"]["cold_archives"] == []
    assert s3.reads == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.parametrize("content_kind", ["metadata", "cold_ciphertext"])
async def test_team_inline_export_byte_limit_fails_visibly_without_ready_record(monkeypatch, content_kind) -> None:
    from backend.core.api.app.services import team_data_portability_service as portability

    directus, _ = await _seed_export_data()
    monkeypatch.setattr(portability, "MAX_TEAM_INLINE_EXPORT_BYTES", 6000)
    s3 = None
    if content_kind == "metadata":
        directus.rows["user_app_settings_and_memories"][0]["encrypted_item_json"] = "ciphertext" * 1000
    else:
        seed_cold_archive(directus)
        content = b"ciphertext" * 1000
        part = directus.rows["cold_archive_parts"][0]
        part["size_bytes"] = len(content)
        part["checksum"] = hashlib.sha256(content).hexdigest()
        s3 = ArchiveS3(content)
    with pytest.raises(TeamDataPortabilityError, match=r"inline byte limit.*POST /v1/account-exports with team_id"):
        await TeamDataPortabilityService(directus, s3_service=s3).export_team_data("team-1", "alice")
    assert directus.rows["team_data_exports"] == []


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.workspace.surface-parity,teams.context.full-switch-local
@pytest.mark.parametrize("confirmed_rows", [0, 1])
@pytest.mark.parametrize("failure", ["negative_ack", "exception"])
async def test_import_reports_persistence_failure_and_preserves_confirmed_partial_writes(confirmed_rows, failure) -> None:
    directus, service = await _seed_export_data()
    create = directus.create_item
    attempts = 0

    async def fail_selected_write(collection, record, admin_required=False):
        nonlocal attempts
        if collection == "user_app_settings_and_memories":
            attempts += 1
            if attempts == confirmed_rows + 1:
                if failure == "exception":
                    raise RuntimeError("synthetic persistence failure")
                return False, None
        return await create(collection, record, admin_required=admin_required)

    directus.create_item = fail_selected_write
    artifact = {
        "schema": "openmates.team_export.v1", "rewrapped_with_destination_team_key": True,
        "collections": {"user_app_settings_and_memories": [
            {"owner_context": "team", "hashed_team_id": hash_id("team-1"),
             "encrypted_item_json": f"destination-ciphertext-{index}"}
            for index in range(3)
        ]},
    }
    with pytest.raises(TeamDataPortabilityError, match=rf"{confirmed_rows} confirmed imported rows.*partial data.*before retrying"):
        await service.import_team_data("team-1", "alice", artifact)
    imported = [row for row in directus.rows["user_app_settings_and_memories"]
                if str(row.get("encrypted_item_json", "")).startswith("destination-ciphertext-")]
    assert len(imported) == confirmed_rows
    assert [row["encrypted_item_json"] for row in imported] == [f"destination-ciphertext-{index}" for index in range(confirmed_rows)]
    assert all(row["hashed_team_id"] == hash_id("team-1") and row["owner_context"] == "team" for row in imported)
    assert attempts == confirmed_rows + 1
