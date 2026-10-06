"""Route-level tests for Teams V1 API behavior.

The Teams router supports both session and API-key authenticated clients. These
tests use dependency overrides so they verify route contracts, response shapes,
and permission-error mapping without a live Directus or auth stack.
"""

import base64
from itertools import count
import sys
import types
from types import SimpleNamespace

import pytest


if "redis" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedisClient:
        pass

    redis_asyncio_module.Redis = FakeRedisClient
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

if "slowapi" not in sys.modules:
    slowapi_module = types.ModuleType("slowapi")
    slowapi_util_module = types.ModuleType("slowapi.util")

    class FakeLimiter:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def limit(self, *_args, **_kwargs):
            def decorator(route_handler):
                return route_handler

            return decorator

    slowapi_module.Limiter = FakeLimiter
    slowapi_util_module.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi_module
    sys.modules["slowapi.util"] = slowapi_util_module

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.models.user import User
from backend.core.api.app.routes import teams
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.storage_usage_metering import StorageUsageIncompleteError, StorageUsageQuote


_TEST_CLIENT_COUNTER = count(1)


async def _fake_encrypt(plaintext: str, _key_id: str):
    return f"cipher:{plaintext}", _key_id


async def _fake_team_billing_key():
    return "vault-team-billing"


async def _fake_decrypt(ciphertext: str, _key_id: str):
    return ciphertext.removeprefix("cipher:")


async def _fake_decrypt_email(_ciphertext: str, _email_key: str):
    return "alice@example.com"


def client_ciphertext(label: bytes = b"ciphertext-ok") -> str:
    return base64.b64encode(b"OM" + bytes.fromhex("1a5b3b7c") + (b"0" * 12) + label + (b"t" * 16)).decode("ascii")


def invite_kdf_context(invite_id: str = "invite-1") -> dict:
    return {"v": 1, "kdf": "HKDF-SHA256", "cipher": "AES-256-GCM", "team_id": "team-1", "invite_id": invite_id, "origin": "https://app.example.com"}


class FakeTeamService:
    def __init__(self) -> None:
        self.created_payload = None
        self.updated_payload = None
        self.events: list[str] = []

    async def get_membership(self, team_id: str, user_id: str):
        assert team_id == "team-1"
        return {"id": f"membership-{user_id}", "role": "admin"} if user_id == "bob" else {"id": "membership-alice", "role": "owner"}

    async def list_teams(self, user_id: str):
        assert user_id == "alice"
        return [{"team_id": "team-1", "encrypted_name": "cipher-name", "role": "owner"}]

    async def create_team(self, user_id: str, payload: dict):
        assert user_id == "alice"
        self.created_payload = payload
        return {"team_id": payload["team_id"], "encrypted_name": payload["encrypted_name"], "role": "owner"}

    async def get_team(self, team_id: str, user_id: str):
        assert user_id == "alice"
        if team_id != "team-1":
            return None
        return {"team_id": team_id, "encrypted_name": "cipher-name", "role": "owner"}

    async def list_members(self, team_id: str, user_id: str):
        assert team_id == "team-1"
        assert user_id == "alice"
        return [{"user_id": "alice", "hashed_user_id": "hash-alice", "encrypted_member_profile": client_ciphertext(b"profile"), "role": "owner", "status": "active", "joined_at": 100}]

    async def update_own_member_profile(self, team_id: str, user_id: str, encrypted_member_profile: str):
        assert team_id == "team-1" and user_id == "alice"
        return {"user_id": user_id, "encrypted_member_profile": encrypted_member_profile}

    async def update_team(self, team_id: str, user_id: str, patch: dict):
        assert team_id == "team-1"
        assert user_id == "alice"
        self.updated_payload = patch
        return {"team_id": team_id, **patch}

    async def delete_team(self, team_id: str, user_id: str):
        assert team_id == "team-1"
        assert user_id == "alice"
        self.events.append("delete_team")
        return True

    async def create_invite(self, team_id: str, user_id: str, payload: dict):
        assert team_id == "team-1"
        assert user_id == "alice"
        return {"invite_id": payload["invite_id"], "role": payload["role"]}

    async def get_invite_join_context(self, invite_id: str):
        return {"invite_id": invite_id, "hashed_team_id": "hash-team", "expires_at": None}

    async def get_security_policy_by_hash(self, team_hash: str):
        assert team_hash == "hash-team"
        return {"restrict_email_domains": False, "allowed_email_domains": [], "require_invite_link_approval": True, "require_strong_auth": False}

    async def accept_invite(self, invite_id: str, user_id: str, accepted_at=None, **_kwargs):
        assert invite_id == "invite-1"
        assert user_id == "alice"
        return {"access_request_id": "access-1", "status": "pending_access_approval", "role": "member", "requested_at": accepted_at}

    async def approve_access_request(self, team_id: str, actor_user_id: str, access_request_id: str, encrypted_team_key: str, approved_at=None):
        assert team_id == "team-1"
        assert actor_user_id == "alice"
        assert access_request_id == "access-1"
        assert encrypted_team_key == client_ciphertext(b"team-key")
        return {"hashed_team_id": "hash-team", "role": "member", "approved_at": approved_at}

    async def remove_member(self, team_id: str, user_id: str, member_user_id: str, removed_at=None):
        assert team_id == "team-1"
        assert user_id == "alice"
        assert member_user_id == "bob"
        assert removed_at == 200
        self.events.append("remove_member")
        return True

    async def prepare_member_removal(self, team_id: str, user_id: str, member_user_id: str):
        assert team_id == "team-1"
        assert user_id == "alice"
        assert member_user_id == "bob"
        return {"role": "member"}

    async def deactivate_member(self, membership: dict, *, removed_at: int):
        assert membership == {"role": "member"}
        assert removed_at == 200
        self.events.append("deactivate_member")

    async def revoke_member_key_wrappers(
        self, team_id: str, member_user_id: str, *, revoked_at: int
    ):
        assert team_id == "team-1"
        assert member_user_id == "bob"
        assert revoked_at == 200
        self.events.append("revoke_member_wrappers")

    async def set_member_role(self, team_id: str, user_id: str, member_user_id: str, role: str, updated_at=None):
        assert team_id == "team-1"
        assert user_id == "alice"
        assert member_user_id == "bob"
        return {"hashed_user_id": "hash-bob", "role": role, "updated_at": updated_at}

    async def require_team_role(self, team_id: str, actor_user_id: str, roles: set[str]):
        assert team_id == "team-1"
        assert actor_user_id == "alice"
        assert "owner" in roles
        return {"role": "owner"}


class DenyingTeamService(FakeTeamService):
    async def update_team(self, team_id: str, user_id: str, patch: dict):
        raise TeamPermissionError("viewer cannot update team")


class RoleTeamService(FakeTeamService):
    def __init__(self, role: str, allowed_team_ids: set[str] | None = None) -> None:
        super().__init__()
        self.role = role
        self.allowed_team_ids = allowed_team_ids or {"team-1"}

    async def require_team_role(self, team_id: str, actor_user_id: str, roles: set[str]):
        assert actor_user_id == "alice"
        if team_id not in self.allowed_team_ids or self.role not in roles:
            raise TeamPermissionError("Team permission denied")
        return {"role": self.role}


class FakeTeamBillingService:
    async def get_billing_summary(self, team_id: str, actor_user_id: str):
        assert team_id == "team-1"
        assert actor_user_id == "alice"
        return {"balance_credits": 100, "encrypted_balance": "cipher-balance-100"}

    async def charge_team_credits(self, **kwargs):
        assert kwargs["team_id"] == "team-1"
        assert kwargs["actor_user_id"] == "alice"
        return {"account": {"balance_credits": 140}, "usage_event": {"credit_amount": 10}}

    async def list_usage(self, team_id: str, actor_user_id: str, member_user_id: str | None = None):
        assert team_id == "team-1"
        assert actor_user_id == "alice"
        assert member_user_id == "bob"
        return [{"event_id": "usage-1", "credit_amount": 10}]


class FakePaymentService:
    is_bank_transfer_available = True

    def __init__(self):
        self.card_customer_ids = []

    async def create_order(self, **kwargs):
        self.card_customer_ids.append(kwargs.get("customer_id"))
        return {"id": f"pi_team_{len(self.card_customer_ids)}", "client_secret": "team-secret", "customer_id": "cus_team"}

    def get_bank_transfer_details(self):
        return {
            "iban": "DE02100100109307118603",
            "bic": "PBNKDEFF",
            "bank_name": "OpenMates Bank",
            "account_holder_name": "OpenMates",
        }


class FakeCacheService:
    def __init__(self) -> None:
        self.cached_orders = []
        self.values = {}

    async def set_bank_transfer_order(self, **kwargs):
        self.cached_orders.append(kwargs)
        return True

    async def set_order(self, **kwargs):
        self.cached_orders.append(kwargs)
        return True

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value, ttl=None):
        del ttl
        self.values[key] = value
        return True

    async def delete(self, key: str):
        self.values.pop(key, None)
        return True

    async def publish_event(self, channel: str, event: dict):
        del channel, event
        return True


class FailingRevocationCacheService(FakeCacheService):
    async def get(self, key: str):
        del key
        raise RuntimeError("cache unavailable")


class FakeDirectusService(SimpleNamespace):
    def __init__(self, team_service) -> None:
        super().__init__(team=team_service)
        self.project = self
        self.offlined_source_members = []
        self.bank_transfer_rows = []
        self.billing_profiles = []
        self.billing_order_contexts = []
        self.signup_completed = True

    async def mark_team_member_sources_offline(self, team_id: str, member_user_id: str, *, updated_at: int):
        self.team.events.append("offline_member_sources")
        self.offlined_source_members.append((team_id, member_user_id, updated_at))
        return 1

    async def get_user_fields_direct(self, user_id: str, fields: list[str], *, no_cache: bool = False):
        del user_id, fields, no_cache
        from backend.core.api.app.services.team_invite_email_service import hash_invite_email
        return {"hashed_email": hash_invite_email("alice@example.com"), "signup_completed": self.signup_completed, "encrypted_tfa_secret": None}

    async def mark_team_sources_offline(self, team_id: str, *, updated_at: int):
        del team_id, updated_at
        self.team.events.append("offline_team_sources")
        return 1

    async def get_items(self, collection: str, params: dict, **_kwargs):
        assert collection in {"pending_bank_transfers", "billing_profiles", "billing_order_contexts"}
        rows = list({
            "pending_bank_transfers": self.bank_transfer_rows,
            "billing_profiles": self.billing_profiles,
            "billing_order_contexts": self.billing_order_contexts,
        }[collection])
        if "filter" in params:
            for field, condition in params["filter"].items():
                if isinstance(condition, dict) and "_eq" in condition:
                    rows = [row for row in rows if row.get(field) == condition["_eq"]]
        for key, expected in params.items():
            if key.startswith("filter[") and "][_eq]" in key:
                field = key.removeprefix("filter[").split("]", 1)[0]
                rows = [row for row in rows if row.get(field) == expected]
        limit = params.get("limit", len(rows))
        return rows if limit == -1 else rows[:limit]

    async def create_item(self, collection: str, record: dict, admin_required: bool = False):
        assert collection in {"pending_bank_transfers", "billing_profiles", "billing_order_contexts"}
        assert admin_required is True
        rows = {
            "pending_bank_transfers": self.bank_transfer_rows,
            "billing_profiles": self.billing_profiles,
            "billing_order_contexts": self.billing_order_contexts,
        }[collection]
        row = {"id": f"{collection}-{len(rows) + 1}", **record}
        rows.append(row)
        return True, row

    async def update_item(self, collection: str, item_id: str, record: dict, admin_required: bool = False):
        assert collection == "billing_profiles" and admin_required
        row = next(row for row in self.billing_profiles if row["id"] == item_id)
        row.update(record)
        return row


class FakeConfigManager:
    def __init__(self, config: dict | None = None) -> None:
        self.config = config if config is not None else {"feature_overrides": {"enabled": ["platform:teams"], "disabled": []}}

    def get_backend_config(self) -> dict:
        return self.config


def build_client(
    team_service,
    team_billing_service=None,
    config: dict | None = None,
    *,
    override_payment_service: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(teams.router)
    app.state.directus_service = FakeDirectusService(team_service)
    app.state.config_manager = FakeConfigManager(config)
    if team_billing_service:
        app.state.team_billing_service = team_billing_service
    app.state.cache_service = FakeCacheService()
    app.state.domain_security_service = SimpleNamespace(config_loaded=True, is_domain_restricted=lambda value: (value == "blocked.example", None))
    app.state.payment_service = FakePaymentService()
    app.state.encryption_service = SimpleNamespace(
        create_user_key=lambda: _fake_team_billing_key(),
        encrypt_with_user_key=lambda plaintext, key_id: _fake_encrypt(plaintext, key_id),
        decrypt_with_user_key=lambda ciphertext, key_id: _fake_decrypt(ciphertext, key_id),
        decrypt_with_email_key=lambda ciphertext, email_key: _fake_decrypt_email(ciphertext, email_key),
    )

    async def fake_current_user(_request=None, _response=None):
        return User(id="alice", username="alice", vault_key_id="vault-alice", encrypted_email_address="cipher-email", stripe_customer_id="cus_personal")

    app.dependency_overrides[teams._current_user] = fake_current_user
    if override_payment_service:
        app.dependency_overrides[teams.get_payment_service] = lambda: app.state.payment_service
    client_index = next(_TEST_CLIENT_COUNTER)
    return TestClient(app, client=(f"teams-test-{client_index}", 50000 + client_index))


def name_approval_token(client: TestClient, name: str = "Acme") -> str:
    response = client.post("/v1/teams/name-approval", json={"name": name})
    assert response.status_code == 200
    return response.json()["approval_token"]


# contract-test: supporting surface=rest_api assertions=teams.workspace.surface-parity
def test_teams_routes_block_when_feature_disabled() -> None:
    client = build_client(FakeTeamService(), config={})

    response = client.get("/v1/teams")

    assert response.status_code == 404
    assert response.json()["detail"] == "FEATURE_DISABLED"


# contract-test: supporting surface=rest_api assertions=teams.workspace.surface-parity
def test_teams_routes_expose_lifecycle_contract() -> None:
    service = FakeTeamService()
    client = build_client(service)

    assert client.get("/v1/teams").json()["teams"][0]["team_id"] == "team-1"
    create_response = client.post(
        "/v1/teams",
        json={
            "team_id": "team-1",
            "encrypted_name": client_ciphertext(b"name"),
            "name_approval_token": name_approval_token(client),
            "encrypted_profile_image_metadata": client_ciphertext(b"profile-image"),
            "encrypted_team_key": client_ciphertext(b"team-key-owner"),
            "encrypted_zero_balance": client_ciphertext(b"zero"),
            "created_at": 100,
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["team"]["role"] == "owner"
    assert service.created_payload["encrypted_team_key"] == client_ciphertext(b"team-key-owner")

    assert client.get("/v1/teams/team-1").json()["team"]["role"] == "owner"
    updated_name = client_ciphertext(b"updated-name")
    assert client.patch("/v1/teams/team-1", json={"encrypted_name": updated_name, "name_approval_token": name_approval_token(client, "Renamed Acme"), "updated_at": 110}).json()["team"]["encrypted_name"] == updated_name
    assert client.delete("/v1/teams/team-1").json() == {"success": True}


# contract-test: supporting surface=rest_api assertions=teams.invites.fragment-key-web-flow,teams.membership.role-gated,teams.workspace.surface-parity
def test_teams_routes_expose_invite_and_member_contract(monkeypatch) -> None:
    service = FakeTeamService()
    client = build_client(service)
    # CLI signup verifies email before account creation, while the separate
    # signup-completion flag can lag after accepting the signup gift.
    client.app.state.directus_service.signup_completed = False
    notifications = []
    monkeypatch.setattr(teams, "_queue_team_membership_email", lambda user_id, team_id, change: notifications.append((user_id, team_id, change)))

    invite_response = client.post("/v1/teams/team-1/invites", json={"invite_id": "invite-1", "role": "viewer", "encrypted_invite_team_key": client_ciphertext(b"invite"), "invite_key_kdf_context": invite_kdf_context(), "created_at": 100})
    assert invite_response.status_code == 200
    assert invite_response.json()["invite"] == {"invite_id": "invite-1", "role": "viewer"}

    mismatched_accept = client.post("/v1/teams/invites/invite-1/accept", json={"accepted_at": 119, "verified_email": "other@example.com", "encrypted_team_key": client_ciphertext(b"invite-key")})
    assert mismatched_accept.status_code == 403
    assert mismatched_accept.json()["detail"] == "TEAM_VERIFIED_EMAIL_REQUIRED"
    accept_response = client.post("/v1/teams/invites/invite-1/accept", json={"accepted_at": 120, "verified_email": "alice@example.com", "encrypted_team_key": client_ciphertext(b"invite-key")})
    assert accept_response.status_code == 200
    assert accept_response.json()["access_request"]["status"] == "pending_access_approval"

    approve_response = client.post("/v1/teams/team-1/access-requests/access-1/approve", json={"encrypted_team_key": client_ciphertext(b"team-key"), "approved_at": 130})
    assert approve_response.status_code == 200
    assert approve_response.json()["membership"]["role"] == "member"

    remove_response = client.post("/v1/teams/team-1/members/bob/remove", json={"removed_at": 200})
    assert remove_response.status_code == 200
    offlined = client.app.state.directus_service.offlined_source_members
    assert offlined and offlined[0][:2] == ("team-1", "bob")
    assert service.events == [
        "deactivate_member",
        "offline_member_sources",
        "revoke_member_wrappers",
    ]
    assert remove_response.json() == {"success": True}

    role_response = client.patch("/v1/teams/team-1/members/bob", json={"role": "viewer", "updated_at": 210})
    assert role_response.status_code == 200
    assert role_response.json()["membership"]["role"] == "viewer"
    assert notifications == [("bob", "team-1", "removed"), ("bob", "team-1", "role_changed")]


# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated
def test_team_delete_offlines_sources_before_durable_team_deletion() -> None:
    service = FakeTeamService()
    client = build_client(service)

    response = client.delete("/v1/teams/team-1")

    assert response.status_code == 200
    assert service.events == ["offline_team_sources", "delete_team"]


# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated
@pytest.mark.parametrize("action", ["delete", "remove", "demote"])
def test_team_lifecycle_works_without_cloud_payment_service(monkeypatch, action: str) -> None:
    from backend.core.api.app.utils import server_mode

    monkeypatch.setattr(server_mode, "is_cloud_billing_enabled", lambda: False)
    service = FakeTeamService()
    client = build_client(service, override_payment_service=False)
    del client.app.state.payment_service
    if action == "delete":
        response = client.delete("/v1/teams/team-1")
        assert "delete_team" in service.events
    elif action == "remove":
        response = client.post("/v1/teams/team-1/members/bob/remove", json={"removed_at": 200})
        assert "deactivate_member" in service.events
    else:
        response = client.patch("/v1/teams/team-1/members/bob", json={"role": "viewer"})
        assert response.json()["membership"]["role"] == "viewer"
    assert response.status_code == 200


# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled
def test_team_delete_requires_provider_when_subscription_is_active(monkeypatch) -> None:
    from backend.core.api.app.services.directus.team_methods import hash_id
    from backend.core.api.app.utils import server_mode

    monkeypatch.setattr(server_mode, "is_cloud_billing_enabled", lambda: False)
    service = FakeTeamService()
    client = build_client(service, override_payment_service=False)
    del client.app.state.payment_service
    client.app.state.directus_service.billing_profiles.append({
        "id": "billing-1", "owner_kind": "team", "owner_hash": hash_id("team-1"),
        "owner_id": "team-1", "monthly_subscription_id": "sub_team",
        "monthly_subscription_status": "active",
    })
    response = client.delete("/v1/teams/team-1")
    assert response.status_code == 503
    assert response.json()["detail"] == "Team subscription cancellation unavailable"
    assert "delete_team" not in service.events


# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.lifecycle.encrypted-profiled
def test_member_removal_stays_fail_closed_if_cache_revocation_fails() -> None:
    service = FakeTeamService()
    client = build_client(service)
    client.app.state.cache_service = FailingRevocationCacheService()

    with pytest.raises(RuntimeError, match="cache unavailable"):
        client.post("/v1/teams/team-1/members/bob/remove", json={"removed_at": 200})

    assert service.events == ["deactivate_member"]


# contract-test: direct surface=rest_api assertions=teams.membership.role-gated
def test_team_permission_error_maps_to_403() -> None:
    client = build_client(DenyingTeamService())

    response = client.patch("/v1/teams/team-1", json={"encrypted_name": client_ciphertext(b"updated-name"), "name_approval_token": name_approval_token(client), "updated_at": 110})

    assert response.status_code == 403
    assert response.json()["detail"] == "TEAM_PERMISSION_DENIED"


# contract-test: direct surface=rest_api assertions=teams.chat-billing.team-credit-boundary,teams.workspace.surface-parity
def test_teams_routes_expose_billing_contract(monkeypatch) -> None:
    monkeypatch.setattr(teams, "get_price_for_credits", lambda _credits, _currency: 500)
    client = build_client(FakeTeamService(), FakeTeamBillingService())

    assert client.get("/v1/teams/team-1/billing").json()["billing"]["balance_credits"] == 100
    order_response = client.post(
        "/v1/teams/team-1/billing/bank-transfer-orders",
        json={"credits_amount": 50, "currency": "eur", "email_encryption_key": "email-key"},
    )
    assert order_response.status_code == 200
    assert order_response.json()["reference"].startswith("OMT-")
    cached_order = client.app.state.cache_service.cached_orders[0]
    assert cached_order["team_id"] == "team-1"
    assert cached_order["hashed_team_id"] == client.app.state.directus_service.bank_transfer_rows[0]["hashed_team_id"]
    assert cached_order["order_type"] == "team_credit_purchase"
    bank_context = client.app.state.directus_service.billing_order_contexts[0]
    assert bank_context["payer_email_vault_key_id"] == "vault-team-billing"
    assert bank_context["encrypted_payer_email"] == "cipher:alice@example.com"
    assert client.get("/v1/teams/team-1/billing/bank-transfer-orders").json()["orders"][0]["credits_amount"] == 50
    assert client.get(f"/v1/teams/team-1/billing/bank-transfer-orders/{order_response.json()['order_id']}").json()["status"] == "pending"

    charge_response = client.post(
        "/v1/teams/team-1/billing/charge",
        json={"event_id": "usage-1", "credits": 10, "encrypted_balance": client_ciphertext(b"balance-140"), "workspace_type": "chat"},
    )
    assert charge_response.status_code == 200
    assert charge_response.json()["charge"]["usage_event"]["credit_amount"] == 10

    usage_response = client.get("/v1/teams/team-1/billing/usage?member_user_id=bob")
    assert usage_response.status_code == 200
    assert usage_response.json()["usage"] == [{"event_id": "usage-1", "credit_amount": 10}]


# contract-test: direct surface=rest_api assertions=billing.storage.team-policy-gate,teams.membership.role-gated
def test_team_storage_quote_is_role_gated_with_team_policy(monkeypatch) -> None:
    monkeypatch.delenv("TEAM_STORAGE_BILLING_ENABLED", raising=False)
    seen: list[list[str]] = []

    class Metering:
        def __init__(self, _directus) -> None:
            pass

        async def quote_team(self, hashes: list[str]):
            seen.append(hashes)
            return {hashes[0]: StorageUsageQuote(
                owner_kind="team", owner_id=hashes[0], policy_version="team-storage-1gb-3credits-week-v1",
                source_version="logical-s3-v1", complete=True, categories={"chat_pages": 40},
                legacy_upload_bytes=0, logical_s3_bytes=40, total_bytes=40,
                measurement_at=1791082800,
            )}

    monkeypatch.setattr(teams, "StorageUsageMeteringService", Metering)
    owner = build_client(RoleTeamService("owner"))
    response = owner.get("/v1/teams/team-1/storage")
    assert response.status_code == 200
    assert response.json() == {"storage": {
        "total_bytes": 40, "legacy_upload_bytes": 0, "logical_s3_bytes": 40,
        "categories": {"chat_pages": 40}, "measurement_at": 1791082800,
        "metering_source_version": "logical-s3-v1", "metering_policy_version": "team-storage-1gb-3credits-week-v1",
        "free_bytes": 1_073_741_824, "credits_per_started_excess_gib_per_week": 3,
        "billable_gib": 0, "weekly_cost_credits": 0,
        "billing_status": "disabled_pending_validation",
        "billing": {"status": "disabled_pending_validation", "invoices": [],
                    "outstanding_credits": 0, "warning_count": 0,
                    "expiry_due": False, "affected_units": []},
    }}
    assert seen == [[teams.hash_id("team-1")]]
    viewer = build_client(RoleTeamService("viewer"))
    assert viewer.get("/v1/teams/team-1/storage").status_code == 403
    assert len(seen) == 1


# contract-test: direct surface=rest_api assertions=billing.storage.team-policy-gate
def test_team_storage_quote_fails_closed_when_metering_incomplete(monkeypatch) -> None:
    class Metering:
        def __init__(self, _directus) -> None:
            pass

        async def quote_team(self, _hashes: list[str]):
            raise StorageUsageIncompleteError("storage_usage_incomplete")

    monkeypatch.setattr(teams, "StorageUsageMeteringService", Metering)
    response = build_client(RoleTeamService("admin")).get("/v1/teams/team-1/storage")
    assert response.status_code == 503
    assert response.json()["detail"] == "TEAM_STORAGE_USAGE_UNAVAILABLE"


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,teams.membership.role-gated
def test_team_import_returns_explicit_restore_error_before_persistence(monkeypatch) -> None:
    from backend.core.api.app.services.team_data_portability_service import TeamDataPortabilityError

    class Portability:
        def __init__(self, _directus) -> None:
            pass

        async def import_team_data(self, *_args, **_kwargs):
            raise TeamDataPortabilityError("Team content restore is unsupported for chats; no rows were imported")

    monkeypatch.setattr(teams, "TeamDataPortabilityService", Portability)
    response = build_client(RoleTeamService("owner")).post("/v1/teams/import", json={
        "destination_team_id": "team-1", "artifact": {"schema": "openmates.team_export.v1"},
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "Team content restore is unsupported for chats; no rows were imported"


# contract-test: supporting surface=rest_api assertions=teams.chat-billing.team-credit-boundary
def test_team_bank_transfer_routes_fail_closed_without_cloud_billing(monkeypatch) -> None:
    from backend.core.api.app.utils import server_mode

    monkeypatch.setattr(server_mode, "is_cloud_billing_enabled", lambda: False)
    client = build_client(
        FakeTeamService(),
        FakeTeamBillingService(),
        override_payment_service=False,
    )

    response = client.post(
        "/v1/teams/team-1/billing/bank-transfer-orders",
        json={"credits_amount": 50, "currency": "eur", "email_encryption_key": "email-key"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Feature not available on this server edition"


# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.chat-billing.team-credit-boundary
def test_team_bank_transfer_create_requires_owner_or_admin(monkeypatch) -> None:
    monkeypatch.setattr(teams, "get_price_for_credits", lambda _credits, _currency: 500)

    for role in ("owner", "admin"):
        client = build_client(RoleTeamService(role), FakeTeamBillingService())
        response = client.post(
            "/v1/teams/team-1/billing/bank-transfer-orders",
            json={"credits_amount": 50, "currency": "eur", "email_encryption_key": "email-key"},
        )
        assert response.status_code == 200

    for role in ("member", "viewer"):
        client = build_client(RoleTeamService(role), FakeTeamBillingService())
        response = client.post(
            "/v1/teams/team-1/billing/bank-transfer-orders",
            json={"credits_amount": 50, "currency": "eur", "email_encryption_key": "email-key"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "TEAM_PERMISSION_DENIED"


# contract-test: direct surface=rest_api assertions=teams.chat-billing.team-credit-boundary
def test_team_bank_transfer_status_is_scoped_to_team_id(monkeypatch) -> None:
    monkeypatch.setattr(teams, "get_price_for_credits", lambda _credits, _currency: 500)
    client = build_client(RoleTeamService("owner", {"team-1", "team-2"}), FakeTeamBillingService())
    order_response = client.post(
        "/v1/teams/team-1/billing/bank-transfer-orders",
        json={"credits_amount": 50, "currency": "eur", "email_encryption_key": "email-key"},
    )
    assert order_response.status_code == 200

    cross_team_status = client.get(f"/v1/teams/team-2/billing/bank-transfer-orders/{order_response.json()['order_id']}")
    cross_team_list = client.get("/v1/teams/team-2/billing/bank-transfer-orders")

    assert cross_team_status.status_code == 404
    assert cross_team_status.json()["detail"] == "Team bank transfer order not found."
    assert cross_team_list.status_code == 200
    assert cross_team_list.json()["orders"] == []


# contract-test: direct surface=rest_api assertions=teams.chat-billing.team-credit-boundary,teams.membership.role-gated
def test_team_card_order_uses_separate_customer_and_encrypted_team_context(monkeypatch) -> None:
    from backend.core.api.app.utils import device_fingerprint

    monkeypatch.setattr(teams, "get_price_for_credits", lambda _credits, _currency: 500)
    monkeypatch.setattr(device_fingerprint, "get_geo_data_from_ip", lambda _ip: {"country_code": "DE"})
    client = build_client(RoleTeamService("owner"), FakeTeamBillingService())
    payload = {"credits_amount": 50, "currency": "eur", "email_encryption_key": "email-key", "buyer_address": {
        "name": "Team Buyer", "street_line_1": "Main 1", "postal_code": "10115", "city": "Berlin", "country": "DE",
    }}

    first = client.post("/v1/teams/team-1/billing/card-orders", json=payload)
    second = client.post("/v1/teams/team-1/billing/card-orders", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert client.app.state.payment_service.card_customer_ids == [None, "cus_team"]
    contexts = client.app.state.directus_service.billing_order_contexts
    assert len(contexts) == 2
    assert all(row["owner_kind"] == "team" for row in contexts)
    assert all(row["encrypted_buyer_address"].startswith("cipher:") for row in contexts)
    assert all(row["address_vault_key_id"] == "vault-team-billing" for row in contexts)
    assert all(row["payer_email_vault_key_id"] == "vault-team-billing" for row in contexts)
    assert client.app.state.directus_service.billing_profiles[0]["stripe_customer_id"] == "cus_team"

    member = build_client(RoleTeamService("member"), FakeTeamBillingService())
    forbidden = member.post("/v1/teams/team-1/billing/card-orders", json=payload)
    assert forbidden.status_code == 403


# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled
def test_teams_routes_reject_cleartext_encrypted_fields() -> None:
    client = build_client(FakeTeamService())

    response = client.post(
        "/v1/teams",
        json={
            "team_id": "team-1",
            "encrypted_name": "Plain Team Name",
            "name_approval_token": name_approval_token(client),
            "encrypted_profile_image_metadata": client_ciphertext(b"profile-image"),
            "encrypted_team_key": client_ciphertext(b"team-key"),
            "created_at": 100,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {"error": "team_cleartext_rejected", "fields": ["encrypted_name"]}


# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated
def test_name_approval_blocks_policy_names_and_requires_single_use_token() -> None:
    client = build_client(FakeTeamService())
    assert client.post("/v1/teams/name-approval", json={"name": "Blocked.Example"}).json()["detail"] == "TEAM_NAME_BLOCKED"
    payload = {
        "team_id": "team-1", "encrypted_name": client_ciphertext(b"name"),
        "encrypted_profile_image_metadata": client_ciphertext(b"image"),
        "encrypted_team_key": client_ciphertext(b"key"), "created_at": 100,
    }
    assert client.post("/v1/teams", json=payload).json()["detail"][0]["type"] == "missing"
    token = name_approval_token(client)
    assert client.post("/v1/teams", json={**payload, "name_approval_token": token}).status_code == 200
    assert client.post("/v1/teams", json={**payload, "name_approval_token": token}).json()["detail"] == "TEAM_NAME_APPROVAL_REQUIRED"


# contract-test: direct surface=rest_api assertions=teams.invites.fragment-key-web-flow,teams.membership.role-gated
def test_invite_preview_checks_verified_account_and_intended_email() -> None:
    from backend.core.api.app.services.team_invite_email_service import hash_invite_email

    class PreviewTeamService(FakeTeamService):
        async def get_invite_for_recipient(self, invite_id: str, recipient_email_hash: str | None):
            if invite_id == "invite-1" and recipient_email_hash == hash_invite_email("alice@example.com"):
                return {"invite_id": invite_id, "hashed_team_id": "hash-team", "encrypted_invite_team_key": client_ciphertext(b"invite-key")}
            return None

    client = build_client(PreviewTeamService())
    client.app.state.directus_service.signup_completed = False
    assert client.post("/v1/teams/invites/invite-1/preview", json={"verified_email": "other@example.com"}).status_code == 403
    valid = client.post("/v1/teams/invites/invite-1/preview", json={"verified_email": "alice@example.com"})
    assert valid.status_code == 200
    assert valid.json()["invite"]["encrypted_invite_team_key"] == client_ciphertext(b"invite-key")


# contract-test: direct surface=rest_api assertions=teams.invites.fragment-key-web-flow
def test_invite_create_rejects_missing_envelope_and_fragment_in_kdf_context() -> None:
    client = build_client(FakeTeamService())
    base = {"invite_id": "invite-1", "role": "member", "created_at": 100}
    assert client.post("/v1/teams/team-1/invites", json=base).json()["detail"] == "TEAM_INVITE_KEY_REQUIRED"
    response = client.post("/v1/teams/team-1/invites", json={
        **base, "encrypted_invite_team_key": client_ciphertext(b"invite"),
        "invite_key_kdf_context": {**invite_kdf_context(), "secret": "must-stay-client-side"},
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "TEAM_INVITE_KDF_INVALID"
    for privileged_field in ("hashed_recipient_email", "one_time_token_hash", "sent_at", "fragment_secret"):
        forged = client.post("/v1/teams/team-1/invites", json={
            **base, "encrypted_invite_team_key": client_ciphertext(b"invite"),
            "invite_key_kdf_context": invite_kdf_context(), privileged_field: "forged",
        })
        assert forged.status_code == 422


# contract-test: direct surface=rest_api assertions=teams.membership.role-gated
def test_team_security_settings_require_admin_and_restrict_direct_invite_domains() -> None:
    class PolicyTeamService(FakeTeamService):
        role = "owner"

        async def get_team(self, team_id: str, user_id: str):
            team = await super().get_team(team_id, user_id)
            return {**team, "role": self.role, "security_policy": {
                "restrict_email_domains": True, "allowed_email_domains": ["example.com"],
                "require_invite_link_approval": True, "require_strong_auth": False,
            }}

        async def update_security_policy(self, team_id: str, user_id: str, policy: dict):
            if self.role != "owner":
                raise teams.TeamPermissionError("denied")
            return policy

    service = PolicyTeamService()
    client = build_client(service)
    blocked = client.post("/v1/teams/team-1/invites", json={"invite_id": "invite-1", "recipient_email": "bob@other.example", "encrypted_invite_team_key": client_ciphertext(b"invite"), "invite_key_kdf_context": invite_kdf_context(), "created_at": 100})
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "TEAM_EMAIL_DOMAIN_NOT_ALLOWED"
    updated = client.patch("/v1/teams/team-1/security", json={"require_strong_auth": True})
    assert updated.status_code == 200
    assert updated.json()["security_policy"] == {"require_strong_auth": True}
    service.role = "viewer"
    assert client.patch("/v1/teams/team-1/security", json={"require_strong_auth": True}).status_code == 403


# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.lifecycle.encrypted-profiled
def test_member_list_detail_and_self_profile_keep_display_snapshot_encrypted() -> None:
    client = build_client(FakeTeamService())
    members = client.get("/v1/teams/team-1/members")
    assert members.status_code == 200
    assert members.headers["cache-control"] == "private, no-store"
    member = members.json()["members"][0]
    assert member["encrypted_member_profile"] == client_ciphertext(b"profile")
    assert member["profile_image_url"] == "/v1/teams/team-1/members/alice/profile-image"
    assert "display_name" not in member
    detail = client.get("/v1/teams/team-1/members/alice")
    assert detail.json()["member"] == member
    assert client.get("/v1/teams/team-1/members/bob").status_code == 404
    new_snapshot = client_ciphertext(b"new-profile")
    update = client.patch("/v1/teams/team-1/members/me/profile", json={"encrypted_member_profile": new_snapshot})
    assert update.json()["member"]["encrypted_member_profile"] == new_snapshot
    assert client.patch("/v1/teams/team-1/members/me/profile", json={"encrypted_member_profile": "plain"}).status_code == 422


# contract-test: direct surface=rest_api assertions=teams.membership.role-gated
def test_team_member_avatar_proxy_refuses_nonmember_target() -> None:
    class AvatarTeamService(FakeTeamService):
        async def get_membership(self, team_id: str, user_id: str):
            assert team_id == "team-1"
            return None if user_id == "bob" else {"role": "owner"}

    client = build_client(AvatarTeamService())
    client.app.state.s3_service = object()
    response = client.get("/v1/teams/team-1/members/bob/profile-image")
    assert response.status_code == 404


# contract-test: direct surface=rest_api assertions=teams.membership.role-gated
def test_team_member_avatar_proxy_scopes_and_disables_plaintext_cache(monkeypatch) -> None:
    from fastapi.responses import StreamingResponse

    class AvatarTeamService(FakeTeamService):
        async def get_membership(self, team_id: str, user_id: str):
            assert team_id == "team-1" and user_id == "bob"
            return {"role": "member"}

    async def fake_profile_image(**kwargs):
        assert kwargs["user_id"] == "bob"
        return StreamingResponse(iter([b"jpeg-bytes"]), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})

    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.profile_api", SimpleNamespace(
        get_profile_image=SimpleNamespace(__wrapped__=fake_profile_image),
    ))
    client = build_client(AvatarTeamService())
    client.app.state.s3_service = object()
    response = client.get("/v1/teams/team-1/members/bob/profile-image")
    assert response.status_code == 200
    assert response.content == b"jpeg-bytes"
    assert response.headers["cache-control"] == "private, no-store"


# contract-test: supporting surface=rest_api assertions=teams.billing.context-parity,teams.membership.role-gated
@pytest.mark.parametrize("action", ["delete", "remove", "demote"])
def test_recurring_team_billing_stops_before_team_or_payer_offboarding(action: str) -> None:
    from backend.core.api.app.services.directus.team_methods import hash_id

    service = FakeTeamService()
    client = build_client(service)
    canceled: list[str] = []

    async def cancel_subscription(subscription_id: str):
        canceled.append(subscription_id)
        return {"status": "canceled"}

    client.app.state.payment_service._stripe_provider = SimpleNamespace(cancel_subscription=cancel_subscription)
    directus = client.app.state.directus_service
    directus.billing_profiles.append({
        "id": "billing-1", "owner_kind": "team", "owner_hash": hash_id("team-1"), "owner_id": "team-1",
        "monthly_subscription_id": "sub_team", "monthly_subscription_status": "active",
        "monthly_payer_user_id": "bob", "auto_topup_enabled": True,
        "auto_topup_payer_user_id": "bob", "encrypted_auto_topup_payment_method": "cipher:pm",
        "encrypted_auto_topup_email": "cipher:email",
    })

    if action == "delete":
        response = client.delete("/v1/teams/team-1")
        assert service.events[-1] == "delete_team"
    elif action == "remove":
        response = client.post("/v1/teams/team-1/members/bob/remove", json={"removed_at": 200})
        assert "deactivate_member" in service.events
    else:
        response = client.patch("/v1/teams/team-1/members/bob", json={"role": "viewer"})
    assert response.status_code == 200
    assert canceled == ["sub_team"]
    profile = directus.billing_profiles[0]
    assert profile["monthly_subscription_id"] == "sub_team"
    assert profile["monthly_subscription_status"] == "canceled"
    assert profile["auto_topup_enabled"] is False
    assert profile["encrypted_auto_topup_payment_method"] is None
