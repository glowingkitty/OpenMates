"""Project embed adoption, rename/delete, diff guard and server-owned fields (P11).

The atomic operations themselves (link uniqueness, path collisions, receipts,
the write fence) run in the embed-version-transaction extension and are
exercised against an in-memory database in
`backend/core/directus/extensions/embed-version-transaction/test/project-items.test.js`.
These tests cover the first-party API surface: authorization before the
extension is called, the exact request forwarded to it, stable error codes,
the chat diff guard, the assistant tool job contract and the server-owned
field allow-list.
"""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes.project_item_links import (  # noqa: E402 - stubs precede route imports.
    AdoptEmbedRequest,
    DeleteItemRequest,
    RenameItemRequest,
    adopt_project_embed,
    delete_project_item_link,
    rename_project_item,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError  # noqa: E402
from backend.core.api.app.services.project_embed_server_fields import (  # noqa: E402
    ServerOwnedFieldError,
    assert_server_owned_change,
    clear_server_owned_refresh,
    find_server_owned_refresh,
    grant_server_owned_refresh,
)

USER = SimpleNamespace(id="user-1")
ITEM_ID = "11111111-1111-5111-8111-111111111111"
NEW_ITEM_ID = "33333333-3333-5333-8333-333333333333"
APP_ITEM_ID = "44444444-4444-4444-8444-444444444444"


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def make_request(method: str = "POST") -> Request:
    return Request({
        "type": "http", "method": method, "path": "/v1/projects/p/items", "headers": [],
        "client": ("testclient", 50000), "server": ("testserver", 80),
        "app": SimpleNamespace(state=SimpleNamespace(cache_service=SimpleNamespace(get=AsyncMock(return_value=None)))),
    })


class FakeResponse:
    def __init__(self, status_code: int, data: dict) -> None:
        self.status_code = status_code
        self._data = data

    def json(self) -> dict:
        return self._data


class FakeExtension:
    """Records internal calls and answers like the extension would."""

    def __init__(self, responses=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.responses = list(responses or [])

    async def __call__(self, method: str, url: str, *, headers: dict, json: dict) -> FakeResponse:
        assert method == "POST" and headers["X-Internal-Service-Token"] == "internal-token"
        action = url.rsplit("/", 1)[-1]
        self.calls.append((action, json))
        if self.responses:
            return self.responses.pop(0)
        status = {"adopt": "adopted", "rename": "renamed", "delete": "deleted"}[action]
        return FakeResponse(200, {"data": {"status": status, "operation_id": json["operation_id"], "idempotent": False}})


def make_directus(*, extension=None, role="member", project=True, item=None, team_denied=False):
    team = SimpleNamespace(require_team_role=AsyncMock(
        side_effect=TeamPermissionError("no") if team_denied else None, return_value={"role": role}))
    return SimpleNamespace(
        base_url="http://directus.internal",
        _make_api_request=extension or FakeExtension(),
        team=team,
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project-row"} if project else None),
            get_item=AsyncMock(return_value=item),
        ),
    )


@pytest.fixture(autouse=True)
def internal_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")


def adopt_body(**extra) -> AdoptEmbedRequest:
    fields = dict(
        operation_id="op-adopt", chat_id="chat-1", embed_id="embed-1", project_item_id=ITEM_ID, kind="file",
        target_id_encrypted="cipher-target", encrypted_display_name="cipher-name",
        encrypted_metadata="cipher-meta", project_key_wrapper="cipher-wrapper",
    )
    fields.update(extra)
    return AdoptEmbedRequest(**fields)


# contract-test: supporting surface=rest_api assertions=projects.files.adopt-embed
@pytest.mark.anyio
@pytest.mark.parametrize("kind,item_id", [("file", ITEM_ID), ("application", APP_ITEM_ID), ("test_result", APP_ITEM_ID)])
async def test_adopt_forwards_each_kind_to_the_atomic_operation(kind: str, item_id: str) -> None:
    extension = FakeExtension()
    directus = make_directus(extension=extension)
    response = await adopt_project_embed(
        request=make_request(), project_id="project-1", body=adopt_body(kind=kind, project_item_id=item_id),
        current_user=USER, directus_service=directus,
    )
    assert response["result"]["status"] == "adopted"
    action, sent = extension.calls[0]
    assert action == "adopt"
    assert sent["kind"] == kind and sent["project_id"] == "project-1" and sent["project_item_id"] == item_id
    assert sent["actor_user_hash"] == sha("user-1")
    assert "team_id" not in sent
    directus.team.require_team_role.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=projects.files.adopt-embed
@pytest.mark.anyio
async def test_adopt_replay_returns_the_first_result() -> None:
    first = {"status": "adopted", "operation_id": "op-adopt", "project_item_id": ITEM_ID, "idempotent": False}
    extension = FakeExtension([FakeResponse(200, {"data": first}),
                               FakeResponse(200, {"data": {**first, "idempotent": True}})])
    directus = make_directus(extension=extension)
    one = await adopt_project_embed(request=make_request(), project_id="project-1", body=adopt_body(),
                                    current_user=USER, directus_service=directus)
    two = await adopt_project_embed(request=make_request(), project_id="project-1", body=adopt_body(),
                                    current_user=USER, directus_service=directus)
    assert one["result"]["idempotent"] is False and two["result"]["idempotent"] is True
    assert extension.calls[0][1] == extension.calls[1][1]


# contract-test: supporting surface=rest_api assertions=projects.files.adopt-embed
@pytest.mark.anyio
@pytest.mark.parametrize("status,code", [
    (409, "embed_already_linked"), (409, "path_conflict"), (404, "embed_not_found"),
    (403, "forbidden"), (400, "invalid_request"), (409, "operation_payload_mismatch"),
])
async def test_adopt_surfaces_stable_error_codes(status: int, code: str) -> None:
    extension = FakeExtension([FakeResponse(status, {"error": {"code": code}})])
    with pytest.raises(HTTPException) as error:
        await adopt_project_embed(request=make_request(), project_id="project-1", body=adopt_body(),
                                  current_user=USER, directus_service=make_directus(extension=extension))
    assert (error.value.status_code, error.value.detail) == (status, code)


# contract-test: supporting surface=rest_api assertions=projects.files.adopt-embed
@pytest.mark.anyio
async def test_unknown_extension_failure_is_a_server_error_not_success() -> None:
    extension = FakeExtension([FakeResponse(500, {"error": {"code": "project_item_transaction_failed"}})])
    with pytest.raises(HTTPException) as error:
        await adopt_project_embed(request=make_request(), project_id="project-1", body=adopt_body(),
                                  current_user=USER, directus_service=make_directus(extension=extension))
    assert (error.value.status_code, error.value.detail) == (500, "project_item_transaction_failed")


# contract-test: supporting surface=rest_api assertions=projects.files.adopt-embed
@pytest.mark.anyio
async def test_non_member_and_unknown_project_never_reach_the_operation() -> None:
    extension = FakeExtension()
    with pytest.raises(HTTPException) as forbidden:
        await adopt_project_embed(request=make_request(), project_id="project-1", body=adopt_body(team_id="team-1"),
                                  current_user=USER, directus_service=make_directus(extension=extension, team_denied=True))
    assert (forbidden.value.status_code, forbidden.value.detail) == (403, "forbidden")
    with pytest.raises(HTTPException) as missing:
        await adopt_project_embed(request=make_request(), project_id="project-1", body=adopt_body(),
                                  current_user=USER, directus_service=make_directus(extension=extension, project=False))
    assert (missing.value.status_code, missing.value.detail) == (404, "project_not_found")
    assert extension.calls == []


# contract-test: supporting surface=rest_api assertions=projects.files.adopt-embed
@pytest.mark.anyio
async def test_team_adopt_forwards_team_scope() -> None:
    extension = FakeExtension()
    directus = make_directus(extension=extension)
    await adopt_project_embed(request=make_request(), project_id="project-1", body=adopt_body(team_id="team-1"),
                              current_user=USER, directus_service=directus)
    assert extension.calls[0][1]["team_id"] == "team-1"
    assert directus.team.require_team_role.await_args.args[:2] == ("team-1", "user-1")


# contract-test: supporting surface=rest_api assertions=projects.files.adopt-embed
def test_adopt_request_rejects_bad_shapes() -> None:
    with pytest.raises(ValidationError):
        adopt_body(kind="folder")
    with pytest.raises(ValidationError):
        adopt_body(project_item_id="web-app/index.html")
    with pytest.raises(ValidationError):
        adopt_body(operation_id="spaces are not allowed")
    with pytest.raises(ValidationError):
        AdoptEmbedRequest(**{**adopt_body().model_dump(exclude_none=True), "hashed_user_id": "smuggled"})


# contract-test: supporting surface=rest_api assertions=projects.files.rename-delete
@pytest.mark.anyio
async def test_rename_moves_the_link_and_keeps_the_embed() -> None:
    renamed = {"status": "renamed", "operation_id": "op-rename", "project_item_id": NEW_ITEM_ID,
               "previous_project_item_id": ITEM_ID, "target_id_hash": sha("embed-1"), "idempotent": False}
    extension = FakeExtension([FakeResponse(200, {"data": renamed})])
    response = await rename_project_item(
        request=make_request(), project_id="project-1", project_item_id=ITEM_ID,
        body=RenameItemRequest(operation_id="op-rename", new_project_item_id=NEW_ITEM_ID,
                               encrypted_display_name="n2", encrypted_metadata="m2"),
        current_user=USER, directus_service=make_directus(extension=extension),
    )
    assert response["result"]["target_id_hash"] == sha("embed-1")
    action, sent = extension.calls[0]
    assert action == "rename"
    assert (sent["project_item_id"], sent["new_project_item_id"]) == (ITEM_ID, NEW_ITEM_ID)
    assert "embed_id" not in sent


# contract-test: supporting surface=rest_api assertions=projects.files.rename-delete
@pytest.mark.anyio
async def test_rename_onto_an_existing_path_is_path_conflict() -> None:
    extension = FakeExtension([FakeResponse(409, {"error": {"code": "path_conflict"}})])
    with pytest.raises(HTTPException) as error:
        await rename_project_item(
            request=make_request(), project_id="project-1", project_item_id=ITEM_ID,
            body=RenameItemRequest(operation_id="op", new_project_item_id=NEW_ITEM_ID,
                                   encrypted_display_name="n", encrypted_metadata="m"),
            current_user=USER, directus_service=make_directus(extension=extension),
        )
    assert (error.value.status_code, error.value.detail) == (409, "path_conflict")


# contract-test: supporting surface=rest_api assertions=projects.files.rename-delete
@pytest.mark.anyio
async def test_delete_removes_only_the_link() -> None:
    extension = FakeExtension()
    directus = make_directus(extension=extension)
    response = await delete_project_item_link(
        request=make_request("DELETE"), project_id="project-1", project_item_id=ITEM_ID,
        body=DeleteItemRequest(operation_id="op-delete"), current_user=USER, directus_service=directus,
    )
    assert response["result"]["operation_id"] == "op-delete"
    action, sent = extension.calls[0]
    assert action == "delete" and set(sent) == {"operation_id", "project_id", "project_item_id", "actor_user_hash"}
    assert not hasattr(directus, "embed")


# contract-test: supporting surface=rest_api assertions=projects.files.rename-delete
@pytest.mark.anyio
async def test_team_member_manages_only_items_they_attached() -> None:
    foreign_item = {"project_item_id": ITEM_ID, "attached_by_user_hash": sha("someone-else")}
    extension = FakeExtension()
    with pytest.raises(HTTPException) as error:
        await delete_project_item_link(
            request=make_request("DELETE"), project_id="project-1", project_item_id=ITEM_ID,
            body=DeleteItemRequest(operation_id="op"), team_id="team-1", current_user=USER,
            directus_service=make_directus(extension=extension, item=foreign_item),
        )
    assert (error.value.status_code, error.value.detail) == (403, "forbidden")
    own_item = {"project_item_id": ITEM_ID, "attached_by_user_hash": sha("user-1")}
    await delete_project_item_link(
        request=make_request("DELETE"), project_id="project-1", project_item_id=ITEM_ID,
        body=DeleteItemRequest(operation_id="op"), team_id="team-1", current_user=USER,
        directus_service=make_directus(extension=extension, item=own_item),
    )
    assert extension.calls[0][1]["team_id"] == "team-1"


# contract-test: supporting surface=rest_api assertions=projects.files.application-single-source
@pytest.mark.anyio
async def test_chat_diff_block_never_writes_a_project_linked_embed() -> None:
    from backend.apps.ai.tasks.stream_consumer import _apply_diff_block_to_existing_embed

    lookups: list[dict] = []

    class LinkedDirectus:
        embed = SimpleNamespace(get_embed_by_id=AsyncMock(return_value=None))

        async def get_items(self, collection, *, params, **_kwargs):
            lookups.append({"collection": collection, **params})
            return [{"id": "link-row"}]

    class NoWriteEmbedService:
        def __getattr__(self, name):
            raise AssertionError(f"Project-linked embed must not be written via {name}")

    cache = SimpleNamespace(get_embed_from_cache=AsyncMock(return_value={"embed_id": "embed-1", "type": "code"}))
    request = SimpleNamespace(chat_id="chat-1", message_id="message-1", user_id="user-1", user_id_hash="hash-1",
                              embed_file_path_index={"index.html-AbC": "embed-1"})
    chunk = await _apply_diff_block_to_existing_embed(
        diff_content="@@ -1 +1 @@\n-old\n+new", diff_embed_ref="index.html-AbC", request_data=request,
        cache_service=cache, directus_service=LinkedDirectus(), encryption_service=SimpleNamespace(),
        embed_service=NoWriteEmbedService(), user_vault_key_id="vault-1", log_prefix="[test]",
    )
    assert "not applied: project_file_tool_required" in chunk
    assert "project_update_file" in chunk
    assert lookups[0]["collection"] == "project_items"
    assert lookups[0]["filter[target_id_hash][_eq]"] == sha("embed-1")
    cache.get_embed_from_cache.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=projects.files.rename-delete
def test_assistant_rename_and_delete_tools_issue_client_jobs() -> None:
    from backend.apps.ai.processing.project_file_tools import PROJECT_FILE_TOOL_TO_OPERATION, build_project_file_tools
    from backend.core.api.app.services.project_file_operation_service import (
        PROJECT_FILE_MUTATIONS,
        ProjectFileOperationError,
        ProjectFileOperationService,
    )

    tools = {tool["function"]["name"]: tool["function"] for tool in build_project_file_tools()}
    assert PROJECT_FILE_TOOL_TO_OPERATION["project_rename_file"] == "rename_file"
    assert PROJECT_FILE_TOOL_TO_OPERATION["project_delete_file"] == "delete_file"
    assert tools["project_rename_file"]["parameters"]["required"] == ["path", "new_path"]
    assert tools["project_delete_file"]["parameters"]["required"] == ["path"]
    assert {"rename_file", "delete_file"} <= PROJECT_FILE_MUTATIONS
    validate = ProjectFileOperationService._validate_arguments
    validate("rename_file", {"path": "web-app/a.js", "new_path": "web-app/b.js"})
    validate("delete_file", {"path": "web-app/a.js"})
    for operation, arguments in [
        ("rename_file", {"path": "a.js", "new_path": "../escape.js"}),
        ("rename_file", {"path": "a.js", "new_path": "a.js"}),
        ("rename_file", {"path": "a.js", "new_path": "b.js", "content": "smuggled"}),
        ("delete_file", {"path": "a.js", "patch": "smuggled"}),
        ("delete_file", {"path": "/etc/passwd"}),
    ]:
        with pytest.raises(ProjectFileOperationError):
            validate(operation, arguments)


class GrantRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)
        return 1


class GrantCache:
    def __init__(self) -> None:
        self.redis = GrantRedis()

    @property
    async def client(self):
        return self.redis


# contract-test: supporting surface=rest_api assertions=projects.files.server-owned-fields
@pytest.mark.anyio
async def test_thumbnail_refresh_passes_but_content_changes_never_do() -> None:
    before = {"type": "application", "embed_ids": ["c1"], "title": "App", "version_number": 2}
    after = {**before, "latest_screenshot": {"files": {"preview": {}}}, "version_number": 3}
    cache = GrantCache()
    await grant_server_owned_refresh(cache, embed_id="app-1", kind="application", version_number=3,
                                     before=before, after=after)
    assert await find_server_owned_refresh(cache, "app-1", 3) == {"link_kind": "application", "version_number": 3}
    assert await find_server_owned_refresh(cache, "app-1", 4) is None
    await clear_server_owned_refresh(cache, "app-1")
    assert await find_server_owned_refresh(cache, "app-1", 3) is None

    for kind, changed in [
        ("application", {**after, "embed_ids": ["c1", "c2"]}),
        ("application", {**after, "title": "Renamed"}),
        ("test_result", {**before, "is_current": False, "evidence": ["smuggled"]}),
        ("file", {**before, "code": "new source"}),
        ("file", {**before, "latest_screenshot": {}}),
    ]:
        with pytest.raises(ServerOwnedFieldError):
            await grant_server_owned_refresh(cache, embed_id="x", kind=kind, version_number=3,
                                             before=before, after=changed)
    assert "embed:x:server_owned_refresh" not in cache.redis.values
    assert_server_owned_change("test_result", {"is_current": True, "stale_reason": None},
                               {"is_current": False, "stale_reason": "revisions_changed"})
    assert json.loads(cache.redis.values.get("embed:app-1:server_owned_refresh", "null")) is None
