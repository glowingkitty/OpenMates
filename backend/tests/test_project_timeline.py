"""Tests for the Project timeline read route: access, hashes-only wire, merge and cursor.

Directus is stubbed; the stub honors the created_at/id cursor filters the route
emits so pagination is exercised end to end.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes.project_timeline import get_project_timeline  # noqa: E402 - stubs precede route imports.
from backend.core.api.app.services.directus.project_methods import hash_id  # noqa: E402

USER = SimpleNamespace(id="user-1")
EMBED_A, EMBED_B = "embed-a", "embed-b"


def make_request() -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/v1/projects/p/timeline", "headers": [],
        "client": ("testclient", 50000), "server": ("testserver", 80),
        "app": SimpleNamespace(state=SimpleNamespace(cache_service=SimpleNamespace(get=AsyncMock(return_value=None)))),
    })


ROWS = {
    "project_commits": [
        {"id": "c1", "commit_id": "commit-1", "author_kind": "assistant", "entries": [], "created_at": 100,
         "encrypted_message": "cipher", "encrypted_paths": "cipher-paths"},
    ],
    "embed_version_commits": [
        {"id": "a1", "embed_id": EMBED_A, "expected_revision": 0, "committed_revision": 1, "created_at": 90},
        {"id": "a2", "embed_id": EMBED_A, "expected_revision": 1, "committed_revision": 2, "created_at": 70},
    ],
    "embed_user_revision_commits": [
        {"id": "u1", "embed_id": EMBED_B, "revision_action": "restore", "committed_revision": 4,
         "restored_from": 2, "created_at": 80},
    ],
    "project_item_operations": [
        {"id": "o1", "operation_kind": "delete", "target_id_hash": hash_id(EMBED_B), "created_at": 100},
    ],
}


def apply_filters(rows, params):
    """Evaluate only the created_at/id filters the route emits."""
    def ok(row):
        if "filter[created_at][_lt]" in params and not row["created_at"] < params["filter[created_at][_lt]"]:
            return False
        if "filter[created_at][_lte]" in params and not row["created_at"] <= params["filter[created_at][_lte]"]:
            return False
        if "filter[_or][0][created_at][_lt]" in params:
            created = params["filter[_or][0][created_at][_lt]"]
            row_id = params["filter[_or][1][_and][1][id][_lt]"]
            return row["created_at"] < created or (row["created_at"] == created and row["id"] < row_id)
        return True
    return sorted((r for r in rows if ok(r)), key=lambda r: (r["created_at"], r["id"]), reverse=True)


def make_directus(*, role="member", project=True):
    async def get_items(collection, params=None, **kwargs):
        return apply_filters(ROWS[collection], params)[: params["limit"]]

    return SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock(return_value={"role": role})),
        project=SimpleNamespace(get_project=AsyncMock(return_value={"id": "row"} if project else None)),
        get_items=AsyncMock(side_effect=get_items),
    )


async def call(directus, **kwargs):
    return await get_project_timeline(
        request=make_request(), project_id="p", current_user=USER, directus_service=directus,
        **{"limit": 50, "before": None, "team_id": None, **kwargs},
    )


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_merge_is_newest_first_hashes_only_and_leaks_no_embed_ids_or_paths() -> None:
    page = await call(make_directus())
    assert [(e["kind"], e["id"]) for e in page["entries"]] == [
        ("commit", "c1"), ("file_operation", "o1"), ("file_version", "a1"), ("file_version", "u1"),
        ("file_version", "a2"),
    ]
    by_id = {e["id"]: e for e in page["entries"]}
    assert by_id["a1"]["action"] == "create" and by_id["a1"]["author_kind"] == "assistant"
    assert by_id["a1"]["target_id_hash"] == hash_id(EMBED_A) and by_id["a1"]["version"] == 1
    assert by_id["a2"]["action"] == "update"
    assert (by_id["u1"]["author_kind"], by_id["u1"]["action"], by_id["u1"]["restored_from_version"]) == ("user", "restore", 2)
    assert by_id["o1"]["action"] == "delete" and by_id["o1"]["version"] is None
    assert by_id["c1"]["commit"]["commit_id"] == "commit-1"
    assert page["next_cursor"] is None
    wire = json.dumps(page)
    assert EMBED_A not in wire and EMBED_B not in wire and '"embed_id"' not in wire
    assert '"path"' not in wire and '"paths"' not in wire


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_cursor_pages_without_duplicates() -> None:
    directus = make_directus()
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        page = await call(directus, limit=2, before=cursor)
        seen.extend(e["id"] for e in page["entries"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ["c1", "o1", "a1", "u1", "a2"]


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
@pytest.mark.parametrize("cursor", ["!!!", "bm90LWEtY3Vyc29y", "LTF8Y29tbWl0fHg", "MTB8Ym9ndXN8eA"])
async def test_bad_cursor_is_400(cursor) -> None:
    with pytest.raises(HTTPException) as error:
        await call(make_directus(), before=cursor)
    assert error.value.status_code == 400


# contract-test: supporting surface=rest_api assertions=projects.files.rename-delete
@pytest.mark.anyio
async def test_team_viewer_can_read_and_scopes_by_team() -> None:
    directus = make_directus(role="viewer")
    await call(directus, team_id="team-1")
    commit_params = directus.get_items.await_args_list[0].kwargs["params"]
    assert commit_params["filter[hashed_team_id][_eq]"] == hash_id("team-1")


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
@pytest.mark.anyio
async def test_non_member_forbidden_and_unknown_project_404() -> None:
    from backend.core.api.app.services.directus.team_methods import TeamPermissionError
    denied = make_directus()
    denied.team.require_team_role = AsyncMock(side_effect=TeamPermissionError("no"))
    with pytest.raises(HTTPException) as forbidden:
        await call(denied, team_id="team-1")
    assert forbidden.value.status_code == 403
    assert denied.get_items.await_count == 0
    with pytest.raises(HTTPException) as missing:
        await call(make_directus(project=False))
    assert missing.value.status_code == 404


# contract-test: supporting surface=rest_api assertions=projects.history.native-commits
def test_unauthenticated_requests_are_refused_by_the_session_dependency() -> None:
    from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
    from backend.core.api.app.routes.project_timeline import router
    route = next(r for r in router.routes if r.path.endswith("/timeline"))
    assert any(d.call is get_current_user for d in route.dependant.dependencies)
