"""Teams V1 lifecycle, membership, and permission contract tests.

These tests exercise Directus helper behavior without a live CMS. They protect
the first backend Teams slice: team creation, owner membership, team key wrapper
creation, invite access approval, viewer read-only role data, and removal revocation.
"""

from collections import defaultdict
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.directus.team_methods import TeamMethods, TeamPermissionError, hash_id


class FakeDirectus:
    base_url = "http://directus.test"

    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.created: list[tuple[str, dict, bool]] = []
        self.updated: list[tuple[str, str, dict, bool]] = []
        self.reads: list[tuple[str, dict]] = []
        self.removal_status: int | None = None

    async def _make_api_request(self, method, url, *, headers, json):
        """Simulate the internal transport; transaction rollback is tested in JS."""
        assert method == "POST"
        assert url == f"{self.base_url}/embed-version-transaction/team-member-removal"
        assert headers == {"X-Internal-Service-Token": "test-team-key-transaction"}
        if self.removal_status is not None:
            return SimpleNamespace(status_code=self.removal_status)
        team_hash = json["team_hash"]
        active = {
            row["hashed_user_id"]: row for row in self.rows["team_memberships"]
            if row["hashed_team_id"] == team_hash and row["status"] == "active"
        }
        team = next((row for row in self.rows["teams"]
                     if row["hashed_team_id"] == team_hash and row["status"] == "active"), None)
        if not team or active.get(json["actor_user_hash"], {}).get("role") not in {"owner", "admin"}:
            return SimpleNamespace(status_code=403)
        target = active.get(json["target_user_hash"])
        if not target or target["role"] == "owner":
            return SimpleNamespace(
                status_code=404, json=lambda: {"error": {"code": "team_member_not_found"}}
            )
        at = json["removed_at"]
        await self.update_item(
            "team_memberships", target["id"], {"status": "removed", "removed_at": at, "updated_at": at},
            admin_required=True,
        )
        self.rows["team_key_wrappers"] = [
            row for row in self.rows["team_key_wrappers"]
            if (row["hashed_team_id"], row["hashed_user_id"]) != (team_hash, target["hashed_user_id"])
        ]
        await self.update_item("teams", team["id"], {"rotation_pending": True, "updated_at": at}, admin_required=True)
        return SimpleNamespace(status_code=200, json=lambda: {"data": {"removed": True}})

    async def create_item(self, collection: str, record: dict, admin_required: bool = False):
        row = {"id": f"{collection}-{len(self.rows[collection]) + 1}", **record}
        self.rows[collection].append(row)
        self.created.append((collection, record.copy(), admin_required))
        return True, row

    async def update_item(self, collection: str, item_id: str, patch: dict, admin_required: bool = False):
        self.updated.append((collection, item_id, patch.copy(), admin_required))
        for row in self.rows[collection]:
            if row.get("id") == item_id:
                row.update(patch)
                return row
        return None

    async def delete_item(self, collection: str, item_id: str, admin_required: bool = False):
        before = len(self.rows[collection])
        self.rows[collection] = [row for row in self.rows[collection] if row.get("id") != item_id]
        return len(self.rows[collection]) < before

    async def get_items(self, collection: str, params: dict, **_kwargs):
        self.reads.append((collection, params.copy()))
        rows = list(self.rows[collection])
        for key, expected in params.items():
            if key.startswith("filter[") and "][_null]" in key:
                field = key.removeprefix("filter[").split("]", 1)[0]
                rows = [row for row in rows if row.get(field) is None]
                continue
            if key.startswith("filter[") and "][_in]" in key:
                field = key.removeprefix("filter[").split("]", 1)[0]
                values = set(expected.split(","))
                rows = [row for row in rows if row.get(field) in values]
                continue
            if not key.startswith("filter[") or "][_eq]" not in key:
                continue
            field = key.removeprefix("filter[").split("]", 1)[0]
            rows = [row for row in rows if row.get(field) == expected]
        limit = params.get("limit", len(rows))
        return rows if limit == -1 else rows[:limit]


def team_payload(**overrides):
    payload = {
        "team_id": "team-1",
        "slug": "acme",
        "encrypted_name": "cipher-name",
        "encrypted_description": "cipher-description",
        "encrypted_profile_image_metadata": "cipher-profile-image-metadata",
        "encrypted_team_key": "cipher-team-key-for-owner",
        "encrypted_zero_balance": "cipher-zero-balance",
        "created_at": 100,
        "updated_at": 100,
    }
    payload.update(overrides)
    return payload


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.lifecycle.encrypted-profiled
async def test_list_teams_batches_large_membership_without_cross_user_keys() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    owner_hash = hash_id("owner")
    other_hash = hash_id("other-user")
    for index in range(184):
        team_id = f"team-{index}"
        team_hash = hash_id(team_id)
        directus.rows["team_memberships"].append({
            "hashed_team_id": team_hash, "hashed_user_id": owner_hash,
            "status": "active", "role": "owner" if index % 2 == 0 else "viewer",
        })
        directus.rows["teams"].append({
            "team_id": team_id, "hashed_team_id": team_hash,
            "status": "inactive" if index == 181 else "active",
            "encrypted_name": f"encrypted-name-{index}",
        })
        if index != 182:
            directus.rows["team_key_wrappers"].append({
                "hashed_team_id": team_hash,
                "hashed_user_id": other_hash if index == 183 else owner_hash,
                "status": "active", "team_key_epoch": 1,
                "encrypted_team_key": f"owner-key-{index}" if index != 183 else "other-user-key",
            })
    directus.rows["team_memberships"].extend([
        {"hashed_team_id": hash_id("inactive-membership"), "hashed_user_id": owner_hash, "status": "inactive", "role": "owner"},
        {"hashed_team_id": hash_id("other-user-team"), "hashed_user_id": other_hash, "status": "active", "role": "owner"},
    ])
    for team_id in ("inactive-membership", "other-user-team"):
        directus.rows["teams"].append({"team_id": team_id, "hashed_team_id": hash_id(team_id), "status": "active"})

    listed = await methods.list_teams("owner")

    assert [team["team_id"] for team in listed] == [f"team-{index}" for index in range(184) if index != 181]
    assert [team["role"] for team in listed] == ["owner" if index % 2 == 0 else "viewer" for index in range(184) if index != 181]
    assert listed[0]["encrypted_team_key"] == "owner-key-0"
    assert "encrypted_team_key" not in listed[-2]
    assert "encrypted_team_key" not in listed[-1]
    assert len(directus.reads) == 7  # One membership read, three Team and three wrapper batches.
    assert [collection for collection, _ in directus.reads] == [
        "team_memberships", "teams", "team_key_wrappers", "teams", "team_key_wrappers", "teams", "team_key_wrappers",
    ]
    for collection, params in directus.reads[1:]:
        assert len(params["filter[hashed_team_id][_in]"].split(",")) <= 64
        assert params["filter[status][_eq]"] == "active"
        if collection == "team_key_wrappers":
            assert params["filter[hashed_user_id][_eq]"] == owner_hash


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.lifecycle.encrypted-profiled
async def test_list_teams_deduplicates_membership_without_overriding_first_role() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    user_hash = hash_id("owner")
    first_hash = hash_id("first")
    second_hash = hash_id("second")
    directus.rows["team_memberships"] = [
        {"hashed_team_id": first_hash, "hashed_user_id": user_hash, "status": "active", "role": "viewer"},
        {"hashed_team_id": second_hash, "hashed_user_id": user_hash, "status": "active", "role": "admin"},
        {"hashed_team_id": first_hash, "hashed_user_id": user_hash, "status": "active", "role": "owner"},
    ]
    directus.rows["teams"] = [
        {"team_id": "first", "hashed_team_id": first_hash, "status": "active"},
        {"team_id": "second", "hashed_team_id": second_hash, "status": "active"},
    ]
    directus.rows["team_key_wrappers"] = [
        {"hashed_team_id": first_hash, "hashed_user_id": user_hash, "status": "active", "team_key_epoch": 1, "encrypted_team_key": "first-key"},
        {"hashed_team_id": second_hash, "hashed_user_id": user_hash, "status": "active", "team_key_epoch": 1, "encrypted_team_key": "second-key"},
    ]

    listed = await methods.list_teams("owner")

    assert [(team["team_id"], team["role"], team["encrypted_team_key"]) for team in listed] == [
        ("first", "viewer", "first-key"), ("second", "admin", "second-key"),
    ]
    assert [collection for collection, _ in directus.reads] == [
        "team_memberships", "teams", "team_key_wrappers",
    ]
    assert directus.reads[1][1]["filter[hashed_team_id][_in]"] == f"{first_hash},{second_hash}"


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated,teams.chat-billing.team-credit-boundary
async def test_create_team_creates_owner_membership_key_wrapper_and_zero_balance() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)

    created = await methods.create_team("alice", team_payload())

    assert created is not None
    assert directus.rows["teams"][0]["hashed_team_id"] == hash_id("team-1")
    assert directus.rows["teams"][0]["created_by_user_hash"] == hash_id("alice")
    assert directus.rows["team_memberships"][0] == {
        "id": "team_memberships-1",
        "hashed_team_id": hash_id("team-1"),
        "hashed_user_id": hash_id("alice"),
        "user_id": "alice",
        "encrypted_member_profile": None,
        "role": "owner",
        "status": "active",
        "invited_by_hash": None,
        "joined_at": 100,
        "removed_at": None,
        "created_at": 100,
        "updated_at": 100,
    }
    assert directus.rows["team_key_wrappers"][0]["team_key_epoch"] == 1
    assert directus.rows["team_key_wrappers"][0]["encrypted_team_key"] == "cipher-team-key-for-owner"
    assert directus.rows["team_credit_accounts"][0]["encrypted_balance"] == "cipher-zero-balance"
    assert all(admin_required is True for _collection, _record, admin_required in directus.created)


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.invites.fragment-key-web-flow,teams.membership.role-gated,teams.lifecycle.encrypted-profiled
async def test_invite_accept_creates_member_and_team_key_wrapper_epoch_one() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())

    invite = await methods.create_invite(
        "team-1",
        "alice",
        {"invite_id": "invite-1", "role": "viewer", "encrypted_recipient_hint": "cipher-bob", "created_at": 110},
    )
    request = await methods.accept_invite("invite-1", "bob", accepted_at=120)

    assert invite is not None
    assert request is not None
    assert request["status"] == "pending_access_approval"
    accepted = await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-bob", approved_at=130)
    assert accepted is not None
    bob_membership = [row for row in directus.rows["team_memberships"] if row["hashed_user_id"] == hash_id("bob")][0]
    assert bob_membership["role"] == "viewer"
    bob_wrapper = [row for row in directus.rows["team_key_wrappers"] if row["hashed_user_id"] == hash_id("bob")][0]
    assert bob_wrapper["team_key_epoch"] == 1
    assert bob_wrapper["encrypted_team_key"] == "cipher-team-key-for-bob"
    assert directus.rows["team_invites"][0]["status"] == "accepted"


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated
async def test_require_team_role_fails_closed_for_viewer_write_action() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-1", "role": "viewer", "created_at": 110})
    request = await methods.accept_invite("invite-1", "viewer", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-viewer", approved_at=130)

    with pytest.raises(TeamPermissionError):
        await methods.require_team_role("team-1", "viewer", {"owner", "admin", "member"})


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.lifecycle.encrypted-profiled
async def test_remove_member_revokes_membership_and_key_without_epoch_rotation(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-team-key-transaction")
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-1", "role": "member", "created_at": 110})
    request = await methods.accept_invite("invite-1", "bob", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-bob", approved_at=130)

    removed = await methods.remove_member("team-1", "alice", "bob", removed_at=130)

    assert removed is True
    bob_membership = [row for row in directus.rows["team_memberships"] if row["hashed_user_id"] == hash_id("bob")][0]
    assert bob_membership["status"] == "removed"
    assert [row for row in directus.rows["team_key_wrappers"] if row["hashed_user_id"] == hash_id("bob")] == []
    assert {row["team_key_epoch"] for row in directus.rows["team_key_wrappers"]} == {1}
    removal_updates = [collection for collection, _item_id, _patch, _admin in directus.updated[-2:]]
    assert removal_updates == ["team_memberships", "teams"]
    assert directus.rows["teams"][0]["rotation_pending"] is True


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.lifecycle.encrypted-profiled
async def test_remove_member_reports_failed_transaction(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-team-key-transaction")
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite(
        "team-1", "alice", {"invite_id": "invite-1", "role": "member", "created_at": 110}
    )
    request = await methods.accept_invite("invite-1", "bob", accepted_at=120)
    await methods.approve_access_request(
        "team-1", "alice", request["access_request_id"], "cipher-team-key-for-bob", approved_at=130
    )

    directus.removal_status = 500

    with pytest.raises(RuntimeError, match="member removal transaction failed"):
        await methods.remove_member("team-1", "alice", "bob", removed_at=140)

    bob_membership = next(
        row for row in directus.rows["team_memberships"] if row["hashed_user_id"] == hash_id("bob")
    )
    assert bob_membership["status"] == "active"


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.lifecycle.encrypted-profiled
async def test_deleted_team_rejects_existing_member_role_checks() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())

    assert await methods.delete_team("team-1", "alice", deleted_at=150) is True
    with pytest.raises(TeamPermissionError):
        await methods.require_team_role("team-1", "alice", {"owner"})


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated
async def test_member_joining_after_rotation_gets_wrapper_at_current_epoch() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    directus.rows["teams"][0]["team_key_epoch"] = 3
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-1", "role": "member", "created_at": 110})
    request = await methods.accept_invite("invite-1", "bob", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], "cipher-team-key-for-bob", approved_at=130)

    bob = [row for row in directus.rows["team_key_wrappers"] if row["hashed_user_id"] == hash_id("bob")]
    assert [row["team_key_epoch"] for row in bob] == [3]
