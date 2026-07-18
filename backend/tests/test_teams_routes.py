"""Route-level tests for Teams V1 API behavior.

The Teams router supports both session and API-key authenticated clients. These
tests use dependency overrides so they verify route contracts, response shapes,
and permission-error mapping without a live Directus or auth stack.
"""

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
        assert encrypted_team_key == "cipher-team-key"
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


class DenyingTeamService(FakeTeamService):
    async def update_team(self, team_id: str, user_id: str, patch: dict):
        raise TeamPermissionError("viewer cannot update team")


class FakeTeamBillingService:
    async def get_billing_summary(self, team_id: str, actor_user_id: str):
        assert team_id == "team-1"
        assert actor_user_id == "alice"
        return {"balance_credits": 100, "encrypted_balance": "cipher-balance-100"}

    async def add_credits(self, **kwargs):
        assert kwargs["team_id"] == "team-1"
        assert kwargs["actor_user_id"] == "alice"
        assert kwargs["event_id"] == "purchase-1"
        return {"account": {"balance_credits": 150}, "credit_event": {"event_type": "purchase", "amount": 50}}

    async def charge_team_credits(self, **kwargs):
        assert kwargs["team_id"] == "team-1"
        assert kwargs["actor_user_id"] == "alice"
        return {"account": {"balance_credits": 140}, "usage_event": {"credit_amount": 10}}

    async def list_usage(self, team_id: str, actor_user_id: str, member_user_id: str | None = None):
        assert team_id == "team-1"
        assert actor_user_id == "alice"
        assert member_user_id == "bob"
        return [{"event_id": "usage-1", "credit_amount": 10}]


def build_client(team_service, team_billing_service=None) -> TestClient:
    app = FastAPI()
    app.include_router(teams.router)
    app.state.directus_service = SimpleNamespace(team=team_service)
    if team_billing_service:
        app.state.team_billing_service = team_billing_service
    app.state.cache_service = SimpleNamespace()

    async def fake_current_user(_request=None, _response=None):
        return User(id="alice", username="alice", vault_key_id="vault-alice")

    app.dependency_overrides[teams._current_user] = fake_current_user
    return TestClient(app)


def test_teams_routes_expose_lifecycle_contract() -> None:
    service = FakeTeamService()
    client = build_client(service)

    assert client.get("/v1/teams").json()["teams"][0]["team_id"] == "team-1"
    create_response = client.post(
        "/v1/teams",
        json={
            "team_id": "team-1",
            "encrypted_name": "cipher-name",
            "encrypted_team_key": "cipher-team-key-owner",
            "encrypted_zero_balance": "cipher-zero",
            "created_at": 100,
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["team"]["role"] == "owner"
    assert service.created_payload["encrypted_team_key"] == "cipher-team-key-owner"

    assert client.get("/v1/teams/team-1").json()["team"]["role"] == "owner"
    assert client.patch("/v1/teams/team-1", json={"encrypted_name": "cipher-updated", "updated_at": 110}).json()["team"]["encrypted_name"] == "cipher-updated"
    assert client.delete("/v1/teams/team-1").json() == {"success": True}


def test_teams_routes_expose_invite_and_member_contract() -> None:
    client = build_client(FakeTeamService())

    invite_response = client.post("/v1/teams/team-1/invites", json={"invite_id": "invite-1", "role": "viewer", "created_at": 100})
    assert invite_response.status_code == 200
    assert invite_response.json()["invite"] == {"invite_id": "invite-1", "role": "viewer"}

    accept_response = client.post("/v1/teams/invites/invite-1/accept", json={"accepted_at": 120})
    assert accept_response.status_code == 200
    assert accept_response.json()["access_request"]["status"] == "pending_access_approval"

    approve_response = client.post("/v1/teams/team-1/access-requests/access-1/approve", json={"encrypted_team_key": "cipher-team-key", "approved_at": 130})
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

    response = client.patch("/v1/teams/team-1", json={"encrypted_name": "cipher-updated", "updated_at": 110})

    assert response.status_code == 403
    assert response.json()["detail"] == "TEAM_PERMISSION_DENIED"


def test_teams_routes_expose_billing_contract() -> None:
    client = build_client(FakeTeamService(), FakeTeamBillingService())

    assert client.get("/v1/teams/team-1/billing").json()["billing"]["balance_credits"] == 100
    add_response = client.post(
        "/v1/teams/team-1/billing/credits",
        json={"event_id": "purchase-1", "credits": 50, "encrypted_balance": "cipher-balance-150", "occurred_at": 200},
    )
    assert add_response.status_code == 200
    assert add_response.json()["billing"]["credit_event"]["amount"] == 50

    charge_response = client.post(
        "/v1/teams/team-1/billing/charge",
        json={"event_id": "usage-1", "credits": 10, "encrypted_balance": "cipher-balance-140", "workspace_type": "chat"},
    )
    assert charge_response.status_code == 200
    assert charge_response.json()["charge"]["usage_event"]["credit_amount"] == 10

    usage_response = client.get("/v1/teams/team-1/billing/usage?member_user_id=bob")
    assert usage_response.status_code == 200
    assert usage_response.json()["usage"] == [{"event_id": "usage-1", "credit_amount": 10}]
