"""Team key rotation: removal deletes wrappers and flags the Team; uploads are validated."""

from types import SimpleNamespace

import pytest

from backend.core.api.app.services.directus.team_key_rotation_methods import (
    TeamKeyRotationError,
    TeamKeyRotationMethods,
)
from backend.core.api.app.services.directus.team_methods import TeamMethods, TeamPermissionError, hash_id
from backend.tests.test_teams_lifecycle import FakeDirectus, team_payload


@pytest.fixture(autouse=True)
def _rotation_internal_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-team-key-transaction")


class RotationDirectus(FakeDirectus):
    base_url = "http://directus.test"

    async def _make_api_request(self, method, url, *, headers, json):
        if url.endswith("/team-member-removal"):
            return await super()._make_api_request(method, url, headers=headers, json=json)
        # The JavaScript transaction tests exercise actual storage and rollback.
        # This stub checks the Python service forwards the preflighted key set.
        assert method == "POST"
        assert url == f"{self.base_url}/embed-version-transaction/team-key-rotation"
        assert headers == {"X-Internal-Service-Token": "test-team-key-transaction"}
        assert json["team_hash"] == hash_id("team-1")
        assert json["actor_user_hash"] == hash_id("alice")
        epoch = json["team_key_epoch"]
        project_uploads = {row["hashed_project_id"]: row["encrypted_project_key"] for row in json["project_key_wrappers"]}
        for row in self.rows["project_key_wrappers"]:
            row.update(encrypted_project_key=project_uploads[row["hashed_project_id"]], team_key_epoch=epoch)
        self.rows["team_key_wrappers"] = [
            {"id": f"rotated-{index}", **row, "hashed_team_id": json["team_hash"],
             "team_key_epoch": epoch, "status": "active"}
            for index, row in enumerate(json["wrappers"])
        ]
        self.rows["teams"][0].update(
            team_key_epoch=epoch, rotation_pending=False,
            encrypted_previous_team_keys=json["encrypted_previous_team_keys"],
            **{field: change["after"] for field, change in json["profile"].items()},
        )
        return SimpleNamespace(status_code=200, json=lambda: {"data": {"team_key_epoch": epoch}})


async def _team_with(*members: str):
    directus = RotationDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    for index, user in enumerate(members):
        await methods.create_invite("team-1", "alice", {"invite_id": f"i-{user}", "role": "member", "created_at": 110})
        request = await methods.accept_invite(f"i-{user}", user, accepted_at=120)
        await methods.approve_access_request("team-1", "alice", request["access_request_id"], f"cipher-{user}", approved_at=130 + index)
    directus.rows["project_key_wrappers"].extend(
        {"id": f"pkw-{n}", "hashed_team_id": hash_id("team-1"), "key_type": "team", "hashed_project_id": f"p{n}",
         "team_key_epoch": 1, "encrypted_project_key": f"old-{n}"}
        for n in (1, 2)
    )
    return directus, methods, TeamKeyRotationMethods(methods)


def _upload(*users: str, epoch: int = 2, projects=("p1", "p2")):
    return {
        "team_key_epoch": epoch,
        "wrappers": [{"hashed_user_id": hash_id(u), "encrypted_team_key": f"OMTK1.{u}"} for u in users],
        "project_key_wrappers": [{"hashed_project_id": p, "encrypted_project_key": f"new-{p}"} for p in projects],
        "encrypted_previous_team_keys": "chain",
        "profile": {
            field: {"before": team_payload()[field], "after": f"rotated-{field}"}
            for field in ("encrypted_name", "encrypted_description", "encrypted_profile_image_metadata")
        },
    }


# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_removal_deletes_wrappers_and_marks_rotation_pending() -> None:
    directus, methods, _rotation = await _team_with("bob")
    assert await methods.remove_member("team-1", "alice", "bob", removed_at=200)
    assert not [r for r in directus.rows["team_key_wrappers"] if r["hashed_user_id"] == hash_id("bob")]
    assert directus.rows["teams"][0]["rotation_pending"] is True


# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_upload_replaces_wrappers_rewraps_projects_and_clears_pending() -> None:
    directus, methods, rotation = await _team_with("bob", "carol")
    await methods.remove_member("team-1", "alice", "bob", removed_at=200)
    assert (await rotation.context("team-1", "alice"))["rotation_pending"] is True

    assert await rotation.apply("team-1", "alice", _upload("alice", "carol")) == 2

    team = directus.rows["teams"][0]
    assert team["team_key_epoch"] == 2 and team["rotation_pending"] is False
    assert team["encrypted_name"] == "rotated-encrypted_name"
    assert {r["hashed_user_id"] for r in directus.rows["team_key_wrappers"]} == {hash_id("alice"), hash_id("carol")}
    assert {r["team_key_epoch"] for r in directus.rows["team_key_wrappers"]} == {2}
    assert {r["encrypted_project_key"] for r in directus.rows["project_key_wrappers"]} == {"new-p1", "new-p2"}
    assert {r["team_key_epoch"] for r in directus.rows["project_key_wrappers"]} == {2}

    # A complete next-epoch upload still requires a pending rotation.
    with pytest.raises(TeamKeyRotationError, match="not pending"):
        await rotation.apply("team-1", "alice", _upload("alice", "carol", epoch=3))
    assert team["team_key_epoch"] == 2
    assert {r["team_key_epoch"] for r in directus.rows["team_key_wrappers"]} == {2}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upload",
    [
        _upload("alice", "carol", epoch=3),
        _upload("alice", "carol", epoch=1),
        _upload("alice"),
        _upload("alice", "carol", "bob"),
        _upload("alice", "carol", projects=("p1",)),
        _upload("alice", "carol", projects=("p1", "p2", "p3")),
    ],
)
# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
async def test_upload_refused_for_wrong_epoch_or_wrong_member_or_project_set(upload) -> None:
    directus, methods, rotation = await _team_with("bob", "carol")
    await methods.remove_member("team-1", "alice", "bob", removed_at=200)
    with pytest.raises(TeamKeyRotationError):
        await rotation.apply("team-1", "alice", upload)
    assert directus.rows["teams"][0]["rotation_pending"] is True
    assert {r["encrypted_project_key"] for r in directus.rows["project_key_wrappers"]} == {"old-1", "old-2"}


# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_non_admin_and_removed_member_cannot_read_or_upload() -> None:
    _directus, methods, rotation = await _team_with("bob", "carol")
    await methods.remove_member("team-1", "alice", "bob", removed_at=200)
    for user in ("carol", "bob"):
        with pytest.raises(TeamPermissionError):
            await rotation.apply("team-1", user, _upload("alice", "carol"))
        with pytest.raises(TeamPermissionError):
            await rotation.context("team-1", user)


# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_member_claims_sealed_wrapper_once_with_master_wrapper() -> None:
    directus, methods, rotation = await _team_with("bob", "carol")
    await methods.remove_member("team-1", "alice", "bob", removed_at=200)
    await rotation.apply("team-1", "alice", _upload("alice", "carol"))
    await rotation.claim("team-1", "carol", 2, "master-wrapped")
    carol = next(r for r in directus.rows["team_key_wrappers"] if r["hashed_user_id"] == hash_id("carol"))
    assert carol["encrypted_team_key"] == "master-wrapped"
    with pytest.raises(TeamKeyRotationError):
        await rotation.claim("team-1", "carol", 2, "again")
    with pytest.raises(TeamKeyRotationError):
        await rotation.claim("team-1", "alice", 1, "stale")
    with pytest.raises(TeamPermissionError):
        await rotation.claim("team-1", "bob", 2, "removed")


# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_team_reads_only_publish_wrappers_for_the_committed_epoch() -> None:
    directus, methods, _ = await _team_with("bob")
    team = directus.rows["teams"][0]
    original = next(row for row in directus.rows["team_key_wrappers"] if row["hashed_user_id"] == hash_id("alice"))
    pending = {**original, "team_key_epoch": 2, "encrypted_team_key": "rotated-wrapper"}
    directus.rows["team_key_wrappers"].insert(0, pending)
    before = await methods.get_team("team-1", "alice")
    assert before["team_key_epoch"] == 1
    assert before["encrypted_team_key"] == original["encrypted_team_key"]
    assert (await methods.list_teams("alice"))[0]["encrypted_team_key"] == original["encrypted_team_key"]

    team["team_key_epoch"] = 2
    after = await methods.get_team("team-1", "alice")
    assert after["team_key_epoch"] == 2
    assert after["encrypted_team_key"] == "rotated-wrapper"
    assert (await methods.list_teams("alice"))[0]["encrypted_team_key"] == "rotated-wrapper"

    directus.rows["team_key_wrappers"].remove(pending)
    assert "encrypted_team_key" not in await methods.get_team("team-1", "alice")
    assert "encrypted_team_key" not in (await methods.list_teams("alice"))[0]
