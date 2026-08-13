"""Teams V1 profile-image contract tests.

These tests protect the backend-first part of feature.teams@1: team creation
must persist client-encrypted generated profile metadata, owner/admin updates
must support generated or uploaded profile states, and team image uploads must
reuse the same private encrypted profile-image pipeline as user profile images.
"""

from __future__ import annotations

import base64
from collections import defaultdict
import sys
import types
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.directus.team_methods import TeamMethods, TeamPermissionError

if "python_multipart" not in sys.modules:
    python_multipart_module = types.ModuleType("python_multipart")
    python_multipart_module.__version__ = "0.0.99"
    sys.modules["python_multipart"] = python_multipart_module
if "multipart.multipart" not in sys.modules:
    multipart_module = types.ModuleType("multipart")
    multipart_submodule = types.ModuleType("multipart.multipart")
    multipart_submodule.parse_options_header = lambda value: (value, {})
    multipart_module.multipart = multipart_submodule
    sys.modules["multipart"] = multipart_module
    sys.modules["multipart.multipart"] = multipart_submodule

from backend.upload.routes import upload_route


def client_ciphertext(label: bytes = b"ciphertext-ok") -> str:
    return base64.b64encode(b"OM" + bytes.fromhex("1a5b3b7c") + (b"0" * 12) + label + (b"t" * 16)).decode("ascii")


class FakeDirectus:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.created: list[tuple[str, dict, bool]] = []
        self.updated: list[tuple[str, str, dict, bool]] = []

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

    async def get_items(self, collection: str, params: dict, **_kwargs):
        rows = list(self.rows[collection])
        for key, expected in params.items():
            if not key.startswith("filter[") or "][_eq]" not in key:
                continue
            field = key.removeprefix("filter[").split("]", 1)[0]
            rows = [row for row in rows if row.get(field) == expected]
        limit = params.get("limit", len(rows))
        return rows if limit == -1 else rows[:limit]


def team_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "team_id": "team-1",
        "slug": "acme",
        "encrypted_name": client_ciphertext(b"name"),
        "encrypted_description": client_ciphertext(b"description"),
        "encrypted_profile_image_metadata": client_ciphertext(b"generated-team-icon-blue"),
        "encrypted_team_key": client_ciphertext(b"team-key-for-owner"),
        "encrypted_zero_balance": client_ciphertext(b"zero-balance"),
        "created_at": 100,
        "updated_at": 100,
    }
    payload.update(overrides)
    return payload


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.profile-image.safe-parity
async def test_create_team_persists_generated_profile_metadata_for_list_and_get() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)

    created = await methods.create_team("alice", team_payload())
    listed = await methods.list_teams("alice")
    fetched = await methods.get_team("team-1", "alice")

    assert created is not None
    assert directus.rows["teams"][0]["encrypted_profile_image_metadata"] == client_ciphertext(b"generated-team-icon-blue")
    assert listed[0]["encrypted_profile_image_metadata"] == client_ciphertext(b"generated-team-icon-blue")
    assert fetched is not None
    assert fetched["encrypted_profile_image_metadata"] == client_ciphertext(b"generated-team-icon-blue")
    assert "icon_name" not in directus.rows["teams"][0]
    assert "background_color" not in directus.rows["teams"][0]


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled
async def test_create_team_requires_encrypted_profile_metadata() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    payload = team_payload()
    payload.pop("encrypted_profile_image_metadata")

    with pytest.raises(ValueError, match="encrypted_profile_image_metadata"):
        await methods.create_team("alice", payload)


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.membership.role-gated,teams.profile-image.safe-parity
async def test_owner_admin_can_update_profile_metadata_but_viewer_cannot() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team("alice", team_payload())
    await methods.create_invite("team-1", "alice", {"invite_id": "invite-1", "role": "viewer", "created_at": 110})
    request = await methods.accept_invite("invite-1", "viewer", accepted_at=120)
    await methods.approve_access_request("team-1", "alice", request["access_request_id"], client_ciphertext(b"viewer-key"), approved_at=130)

    updated = await methods.update_team(
        "team-1",
        "alice",
        {"encrypted_profile_image_metadata": client_ciphertext(b"generated-team-icon-green"), "updated_at": 140},
    )

    assert updated is not None
    assert updated["encrypted_profile_image_metadata"] == client_ciphertext(b"generated-team-icon-green")
    assert directus.updated[-1][2]["encrypted_profile_image_metadata"] == client_ciphertext(b"generated-team-icon-green")
    with pytest.raises(TeamPermissionError):
        await methods.update_team(
            "team-1",
            "viewer",
            {"encrypted_profile_image_metadata": client_ciphertext(b"viewer-change"), "updated_at": 150},
        )


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.profile-image.safe-parity,teams.lifecycle.encrypted-profiled
async def test_process_uploaded_team_profile_image_replaces_old_private_blob_metadata() -> None:
    directus = FakeDirectus()
    methods = TeamMethods(directus)
    await methods.create_team(
        "alice",
        team_payload(
            profile_image_s3_key="old-profile.enc",
            encrypted_profile_image_aes_key="vault:v1:old-key",
            profile_image_aes_nonce="old-nonce",
            profile_image_vault_key_id="vault-alice",
        ),
    )

    result = await methods.process_team_profile_image(
        team_id="team-1",
        actor_user_id="alice",
        encrypted_profile_image_metadata=client_ciphertext(b"uploaded-team-profile"),
        s3_key="new-profile.enc",
        encrypted_profile_image_aes_key="vault:v1:new-key",
        profile_image_aes_nonce="new-nonce",
        profile_image_vault_key_id="vault-alice",
        updated_at=160,
    )

    assert result["old_s3_key"] == "old-profile.enc"
    assert result["team"]["profile_image_s3_key"] == "new-profile.enc"
    assert result["team"]["encrypted_profile_image_metadata"] == client_ciphertext(b"uploaded-team-profile")
    assert result["team"]["profile_image_updated_at"] == 160


class FakeUploadFile:
    filename = "team-profile.jpg"
    content_type = "image/jpeg"

    async def read(self) -> bytes:
        return b"fake-jpeg-bytes"


class FakeMalwareScanner:
    async def scan(self, _file_bytes: bytes):
        return SimpleNamespace(is_clean=True, threat_name=None)


class FakeSightEngine:
    is_enabled = True

    async def check_content_safety(self, *_args, **_kwargs):
        return SimpleNamespace(is_safe=True, reason=None)


class FakeFileEncryption:
    def encrypt_bytes(self, file_bytes: bytes):
        return b"encrypted-" + file_bytes, "aes-key", "aes-nonce"


class FakeS3:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str]] = []

    async def upload_profile_image_private(self, *, s3_key: str, content: bytes, target_env: str = "prod") -> str:
        self.uploads.append((s3_key, content, target_env))
        return s3_key


class FakeAsyncClient:
    posted: list[dict[str, object]] = []

    def __init__(self, timeout: int) -> None:
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url: str, json: dict, headers: dict):
        self.posted.append({"url": url, "json": json, "headers": headers})
        if url.endswith("/internal/team-profile-image/authorize"):
            return SimpleNamespace(status_code=200, json=lambda: {"status": "ok"}, text="")
        return SimpleNamespace(status_code=200, json=lambda: {"status": "ok", "url": f"/v1/teams/{json['team_id']}/profile-image"}, text="")


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=teams.profile-image.safe-parity,teams.membership.role-gated
async def test_upload_team_profile_image_uses_private_profile_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAsyncClient.posted = []
    monkeypatch.setenv("DEV_CORE_API_URL", "https://api.dev.openmates.org")
    monkeypatch.setenv("DEV_INTERNAL_API_SHARED_TOKEN", "dev-token")
    monkeypatch.setattr(upload_route.httpx, "AsyncClient", FakeAsyncClient)
    state = SimpleNamespace(
        malware_scanner=FakeMalwareScanner(),
        sightengine=FakeSightEngine(),
        file_encryption=FakeFileEncryption(),
        s3=FakeS3(),
    )
    request = SimpleNamespace(headers={"X-Target-Env": "dev"}, app=SimpleNamespace(state=state))

    response = await upload_route.upload_team_profile_image(
        request=request,
        team_id="team-1",
        encrypted_profile_image_metadata=client_ciphertext(b"uploaded-team-profile"),
        file=FakeUploadFile(),
        user={"user_id": "alice"},
    )

    assert response.status == "ok"
    assert response.url == "/v1/teams/team-1/profile-image"
    assert state.s3.uploads[0][0].startswith("teams/team-1/")
    assert state.s3.uploads[0][1] == b"encrypted-fake-jpeg-bytes"
    assert state.s3.uploads[0][2] == "dev"
    assert FakeAsyncClient.posted[0]["url"] == "https://api.dev.openmates.org/internal/team-profile-image/authorize"
    assert FakeAsyncClient.posted[0]["json"] == {"user_id": "alice", "team_id": "team-1"}
    posted = FakeAsyncClient.posted[1]
    assert posted["url"] == "https://api.dev.openmates.org/internal/team-profile-image/process"
    assert posted["headers"] == {"X-Internal-Service-Token": "dev-token"}
    assert posted["json"]["user_id"] == "alice"
    assert posted["json"]["team_id"] == "team-1"
    assert posted["json"]["encrypted_profile_image_metadata"] == client_ciphertext(b"uploaded-team-profile")
