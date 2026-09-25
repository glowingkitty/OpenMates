"""Tests for privacy-preserving user plan backend helpers.

Plans are durable coordination records for complex user/AI work. These tests
lock the Directus/service contract without a live CMS or FastAPI app.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods, hash_id
from backend.core.api.app.services.user_plan_service import UserPlanConflictError, UserPlanService


def plan_payload(**overrides):
    base = {
        "plan_id": "plan-1",
        "encrypted_title": "cipher-title",
        "encrypted_goal": "cipher-goal",
        "encrypted_scope_in": "cipher-scope-in",
        "encrypted_linked_project_ids": "cipher-linked-project-ids",
        "status": "draft",
        "primary_chat_id": "chat-1",
        "linked_project_ids": ["project-1"],
        "planner_focus_id": "openmates-plan",
        "created_at": 100,
        "updated_at": 100,
        "key_wrappers": [
            {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 100},
            {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_plan_key": "cipher-chat", "created_at": 100},
            {"key_type": "project", "hashed_project_id": hash_id("project-1"), "encrypted_plan_key": "cipher-project", "created_at": 100},
        ],
    }
    base.update(overrides)
    return base


def criterion_payload(**overrides):
    base = {
        "criterion_id": "AC-1",
        "encrypted_text": "cipher-ac",
        "type": "functional",
        "status": "pending",
        "required": True,
        "verification_ids": ["V-1"],
        "created_at": 100,
        "updated_at": 100,
    }
    base.update(overrides)
    return base


def verification_payload(**overrides):
    base = {
        "verification_id": "V-1",
        "kind": "automated_test",
        "phase": "green",
        "status": "pending",
        "required_for_done": True,
        "covers": ["AC-1"],
        "created_at": 100,
        "updated_at": 100,
    }
    base.update(overrides)
    return base


def learning_payload(**overrides):
    base = {
        "learning_id": "LRN-1",
        "type": "workflow_improvement",
        "target_kind": "workflow",
        "status": "accepted",
        "encrypted_title": "cipher-learning-title",
        "encrypted_task_draft": "cipher-task-draft",
        "created_at": 100,
        "updated_at": 100,
    }
    base.update(overrides)
    return base


# contract-test: supporting surface=rest_api assertions=plans.content.client-encrypted,plans.project-links.encrypted
@pytest.mark.asyncio
async def test_create_plan_hashes_owner_and_projects_without_plaintext_content() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1", **plan_payload()}))

    methods = UserPlanMethods(directus)
    created = await methods.create_plan("user-1", plan_payload())

    assert created is not None
    collection, record = directus.create_item.await_args_list[0].args
    assert collection == "user_plans"
    assert record["hashed_user_id"] == hash_id("user-1")
    assert record["hashed_primary_chat_id"] == hash_id("chat-1")
    assert "linked_project_ids" not in record
    assert record["linked_project_hashes"] == [hash_id("project-1")]
    assert record["encrypted_linked_project_ids"] == "cipher-linked-project-ids"
    assert record["encrypted_title"] == "cipher-title"
    assert "encrypted_plan_key" not in record
    assert "title" not in record
    assert "goal" not in record


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"linked_project_ids": []},
        {"encrypted_linked_project_ids": None},
        {
            "key_wrappers": [
                {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 100},
                {
                    "key_type": "chat",
                    "hashed_chat_id": hash_id("chat-1"),
                    "encrypted_plan_key": "cipher-chat",
                    "created_at": 100,
                },
            ]
        },
    ],
)
# contract-test: supporting surface=rest_api assertions=plans.project-links.encrypted,plans.key-wrappers.contextual
async def test_create_plan_persistence_rejects_incomplete_project_links(overrides: dict[str, object]) -> None:
    directus = SimpleNamespace(create_item=AsyncMock())

    created = await UserPlanMethods(directus).create_plan("user-1", plan_payload(**overrides))

    assert created is None
    directus.create_item.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=plans.lifecycle.visible,plans.project-links.encrypted,plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_restore_plan_snapshot_authorizes_hashes_and_never_stores_raw_project_ids() -> None:
    project_methods = SimpleNamespace(list_projects=AsyncMock(return_value=[{"project_id": "project-1"}]))
    directus = SimpleNamespace(project=project_methods)
    directus.create_item = AsyncMock(
        side_effect=lambda collection, record: (True, {"id": f"{collection}-row", **record})
    )
    snapshot = plan_payload()
    snapshot.pop("linked_project_ids")
    snapshot["linked_project_hashes"] = [hash_id("project-1")]

    restored = await UserPlanMethods(directus).restore_plan_snapshot("user-1", snapshot)

    assert restored is not None
    project_methods.list_projects.assert_awaited_once_with("user-1", include_archived=True)
    collection, record = directus.create_item.await_args_list[0].args
    assert collection == "user_plans"
    assert record["linked_project_hashes"] == [hash_id("project-1")]
    assert "linked_project_ids" not in record


# contract-test: supporting surface=rest_api assertions=plans.lifecycle.visible,plans.project-links.encrypted
@pytest.mark.asyncio
async def test_restore_plan_snapshot_rejects_inaccessible_project_hash() -> None:
    project_methods = SimpleNamespace(list_projects=AsyncMock(return_value=[{"project_id": "project-2"}]))
    directus = SimpleNamespace(project=project_methods, create_item=AsyncMock())
    snapshot = plan_payload()
    snapshot.pop("linked_project_ids")
    snapshot["linked_project_hashes"] = [hash_id("project-1")]

    restored = await UserPlanMethods(directus).restore_plan_snapshot("user-1", snapshot)

    assert restored is None
    directus.create_item.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=plans.lifecycle.visible
@pytest.mark.asyncio
async def test_restore_plan_snapshot_preserves_legacy_unlinked_plan() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(
        side_effect=lambda collection, record: (True, {"id": f"{collection}-row", **record})
    )
    snapshot = plan_payload(
        encrypted_linked_project_ids=None,
        linked_project_ids=[],
        key_wrappers=[
            {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 100},
            {
                "key_type": "chat",
                "hashed_chat_id": hash_id("chat-1"),
                "encrypted_plan_key": "cipher-chat",
                "created_at": 100,
            },
        ],
    )
    snapshot.pop("linked_project_ids")
    snapshot["linked_project_hashes"] = []

    restored = await UserPlanMethods(directus).restore_plan_snapshot("user-1", snapshot)

    assert restored is not None
    _, record = directus.create_item.await_args_list[0].args
    assert record["linked_project_hashes"] == []
    assert record["encrypted_linked_project_ids"] is None


# contract-test: supporting surface=rest_api assertions=plans.lifecycle.visible,plans.project-links.encrypted,plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_update_plan_from_history_snapshot_relinks_with_authorized_hashes() -> None:
    old_wrapper = {"id": "old-wrapper", "key_type": "project", "hashed_project_id": hash_id("project-1")}
    existing = {
        "id": "plan-row",
        "plan_id": "plan-1",
        "version": 2,
        "linked_project_hashes": [hash_id("project-1")],
        "key_wrappers": [old_wrapper],
    }
    project_methods = SimpleNamespace(list_projects=AsyncMock(return_value=[{"project_id": "project-2"}]))
    directus = SimpleNamespace(
        project=project_methods,
        get_items=AsyncMock(return_value=[existing]),
        create_item=AsyncMock(side_effect=lambda _collection, record: (True, {"id": "new-wrapper", **record})),
        update_item=AsyncMock(return_value={"id": "plan-row", "version": 3}),
        delete_item=AsyncMock(return_value=True),
    )
    snapshot = {
        "version": 3,
        "encrypted_title": "cipher-restored-title",
        "encrypted_linked_project_ids": "cipher-restored-project-links",
        "linked_project_hashes": [hash_id("project-2")],
        "key_wrappers": [
            {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 200},
            {
                "key_type": "project",
                "hashed_project_id": hash_id("project-2"),
                "encrypted_plan_key": "cipher-project-2",
                "created_at": 200,
            },
        ],
    }

    updated = await UserPlanMethods(directus).update_plan_from_history_snapshot(
        "plan-1",
        "user-1",
        snapshot,
    )

    assert updated is not None
    project_methods.list_projects.assert_awaited_once_with("user-1", include_archived=True)
    _, _, patch = directus.update_item.await_args.args
    assert patch["linked_project_hashes"] == [hash_id("project-2")]
    assert "linked_project_ids" not in patch
    assert len(updated["key_wrappers"]) == 2
    directus.delete_item.assert_awaited_once_with("user_plan_key_wrappers", "old-wrapper")


# contract-test: direct surface=rest_api assertions=plans.project-links.encrypted
@pytest.mark.asyncio
async def test_create_plan_requires_access_to_every_linked_project() -> None:
    plan_methods = SimpleNamespace(create_plan=AsyncMock(return_value={"plan_id": "plan-1"}))
    project_methods = SimpleNamespace(list_projects=AsyncMock(return_value=[{"project_id": "project-1"}]))
    service = UserPlanService(plan_methods, project_methods=project_methods)

    with pytest.raises(ValueError, match="Linked Project not found or inaccessible"):
        await service.create_plan(
            "user-1",
            plan_payload(
                linked_project_ids=["project-1", "project-2"],
                key_wrappers=[
                    {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 100},
                    {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_plan_key": "cipher-chat", "created_at": 100},
                    {"key_type": "project", "hashed_project_id": hash_id("project-1"), "encrypted_plan_key": "cipher-project-1", "created_at": 100},
                    {"key_type": "project", "hashed_project_id": hash_id("project-2"), "encrypted_plan_key": "cipher-project-2", "created_at": 100},
                ],
            ),
        )

    project_methods.list_projects.assert_awaited_once_with("user-1", include_archived=True)
    plan_methods.create_plan.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=plans.project-links.encrypted
@pytest.mark.asyncio
async def test_create_plan_persists_after_linked_project_authorization() -> None:
    plan_methods = SimpleNamespace(create_plan=AsyncMock(return_value={"plan_id": "plan-1"}))
    project_methods = SimpleNamespace(list_projects=AsyncMock(return_value=[{"project_id": "project-1"}]))
    service = UserPlanService(plan_methods, project_methods=project_methods)

    created = await service.create_plan("user-1", plan_payload())

    assert created == {"plan_id": "plan-1"}
    project_methods.list_projects.assert_awaited_once_with("user-1", include_archived=True)
    persisted_payload = plan_methods.create_plan.await_args.args[1]
    assert persisted_payload["linked_project_ids"] == ["project-1"]
    assert persisted_payload["encrypted_linked_project_ids"] == "cipher-linked-project-ids"


# contract-test: supporting surface=rest_api assertions=plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_create_plan_persists_key_wrappers_separately() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=lambda _collection, record: (True, record))

    methods = UserPlanMethods(directus)
    await methods.create_plan(
        "user-1",
        plan_payload(
            key_wrappers=[
                {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 100},
                {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_plan_key": "cipher-chat", "created_at": 100},
                {
                    "key_type": "project",
                    "hashed_project_id": hash_id("project-1"),
                    "encrypted_plan_key": "cipher-project",
                    "created_at": 100,
                },
            ]
        ),
    )

    plan_collection, plan_record = directus.create_item.await_args_list[0].args
    wrapper_collection, wrapper_record = directus.create_item.await_args_list[1].args
    assert plan_collection == "user_plans"
    assert "key_wrappers" not in plan_record
    assert wrapper_collection == "user_plan_key_wrappers"
    assert wrapper_record["hashed_plan_id"] == hash_id("plan-1")
    assert wrapper_record["hashed_user_id"] == hash_id("user-1")
    assert wrapper_record["key_type"] == "master"


# contract-test: direct surface=rest_api assertions=plans.content.client-encrypted,plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_create_plan_requires_a_complete_key_wrapper_set() -> None:
    directus = SimpleNamespace(create_item=AsyncMock())

    created = await UserPlanMethods(directus).create_plan("user-1", plan_payload(key_wrappers=[]))

    assert created is None
    directus.create_item.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=plans.content.client-encrypted,plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_list_plans_hydrates_key_wrappers_for_client_decryption() -> None:
    plan = {key: value for key, value in plan_payload().items() if key != "key_wrappers"}
    wrappers = [{"key_type": "master", "encrypted_plan_key": "cipher-master"}]
    directus = SimpleNamespace(get_items=AsyncMock(side_effect=[[plan], wrappers]))

    plans = await UserPlanMethods(directus).list_plans("user-1")

    assert plans[0]["key_wrappers"] == wrappers


# contract-test: direct surface=rest_api assertions=plans.lifecycle.visible
@pytest.mark.asyncio
async def test_list_plans_preserves_legacy_unlinked_plans() -> None:
    legacy_plan = {
        key: value
        for key, value in plan_payload(linked_project_ids=[], encrypted_linked_project_ids=None).items()
        if key != "key_wrappers"
    }
    legacy_plan["linked_project_hashes"] = []
    wrappers = [{"key_type": "master", "encrypted_plan_key": "cipher-master"}]
    directus = SimpleNamespace(get_items=AsyncMock(side_effect=[[legacy_plan], wrappers]))

    plans = await UserPlanMethods(directus).list_plans("user-1")

    assert plans == [{**legacy_plan, "key_wrappers": wrappers}]


# contract-test: supporting surface=rest_api assertions=plans.lifecycle.visible,plans.project-links.encrypted
@pytest.mark.asyncio
async def test_list_plans_filters_by_chat_and_project_hashes() -> None:
    project_hash = hash_id("project-1")
    matching = {key: value for key, value in plan_payload(plan_id="plan-1").items() if key != "key_wrappers"}
    matching["linked_project_hashes"] = [project_hash]
    nonmatching = {**matching, "plan_id": "plan-2", "linked_project_hashes": [hash_id("project-2")]}
    wrappers = [{"key_type": "master", "encrypted_plan_key": "cipher-master"}]
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[matching, nonmatching], wrappers])

    methods = UserPlanMethods(directus)
    plans = await methods.list_plans("user-1", chat_id="chat-1", project_id="project-1", status="active")

    params = directus.get_items.await_args_list[0].kwargs["params"]
    assert params["filter[hashed_user_id][_eq]"] == hash_id("user-1")
    assert params["filter[hashed_primary_chat_id][_eq]"] == hash_id("chat-1")
    assert "filter[linked_project_hashes][_contains]" not in params
    assert params["filter[status][_eq]"] == "active"
    assert params["limit"] == -1
    assert [plan["plan_id"] for plan in plans] == ["plan-1"]


# contract-test: supporting surface=rest_api assertions=plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_create_plan_rolls_back_row_and_wrappers_when_wrapper_write_fails() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=[
        (True, {"id": "plan-row", **plan_payload()}),
        (True, {"id": "wrapper-row", "key_type": "master"}),
        (False, {"error": "wrapper failed"}),
    ])
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserPlanMethods(directus)
    created = await methods.create_plan(
        "user-1",
        plan_payload(
            key_wrappers=[
                {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 100},
                {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_plan_key": "cipher-chat", "created_at": 100},
                {"key_type": "project", "hashed_project_id": hash_id("project-1"), "encrypted_plan_key": "cipher-project", "created_at": 100},
            ]
        ),
    )

    assert created is None
    assert directus.delete_item.await_args_list[0].args == ("user_plan_key_wrappers", "wrapper-row")
    assert directus.delete_item.await_args_list[1].args == ("user_plans", "plan-row")


# contract-test: supporting surface=rest_api assertions=plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_create_plan_rejects_raw_project_id_in_key_wrapper_hash_field() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=[(True, {"id": "plan-row", **plan_payload()})])
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserPlanMethods(directus)
    created = await methods.create_plan(
        "user-1",
        plan_payload(
            key_wrappers=[
                {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 100},
                {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_plan_key": "cipher-chat", "created_at": 100},
                {"key_type": "project", "hashed_project_id": "project-1", "encrypted_plan_key": "cipher-project", "created_at": 100},
            ]
        ),
    )

    assert created is None
    directus.create_item.assert_not_awaited()
    directus.delete_item.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_replace_plan_key_wrappers_creates_new_set_then_deletes_old_wrappers() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[{"id": "plan-row", "plan_id": "plan-1"}], [{"id": "old-wrapper"}]])
    directus.create_item = AsyncMock(return_value=(True, {"id": "new-wrapper", "key_type": "master"}))
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserPlanMethods(directus)
    created = await methods.replace_plan_key_wrappers(
        "user-1",
        "plan-1",
        [{"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 100}],
    )

    assert created == [{"id": "new-wrapper", "key_type": "master"}]
    directus.delete_item.assert_awaited_once_with("user_plan_key_wrappers", "old-wrapper")


# contract-test: supporting surface=rest_api assertions=plans.lifecycle.visible
@pytest.mark.asyncio
async def test_update_rejects_stale_plan_version() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "row-1", "version": 3, "plan_id": "plan-1"}])
    directus.update_item = AsyncMock(return_value={"id": "row-1", "version": 4, "plan_id": "plan-1"})

    service = UserPlanService(UserPlanMethods(directus))

    with pytest.raises(UserPlanConflictError):
        await service.update_plan("plan-1", "user-1", {"status": "active", "version": 2})

    directus.update_item.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=plans.key-wrappers.contextual,plans.project-links.encrypted
@pytest.mark.asyncio
async def test_update_plan_replaces_wrappers_with_project_hash_update() -> None:
    existing = {"id": "plan-row", "version": 2, "plan_id": "plan-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[existing], [{"id": "old-wrapper"}]])
    directus.create_item = AsyncMock(return_value=(True, {"id": "new-wrapper", "key_type": "project"}))
    directus.update_item = AsyncMock(return_value={"id": "plan-row", "version": 3})
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserPlanMethods(directus)
    updated = await methods.update_plan(
        "plan-1",
        "user-1",
        {
            "version": 2,
            "linked_project_ids": ["project-2"],
            "encrypted_linked_project_ids": "cipher-linked-project-ids-v2",
            "key_wrappers": [
                {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 200},
                {"key_type": "project", "hashed_project_id": hash_id("project-2"), "encrypted_plan_key": "cipher-project", "created_at": 200},
            ],
        },
    )

    assert updated == {"id": "plan-row", "version": 3, "key_wrappers": [{"id": "new-wrapper", "key_type": "project"}, {"id": "new-wrapper", "key_type": "project"}]}
    _, _, patch = directus.update_item.await_args.args
    assert patch["linked_project_hashes"] == [hash_id("project-2")]
    assert patch["encrypted_linked_project_ids"] == "cipher-linked-project-ids-v2"
    assert "linked_project_ids" not in patch
    assert "key_wrappers" not in patch
    directus.delete_item.assert_awaited_once_with("user_plan_key_wrappers", "old-wrapper")


# contract-test: supporting surface=rest_api assertions=plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_update_plan_fails_visibly_when_old_wrapper_delete_fails() -> None:
    existing = {"id": "plan-row", "version": 2, "plan_id": "plan-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[existing], [{"id": "old-wrapper"}]])
    directus.create_item = AsyncMock(return_value=(True, {"id": "new-wrapper", "key_type": "master"}))
    directus.update_item = AsyncMock(return_value={"id": "plan-row", "version": 3})
    directus.delete_item = AsyncMock(return_value=False)

    methods = UserPlanMethods(directus)

    with pytest.raises(RuntimeError, match="Failed to delete old user plan key wrappers"):
        await methods.update_plan(
            "plan-1",
            "user-1",
            {
                "linked_project_ids": ["project-2"],
                "encrypted_linked_project_ids": "cipher-linked-project-ids-v2",
                "key_wrappers": [
                    {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 200},
                    {"key_type": "project", "hashed_project_id": hash_id("project-2"), "encrypted_plan_key": "cipher-project", "created_at": 200},
                ],
            },
        )

    directus.update_item.assert_awaited_once()
    directus.delete_item.assert_awaited_once_with("user_plan_key_wrappers", "old-wrapper")


# contract-test: supporting surface=rest_api assertions=plans.project-links.encrypted,plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_update_plan_rejects_project_relink_without_replacement_wrappers() -> None:
    existing = {"id": "plan-row", "version": 2, "plan_id": "plan-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item = AsyncMock()

    service = UserPlanService(UserPlanMethods(directus))

    with pytest.raises(ValueError, match="Failed to update plan"):
        await service.update_plan(
            "plan-1",
            "user-1",
            {"version": 2, "linked_project_ids": ["project-2"], "encrypted_linked_project_ids": "cipher-linked-project-ids-v2"},
        )

    directus.update_item.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=plans.project-links.encrypted,plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_update_plan_rejects_project_relink_with_empty_replacement_wrappers() -> None:
    existing = {"id": "plan-row", "version": 2, "plan_id": "plan-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item = AsyncMock()

    service = UserPlanService(UserPlanMethods(directus))

    with pytest.raises(ValueError, match="Failed to update plan"):
        await service.update_plan(
            "plan-1",
            "user-1",
            {
                "version": 2,
                "linked_project_ids": ["project-2"],
                "encrypted_linked_project_ids": "cipher-linked-project-ids-v2",
                "key_wrappers": [],
            },
        )

    directus.update_item.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=plans.execution.gates-evidence,plans.lifecycle.visible
@pytest.mark.asyncio
async def test_completion_blocks_missing_required_verification() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[
        [{"id": "row-1", "version": 1, **plan_payload(status="active")}],
        [criterion_payload(status="satisfied")],
        [verification_payload(status="pending")],
        [],
        [],
        [learning_payload()],
    ])
    directus.update_item = AsyncMock()

    service = UserPlanService(UserPlanMethods(directus))
    result = await service.complete_plan("plan-1", "user-1", {"version": 1})

    assert result["plan"] is None
    assert result["blocked_by"] == [{"kind": "verification", "id": "V-1", "status": "pending"}]
    directus.update_item.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=plans.execution.gates-evidence
@pytest.mark.asyncio
async def test_red_phase_passed_unexpectedly_does_not_block_completion() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[
        [{"id": "row-1", "version": 1, **plan_payload(status="active")}],
        [criterion_payload(status="satisfied")],
        [verification_payload(phase="red", status="passed_unexpectedly", required_for_done=False)],
        [],
        [],
        [learning_payload()],
        [{"id": "row-1", "version": 1, **plan_payload(status="active")}],
    ])
    directus.update_item = AsyncMock(return_value={"id": "row-1", "status": "completed"})

    service = UserPlanService(UserPlanMethods(directus))
    result = await service.complete_plan("plan-1", "user-1", {"version": 1, "updated_at": 200})

    assert result["blocked_by"] == []
    assert result["plan"]["status"] == "completed"


# contract-test: supporting surface=rest_api assertions=plans.execution.gates-evidence,plans.key-wrappers.contextual
@pytest.mark.asyncio
async def test_create_verification_can_create_linked_verification_task() -> None:
    plan_methods = SimpleNamespace()
    plan_methods.get_plan = AsyncMock(return_value={"plan_id": "plan-1"})
    plan_methods.create_verification = AsyncMock(return_value={"plan_id": "plan-1", **verification_payload(linked_task_id="task-1")})
    task_service = SimpleNamespace(create_task=AsyncMock(return_value={"task_id": "task-1", "task_type": "verification"}))

    service = UserPlanService(plan_methods, task_service=task_service)
    result = await service.create_verification(
        "plan-1",
        "user-1",
        {
            **verification_payload(),
            "create_task": True,
            "task_id": "task-1",
            "encrypted_task_key": "cipher-task-key",
            "task_key_wrappers": [{"key_type": "master", "encrypted_task_key": "cipher-task-key", "created_at": 100}],
            "encrypted_linked_project_ids": "cipher-linked-project-ids",
            "encrypted_title": "cipher-verification-task",
            "created_at": 100,
            "updated_at": 100,
        },
    )

    assert result["verification"]["linked_task_id"] == "task-1"
    task_service.create_task.assert_awaited_once()
    task_payload = task_service.create_task.await_args.args[1]
    assert task_payload["version"] == 1
    assert task_payload["plan_id"] == "plan-1"
    assert task_payload["task_type"] == "verification"
    assert task_payload["verification_id"] == "V-1"
    assert task_payload["key_wrappers"] == [{"key_type": "master", "encrypted_task_key": "cipher-task-key", "created_at": 100}]
    assert task_payload["encrypted_linked_project_ids"] == "cipher-linked-project-ids"
    verification_payload_arg = plan_methods.create_verification.await_args.args[1]
    assert "linked_project_ids" not in verification_payload_arg
    assert "encrypted_linked_project_ids" not in verification_payload_arg
    assert "encrypted_task_key" not in verification_payload_arg
    assert "primary_chat_id" not in verification_payload_arg
