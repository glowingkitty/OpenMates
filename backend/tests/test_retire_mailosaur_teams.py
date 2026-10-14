"""Administrative tooling guards; no live Teams or accounts are modified."""

# contract-test-file: tooling
from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.scripts import retire_mailosaur_teams as retirement


class Fixtures:
    def __init__(self):
        self.team_id = "fixture-team"
        self.team_hash = retirement._hash_id(self.team_id)
        self.records = {
            "account_contact_emails": [],
            "users": [],
            "team_memberships": [],
            "teams": [
                {
                    "id": "team-row",
                    "team_id": self.team_id,
                    "hashed_team_id": self.team_hash,
                    "status": "active",
                }
            ],
            "billing_profiles": [],
        }
        self.add_user("owner", "owner@ae20drx9.mailosaur.net", "owner")
        self.add_user("member", "member@ae20drx9.mailosaur.net", "member")
        self.encryption = SimpleNamespace(
            initialize=AsyncMock(return_value=True),
            close=AsyncMock(),
            decrypt_account_contact_email=AsyncMock(
                side_effect=lambda value: value.removeprefix("encrypted:")
            ),
        )
        self.directus = SimpleNamespace(
            get_items=AsyncMock(side_effect=self.read), close=AsyncMock()
        )
        self.cache = SimpleNamespace(close=AsyncMock())

    def add_user(self, user_id, email, role):
        from backend.scripts.delete_user_account import hash_email_sha256

        digest = hash_email_sha256(email)
        self.records["users"].append(
            {"id": user_id, "hashed_email": digest, "status": "active"}
        )
        self.records["account_contact_emails"].append(
            {
                "id": "contact-" + user_id,
                "user_id": user_id,
                "hashed_email": digest,
                "encrypted_email_address": "encrypted:" + email,
                "purpose": "account_lifecycle",
                "verified_at": "2026-10-01T00:00:00Z",
            }
        )
        self.records["team_memberships"].append(
            {
                "id": "membership-" + user_id,
                "hashed_team_id": self.team_hash,
                "hashed_user_id": retirement._hash_id(user_id),
                "role": role,
                "status": "active",
            }
        )

    async def read(self, collection, *, params, **_kwargs):
        rows = self.records.get(collection, [])
        filters = params.get("filter", {})

        def matches(row):
            for key, rule in filters.items():
                if "_eq" in rule and row.get(key) != rule["_eq"]:
                    return False
                if "_in" in rule and row.get(key) not in rule["_in"]:
                    return False
                if "_nnull" in rule and row.get(key) is None:
                    return False
            return True

        return [copy.deepcopy(row) for row in rows if matches(row)]


def test_discovery_only_targets_verified_owned_active_teams():
    fixture = Fixtures()
    tombstone_id = "already-deleted-team"
    tombstone_hash = retirement._hash_id(tombstone_id)
    fixture.records["teams"].append(
        {
            "id": "deleted-row",
            "team_id": tombstone_id,
            "hashed_team_id": tombstone_hash,
            "status": "deleted",
        }
    )
    fixture.records["team_memberships"].append(
        {
            "id": "old-owner-membership",
            "hashed_user_id": retirement._hash_id("owner"),
            "hashed_team_id": tombstone_hash,
            "role": "owner",
            "status": "active",
        }
    )
    candidates, counts = asyncio.run(
        retirement.prepare_teams(fixture.directus, fixture.encryption)
    )
    assert len(candidates) == 1
    assert candidates[0]["blocker"] is None
    assert candidates[0]["active_members"] == 2
    assert counts == {"candidate_accounts": 2, "deleted_team_tombstones": 1}


@pytest.mark.parametrize(
    "defect",
    [
        "external_member",
        "missing_contact",
        "unconfirmed",
        "wrong_purpose",
        "owner_missing",
        "paid_subscription",
    ],
)
def test_fresh_unsafe_identity_membership_or_billing_blocks_deletion(defect):
    fixture = Fixtures()
    candidates, _ = asyncio.run(
        retirement.prepare_teams(fixture.directus, fixture.encryption)
    )
    if defect == "external_member":
        fixture.add_user("outside", "person@example.org", "member")
    elif defect == "missing_contact":
        fixture.records["account_contact_emails"].pop()
    elif defect == "unconfirmed":
        fixture.records["account_contact_emails"][-1]["verified_at"] = None
    elif defect == "wrong_purpose":
        fixture.records["account_contact_emails"][-1]["purpose"] = "optional_contact"
    elif defect == "owner_missing":
        fixture.records["team_memberships"][0]["role"] = "admin"
    elif defect == "paid_subscription":
        fixture.records["billing_profiles"].append(
            {
                "id": "billing",
                "owner_kind": "team",
                "owner_hash": fixture.team_hash,
                "monthly_subscription_id": "sandbox-subscription",
                "monthly_subscription_status": "active",
            }
        )
    lifecycle = AsyncMock()
    with pytest.raises(RuntimeError, match="unsafe"):
        asyncio.run(
            retirement.retire_team(
                fixture.directus,
                fixture.cache,
                fixture.encryption,
                candidates[0],
                lifecycle,
            )
        )
    lifecycle.assert_not_awaited()
    assert fixture.records["teams"][0]["status"] == "active"


@pytest.mark.parametrize("defect", ["contact_hash", "user_hash", "team_hash"])
def test_identity_hash_mismatch_never_enters_normal_lifecycle(defect):
    fixture = Fixtures()
    candidate = {"team": {"hashed_team_id": fixture.team_hash}}
    if defect == "contact_hash":
        fixture.records["account_contact_emails"][0]["hashed_email"] = "changed"
    elif defect == "user_hash":
        fixture.records["users"][0]["hashed_email"] = "changed"
    else:
        fixture.records["teams"][0]["team_id"] = "changed-team"
    lifecycle = AsyncMock()
    with pytest.raises(RuntimeError, match="identity|hash"):
        asyncio.run(
            retirement.retire_team(
                fixture.directus,
                fixture.cache,
                fixture.encryption,
                candidate,
                lifecycle,
            )
        )
    lifecycle.assert_not_awaited()


def test_deleted_team_replay_and_failed_lifecycle_are_not_success():
    fixture = Fixtures()
    candidate = {"team": {"hashed_team_id": fixture.team_hash}}
    fixture.records["teams"][0]["status"] = "deleted"
    lifecycle = AsyncMock()
    assert not asyncio.run(
        retirement.retire_team(
            fixture.directus, fixture.cache, fixture.encryption, candidate, lifecycle
        )
    )
    lifecycle.assert_not_awaited()
    fixture.records["teams"][0]["status"] = "active"
    with pytest.raises(RuntimeError, match="persist"):
        asyncio.run(
            retirement.retire_team(
                fixture.directus,
                fixture.cache,
                fixture.encryption,
                candidate,
                lifecycle,
            )
        )


def test_normal_lifecycle_keeps_billing_remote_project_and_owner_deletion_order(
    monkeypatch,
):
    from backend.core.api.app.routes import teams

    events = []

    async def billing(*_args, **_kwargs):
        events.append("billing")

    async def remote(**_kwargs):
        events.append("remote_access")

    async def projects(*_args, **_kwargs):
        events.append("project_sources")

    async def delete(*_args, **_kwargs):
        events.append("team_delete")
        return True

    directus = SimpleNamespace(
        team=SimpleNamespace(
            require_team_role=AsyncMock(), delete_team=AsyncMock(side_effect=delete)
        ),
        project=SimpleNamespace(
            mark_team_sources_offline=AsyncMock(side_effect=projects)
        ),
    )
    monkeypatch.setattr(teams, "_stop_team_recurring_billing", billing)
    monkeypatch.setattr(
        teams,
        "ProjectRemoteAccessService",
        Mock(return_value=SimpleNamespace(revoke_team=remote)),
    )
    asyncio.run(
        retirement.normal_team_deletion(
            directus, object(), object(), team_id="team", owner_user_id="owner"
        )
    )
    directus.team.require_team_role.assert_awaited_once_with("team", "owner", {"owner"})
    assert events == ["billing", "remote_access", "project_sources", "team_delete"]


def test_default_dry_run_reports_only_counters_and_never_calls_lifecycle(
    monkeypatch, tmp_path
):
    fixture = Fixtures()
    from backend.scripts import delete_user_account

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("CMS_URL", "http://cms:8055")
    monkeypatch.delenv("OPENMATES_CI_ISOLATED", raising=False)
    monkeypatch.setattr(
        delete_user_account,
        "initialize_services",
        AsyncMock(return_value=(fixture.cache, fixture.encryption, fixture.directus)),
    )
    lifecycle = AsyncMock()
    monkeypatch.setattr(retirement, "retire_team", lifecycle)
    receipt = asyncio.run(
        retirement.run(SimpleNamespace(apply=False, receipt=tmp_path / "receipt.json"))
    )
    assert (
        receipt["dry_run"]
        and receipt["active_teams"] == 1
        and receipt["deleted_teams"] == 0
    )
    assert receipt["blocked_teams"] == 0
    lifecycle.assert_not_awaited()
    text = (tmp_path / "receipt.json").read_text()
    assert "@" not in text and "owner" not in text and "member@" not in text


def test_apply_refuses_all_changes_when_initial_dry_run_contains_any_outside_member(
    monkeypatch, tmp_path
):
    fixture = Fixtures()
    fixture.add_user("outside", "person@example.org", "member")
    from backend.scripts import delete_user_account

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("CMS_URL", "http://cms:8055")
    monkeypatch.delenv("OPENMATES_CI_ISOLATED", raising=False)
    monkeypatch.setattr(
        delete_user_account,
        "initialize_services",
        AsyncMock(return_value=(fixture.cache, fixture.encryption, fixture.directus)),
    )
    lifecycle = AsyncMock()
    monkeypatch.setattr(retirement, "retire_team", lifecycle)
    with pytest.raises(RuntimeError, match="blockers"):
        asyncio.run(
            retirement.run(
                SimpleNamespace(apply=True, receipt=tmp_path / "receipt.json")
            )
        )
    lifecycle.assert_not_awaited()
