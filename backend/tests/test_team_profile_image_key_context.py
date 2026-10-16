"""Team avatar keys remain readable after the uploader deletes their account."""

import ast
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.services.directus.team_methods import TeamPermissionError


# Load the actual route body without unrelated runtime dependencies of internal_api.
source = Path(__file__).parents[1] / "core/api/app/routes/internal_api.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
route_node = next(
    node for node in tree.body
    if isinstance(node, ast.AsyncFunctionDef) and node.name == "process_team_profile_image"
)
route_node.decorator_list = []
route_module = ast.Module(
    body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), route_node],
    type_ignores=[],
)
route_globals = {
    "Depends": lambda _dependency: None,
    "get_directus_service": lambda: None,
    "get_encryption_service": lambda: None,
    "get_cache_service": lambda: None,
    "TeamPermissionError": TeamPermissionError,
    "HTTPException": HTTPException,
    "logger": logging.getLogger(__name__),
    "time": time,
}
exec(compile(ast.fix_missing_locations(route_module), str(source), "exec"), route_globals)
process_team_profile_image = route_globals["process_team_profile_image"]


class FakeTeam:
    def __init__(self, *, allowed=True):
        self.allowed = allowed
        self.events = []
        self.metadata = None

    async def require_team_role(self, team_id, user_id, roles):
        self.events.append("role")
        assert (team_id, user_id, roles) == ("team-1", "alice", {"owner", "admin"})
        if not self.allowed:
            raise TeamPermissionError("denied")

    async def process_team_profile_image(self, **payload):
        self.events.append("persist")
        self.metadata = payload
        return {"old_s3_key": "old-image.enc"}


class FakeDirectus:
    def __init__(self, team):
        self.team = team
        self.profiles = []

    async def get_items(self, collection, params, **_kwargs):
        assert collection == "billing_profiles"
        rows = self.profiles
        for field, condition in params["filter"].items():
            rows = [row for row in rows if row.get(field) == condition["_eq"]]
        return rows[:params["limit"]]

    async def create_item(self, collection, payload, **_kwargs):
        assert collection == "billing_profiles"
        row = {"id": "billing-1", **payload}
        self.profiles.append(row)
        return True, row


class FakeEncryption:
    def __init__(self):
        self.created = 0
        self.wrapped_with = []

    async def create_user_key(self):
        self.created += 1
        return "team-independent-key"

    async def encrypt_with_user_key(self, plaintext, key_id):
        self.wrapped_with.append((plaintext, key_id))
        return "wrapped-team-image-key", key_id


class FakeCache:
    def __init__(self):
        self.reads = 0

    async def get_user_vault_key_id(self, user_id):
        self.reads += 1
        return "personal-uploader-key"


# contract-test: supporting surface=rest_api assertions=teams.profile-image.safe-parity
@pytest.mark.anyio
async def test_team_image_wraps_with_team_key_and_cleans_old_object():
    team = FakeTeam()
    directus = FakeDirectus(team)
    encryption = FakeEncryption()
    cache = FakeCache()
    deleted = []

    async def delete_file(bucket, key):
        deleted.append((bucket, key))

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        s3_service=SimpleNamespace(delete_file=delete_file)
    )))
    payload = SimpleNamespace(
        user_id="alice", team_id="team-1", encrypted_profile_image_metadata="client-ciphertext",
        s3_key="new-image.enc", aes_key_b64="aes-key", nonce_b64="nonce",
    )
    result = await process_team_profile_image(
        payload, request, directus_service=directus, encryption_service=encryption,
        cache_service=cache,
    )

    assert result == {"status": "ok", "url": "/v1/teams/team-1/profile-image"}
    assert team.events == ["role", "persist"]
    assert encryption.wrapped_with == [("aes-key", "team-independent-key")]
    assert team.metadata["profile_image_vault_key_id"] == "team-independent-key"
    assert directus.profiles[0]["billing_vault_key_id"] == "team-independent-key"
    assert deleted == [("profile_images_private", "old-image.enc")]


# contract-test: supporting surface=rest_api assertions=teams.profile-image.safe-parity,teams.membership.role-gated
@pytest.mark.anyio
async def test_team_image_denial_precedes_key_and_metadata_changes():
    team = FakeTeam(allowed=False)
    directus = FakeDirectus(team)
    encryption = FakeEncryption()
    cache = FakeCache()
    payload = SimpleNamespace(
        user_id="alice", team_id="team-1", encrypted_profile_image_metadata="client-ciphertext",
        s3_key="new-image.enc", aes_key_b64="aes-key", nonce_b64="nonce",
    )

    with pytest.raises(HTTPException) as error:
        await process_team_profile_image(
            payload, SimpleNamespace(), directus_service=directus,
            encryption_service=encryption, cache_service=cache,
        )

    assert error.value.status_code == 403
    assert team.events == ["role"]
    assert cache.reads == 0
    assert encryption.created == 0
    assert encryption.wrapped_with == []
    assert directus.profiles == []
    assert team.metadata is None
