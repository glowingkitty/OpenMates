"""Tests for Projects V1 backend helpers.

Projects protect referenced embeds from chat/message deletion. These tests use
mocked Directus services so they run quickly without a live CMS.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes.projects import (  # noqa: E402 - optional dependency stubs precede route imports.
    ProjectAskRequest,
    ProjectCreateRequest,
    ProjectMoveRequest,
    ProjectRestoreRequest,
    ProjectSettingsUpdateRequest,
    ask_projects,
    create_project,
    delete_project,
    delete_project_source,
    get_project,
    list_projects,
    list_project_history,
    list_project_sources,
    move_project_to_team,
    restore_project_from_history,
    update_project_settings,
)
from backend.core.api.app.services.directus.project_methods import ProjectMethods, hash_id  # noqa: E402
from backend.core.api.app.services.directus.team_methods import TeamPermissionError  # noqa: E402
from backend.core.api.app.services.project_remote_access_service import ProjectRemoteAccessService  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


def make_request(method: str = "POST") -> Request:
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": "/v1/projects/test",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "app": SimpleNamespace(state=SimpleNamespace(cache_service=SimpleNamespace())),
        }
    )
    return request


def team_project_wrapper(team_id: str = "team-1", epoch: int = 1) -> dict[str, object]:
    return {
        "key_type": "team",
        "hashed_team_id": hash_id(team_id),
        "team_key_epoch": epoch,
        "encrypted_project_key": "cipher-team-project-key",
        "created_at": 1,
    }


@pytest.mark.anyio
async def test_team_project_projection_includes_authorized_wrapper_and_permissions() -> None:
    project = {"project_id": "project-1", "encrypted_project_key": None, "encrypted_name": "cipher-name"}
    wrappers = [team_project_wrapper()]
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock(return_value={"role": "member"})),
        project=SimpleNamespace(
            list_projects=AsyncMock(return_value=[project]),
            get_project=AsyncMock(return_value=project),
            list_project_key_wrappers=AsyncMock(return_value=wrappers),
            list_folders=AsyncMock(return_value=[]),
            list_items=AsyncMock(return_value=[]),
        ),
    )

    listed = await list_projects(
        request=make_request("GET"),
        include_archived=True,
        team_id="team-1",
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )
    shown = await get_project(
        request=make_request("GET"),
        project_id="project-1",
        team_id="team-1",
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )

    for projected in (listed["projects"][0], shown["project"]):
        assert projected["key_wrappers"] == wrappers
        assert projected["mutation_permissions"] == {
            "create": True,
            "update": True,
            "archive": True,
            "delete": False,
            "settings": False,
            "manage_any_items": False,
            "manage_any_sources": False,
            "manage_own_items": True,
            "manage_own_sources": True,
        }


@pytest.mark.anyio
async def test_project_reference_counts_group_by_project() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(
        return_value=[
            {"target_id_hash": hash_id("embed-1"), "hashed_project_id": "project-a"},
            {"target_id_hash": hash_id("embed-1"), "hashed_project_id": "project-b"},
            {"target_id_hash": hash_id("embed-1"), "hashed_project_id": "project-a"},
            {"target_id_hash": hash_id("embed-2"), "hashed_project_id": "project-a"},
        ]
    )

    methods = ProjectMethods(directus)
    counts = await methods.get_project_embed_reference_counts(["embed-1", "embed-2", "embed-3"], "user-1")

    assert counts == {"embed-1": 2, "embed-2": 1, "embed-3": 0}
    directus.get_items.assert_awaited_once()


@pytest.mark.anyio
async def test_remove_items_for_target_hashes_filters_by_user_and_type() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.delete_items = AsyncMock(return_value=2)

    methods = ProjectMethods(directus)
    deleted = await methods.remove_items_for_target_hashes([hash_id("embed-1")], "embed", "user-1")

    assert deleted == 2
    directus.delete_items.assert_awaited_once_with(
        "project_items",
        {
            "target_id_hash": {"_in": [hash_id("embed-1")]},
            "item_type": {"_eq": "embed"},
            "hashed_user_id": {"_eq": hash_id("user-1")},
            "hashed_team_id": {"_null": True},
        },
    )


@pytest.mark.anyio
async def test_remove_items_for_target_hashes_decrements_each_project_count() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(
        side_effect=[
            [
                {"hashed_project_id": "project-a"},
                {"hashed_project_id": "project-a"},
                {"hashed_project_id": "project-b"},
            ],
            [{"id": "a", "item_count": 5}],
            [{"id": "b", "item_count": 2}],
        ]
    )
    directus.delete_items = AsyncMock(return_value=3)
    directus.update_item = AsyncMock()

    methods = ProjectMethods(directus)
    deleted = await methods.remove_items_for_target_hashes([hash_id("embed-1")], "embed", "user-1")

    assert deleted == 3
    directus.update_item.assert_any_await("projects", "a", {"item_count": 3})
    directus.update_item.assert_any_await("projects", "b", {"item_count": 1})


@pytest.mark.anyio
async def test_delete_item_for_project_target_filters_project_type_target_and_user() -> None:
    directus = SimpleNamespace()
    directus.delete_items = AsyncMock(return_value=1)
    directus.get_items = AsyncMock(return_value=[{"id": "project-row", "item_count": 4}])
    directus.update_item = AsyncMock()

    methods = ProjectMethods(directus)
    deleted = await methods.delete_item_for_project_target("project-1", "embed", "embed-1", "user-1")

    assert deleted == 1
    directus.delete_items.assert_awaited_once_with(
        "project_items",
        {
            "hashed_project_id": {"_eq": hash_id("project-1")},
            "target_id_hash": {"_eq": hash_id("embed-1")},
            "item_type": {"_eq": "embed"},
            "hashed_user_id": {"_eq": hash_id("user-1")},
            "hashed_team_id": {"_null": True},
        },
    )
    directus.update_item.assert_awaited_once_with("projects", "project-row", {"item_count": 3})


@pytest.mark.anyio
async def test_team_project_create_persists_team_owner_creator_and_wrapper() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=[(True, {"id": "project-row"}), (True, {"id": "wrapper-row"})])
    methods = ProjectMethods(directus)

    created = await methods.create_project(
        "user-1",
        {
            "project_id": "project-1",
            "encrypted_project_key": None,
            "encrypted_name": "cipher-name",
            "created_at": 1,
            "updated_at": 1,
            "key_wrappers": [
                {
                    "key_type": "team",
                    "hashed_team_id": hash_id("team-1"),
                    "team_key_epoch": 1,
                    "encrypted_project_key": "cipher-key",
                    "created_at": 1,
                }
            ],
        },
        team_id="team-1",
    )

    assert created == {"id": "project-row"}
    project_record = directus.create_item.await_args_list[0].args[1]
    assert project_record["hashed_user_id"] is None
    assert project_record["hashed_team_id"] == hash_id("team-1")
    assert project_record["created_by_user_hash"] == hash_id("user-1")
    wrapper_record = directus.create_item.await_args_list[1].args[1]
    assert wrapper_record["hashed_user_id"] is None
    assert wrapper_record["hashed_team_id"] == hash_id("team-1")


def test_project_move_requires_matching_team_epoch_one_wrapper() -> None:
    with pytest.raises(ValidationError):
        ProjectMoveRequest(
            team_id="team-1",
            confirmed=True,
            team_project_key_wrapper=team_project_wrapper(epoch=2),
        )
    with pytest.raises(ValidationError):
        ProjectMoveRequest(
            team_id="team-1",
            confirmed=True,
            team_project_key_wrapper=team_project_wrapper(team_id="other-team"),
        )


@pytest.mark.anyio
async def test_project_move_route_persists_valid_wrapper_with_context() -> None:
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock(return_value={"role": "member"})),
        project=SimpleNamespace(move_project_to_team=AsyncMock(return_value={"project_id": "project-1"})),
    )
    body = ProjectMoveRequest(
        team_id="team-1",
        confirmed=True,
        moved_at=10,
        team_project_key_wrapper=team_project_wrapper(),
    )

    response = await move_project_to_team(
        request=make_request(),
        project_id="project-1",
        body=body,
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )

    assert response == {"project": {"project_id": "project-1"}}
    directus.project.move_project_to_team.assert_awaited_once_with(
        "project-1",
        "user-1",
        "team-1",
        body.team_project_key_wrapper.model_dump(),
        moved_at=10,
    )


@pytest.mark.anyio
async def test_project_child_move_failure_rolls_back_and_never_mutates_parent() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(
        side_effect=[
            [{"id": "project-row", "project_id": "project-1", "hashed_user_id": hash_id("user-1"), "hashed_team_id": None}],
            [{"id": "folder-row", "hashed_user_id": hash_id("user-1"), "hashed_team_id": None, "created_by_user_hash": hash_id("user-1")}],
            [],
            [],
            [],
        ]
    )
    directus.create_item = AsyncMock(return_value=(True, {"id": "wrapper-row"}))
    directus.update_item = AsyncMock(side_effect=[None, {"id": "folder-row"}])
    directus.delete_item = AsyncMock(return_value=True)
    methods = ProjectMethods(directus)

    with pytest.raises(RuntimeError, match="Failed to move Project child rows"):
        await methods.move_project_to_team(
            "project-1",
            "user-1",
            "team-1",
            team_project_wrapper(),
            moved_at=10,
        )

    assert not any(call.args[0] == "projects" for call in directus.update_item.await_args_list)
    directus.delete_item.assert_awaited_once_with("project_key_wrappers", "wrapper-row")


@pytest.mark.anyio
async def test_project_move_rejects_mismatched_child_before_wrapper_or_parent_write() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(
        side_effect=[
            [{"id": "project-row", "project_id": "project-1", "hashed_user_id": hash_id("user-1"), "hashed_team_id": None}],
            [{"id": "folder-row", "hashed_user_id": hash_id("other-user"), "hashed_team_id": None, "created_by_user_hash": hash_id("other-user")}],
        ]
    )
    directus.create_item = AsyncMock()
    directus.update_item = AsyncMock()
    methods = ProjectMethods(directus)

    with pytest.raises(RuntimeError, match="Project child ownership does not match Personal context"):
        await methods.move_project_to_team(
            "project-1",
            "user-1",
            "team-1",
            team_project_wrapper(),
        )

    directus.create_item.assert_not_awaited()
    directus.update_item.assert_not_awaited()


@pytest.mark.anyio
async def test_project_move_persists_wrapper_and_moves_parent_last() -> None:
    calls: list[str] = []
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(
        side_effect=[
            [{"id": "project-row", "project_id": "project-1", "hashed_user_id": hash_id("user-1"), "hashed_team_id": None, "updated_at": 1}],
            [{"id": "folder-row", "hashed_user_id": hash_id("user-1"), "hashed_team_id": None, "created_by_user_hash": hash_id("user-1")}],
            [],
            [],
            [],
        ]
    )

    async def create_item(collection: str, record: dict[str, object]):
        calls.append(f"create:{collection}")
        return True, {"id": "wrapper-row", **record}

    async def update_item(collection: str, row_id: str, patch: dict[str, object]):
        del row_id, patch
        calls.append(f"update:{collection}")
        return {"id": "project-row"} if collection == "projects" else {"id": "folder-row"}

    directus.create_item = AsyncMock(side_effect=create_item)
    directus.update_item = AsyncMock(side_effect=update_item)
    directus.delete_item = AsyncMock(return_value=True)
    methods = ProjectMethods(directus)

    moved = await methods.move_project_to_team(
        "project-1",
        "user-1",
        "team-1",
        team_project_wrapper(),
        moved_at=10,
    )

    assert moved == {"id": "project-row"}
    assert calls == [
        "create:project_key_wrappers",
        "update:project_folders",
        "update:projects",
    ]
    wrapper_record = directus.create_item.await_args.args[1]
    assert wrapper_record["hashed_team_id"] == hash_id("team-1")
    assert wrapper_record["team_key_epoch"] == 1
    parent_patch = directus.update_item.await_args_list[-1].args[2]
    assert parent_patch["hashed_user_id"] is None
    assert parent_patch["hashed_team_id"] == hash_id("team-1")


@pytest.mark.anyio
async def test_project_parent_move_failure_rolls_back_parent_children_and_wrapper() -> None:
    directus = SimpleNamespace()
    project = {
        "id": "project-row",
        "project_id": "project-1",
        "hashed_user_id": hash_id("user-1"),
        "hashed_team_id": None,
        "created_by_user_hash": hash_id("user-1"),
        "updated_at": 1,
    }
    folder = {
        "id": "folder-row",
        "hashed_user_id": hash_id("user-1"),
        "hashed_team_id": None,
        "created_by_user_hash": hash_id("user-1"),
    }
    directus.get_items = AsyncMock(side_effect=[[project], [folder], [], [], []])
    directus.create_item = AsyncMock(return_value=(True, {"id": "wrapper-row"}))
    directus.update_item = AsyncMock(
        side_effect=[
            {"id": "folder-row"},
            None,
            {"id": "project-row"},
            {"id": "folder-row"},
        ]
    )
    directus.delete_item = AsyncMock(return_value=True)
    methods = ProjectMethods(directus)

    with pytest.raises(RuntimeError, match="Failed to move Project owner context"):
        await methods.move_project_to_team(
            "project-1",
            "user-1",
            "team-1",
            team_project_wrapper(),
            moved_at=10,
        )

    assert [call.args[0] for call in directus.update_item.await_args_list] == [
        "project_folders",
        "projects",
        "projects",
        "project_folders",
    ]
    restored_parent = directus.update_item.await_args_list[2].args[2]
    assert restored_parent["hashed_user_id"] == hash_id("user-1")
    assert restored_parent["hashed_team_id"] is None
    directus.delete_item.assert_awaited_once_with("project_key_wrappers", "wrapper-row")


@pytest.mark.anyio
async def test_team_children_and_sources_use_team_scope_and_attacher() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.create_item = AsyncMock(return_value=(True, {"id": "created-row"}))
    methods = ProjectMethods(directus)

    await methods.list_items("project-1", "user-1", team_id="team-1")
    item_params = directus.get_items.await_args.kwargs["params"]
    assert item_params["filter[hashed_team_id][_eq]"] == hash_id("team-1")
    assert "filter[hashed_user_id][_eq]" not in item_params

    await methods.create_source(
        "project-1",
        "user-1",
        {
            "source_id": "source-1",
            "source_type": "remote_folder",
            "encrypted_display_name": "cipher-name",
            "encrypted_metadata": "cipher-metadata",
            "created_at": 1,
            "updated_at": 1,
        },
        team_id="team-1",
    )
    source_record = directus.create_item.await_args.args[1]
    assert source_record["hashed_user_id"] is None
    assert source_record["hashed_team_id"] == hash_id("team-1")
    assert source_record["attached_by_user_hash"] == hash_id("user-1")


@pytest.mark.anyio
async def test_removed_team_member_sources_are_retained_offline() -> None:
    directus = SimpleNamespace(
        get_items=AsyncMock(return_value=[{"id": "source-1"}, {"id": "source-2"}]),
        update_item=AsyncMock(return_value=True),
    )
    methods = ProjectMethods(directus)

    count = await methods.mark_team_member_sources_offline(
        "team-1", "member-1", updated_at=123
    )

    assert count == 2
    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[hashed_team_id][_eq]"] == hash_id("team-1")
    assert params["filter[attached_by_user_hash][_eq]"] == hash_id("member-1")
    assert all(
        call.args[2] == {"status": "offline", "updated_at": 123}
        for call in directus.update_item.await_args_list
    )


@pytest.mark.anyio
async def test_deleted_team_sources_are_retained_offline() -> None:
    directus = SimpleNamespace(
        get_items=AsyncMock(return_value=[{"id": "source-1"}, {"id": "source-2"}]),
        update_item=AsyncMock(return_value=True),
    )
    methods = ProjectMethods(directus)

    count = await methods.mark_team_sources_offline("team-1", updated_at=124)

    assert count == 2
    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[hashed_team_id][_eq]"] == hash_id("team-1")
    assert "filter[attached_by_user_hash][_eq]" not in params
    assert all(
        call.args[2] == {"status": "offline", "updated_at": 124}
        for call in directus.update_item.await_args_list
    )


@pytest.mark.anyio
async def test_personal_scope_remains_explicitly_team_null() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    methods = ProjectMethods(directus)

    await methods.list_sources("project-1", "user-1")

    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[hashed_user_id][_eq]"] == hash_id("user-1")
    assert params["filter[hashed_team_id][_null]"] is True


@pytest.mark.anyio
async def test_team_source_list_hides_attacher_and_runtime_internals(monkeypatch) -> None:
    source = {
        "id": "source-row",
        "source_id": "source-1",
        "hashed_project_id": hash_id("project-1"),
        "hashed_team_id": hash_id("team-1"),
        "hashed_user_id": None,
        "attached_by_user_hash": hash_id("other-user"),
        "source_type": "remote_folder",
        "encrypted_display_name": "cipher-name",
        "encrypted_metadata": "cipher-metadata",
        "capabilities": ["read"],
        "status": "connected",
        "created_at": 1,
        "updated_at": 2,
        "last_indexed_at": None,
        "device_fingerprint_hash": "device-secret",
    }
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock(return_value={"role": "viewer"})),
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project-row"}),
            list_sources=AsyncMock(return_value=[source]),
        ),
    )
    monkeypatch.setattr(
        "backend.core.api.app.routes.projects.ProjectRemoteAccessService.get_active_binding",
        AsyncMock(return_value={"source_session_id": "session-secret", "key_epoch": 1, "device_fingerprint_hash": "device-secret"}),
    )

    response = await list_project_sources(
        request=make_request("GET"),
        project_id="project-1",
        team_id="team-1",
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )

    listed = response["sources"][0]
    assert listed["ownership_label"] == "team_source"
    assert listed["status"] == "connected"
    for forbidden in (
        "id",
        "hashed_project_id",
        "hashed_team_id",
        "hashed_user_id",
        "attached_by_user_hash",
        "source_session_id",
        "key_epoch",
        "device_fingerprint_hash",
    ):
        assert forbidden not in listed


@pytest.mark.anyio
async def test_viewer_cannot_create_team_project() -> None:
    directus = SimpleNamespace()
    directus.team = SimpleNamespace(require_team_role=AsyncMock(side_effect=TeamPermissionError("denied")))
    directus.project = SimpleNamespace(create_project=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await create_project(
            request=make_request(),
            body=ProjectCreateRequest(
                project_id="project-1",
                encrypted_project_key=None,
                encrypted_name="cipher-name",
                created_at=1,
                updated_at=1,
                last_opened_at=1,
                key_wrappers=[
                    {
                        "key_type": "team",
                        "hashed_team_id": hash_id("team-1"),
                        "team_key_epoch": 1,
                        "encrypted_project_key": "cipher-key",
                        "created_at": 1,
                    }
                ],
            ),
            team_id="team-1",
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
            history_service=AsyncMock(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "TEAM_PERMISSION_DENIED"
    directus.project.create_project.assert_not_awaited()


@pytest.mark.anyio
async def test_team_settings_require_owner_or_admin() -> None:
    directus = SimpleNamespace()
    directus.team = SimpleNamespace(require_team_role=AsyncMock(side_effect=TeamPermissionError("denied")))
    directus.project = SimpleNamespace(get_project=AsyncMock(), upsert_project_settings=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await update_project_settings(
            request=make_request("PATCH"),
            project_id="project-1",
            body=ProjectSettingsUpdateRequest(write_mode="always_ask", updated_at=1),
            team_id="team-1",
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )

    assert exc_info.value.detail == "TEAM_PERMISSION_DENIED"
    directus.project.upsert_project_settings.assert_not_awaited()


@pytest.mark.anyio
async def test_member_can_remove_only_source_they_attached() -> None:
    directus = SimpleNamespace()
    directus.team = SimpleNamespace(require_team_role=AsyncMock(return_value={"role": "member"}))
    directus.project = SimpleNamespace(
        get_project=AsyncMock(return_value={"id": "project-row"}),
        get_source=AsyncMock(return_value={"id": "source-row", "attached_by_user_hash": hash_id("other-user")}),
        delete_source=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await delete_project_source(
            request=make_request("DELETE"),
            project_id="project-1",
            source_id="source-1",
            confirmation_source_id="source-1",
            team_id="team-1",
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )

    assert exc_info.value.detail == "TEAM_PERMISSION_DENIED"
    directus.project.delete_source.assert_not_awaited()


@pytest.mark.anyio
async def test_source_removal_requires_explicit_confirmation() -> None:
    directus = SimpleNamespace()
    directus.project = SimpleNamespace(delete_source=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await delete_project_source(
            request=make_request("DELETE"),
            project_id="project-1",
            source_id="source-1",
            confirmation_source_id=None,
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "SOURCE_REMOVAL_CONFIRMATION_REQUIRED"
    directus.project.delete_source.assert_not_awaited()


@pytest.mark.anyio
async def test_source_removal_rejects_mismatched_exact_source_id() -> None:
    directus = SimpleNamespace()
    directus.project = SimpleNamespace(delete_source=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await delete_project_source(
            request=make_request("DELETE"),
            project_id="project-1",
            source_id="source-1",
            confirmation_source_id="source-2",
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "SOURCE_REMOVAL_CONFIRMATION_MISMATCH"
    directus.project.delete_source.assert_not_awaited()


@pytest.mark.anyio
async def test_source_removal_revokes_runtime_before_deleting_row(monkeypatch) -> None:
    calls: list[str] = []
    directus = SimpleNamespace()
    directus.team = SimpleNamespace(require_team_role=AsyncMock(return_value={"role": "admin"}))
    directus.project = SimpleNamespace(
        get_project=AsyncMock(return_value={"id": "project-row"}),
        get_source=AsyncMock(return_value={"id": "source-row", "attached_by_user_hash": hash_id("other-user")}),
        delete_source=AsyncMock(side_effect=lambda *args, **kwargs: calls.append("delete") or True),
    )
    revoke = AsyncMock(side_effect=lambda **kwargs: calls.append("revoke") or True)
    monkeypatch.setattr("backend.core.api.app.routes.projects.ProjectRemoteAccessService.revoke_source", revoke)

    response = await delete_project_source(
        request=make_request("DELETE"),
        project_id="project-1",
        source_id="source-1",
        confirmation_source_id="source-1",
        team_id="team-1",
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )

    assert response == {"deleted": True}
    assert calls == ["revoke", "delete"]


@pytest.mark.anyio
async def test_source_revocation_invalidates_binding_session_and_pending_requests() -> None:
    store: dict[str, object] = {}

    async def get(key: str) -> object | None:
        return store.get(key)

    async def set_value(key: str, value: object, ttl: int) -> None:
        del ttl
        store[key] = value

    async def delete(key: str) -> None:
        store.pop(key, None)

    cache = SimpleNamespace(get=get, set=set_value, delete=delete)
    service = ProjectRemoteAccessService(cache)
    user_id = "team-1"
    session_id = "session-1"
    binding_key = service._binding_key(user_id, "project-1", "source-1")
    session_key = service._session_key(user_id, session_id)
    store[binding_key] = {"source_session_id": session_id}
    store[session_key] = {
        "source_session_id": session_id,
        "bindings": [{"project_id": "project-1", "source_id": "source-1"}],
        "in_flight": ["request-1"],
        "queued": ["request-2"],
    }
    for request_id in ("request-1", "request-2"):
        store[service._request_key(user_id, request_id)] = {
            "project_id": "project-1",
            "source_id": "source-1",
        }

    assert await service.revoke_source(user_id=user_id, project_id="project-1", source_id="source-1")
    assert binding_key not in store
    assert session_key not in store
    for request_id in ("request-1", "request-2"):
        assert service._request_key(user_id, request_id) not in store
        assert store[service._tombstone_key(user_id, request_id)] is True


@pytest.mark.anyio
async def test_project_delete_revokes_all_sources_before_durable_delete(monkeypatch) -> None:
    calls: list[str] = []
    directus = SimpleNamespace(
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project-row", "project_id": "project-1"}),
            list_sources=AsyncMock(return_value=[{"source_id": "source-1"}, {"source_id": "source-2"}]),
            delete_project=AsyncMock(side_effect=lambda *args, **kwargs: calls.append("delete") or True),
        )
    )
    revoke = AsyncMock(side_effect=lambda **kwargs: calls.append(f"revoke:{kwargs['source_id']}") or True)
    monkeypatch.setattr("backend.core.api.app.routes.projects.ProjectRemoteAccessService.revoke_source", revoke)
    history_service = SimpleNamespace(
        record_change_set=AsyncMock(
            return_value={"change_set": {"change_set_id": "change-1"}, "entries": []}
        )
    )

    response = await delete_project(
        request=make_request("DELETE"),
        project_id="project-1",
        confirmation_project_id="project-1",
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
        history_service=history_service,
    )

    assert response["deleted"] is True
    assert calls == ["revoke:source-1", "revoke:source-2", "delete"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("confirmation_project_id", "detail"),
    [
        (None, "PROJECT_DELETION_CONFIRMATION_REQUIRED"),
        ("project-2", "PROJECT_DELETION_CONFIRMATION_MISMATCH"),
    ],
)
async def test_project_delete_requires_matching_exact_project_id(
    confirmation_project_id: str | None,
    detail: str,
) -> None:
    directus = SimpleNamespace(
        project=SimpleNamespace(
            get_project=AsyncMock(),
            list_sources=AsyncMock(),
            delete_project=AsyncMock(),
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await delete_project(
            request=make_request("DELETE"),
            project_id="project-1",
            confirmation_project_id=confirmation_project_id,
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
            history_service=AsyncMock(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == detail
    directus.project.get_project.assert_not_awaited()
    directus.project.delete_project.assert_not_awaited()


@pytest.mark.anyio
async def test_project_ask_delete_also_revokes_sources_before_durable_delete(monkeypatch) -> None:
    calls: list[str] = []
    directus = SimpleNamespace(
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project-row", "project_id": "project-1"}),
            list_sources=AsyncMock(return_value=[{"source_id": "source-1"}]),
            delete_project=AsyncMock(side_effect=lambda *args, **kwargs: calls.append("delete") or True),
        )
    )
    monkeypatch.setattr(
        "backend.core.api.app.routes.projects.ProjectRemoteAccessService.revoke_source",
        AsyncMock(side_effect=lambda **kwargs: calls.append(f"revoke:{kwargs['source_id']}") or True),
    )
    history_service = SimpleNamespace(
        record_change_set=AsyncMock(
            return_value={"change_set": {"change_set_id": "change-1"}, "entries": []}
        )
    )

    response = await ask_projects(
        request=make_request(),
        body=ProjectAskRequest(
            instruction="delete project",
            exact_delete={"project_id": "project-1"},
        ),
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
        history_service=history_service,
    )

    assert response["deleted_project_ids"] == ["project-1"]
    assert calls == ["revoke:source-1", "delete"]


@pytest.mark.anyio
async def test_team_project_history_and_restore_are_explicitly_unsupported() -> None:
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock(return_value={"role": "admin"})),
        project=SimpleNamespace(get_project=AsyncMock()),
    )
    history_service = SimpleNamespace(
        list_object_history=AsyncMock(),
        restore_object_to_entry=AsyncMock(),
    )

    with pytest.raises(HTTPException) as history_error:
        await list_project_history(
            request=make_request("GET"),
            project_id="project-1",
            team_id="team-1",
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
            history_service=history_service,
        )
    with pytest.raises(HTTPException) as restore_error:
        await restore_project_from_history(
            request=make_request(),
            project_id="project-1",
            body=ProjectRestoreRequest(entry_id="entry-1"),
            team_id="team-1",
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
            history_service=history_service,
        )

    assert history_error.value.status_code == 409
    assert history_error.value.detail == "TEAM_PROJECT_HISTORY_UNSUPPORTED"
    assert restore_error.value.status_code == 409
    assert restore_error.value.detail == "TEAM_PROJECT_HISTORY_UNSUPPORTED"
    directus.project.get_project.assert_not_awaited()
    history_service.list_object_history.assert_not_awaited()
    history_service.restore_object_to_entry.assert_not_awaited()


def test_project_owner_context_migration_is_idempotent_and_rejects_mixed_ownership() -> None:
    migration = (ROOT / "backend/core/directus/setup/migrate_project_owner_context.sql").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS created_by_user_hash" in migration
    assert "ADD COLUMN IF NOT EXISTS attached_by_user_hash" in migration
    assert "project_owner_context_check" in migration
    assert "num_nonnulls(hashed_user_id, hashed_team_id) = 1" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS project_sources_team_source_uq" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS project_sources_personal_source_uq" in migration
    assert "ALTER COLUMN attached_by_user_hash SET NOT NULL" in migration
    assert migration.index("UPDATE public.project_sources AS child") < migration.index(
        "VALIDATE CONSTRAINT project_sources_owner_context_check"
    )
    assert "IF NOT EXISTS (" in migration


def test_project_owner_context_schema_and_setup_wiring_are_complete() -> None:
    schema_expectations = {
        "projects.yml": "created_by_user_hash",
        "project_folders.yml": "created_by_user_hash",
        "project_items.yml": "attached_by_user_hash",
        "project_sources.yml": "attached_by_user_hash",
        "project_settings.yml": "updated_by_user_hash",
    }
    schema_root = ROOT / "backend/core/directus/schemas"
    for filename, actor_field in schema_expectations.items():
        schema = (schema_root / filename).read_text(encoding="utf-8")
        assert "hashed_team_id:" in schema
        assert actor_field in schema

    setup = (ROOT / "backend/core/directus/setup/setup_schemas.py").read_text(encoding="utf-8")
    compose = (ROOT / "backend/core/docker-compose.yml").read_text(encoding="utf-8")
    selfhost = (ROOT / "backend/core/directus/Dockerfile.setup.selfhost").read_text(encoding="utf-8")
    assert "apply_and_verify_project_owner_context()" in setup
    assert "migrate_project_owner_context.sql" in compose
    assert "migrate_project_owner_context.sql" in selfhost
