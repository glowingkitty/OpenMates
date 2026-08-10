"""Teams V1 data portability tests.

Team export/import must behave like personal export in privacy posture while
remaining strictly team-scoped: owner/admin only, no viewer exports, no personal
rows, no team-key or connected-account secret leakage, and destination-team-only
imports after rewrap.
"""

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
async def test_viewer_export_is_denied() -> None:
    directus, service = await _seed_export_data()
    methods = directus.team
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-viewer", "role": "viewer", "created_at": 110})
    request = await methods.accept_invite("invite-viewer", "vera", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-vera", approved_at=130)

    with pytest.raises(TeamPermissionError):
        await service.export_team_data("team-1", "vera")


@pytest.mark.anyio
async def test_import_requires_destination_rewrap_and_writes_team_rows_only() -> None:
    directus, service = await _seed_export_data()
    await directus.team.create_team("alice", team_payload(team_id="team-2", slug="team-two"))
    export = await service.export_team_data("team-1", "alice", export_id="export-1", created_at=200)

    with pytest.raises(TeamDataPortabilityError):
        await service.import_team_data("team-2", "alice", export["artifact"], imported_at=300)

    artifact = {**export["artifact"], "rewrapped_with_destination_team_key": True}
    result = await service.import_team_data("team-2", "alice", artifact, imported_at=300)

    assert result["success"] is True
    assert result["hashed_team_id"] == hash_id("team-2")
    imported_memories = [row for row in directus.rows["user_app_settings_and_memories"] if row.get("hashed_team_id") == hash_id("team-2")]
    assert imported_memories
    assert all(row["owner_context"] == "team" for row in imported_memories)


@pytest.mark.anyio
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
