"""Teams V1 connected-account context tests.

Team rows are explicit and encrypted. Owner/admin manage them, members and
viewers receive safe metadata only, and Team requests never fall back to a
Personal connected account or token reference.
"""

import sys
import types


if "redis" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class FakeRedisClient:
        pass

    redis_asyncio_module.Redis = FakeRedisClient
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = types.SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

if "aiohttp" not in sys.modules:
    aiohttp_module = types.ModuleType("aiohttp")

    class FakeClientSession:
        pass

    aiohttp_module.ClientSession = FakeClientSession
    sys.modules["aiohttp"] = aiohttp_module

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.core.api.app.models.user import User
from backend.core.api.app.routes import connected_accounts
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.core.api.app.services.token_broker import TokenBrokerService


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, dict] = {}

    async def set(self, key: str, value: dict, ttl: int | None = None):
        self.values[key] = value | {"ttl": ttl}
        return True

    async def get(self, key: str):
        return self.values.get(key)

    async def delete(self, key: str):
        self.values.pop(key, None)
        return True


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext: str, _key_id: str):
        return f"enc:{plaintext}", 1

    async def decrypt_with_user_key(self, ciphertext: str, _key_id: str):
        return ciphertext.removeprefix("enc:")


class FakeTeamService:
    def __init__(self, role: str = "member") -> None:
        self.role = role

    async def require_team_role(self, team_id: str, user_id: str, allowed_roles: set[str]):
        assert team_id == "team-1"
        assert user_id == "alice"
        if self.role not in allowed_roles:
            raise TeamPermissionError("role denied")
        return {"role": self.role}


class FakeDirectus:
    def __init__(self, role: str = "member") -> None:
        self.team = FakeTeamService(role)
        self.rows: dict[str, dict] = {}

    async def get_items(self, _collection: str, params: dict | None = None):
        params = params or {}
        rows = list(self.rows.values())
        account_id = params.get("filter[id][_eq]")
        hashed_user_id = params.get("filter[hashed_user_id][_eq]")
        hashed_team_id = params.get("filter[hashed_team_id][_eq]")
        if account_id:
            rows = [row for row in rows if row.get("id") == account_id]
        if hashed_team_id:
            rows = [row for row in rows if row.get("hashed_team_id") == hashed_team_id]
        elif params.get("filter[hashed_team_id][_null]") is True:
            rows = [row for row in rows if row.get("hashed_team_id") is None]
        if hashed_user_id:
            rows = [row for row in rows if row.get("hashed_user_id") == hashed_user_id]
        return rows

    async def create_item(self, _collection: str, payload: dict):
        self.rows[payload["id"]] = dict(payload)
        return True, dict(payload)

    async def update_item(self, _collection: str, item_id: str, payload: dict):
        self.rows[item_id].update(payload)
        return dict(self.rows[item_id])


def _client(directus: FakeDirectus) -> TestClient:
    app = FastAPI()
    app.include_router(connected_accounts.router)
    app.dependency_overrides[connected_accounts.get_current_user] = lambda: User(id="alice", username="alice", vault_key_id="vault-1")
    app.dependency_overrides[connected_accounts.get_directus_service] = lambda: directus
    return TestClient(app)


def _row(account_id: str, *, team_id: str | None = None) -> dict:
    return {
        "id": account_id,
        "hashed_user_id": hash_id("alice"),
        "hashed_team_id": hash_id(team_id) if team_id else None,
        "encrypted_provider_type": "enc:google",
        "provider_type_hash": "hash:google",
        "encrypted_account_label": "enc:work",
        "encrypted_refresh_token_bundle": "enc:refresh",
        "encrypted_capabilities": "enc:caps",
        "encrypted_app_permissions": "enc:perms",
    }


# contract-test: supporting surface=rest_api assertions=teams.connected-accounts.team-owned-isolation
def test_connected_account_list_switches_context_and_redacts_member_secrets() -> None:
    directus = FakeDirectus(role="member")
    directus.rows = {"personal": _row("personal"), "team": _row("team", team_id="team-1")}
    client = _client(directus)

    assert [row["id"] for row in client.get("/v1/connected-accounts").json()["rows"]] == ["personal"]
    response = client.get("/v1/connected-accounts?team_id=team-1")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["rows"]] == ["team"]
    assert "encrypted_refresh_token_bundle" not in response.json()["rows"][0]


# contract-test: supporting surface=rest_api assertions=teams.connected-accounts.team-owned-isolation
def test_team_connected_account_create_requires_owner_or_admin() -> None:
    directus = FakeDirectus(role="member")
    response = _client(directus).post("/v1/connected-accounts?team_id=team-1", json=_row("team-created"))

    assert response.status_code == 403
    assert directus.rows == {}

    owner_directus = FakeDirectus(role="owner")
    owner_response = _client(owner_directus).post(
        "/v1/connected-accounts?team_id=team-1",
        json=_row("team-created"),
    )
    assert owner_response.status_code == 200
    assert owner_directus.rows["team-created"]["hashed_team_id"] == hash_id("team-1")


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=teams.connected-accounts.team-owned-isolation
async def test_team_turn_token_ref_cannot_be_exchanged_as_personal_context() -> None:
    async def exchange_refresh_token(_refresh_token: str, _metadata: dict):
        return {"access_token": "access-token"}

    broker = TokenBrokerService(
        cache_service=FakeCache(),
        encryption_service=FakeEncryption(),
        exchange_refresh_token=exchange_refresh_token,
    )
    ref = await broker.create_turn_token_ref(
        user_id="alice",
        user_vault_key_id="vault-1",
        connected_account_id="team-account",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": "secret"},
        team_id="team-1",
    )

    with pytest.raises(PermissionError):
        await broker.exchange_turn_token_ref(
            turn_token_ref=ref.turn_token_ref,
            user_id="alice",
            user_vault_key_id="vault-1",
            chat_id="chat-1",
            message_id="msg-1",
            app_id="calendar",
            action="read",
        )

    handle = await broker.exchange_turn_token_ref(
        turn_token_ref=ref.turn_token_ref,
        user_id="alice",
        user_vault_key_id="vault-1",
        chat_id="chat-1",
        message_id="msg-1",
        app_id="calendar",
        action="read",
        team_id="team-1",
    )
    assert handle.access_token_handle.startswith("ath_")
