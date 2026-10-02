"""Security and retry invariants for ciphertext-only Apps result persistence."""

from __future__ import annotations

import base64
import importlib.util
import sys
import types
from uuid import uuid4

import pytest
from pydantic import ValidationError
from fastapi import HTTPException

if importlib.util.find_spec("slowapi") is None:
    # The lightweight local unit environment omits the API rate-limit package.
    limiter_module = types.ModuleType("backend.core.api.app.services.limiter")
    limiter_module.limiter = types.SimpleNamespace(limit=lambda *_args, **_kwargs: lambda fn: fn)
    sys.modules[limiter_module.__name__] = limiter_module
    util_module = types.ModuleType("slowapi.util")
    util_module.get_remote_address = lambda _request: "test"
    sys.modules["slowapi.util"] = util_module

from backend.core.api.app.routes.apps_workspace import LegacyIndexBatch, SaveAppsResult, index_legacy_embed_batch, save_result
from backend.core.api.app.models.user import User
from backend.core.api.app.services.apps_workspace_results_service import AppsResultConflict, AppsWorkspaceResultsService
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id


def cipher(data: bytes = b"ciphertext") -> str:
    return base64.b64encode(b"\x01" * 12 + data + b"\x02" * 16).decode()


def payload(root_id: str, child_id: str | None = None, *, team_id: str | None = None, status: str = "finished") -> dict:
    return {
        "app_id": "events", "skill_id": "search", "team_id": team_id,
        "root_embed_id": root_id, "encrypted_embed_key": cipher(b"\x03" * 32),
        "expected_user_id": "00000000-0000-4000-8000-000000000001",
        "embeds": [
            {"embed_id": root_id, "encrypted_type": cipher(), "encrypted_content": cipher(),
             "status": status, "embed_ids": [child_id] if child_id else []},
            *([{"embed_id": child_id, "encrypted_type": cipher(), "encrypted_content": cipher(),
                "status": "finished", "parent_embed_id": root_id}] if child_id else []),
        ],
    }


class FakeTeam:
    def __init__(self):
        self.roles = []

    async def require_team_role(self, team_id, user_id, roles):
        self.roles.append(roles)
        if user_id == "outsider" or (user_id == "viewer" and "viewer" not in roles):
            raise TeamPermissionError("denied")


class FakeDirectus:
    def __init__(self):
        self.team = FakeTeam()
        self.embeds = {}
        self.keys = []
        self.reads = []
        self.creates = []
        self.chats = {}

    async def get_items(self, collection, params=None, **_kwargs):
        self.reads.append((collection, params))
        if collection == "chats":
            chat = self.chats.get(params["filter[id][_eq]"])
            return [chat] if chat else []
        if collection == "embed_keys":
            return [key for key in self.keys if key["hashed_embed_id"] == params["filter[hashed_embed_id][_eq]"]]
        if "filter[embed_id][_eq]" in params:
            row = self.embeds.get(params["filter[embed_id][_eq]"])
            return [row] if row else []
        if "filter[embed_id][_in]" in params:
            return [self.embeds[id] for id in params["filter[embed_id][_in]"].split(",") if id in self.embeds]
        rows = [row for row in self.embeds.values() if row.get("app_id") == params.get("filter[app_id][_eq]") and row.get("workspace_origin") in {"web_apps", "chat"}]
        team_hash = params.get("filter[hashed_team_id][_eq]")
        rows = [row for row in rows if row.get("hashed_team_id") == team_hash]
        if "filter[hashed_user_id][_eq]" in params:
            rows = [row for row in rows if row["hashed_user_id"] == params["filter[hashed_user_id][_eq]"]]
        if params.get("filter[parent_embed_id][_null]"):
            rows = [row for row in rows if not row.get("parent_embed_id")]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return rows[params["offset"]:params["offset"] + params["limit"]]

    async def create_item(self, collection, data, **_kwargs):
        self.creates.append((collection, data))
        if collection == "embed_keys":
            self.keys.append(data)
        else:
            self.embeds[data["embed_id"]] = {"id": str(uuid4()), **data}
        return True, data

    async def update_item(self, collection, internal_id, data, **_kwargs):
        row = next(row for row in self.embeds.values() if row["id"] == internal_id)
        row.update(data)
        return row


# contract-test: direct surface=rest_api assertions=apps.results.web-retained-graph
def test_rejects_plaintext_and_broken_graph_before_storage():
    root_id, child_id = str(uuid4()), str(uuid4())
    bad = payload(root_id, child_id)
    bad["embeds"][1]["encrypted_content"] = "private appointment details"
    with pytest.raises(ValidationError):
        SaveAppsResult.model_validate(bad)
    broken = payload(root_id, child_id)
    broken["embeds"][0]["embed_ids"] = []
    with pytest.raises(ValidationError):
        SaveAppsResult.model_validate(broken)
    bad_extra = payload(root_id)
    bad_extra["input"] = {"query": "private"}
    with pytest.raises(ValidationError):
        SaveAppsResult.model_validate(bad_extra)


# contract-test: direct surface=rest_api assertions=apps.results.web-retained-graph,apps.anonymous.local-results-and-promotion
@pytest.mark.asyncio
async def test_save_is_idempotent_and_updates_same_processing_root():
    db = FakeDirectus()
    service = AppsWorkspaceResultsService(db)
    root_id, child_id = str(uuid4()), str(uuid4())
    processing = payload(root_id, status="processing")
    await service.save("owner", processing)
    completed = payload(root_id, child_id)
    await service.save("owner", completed)
    await service.save("owner", completed)
    assert len([row for row in db.creates if row[0] == "embeds"]) == 2
    assert len([row for row in db.creates if row[0] == "embed_keys"]) == 1
    assert db.embeds[root_id]["status"] == "finished"
    assert db.embeds[root_id]["embed_ids"] == [child_id]
    detail = await service.detail("owner", root_id, None)
    assert [row["embed_id"] for row in detail["children"]] == [child_id]


# contract-test: direct surface=rest_api assertions=apps.library.embeds-account-paginated
@pytest.mark.asyncio
async def test_personal_and_team_catalog_are_separate_and_team_viewer_cannot_write():
    db = FakeDirectus()
    service = AppsWorkspaceResultsService(db)
    personal = str(uuid4())
    team = str(uuid4())
    team_id = str(uuid4())
    await service.save("owner", payload(personal))
    await service.save("owner", payload(team, team_id=team_id))
    personal_page = await service.list("owner", "events", None, 0, 1)
    team_page = await service.list("viewer", "events", team_id, 0, 1)
    assert [row["embed_id"] for row in personal_page["items"]] == [personal]
    assert [row["embed_id"] for row in team_page["items"]] == [team]
    assert await service.detail("outsider", personal, None) is None
    with pytest.raises(TeamPermissionError):
        await service.save("viewer", payload(str(uuid4()), team_id=team_id))
    with pytest.raises(AppsResultConflict):
        await service.save("outsider", payload(personal))
    assert await service.detail("owner", team, None) is None
    with pytest.raises(AppsResultConflict):
        await service.save("owner", payload(team))
    assert db.embeds[team]["hashed_team_id"] == hash_id(team_id)


# contract-test: direct surface=rest_api assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
@pytest.mark.asyncio
async def test_large_graph_and_existing_generated_asset_keep_one_root_and_original_asset_row():
    db = FakeDirectus()
    service = AppsWorkspaceResultsService(db)
    root_id = str(uuid4())
    child_ids = [str(uuid4()) for _ in range(25)]
    graph = payload(root_id)
    graph["embeds"][0]["embed_ids"] = child_ids
    graph["embeds"].extend({"embed_id": child_id, "encrypted_type": cipher(), "encrypted_content": cipher(),
                            "status": "finished", "parent_embed_id": root_id} for child_id in child_ids)
    SaveAppsResult.model_validate(graph)
    original = {"id": str(uuid4()), "embed_id": child_ids[0], "hashed_user_id": hash_id("owner"),
                "hashed_team_id": None, "encrypted_content": cipher(b"original-asset"),
                "created_at": 1}
    db.embeds[child_ids[0]] = original.copy()
    result = await service.save("owner", graph)
    assert result["linked_embed_ids"] == [child_ids[0]]
    assert db.embeds[child_ids[0]] == original
    assert len(db.embeds) == 26
    detail = await service.detail("owner", root_id, None)
    assert len(detail["children"]) == 24
    assert [row["embed_id"] for row in detail["linked"]] == [child_ids[0]]


# contract-test: direct surface=rest_api assertions=apps.results.web-retained-graph
@pytest.mark.asyncio
async def test_changed_key_wrapper_cannot_overwrite_existing_result_ciphertext():
    db = FakeDirectus()
    service = AppsWorkspaceResultsService(db)
    root_id = str(uuid4())
    first = payload(root_id, status="processing")
    await service.save("owner", first)
    updated = payload(root_id, status="finished")
    updated["encrypted_embed_key"] = cipher(b"another-key" * 4)
    with pytest.raises(AppsResultConflict, match="wrapper changed"):
        await service.save("owner", updated)
    assert db.embeds[root_id]["status"] == "processing"


# contract-test: direct surface=rest_api assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
@pytest.mark.asyncio
async def test_second_team_member_cannot_poison_existing_root_or_its_team_wrapper():
    db = FakeDirectus()
    service = AppsWorkspaceResultsService(db)
    root_id = str(uuid4())
    team_id = str(uuid4())
    await service.save("owner", payload(root_id, team_id=team_id))
    original_key_count = len(db.keys)
    original_ciphertext = db.embeds[root_id]["encrypted_content"]
    with pytest.raises(TeamPermissionError):
        await service.save("viewer", payload(root_id, team_id=team_id))
    # A second member with write role is still not the request creator.
    with pytest.raises(AppsResultConflict):
        await service.save("other-member", payload(root_id, team_id=team_id))
    assert len(db.keys) == original_key_count
    assert db.embeds[root_id]["encrypted_content"] == original_ciphertext
    detail = await service.detail("viewer", root_id, team_id)
    assert detail["key"]["hashed_user_id"] == hash_id("owner")


# contract-test: direct surface=rest_api assertions=apps.anonymous.local-results-and-promotion,apps.results.web-retained-graph
@pytest.mark.asyncio
async def test_account_switch_rejected_before_any_ciphertext_or_key_write():
    db = FakeDirectus()
    user = User(id="00000000-0000-4000-8000-000000000002", username="other", vault_key_id="vault")
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(directus_service=db)))
    body = SaveAppsResult.model_validate(payload(str(uuid4())))
    with pytest.raises(HTTPException) as error:
        await save_result(body, request, user)
    assert error.value.status_code == 409
    assert db.creates == []


# contract-test: direct surface=rest_api assertions=apps.library.embeds-account-paginated
@pytest.mark.asyncio
async def test_legacy_personal_batch_indexes_verified_chat_roots_only():
    db = FakeDirectus()
    service = AppsWorkspaceResultsService(db)
    chat_id, root_id, child_id = str(uuid4()), str(uuid4()), str(uuid4())
    owner_hash = hash_id("owner")
    db.chats[chat_id] = {"id": chat_id, "hashed_user_id": owner_hash, "hashed_team_id": None}
    db.embeds[root_id] = {"id": str(uuid4()), "embed_id": root_id, "hashed_user_id": owner_hash,
                          "hashed_chat_id": hash_id(chat_id), "parent_embed_id": None, "app_id": None,
                          "skill_id": None, "workspace_origin": None, "hashed_team_id": None,
                          "created_at": 1, "status": "finished", "embed_ids": [child_id]}
    db.embeds[child_id] = {"id": str(uuid4()), "embed_id": child_id, "hashed_user_id": owner_hash,
                           "hashed_chat_id": hash_id(chat_id), "parent_embed_id": root_id,
                           "app_id": None, "workspace_origin": None, "hashed_team_id": None}
    item = {"embed_id": root_id, "chat_id": chat_id, "app_id": "audio", "skill_id": "generate"}
    assert await service.index_legacy_batch("owner", None, [item]) == {"indexed": 1, "received": 1}
    assert db.embeds[root_id]["root_embed_id"] == root_id
    assert db.embeds[root_id]["workspace_origin"] == "chat"
    assert db.embeds[child_id]["app_id"] is None
    assert [row["embed_id"] for row in (await service.list("owner", "audio", None, 0, 20))["items"]] == [root_id]
    assert (await service.detail("owner", root_id, None))["key"] is None  # legacy chat wrapper only
    assert (await service.index_legacy_batch("owner", None, [{**item, "embed_id": child_id}]))["indexed"] == 0
    linked_id = str(uuid4())
    db.embeds[linked_id] = {"id": str(uuid4()), "embed_id": linked_id, "hashed_user_id": owner_hash,
                            "hashed_chat_id": hash_id(chat_id), "parent_embed_id": None,
                            "root_embed_id": root_id, "workspace_origin": None, "hashed_team_id": None}
    assert (await service.index_legacy_batch("owner", None, [{**item, "embed_id": linked_id}]))["indexed"] == 0


# contract-test: direct surface=rest_api assertions=apps.library.embeds-account-paginated
@pytest.mark.asyncio
async def test_legacy_team_batch_derives_scope_and_rejects_forged_chat_or_account():
    db = FakeDirectus()
    service = AppsWorkspaceResultsService(db)
    chat_id, other_chat, root_id, team_id, child_id = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    team_hash = hash_id(team_id)
    db.chats[chat_id] = {"id": chat_id, "hashed_user_id": hash_id("creator"), "hashed_team_id": team_hash}
    db.chats[other_chat] = {"id": other_chat, "hashed_user_id": hash_id("owner"), "hashed_team_id": None}
    db.embeds[root_id] = {"id": str(uuid4()), "embed_id": root_id, "hashed_user_id": hash_id("creator"),
                          "hashed_chat_id": hash_id(chat_id), "parent_embed_id": None, "app_id": None,
                          "skill_id": None, "workspace_origin": None, "hashed_team_id": None,
                          "created_at": 1, "status": "finished", "embed_ids": [child_id]}
    db.embeds[child_id] = {"id": str(uuid4()), "embed_id": child_id, "hashed_user_id": hash_id("creator"),
                           "hashed_chat_id": hash_id(chat_id), "parent_embed_id": root_id,
                           "app_id": None, "workspace_origin": None, "hashed_team_id": None}
    item = {"embed_id": root_id, "chat_id": chat_id, "app_id": "audio", "skill_id": "generate"}
    assert (await service.index_legacy_batch("owner", None, [item]))["indexed"] == 0
    assert (await service.index_legacy_batch("owner", team_id, [{**item, "chat_id": other_chat}]))["indexed"] == 0
    with pytest.raises(TeamPermissionError):
        await service.index_legacy_batch("outsider", team_id, [item])
    assert (await service.index_legacy_batch("viewer", team_id, [item]))["indexed"] == 0
    assert db.embeds[root_id]["hashed_team_id"] is None
    assert (await service.index_legacy_batch("other-member", team_id, [item]))["indexed"] == 1
    assert db.embeds[root_id]["hashed_team_id"] == team_hash
    assert db.embeds[child_id]["hashed_team_id"] == team_hash
    assert (await service.index_legacy_batch("viewer", team_id, [item]))["indexed"] == 1
    assert [child["embed_id"] for child in (await service.detail("viewer", root_id, team_id))["children"]] == [child_id]
    assert (await service.list("viewer", "audio", team_id, 0, 20))["items"][0]["embed_id"] == root_id
    assert (await service.list("creator", "audio", None, 0, 20))["items"] == []
    with pytest.raises(ValidationError):
        LegacyIndexBatch.model_validate({"expected_user_id": str(uuid4()), "team_id": team_id,
                                          "items": [item] * 51})


# contract-test: direct surface=rest_api assertions=apps.library.embeds-account-paginated
@pytest.mark.asyncio
async def test_legacy_batch_rejects_switched_session_before_indexing():
    db = FakeDirectus()
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(directus_service=db)))
    body = LegacyIndexBatch.model_validate({"expected_user_id": "00000000-0000-4000-8000-000000000001",
        "items": [{"embed_id": str(uuid4()), "chat_id": str(uuid4()), "app_id": "audio", "skill_id": "generate"}]})
    user = User(id="00000000-0000-4000-8000-000000000002", username="other", vault_key_id="vault")
    with pytest.raises(HTTPException) as error:
        await index_legacy_embed_batch(body, request, user)
    assert error.value.status_code == 409
    assert db.reads == []


# contract-test: direct surface=rest_api assertions=apps.library.embeds-account-paginated
@pytest.mark.asyncio
async def test_viewer_cannot_promote_forged_personal_root_or_unverified_child_into_team():
    db = FakeDirectus()
    service = AppsWorkspaceResultsService(db)
    chat_id, team_id, forged_id, root_id, child_id = (str(uuid4()) for _ in range(5))
    team_hash = hash_id(team_id)
    db.chats[chat_id] = {"id": chat_id, "hashed_user_id": hash_id("creator"), "hashed_team_id": team_hash}
    db.embeds[forged_id] = {"id": str(uuid4()), "embed_id": forged_id,
        "hashed_user_id": hash_id("viewer"), "hashed_chat_id": hash_id(chat_id),
        "hashed_team_id": None, "parent_embed_id": None, "workspace_origin": None,
        "app_id": None, "skill_id": None, "embed_ids": []}
    forged_item = {"embed_id": forged_id, "chat_id": chat_id, "app_id": "audio", "skill_id": "generate"}
    assert (await service.index_legacy_batch("viewer", team_id, [forged_item]))["indexed"] == 0
    assert (await service.index_legacy_batch("other-member", team_id, [forged_item]))["indexed"] == 0
    assert db.embeds[forged_id]["hashed_team_id"] is None
    db.embeds[root_id] = {"id": str(uuid4()), "embed_id": root_id,
        "hashed_user_id": hash_id("creator"), "hashed_chat_id": hash_id(chat_id),
        "hashed_team_id": None, "parent_embed_id": None, "workspace_origin": None,
        "app_id": None, "skill_id": None, "embed_ids": [child_id]}
    db.embeds[child_id] = {"id": str(uuid4()), "embed_id": child_id,
        "hashed_user_id": hash_id("viewer"), "hashed_chat_id": hash_id(chat_id),
        "hashed_team_id": None, "parent_embed_id": root_id, "workspace_origin": None,
        "app_id": None, "skill_id": None}
    item = {**forged_item, "embed_id": root_id}
    assert (await service.index_legacy_batch("other-member", team_id, [item]))["indexed"] == 0
    assert db.embeds[root_id]["hashed_team_id"] is None
    assert db.embeds[child_id]["hashed_team_id"] is None


# contract-test: direct surface=rest_api assertions=apps.library.embeds-account-paginated
@pytest.mark.asyncio
async def test_library_excludes_indexed_children_and_refuses_to_promote_them():
    db = FakeDirectus()
    service = AppsWorkspaceResultsService(db)
    root_id, child_id = str(uuid4()), str(uuid4())
    await service.save("owner", payload(root_id, child_id))
    # Simulate old rows incorrectly classified as independent library entries.
    db.embeds[child_id].update(workspace_origin="chat", root_embed_id=child_id, hashed_chat_id="chat-hash")
    page = await service.list("owner", "events", None, 0, 20)
    assert [row["embed_id"] for row in page["items"]] == [root_id]
    assert await service.detail("owner", child_id, None) is None
    # If parent metadata was lost, the existing root relationship still rules it out.
    db.embeds[child_id].update(parent_embed_id=None, root_embed_id=root_id)
    with pytest.raises(AppsResultConflict, match="Only parent"):
        await service.index_existing("owner", child_id, "events", None)
    page = await service.list("owner", "events", None, 0, 20)
    assert [row["embed_id"] for row in page["items"]] == [root_id]
    assert len((await service.detail("owner", root_id, None))["children"]) == 1
