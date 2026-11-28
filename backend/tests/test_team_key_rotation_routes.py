"""Team key rotation HTTP routes: auth, typed 409/403 refusals and the successful upload."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.core.api.app.models.user import User
from backend.core.api.app.routes import teams
from backend.core.api.app.services.directus.team_methods import hash_id
from backend.tests.test_team_key_rotation import _team_with, _upload


def _client(methods, user: str | None) -> TestClient:
    app = FastAPI()
    app.include_router(teams.router)  # includes the key-rotation router
    app.state.directus_service = type("Directus", (), {"team": methods})()
    app.state.cache_service = object()
    app.state.config_manager = SimpleNamespace(
        get_backend_config=lambda: {"feature_overrides": {"enabled": ["platform:teams"], "disabled": []}}
    )
    if user is not None:
        async def current_user(_request=None, _response=None):
            return User(id=user, username=user, vault_key_id=f"vault-{user}")

        app.dependency_overrides[teams._current_user] = current_user
    return TestClient(app, client=("rotation-route-test", 50100))


async def _removed_bob():
    directus, methods, _rotation = await _team_with("bob", "carol")
    await methods.remove_member("team-1", "alice", "bob", removed_at=200)
    return directus, methods


# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_rotation_routes_need_authentication() -> None:
    _directus, methods = await _removed_bob()
    client = _client(methods, None)
    assert client.get("/v1/teams/team-1/key-rotation").status_code in (401, 403)
    assert client.post("/v1/teams/team-1/key-rotation", json=_upload("alice", "carol")).status_code in (401, 403)


# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_post_key_rotation_succeeds_for_owner_and_clears_pending() -> None:
    directus, methods = await _removed_bob()
    client = _client(methods, "alice")
    context = client.get("/v1/teams/team-1/key-rotation")
    assert context.status_code == 200 and context.json()["rotation_pending"] is True
    assert context.json()["profile"]["encrypted_name"] == "cipher-name"
    response = client.post("/v1/teams/team-1/key-rotation", json=_upload("alice", "carol"))
    assert response.status_code == 200
    assert response.json() == {"success": True, "team_key_epoch": 2}
    assert directus.rows["teams"][0]["rotation_pending"] is False
    assert {r["hashed_user_id"] for r in directus.rows["team_key_wrappers"]} == {hash_id("alice"), hash_id("carol")}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upload",
    [
        _upload("alice", "carol", epoch=3),
        _upload("alice"),
        _upload("alice", "carol", "bob"),
        _upload("alice", "carol", projects=("p1",)),
    ],
)
# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
async def test_post_key_rotation_conflicts_leave_the_team_pending(upload) -> None:
    directus, methods = await _removed_bob()
    response = _client(methods, "alice").post("/v1/teams/team-1/key-rotation", json=upload)
    assert response.status_code == 409
    assert directus.rows["teams"][0]["rotation_pending"] is True


# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_post_key_rotation_refuses_a_plain_member() -> None:
    _directus, methods = await _removed_bob()
    response = _client(methods, "carol").post("/v1/teams/team-1/key-rotation", json=_upload("alice", "carol"))
    assert response.status_code == 403
