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


_TEST_CLIENT_COUNTER = count(1)


def client_ciphertext(label: bytes = b"ciphertext-ok") -> str:
    return base64.b64encode(b"OM" + bytes.fromhex("1a5b3b7c") + (b"0" * 12) + label + (b"t" * 16)).decode("ascii")


class FakeTeamService:
    def __init__(self) -> None:
        self.created_payload = None
        self.updated_payload = None

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

    async def update_team(self, team_id: str, user_id: str, patch: dict):
        assert team_id == "team-1"
        assert user_id == "alice"
        self.updated_payload = patch
        return {"team_id": team_id, **patch}

    async def delete_team(self, team_id: str, user_id: str):
        assert team_id == "team-1"
        assert user_id == "alice"
        return True

    async def create_invite(self, team_id: str, user_id: str, payload: dict):
        assert team_id == "team-1"
        assert user_id == "alice"
        return {"invite_id": payload["invite_id"], "role": payload["role"]}

    async def accept_invite(self, invite_id: str, user_id: str, accepted_at=None):
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
        return True

    async def set_member_role(self, team_id: str, user_id: str, member_user_id: str, role: str, updated_at=None):
        assert team_id == "team-1"
        assert user_id == "alice"
        assert member_user_id == "bob"
        return {"hashed_user_id": "hash-bob", "role": role, "updated_at": updated_at}

    async def require_team_role(self, team_id: str, actor_user_id: str, roles: set[str]):
        assert team_id == "team-1"
        assert actor_user_id == "alice"
        assert "admin" in roles
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

    async def set_bank_transfer_order(self, **kwargs):
        self.cached_orders.append(kwargs)
        return True


class FakeDirectusService(SimpleNamespace):
    def __init__(self, team_service) -> None:
        super().__init__(team=team_service)
        self.bank_transfer_rows = []

    async def get_items(self, collection: str, params: dict, **_kwargs):
        assert collection == "pending_bank_transfers"
        rows = list(self.bank_transfer_rows)
        for key, expected in params.items():
            if key.startswith("filter[") and "][_eq]" in key:
                field = key.removeprefix("filter[").split("]", 1)[0]
                rows = [row for row in rows if row.get(field) == expected]
        limit = params.get("limit", len(rows))
        return rows if limit == -1 else rows[:limit]

    async def create_item(self, collection: str, record: dict, admin_required: bool = False):
        assert collection == "pending_bank_transfers"
        assert admin_required is True
        row = {"id": f"pending-{len(self.bank_transfer_rows) + 1}", **record}
        self.bank_transfer_rows.append(row)
        return True, row


class FakeConfigManager:
    def __init__(self, config: dict | None = None) -> None:
        self.config = config if config is not None else {"feature_overrides": {"enabled": ["platform:teams"], "disabled": []}}

    def get_backend_config(self) -> dict:
        return self.config


def build_client(team_service, team_billing_service=None, config: dict | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(teams.router)
    app.state.directus_service = FakeDirectusService(team_service)
    app.state.config_manager = FakeConfigManager(config)
    if team_billing_service:
        app.state.team_billing_service = team_billing_service
    app.state.cache_service = FakeCacheService()
    app.state.payment_service = FakePaymentService()

    async def fake_current_user(_request=None, _response=None):
        return User(id="alice", username="alice", vault_key_id="vault-alice")

    app.dependency_overrides[teams._current_user] = fake_current_user
    client_index = next(_TEST_CLIENT_COUNTER)
    return TestClient(app, client=(f"teams-test-{client_index}", 50000 + client_index))


def test_teams_routes_block_when_feature_disabled() -> None:
    client = build_client(FakeTeamService(), config={})

    response = client.get("/v1/teams")

    assert response.status_code == 404
    assert response.json()["detail"] == "FEATURE_DISABLED"


def test_teams_routes_expose_lifecycle_contract() -> None:
    service = FakeTeamService()
    client = build_client(service)

    assert client.get("/v1/teams").json()["teams"][0]["team_id"] == "team-1"
    create_response = client.post(
        "/v1/teams",
        json={
            "team_id": "team-1",
            "encrypted_name": client_ciphertext(b"name"),
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
    assert client.patch("/v1/teams/team-1", json={"encrypted_name": updated_name, "updated_at": 110}).json()["team"]["encrypted_name"] == updated_name
    assert client.delete("/v1/teams/team-1").json() == {"success": True}


def test_teams_routes_expose_invite_and_member_contract() -> None:
    client = build_client(FakeTeamService())

    invite_response = client.post("/v1/teams/team-1/invites", json={"invite_id": "invite-1", "role": "viewer", "created_at": 100})
    assert invite_response.status_code == 200
    assert invite_response.json()["invite"] == {"invite_id": "invite-1", "role": "viewer"}

    accept_response = client.post("/v1/teams/invites/invite-1/accept", json={"accepted_at": 120})
    assert accept_response.status_code == 200
    assert accept_response.json()["access_request"]["status"] == "pending_access_approval"

    approve_response = client.post("/v1/teams/team-1/access-requests/access-1/approve", json={"encrypted_team_key": client_ciphertext(b"team-key"), "approved_at": 130})
    assert approve_response.status_code == 200
    assert approve_response.json()["membership"]["role"] == "member"

    remove_response = client.post("/v1/teams/team-1/members/bob/remove", json={"removed_at": 200})
    assert remove_response.status_code == 200
    assert remove_response.json() == {"success": True}

    role_response = client.patch("/v1/teams/team-1/members/bob", json={"role": "viewer", "updated_at": 210})
    assert role_response.status_code == 200
    assert role_response.json()["membership"]["role"] == "viewer"


def test_team_permission_error_maps_to_403() -> None:
    client = build_client(DenyingTeamService())

    response = client.patch("/v1/teams/team-1", json={"encrypted_name": client_ciphertext(b"updated-name"), "updated_at": 110})

    assert response.status_code == 403
    assert response.json()["detail"] == "TEAM_PERMISSION_DENIED"


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


def test_teams_routes_reject_cleartext_encrypted_fields() -> None:
    client = build_client(FakeTeamService())

    response = client.post(
        "/v1/teams",
        json={
            "team_id": "team-1",
            "encrypted_name": "Plain Team Name",
            "encrypted_team_key": client_ciphertext(b"team-key"),
            "created_at": 100,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {"error": "team_cleartext_rejected", "fields": ["encrypted_name"]}
