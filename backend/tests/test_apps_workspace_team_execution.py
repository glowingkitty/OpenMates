"""Team context must be authorized and charged to the selected Team ledger."""

from __future__ import annotations

import hashlib
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

# Reuse the established lightweight Apps route imports and dependency stubs.
from backend.tests import test_apps_api as infra
from backend.tests import test_generated_model_streaming_storage as generated_asset_infra  # noqa: F401

from backend.core.api.app.routes import apps_api
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.shared.python_utils.team_skill_billing import skill_billing_request
from backend.tests.test_teams_lifecycle import FakeDirectus


def _app() -> infra.AppYAML:
    return infra.AppYAML.model_validate({
        "id": "team_execution_contract",
        "name_translation_key": "apps.team_execution_contract",
        "description_translation_key": "apps.team_execution_contract.description",
        "skills": [{
            "id": "search",
            "name_translation_key": "app_skills.team_execution_contract.search",
            "description_translation_key": "app_skills.team_execution_contract.search.description",
            "tool_schema": {
                "type": "object",
                "properties": {"requests": {
                    "type": "array", "items": {"type": "object", "properties": {
                        "query": {"type": "string"},
                    }, "required": ["query"]},
                }},
                "required": ["requests"],
            },
        }],
    })


# contract-test: supporting surface=rest_api assertions=apps.execution.direct-shared-contract
def test_team_query_authorizes_member_and_bills_team_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    charges: list[dict] = []

    async def require_team_role(team_id, user_id, roles):
        calls.append({"team_id": team_id, "user_id": user_id, "roles": roles})
        if team_id in {"forbidden-team", "viewer-team"} or "member" not in roles:
            raise TeamPermissionError("Team permission denied")
        return {"role": "member"}

    async def skill(**kwargs):
        calls.append(kwargs)
        return {"results": [{"results": [{"title": "found"}]}]}

    async def credits(**_kwargs):
        return 5

    async def charge(**kwargs):
        charges.append(kwargs)

    directus = FakeDirectus()
    directus.team = SimpleNamespace(require_team_role=require_team_role)
    for team_id, balance in (("team-1", 100), ("empty-team", 0), ("held-team", 100)):
        directus.rows["team_credit_accounts"].append({
            "id": team_id, "hashed_team_id": hash_id(team_id), "balance_credits": balance,
        })
    directus.rows["billing_reservations"].append({
        "subject_kind": "team", "subject_hash": hash_id("held-team"),
        "state": "reserved", "quoted_credits": 100,
    })
    app = FastAPI()
    app.state.config_manager = SimpleNamespace(get_provider_config=lambda *_: None)
    user_info = {"user_id": "user-1", "api_key_hash": None}
    app.dependency_overrides[apps_api.get_session_or_api_key_info] = lambda: user_info
    app.dependency_overrides[apps_api.get_cache_service] = lambda: object()
    app.dependency_overrides[apps_api.get_directus_service] = lambda: directus
    monkeypatch.setattr(apps_api, "call_app_skill", skill)
    monkeypatch.setattr(apps_api, "calculate_skill_credits", credits)
    monkeypatch.setattr(apps_api, "charge_credits_via_internal_api", charge)
    apps_api.register_app_and_skill_routes(app, {"team_execution_contract": _app()})
    client = TestClient(app)
    path = "/v1/apps/team_execution_contract/skills/search"

    response = client.post(path + "?team_id=team-1", json={"requests": [{"query": "x"}]})
    assert response.status_code == 200, response.text
    assert calls[0]["roles"] == {"owner", "admin", "member"}
    assert calls[2]["user_info"]["team_id"] == "team-1"
    assert charges[0]["team_id"] == "team-1"

    calls.clear()
    charges.clear()
    forbidden = client.post(path + "?team_id=forbidden-team", json={"requests": [{"query": "x"}]})
    assert forbidden.status_code == 403
    assert len(calls) == 1 and charges == []

    calls.clear()
    held = client.post(path + "?team_id=held-team", json={"requests": [{"query": "x"}]})
    assert held.status_code == 402
    assert len(calls) == 2 and charges == []

    calls.clear()
    empty = client.post(path + "?team_id=empty-team", json={"requests": [{"query": "x"}]})
    assert empty.status_code == 402
    assert len(calls) == 2 and charges == []

    calls.clear()
    viewer = client.post(path + "?team_id=viewer-team", json={"requests": [{"query": "x"}]})
    assert viewer.status_code == 403
    assert len(calls) == 1 and charges == []

    calls.clear()
    user_info["api_key_hash"] = "developer-key"
    developer = client.post(path + "?team_id=team-1", json={"requests": [{"query": "x"}]})
    assert developer.status_code == 403
    assert calls == [] and charges == []
    user_info["api_key_hash"] = None

    personal = client.post(path, json={"requests": [{"query": "x"}]})
    assert personal.status_code == 200
    assert "team_id" not in calls[0]["user_info"]
    assert "team_id" not in charges[0]


# contract-test: supporting surface=rest_api assertions=apps.execution.direct-shared-contract
def test_worker_billing_request_never_carries_personal_account_fields() -> None:
    personal = {
        "user_id": "user-1", "user_id_hash": "hash", "credits": 7,
        "app_id": "images", "skill_id": "generate", "api_key_hash": "key",
        "usage_details": {"units_processed": 1},
    }
    path, payload = skill_billing_request(personal, "team-1", event_id="embed-1")
    assert path == "/internal/billing/team/charge"
    assert payload == {
        "team_id": "team-1", "actor_user_id": "user-1", "credits": 7,
        "app_id": "images", "skill_id": "generate",
        "idempotency_key": "app-skill:embed-1",
        "usage_details": {"units_processed": 1, "workspace_type": "apps"},
    }
    assert skill_billing_request(personal, None, event_id="embed-1") == (
        "/internal/billing/charge", personal
    )


# contract-test: supporting surface=rest_api assertions=apps.execution.direct-shared-contract
@pytest.mark.anyio
async def test_skill_body_cannot_choose_team_without_authorized_query(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatched: list[dict] = []

    class Registry:
        async def dispatch_skill(self, _app_id, _skill_id, payload):
            dispatched.append(payload)
            return {"results": []}

        def get_metadata(self, _app_id):
            return None

    async def safe_output(result, _context):
        return result

    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.skill_registry",
        SimpleNamespace(get_global_registry=lambda: Registry()),
    )
    monkeypatch.setattr(apps_api, "sanitize_app_skill_output", safe_output)
    body = {
        "requests": [{"query": "x"}], "team_id": "forged-team",
        "_team_id": "forged-team", "team_id_hash": "forged-hash",
        "team_workspace_type": "forged-workspace",
    }
    await apps_api.call_app_skill(
        "weather", "search", body, {}, {"user_id": "user-1"},
        enforce_rest_exposure_policy=False,
    )
    assert all(key not in dispatched[0] for key in (
        "team_id", "_team_id", "team_id_hash", "team_workspace_type",
    ))
    await apps_api.call_app_skill(
        "weather", "search", body, {}, {"user_id": "user-1", "team_id": "authorized-team"},
        enforce_rest_exposure_policy=False,
    )
    assert dispatched[1]["team_id"] == dispatched[1]["_team_id"] == "authorized-team"


# contract-test: supporting surface=rest_api assertions=apps.execution.direct-shared-contract
@pytest.mark.anyio
async def test_team_rest_charge_uses_team_endpoint_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[str, dict]] = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, json, headers):
            posted.append((url, json))
            request = httpx.Request("POST", url)
            return httpx.Response(402, request=request, json={"detail": "INSUFFICIENT_TEAM_CREDITS"})

    monkeypatch.setattr(apps_api.httpx, "AsyncClient", Client)
    with pytest.raises(apps_api.HTTPException) as exc:
        await apps_api.charge_credits_via_internal_api(
            user_id="user-1", user_id_hash="hash", credits=5,
            app_id="weather", skill_id="forecast", team_id="team-1",
        )
    assert exc.value.status_code == 402
    assert posted[0][0].endswith("/internal/billing/team/charge")
    assert posted[0][1]["actor_user_id"] == "user-1"
    assert "user_id_hash" not in posted[0][1]


# contract-test: supporting surface=rest_api assertions=apps.execution.direct-shared-contract
@pytest.mark.anyio
async def test_async_audio_charge_uses_team_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery")
    from backend.apps.audio.tasks import common as audio_common

    posted: list[tuple[str, dict]] = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, json, headers):
            posted.append((url, json))
            return httpx.Response(200, request=httpx.Request("POST", url), json={"status": "success"})

    monkeypatch.setattr(audio_common.httpx, "AsyncClient", Client)
    await audio_common.charge_audio_generation_credits(
        user_id="user-1", app_id="audio", skill_id="speak",
        task_id="task-1", request_id="request-1", credits=9,
        model_ref="elevenlabs/flash", duration_seconds=2.0,
        chat_id=None, message_id=None, external_request=True,
        api_key_hash=None, device_hash=None, api_key_name=None,
        log_prefix="[test]", team_id="team-1",
    )
    assert posted[0][0].endswith("/internal/billing/team/charge")
    assert posted[0][1]["team_id"] == "team-1"
    assert posted[0][1]["idempotency_key"] == "app-skill:audio:task-1:request-1"
    assert "user_id_hash" not in posted[0][1]


# contract-test: supporting surface=rest_api assertions=apps.library.embeds-account-paginated
@pytest.mark.anyio
async def test_team_member_refreshes_original_owners_asset_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.api.app.routes import generated_assets_api

    chat_hash = hashlib.sha256(b"chat-1").hexdigest()
    team_hash = hashlib.sha256(b"team-1").hexdigest()

    async def get_items(collection, **_kwargs):
        assert collection == "upload_files"
        return [{"user_id": "user-1", "files_metadata": {"original": {"s3_key": "private"}}}]

    async def get_embed(_asset_id):
        return {
            "embed_id": "asset-1",
            "hashed_user_id": hashlib.sha256(b"user-1").hexdigest(),
            "hashed_team_id": team_hash,
            "hashed_chat_id": chat_hash,
        }

    async def resolve_chat(_self, operation, data):
        assert operation == "resolve_chat_hashes" and data == {"hashes": [chat_hash]}
        return {"chats": [{"hashed_chat_id": chat_hash,
                           "hashed_team_id": team_hash, "storage_state": "hot"}]}

    async def require_team_role(team_id, user_id, allowed_roles):
        assert (team_id, user_id) == ("team-1", "user-2")
        assert "viewer" in allowed_roles
        return {"role": "viewer"}

    directus = SimpleNamespace(
        get_items=get_items,
        embed=SimpleNamespace(get_embed_by_id=get_embed),
        team=SimpleNamespace(require_team_role=require_team_role),
    )
    request = Request({
        "type": "http", "method": "GET", "path": "/", "headers": [],
        "scheme": "https", "server": ("api.dev.openmates.org", 443),
    })
    monkeypatch.setattr(generated_assets_api, "create_download_token", lambda **kwargs: f"owner:{kwargs['user_id']}")
    monkeypatch.setattr(generated_assets_api.ChatMessageArchiveService, "transaction", resolve_chat)
    response = await generated_assets_api.refresh_generated_asset_download_url(
        "asset-1", "original", request, team_id="team-1",
        current_user=SimpleNamespace(id="user-2"), directus_service=directus,
    )
    assert response["download_url"].endswith("/v1/generated-assets/asset-1/files/original/download?token=owner:user-1")
    assert set(response) == {"download_url", "download_expires_at"}

    with pytest.raises(apps_api.HTTPException) as exc:
        await generated_assets_api.refresh_generated_asset_download_url(
            "asset-1", "original", request, team_id=None,
            current_user=SimpleNamespace(id="user-2"), directus_service=directus,
        )
    assert exc.value.status_code == 404


# contract-test: direct surface=rest_api assertions=apps.library.embeds-account-paginated,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_team_asset_url_rejects_revoked_or_unreferenced_media(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.api.app.routes import generated_assets_api

    team_hash = hashlib.sha256(b"team-1").hexdigest()
    chat_hash = hashlib.sha256(b"chat-1").hexdigest()
    owner_hash = hashlib.sha256(b"user-1").hexdigest()
    embed = {"embed_id": "asset-1", "hashed_user_id": owner_hash,
             "hashed_team_id": team_hash, "hashed_chat_id": chat_hash}
    chat = {"hashed_chat_id": chat_hash, "hashed_team_id": team_hash,
            "storage_state": "hot"}
    member = {"active": True}

    async def get_items(collection, **_kwargs):
        assert collection == "upload_files"
        return [{"user_id": "user-1", "files_metadata": {"original": {"s3_key": "private"}}}]

    async def get_embed(_asset_id):
        return embed

    async def require_team_role(_team_id, _user_id, _roles):
        if not member["active"]:
            raise TeamPermissionError("removed")
        return {"role": "viewer"}

    async def resolve_chat(_self, _operation, _data):
        return {"chats": [chat] if chat else []}

    directus = SimpleNamespace(get_items=get_items,
        embed=SimpleNamespace(get_embed_by_id=get_embed),
        team=SimpleNamespace(require_team_role=require_team_role))
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [],
                       "scheme": "https", "server": ("api.dev.openmates.org", 443)})
    monkeypatch.setattr(generated_assets_api.ChatMessageArchiveService, "transaction", resolve_chat)
    monkeypatch.setattr(generated_assets_api, "create_download_token", lambda **_kwargs: "signed")

    async def mint():
        return await generated_assets_api.refresh_generated_asset_download_url(
            "asset-1", "original", request, team_id="team-1",
            current_user=SimpleNamespace(id="user-2"), directus_service=directus)

    assert "token=signed" in (await mint())["download_url"]
    member["active"] = False
    with pytest.raises(generated_assets_api.HTTPException) as revoked:
        await mint()
    assert revoked.value.status_code == 403
    member["active"] = True
    for invalid_chat in ({"hashed_chat_id": chat_hash,
                          "hashed_team_id": hashlib.sha256(b"other-team").hexdigest(),
                          "storage_state": "hot"},
                         {"hashed_chat_id": chat_hash, "hashed_team_id": team_hash,
                          "storage_state": "deleting"}, {}):
        chat.clear()
        chat.update(invalid_chat)
        with pytest.raises(generated_assets_api.HTTPException) as denied:
            await mint()
        assert denied.value.status_code == 404


# contract-test: direct surface=rest_api assertions=apps.library.embeds-account-paginated,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_team_apps_asset_url_requires_saved_root_reference() -> None:
    from backend.core.api.app.routes.generated_assets_api import _require_live_team_asset_reference

    team_hash = hashlib.sha256(b"team-1").hexdigest()
    owner_hash = hashlib.sha256(b"user-1").hexdigest()
    root = {"embed_id": "root-1", "workspace_origin": "web_apps",
            "hashed_team_id": team_hash, "hashed_user_id": owner_hash,
            "root_embed_id": "root-1", "parent_embed_id": None,
            "embed_ids": ["asset-1"]}
    child = {"root_embed_id": "root-1", "parent_embed_id": "root-1"}

    async def get_embed(_embed_id):
        return root

    directus = SimpleNamespace(embed=SimpleNamespace(get_embed_by_id=get_embed))
    await _require_live_team_asset_reference("asset-1", child, team_hash, owner_hash, directus)
    root["embed_ids"] = []
    with pytest.raises(apps_api.HTTPException) as unreferenced:
        await _require_live_team_asset_reference("asset-1", child, team_hash, owner_hash, directus)
    assert unreferenced.value.status_code == 404
