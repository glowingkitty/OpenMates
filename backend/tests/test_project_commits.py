"""Tests for native Project commits: routes, authorization and restore semantics.

Directus is mocked; the real Directus access layer is exercised with a stub
service so query scoping (owner, Team, Project) is asserted.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes.project_commits import (  # noqa: E402 - stubs precede route imports.
    ProjectCommitCreateRequest,
    create_project_commit,
    get_project_commit,
    list_project_commits,
    record_project_commit_restore,
)
from backend.core.api.app.services.directus.project_commit_methods import ProjectCommitMethods  # noqa: E402
from backend.core.api.app.services.directus.project_methods import hash_id  # noqa: E402

H1, H2 = hash_id("embed-1"), hash_id("embed-2")
USER = SimpleNamespace(id="user-1")


def make_request(method: str = "POST") -> Request:
    return Request({
        "type": "http", "method": method, "path": "/v1/projects/p/commits", "headers": [],
        "client": ("testclient", 50000), "server": ("testserver", 80),
        "app": SimpleNamespace(state=SimpleNamespace(cache_service=SimpleNamespace(get=AsyncMock(return_value=None)))),
    })


def body(entries=None, commit_id=None, **extra) -> ProjectCommitCreateRequest:
    return ProjectCommitCreateRequest(
        commit_id=commit_id or str(uuid.uuid4()), author_kind="user", encrypted_message="cipher-message",
        entries=entries or [{"target_id_hash": H1, "embed_version": 3}, {"target_id_hash": H2, "embed_version": 5}],
        created_at=100, **extra,
    )


def make_directus(*, members=(H1, H2), existing=None, role="member", source=None):
    commit = SimpleNamespace(
        find_member_target_hashes=AsyncMock(return_value=set(members)),
        get_commit=AsyncMock(side_effect=lambda *a, **k: source if a[1] == "source-commit" else existing),
        create_commit=AsyncMock(side_effect=lambda pid, uid, payload, team_id=None: {**payload, "id": "row"}),
        list_commits=AsyncMock(return_value=[]),
    )
    return SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock(return_value={"role": role})),
        project=SimpleNamespace(get_project=AsyncMock(return_value={"id": "project-row"})),
        project_commit=commit,
    )


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_create_commit_stores_pointers_only_and_hashes_chat() -> None:
    directus = make_directus()
    response = await create_project_commit(
        request=make_request(), project_id="project-1", body=body(chat_id="chat-1"),
        current_user=USER, directus_service=directus,
    )
    stored = directus.project_commit.create_commit.await_args.args[2]
    assert stored["entries"] == [{"target_id_hash": H1, "embed_version": 3}, {"target_id_hash": H2, "embed_version": 5}]
    assert stored["restored_from_commit_id"] is None
    assert "created_by_user_hash" not in response["commit"]
    assert response["commit"]["encrypted_message"] == "cipher-message"


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_create_commit_rejects_files_outside_the_project_and_duplicates() -> None:
    with pytest.raises(HTTPException) as outside:
        await create_project_commit(
            request=make_request(), project_id="project-1", body=body(), current_user=USER,
            directus_service=make_directus(members=(H1,)),
        )
    assert outside.value.status_code == 422
    with pytest.raises(HTTPException) as duplicate:
        await create_project_commit(
            request=make_request(), project_id="project-1", body=body(), current_user=USER,
            directus_service=make_directus(existing={"commit_id": "x"}),
        )
    assert duplicate.value.status_code == 409


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_unknown_project_is_404_and_viewer_cannot_commit() -> None:
    directus = make_directus()
    directus.project.get_project = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as missing:
        await create_project_commit(
            request=make_request(), project_id="p", body=body(), current_user=USER, directus_service=directus,
        )
    assert missing.value.status_code == 404
    denied = make_directus()
    from backend.core.api.app.services.directus.team_methods import TeamPermissionError
    denied.team.require_team_role = AsyncMock(side_effect=TeamPermissionError("no"))
    with pytest.raises(HTTPException) as forbidden:
        await create_project_commit(
            request=make_request(), project_id="p", body=body(), team_id="team-1",
            current_user=USER, directus_service=denied,
        )
    assert forbidden.value.status_code == 403
    assert denied.project_commit.create_commit.await_count == 0


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
def test_request_validation_rejects_bad_shapes() -> None:
    with pytest.raises(ValidationError):
        body(entries=[{"target_id_hash": "not-a-hash", "embed_version": 1}])
    with pytest.raises(ValidationError):
        body(entries=[{"target_id_hash": H1, "embed_version": 0}])
    with pytest.raises(ValidationError):
        body(entries=[{"target_id_hash": H1, "embed_version": 1}, {"target_id_hash": H1, "embed_version": 2}])
    with pytest.raises(ValidationError):
        body(commit_id="nope")
    with pytest.raises(ValidationError):
        body(restored_from_commit_id="smuggled")
    with pytest.raises(ValidationError):
        ProjectCommitCreateRequest(
            commit_id=str(uuid.uuid4()), author_kind="robot", encrypted_message="c",
            entries=[{"target_id_hash": H1, "embed_version": 1}], created_at=1,
        )


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_list_commits_pages_with_cursor_and_viewer_can_read() -> None:
    directus = make_directus(role="viewer")
    rows = [{"commit_id": f"c{i}", "entries": [], "created_at": 10 - i} for i in range(3)]
    directus.project_commit.list_commits = AsyncMock(return_value=rows)
    page = await list_project_commits(
        request=make_request("GET"), project_id="p", limit=2, cursor=4, team_id="team-1",
        current_user=USER, directus_service=directus,
    )
    assert [c["commit_id"] for c in page["commits"]] == ["c0", "c1"]
    assert page["next_cursor"] == 6
    assert directus.project_commit.list_commits.await_args.kwargs == {"team_id": "team-1", "limit": 3, "offset": 4}
    last = await list_project_commits(
        request=make_request("GET"), project_id="p", limit=5, cursor=0,
        current_user=USER, directus_service=make_directus(),
    )
    assert last["next_cursor"] is None


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_get_commit_404() -> None:
    with pytest.raises(HTTPException) as missing:
        await get_project_commit(
            request=make_request("GET"), project_id="p", commit_id="nope",
            current_user=USER, directus_service=make_directus(),
        )
    assert missing.value.status_code == 404


SOURCE = {"commit_id": "source-commit", "entries": [
    {"target_id_hash": H1, "embed_version": 3}, {"target_id_hash": H2, "embed_version": 5}]}


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_restore_records_new_commit_with_newer_revisions_and_keeps_source() -> None:
    directus = make_directus(source=SOURCE)
    restored = body(entries=[{"target_id_hash": H1, "embed_version": 9}, {"target_id_hash": H2, "embed_version": 5}])
    response = await record_project_commit_restore(
        request=make_request(), project_id="p", commit_id="source-commit", body=restored,
        current_user=USER, directus_service=directus,
    )
    assert response["commit"]["restored_from_commit_id"] == "source-commit"
    assert response["commit"]["commit_id"] == restored.commit_id
    assert not hasattr(directus.project_commit, "delete_commit")


@pytest.mark.anyio
@pytest.mark.parametrize("entries,code", [
    ([{"target_id_hash": H1, "embed_version": 2}, {"target_id_hash": H2, "embed_version": 5}], "RESTORE_MUST_NOT_REWIND_HISTORY"),
    ([{"target_id_hash": H1, "embed_version": 3}], "RESTORE_ENTRIES_MISMATCH"),
])
# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
async def test_restore_rejects_rewinds_and_mismatched_file_sets(entries, code) -> None:
    directus = make_directus(source=SOURCE)
    with pytest.raises(HTTPException) as error:
        await record_project_commit_restore(
            request=make_request(), project_id="p", commit_id="source-commit", body=body(entries=entries),
            current_user=USER, directus_service=directus,
        )
    assert (error.value.status_code, error.value.detail) == (422, code)
    assert directus.project_commit.create_commit.await_count == 0


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_restore_unknown_commit_is_404() -> None:
    with pytest.raises(HTTPException) as error:
        await record_project_commit_restore(
            request=make_request(), project_id="p", commit_id="other", body=body(),
            current_user=USER, directus_service=make_directus(source=SOURCE),
        )
    assert error.value.status_code == 404


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_access_layer_scopes_every_query_to_project_and_owner() -> None:
    directus = SimpleNamespace(
        get_items=AsyncMock(return_value=[]),
        create_item=AsyncMock(return_value=(True, {"id": "row"})),
        delete_items=AsyncMock(return_value=2),
    )
    methods = ProjectCommitMethods(directus)
    await methods.list_commits("project-1", "user-1", limit=10, offset=20)
    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[hashed_project_id][_eq]"] == hash_id("project-1")
    assert params["filter[hashed_user_id][_eq]"] == hash_id("user-1")
    assert params["filter[hashed_team_id][_null]"] is True
    assert (params["sort"], params["limit"], params["offset"]) == ("-created_at,-id", 10, 20)
    await methods.get_commit("project-1", "c1", "user-1", team_id="team-1")
    team_params = directus.get_items.await_args.kwargs["params"]
    assert team_params["filter[hashed_team_id][_eq]"] == hash_id("team-1")
    assert "filter[hashed_user_id][_eq]" not in team_params
    await methods.create_commit("project-1", "user-1", {
        "commit_id": "c1", "author_kind": "assistant", "chat_id": "chat-1", "encrypted_message": "m",
        "entries": [{"target_id_hash": H1, "embed_version": 1}], "created_at": 5}, team_id="team-1")
    record = directus.create_item.await_args.args[1]
    assert record["hashed_team_id"] == hash_id("team-1") and record["hashed_user_id"] is None
    assert record["hashed_chat_id"] == hash_id("chat-1") and record["entry_count"] == 1
    assert await methods.delete_project_commits_by_project_hash(hash_id("project-1"), "user-1") == 2
