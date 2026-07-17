"""Tests for privacy-preserving user task backend helpers.

User-facing tasks are distinct from Celery task polling. These tests focus on
the Directus/service contract so they run without a live CMS or FastAPI app.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods, derive_task_short_id, hash_id
from backend.core.api.app.services.user_task_service import UserTaskConflictError, UserTaskService


def task_payload(**overrides):
    base = {
        "task_id": "task-1",
        "encrypted_task_key": "cipher-task-key",
        "encrypted_title": "cipher-title",
        "encrypted_description": "cipher-description",
        "encrypted_tags": "cipher-tags",
        "encrypted_linked_project_ids": "cipher-linked-project-ids",
        "status": "todo",
        "assignee_type": "user",
        "assignee_hash": hash_id("user-1"),
        "primary_chat_id": "chat-1",
        "linked_project_ids": ["project-1"],
        "due_at": None,
        "priority": 0,
        "position": 10,
        "version": 1,
        "created_at": 100,
        "updated_at": 100,
    }
    base.update(overrides)
    return base


class FakeLockClient:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


class FakeCache:
    def __init__(self):
        self.client_value = FakeLockClient()

    @property
    def client(self):
        return self._client()

    async def _client(self):
        return self.client_value


def with_lock_cache(directus):
    directus.cache = FakeCache()
    return directus


@pytest.mark.asyncio
async def test_create_task_hashes_owner_and_projects_without_plaintext_content() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1", **task_payload()}))

    methods = UserTaskMethods(with_lock_cache(directus))
    created = await methods.create_task("user-1", task_payload())

    assert created is not None
    collection, record = directus.create_item.await_args.args
    assert collection == "user_tasks"
    assert record["hashed_user_id"] == hash_id("user-1")
    assert record["hashed_primary_chat_id"] == hash_id("chat-1")
    assert "linked_project_ids" not in record
    assert record["linked_project_hashes"] == [hash_id("project-1")]
    assert record["encrypted_linked_project_ids"] == "cipher-linked-project-ids"
    assert record["encrypted_title"] == "cipher-title"
    assert record["encrypted_task_key"] == "cipher-task-key"
    assert "title" not in record
    assert "description" not in record


def test_task_short_id_matches_cli_derivation() -> None:
    task = {"task_id": "123e4567-e89b-12d3-a456-426614174000"}

    assert derive_task_short_id(task) == "TASK-9020"


@pytest.mark.asyncio
async def test_task_short_id_lookup_rejects_ambiguous_collisions() -> None:
    methods = UserTaskMethods(SimpleNamespace())
    methods.list_tasks = AsyncMock(return_value=[
        {"task_id": "task-1", "short_id": "TASK-1234"},
        {"task_id": "task-2", "short_id": "TASK-1234"},
    ])

    assert await methods.get_task_by_short_id("TASK-1234", "user-1") is None


@pytest.mark.asyncio
async def test_update_task_uses_storage_level_conditional_patch() -> None:
    existing = {"id": "task-row", "version": 2, "task_id": "task-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item_if_version = AsyncMock(return_value={"id": "task-row", "version": 3})

    methods = UserTaskMethods(with_lock_cache(directus))
    updated = await methods.update_task_if_version("task-1", "user-1", {"version": 2, "status": "done"}, 2)

    assert updated == {"id": "task-row", "version": 3}
    directus.update_item_if_version.assert_awaited_once_with(
        "user_tasks",
        "task-row",
        {"version": 3, "status": "done"},
        2,
        owner_hash_field="hashed_user_id",
        owner_hash=hash_id("user-1"),
    )


@pytest.mark.asyncio
async def test_update_task_if_version_honors_committed_payload_version() -> None:
    existing = {"id": "task-row", "version": 2, "task_id": "task-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item_if_version = AsyncMock(return_value={"id": "task-row", "version": 5})

    methods = UserTaskMethods(with_lock_cache(directus))
    updated = await methods.update_task_if_version("task-1", "user-1", {"version": 5, "encrypted_title": "cipher-title-v5"}, 2)

    assert updated == {"id": "task-row", "version": 5}
    directus.update_item_if_version.assert_awaited_once_with(
        "user_tasks",
        "task-row",
        {"version": 5, "encrypted_title": "cipher-title-v5"},
        2,
        owner_hash_field="hashed_user_id",
        owner_hash=hash_id("user-1"),
    )


@pytest.mark.asyncio
async def test_update_task_if_version_relinks_chat_with_replacement_key_wrappers() -> None:
    existing = {
        "id": "task-row",
        **task_payload(),
        "hashed_primary_chat_id": hash_id("chat-1"),
        "linked_project_hashes": [hash_id("project-1")],
    }
    existing_wrappers = [
        {"id": "wrapper-master-old", "key_type": "master", "encrypted_task_key": "old-master"},
        {"id": "wrapper-chat-old", "key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_task_key": "old-chat"},
        {"id": "wrapper-project-old", "key_type": "project", "hashed_project_id": hash_id("project-1"), "encrypted_task_key": "old-project"},
    ]
    replacement_wrappers = [
        {"key_type": "master", "encrypted_task_key": "new-master", "created_at": 200},
        {"key_type": "chat", "hashed_chat_id": hash_id("chat-2"), "encrypted_task_key": "new-chat", "created_at": 200},
        {"key_type": "project", "hashed_project_id": hash_id("project-1"), "encrypted_task_key": "old-project", "created_at": 100, "expires_at": None},
    ]
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[existing], existing_wrappers])
    directus.create_item = AsyncMock(side_effect=[
        (True, {"id": "wrapper-master-new", **replacement_wrappers[0]}),
        (True, {"id": "wrapper-chat-new", **replacement_wrappers[1]}),
        (True, {"id": "wrapper-project-new", **replacement_wrappers[2]}),
    ])
    directus.delete_item = AsyncMock(return_value=True)
    directus.update_item_if_version = AsyncMock(return_value={**existing, "primary_chat_id": "chat-2", "version": 2})

    methods = UserTaskMethods(with_lock_cache(directus))
    updated = await methods.update_task_if_version(
        "task-1",
        "user-1",
        {
            "version": 1,
            "primary_chat_id": "chat-2",
            "linked_project_ids": ["project-1"],
            "encrypted_linked_project_ids": "cipher-linked-project-ids-v2",
            "key_wrappers": replacement_wrappers,
            "updated_at": 200,
        },
        1,
    )

    assert updated is not None
    persisted_patch = directus.update_item_if_version.await_args.args[2]
    assert persisted_patch["primary_chat_id"] == "chat-2"
    assert persisted_patch["hashed_primary_chat_id"] == hash_id("chat-2")
    assert persisted_patch["linked_project_hashes"] == [hash_id("project-1")]
    assert persisted_patch["version"] == 2
    assert directus.get_items.await_args_list[1].kwargs["admin_required"] is True
    assert all(call.kwargs.get("admin_required") is True for call in directus.create_item.await_args_list)
    assert directus.delete_item.await_count == len(existing_wrappers)


@pytest.mark.asyncio
async def test_create_task_persists_key_wrappers_separately() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=lambda _collection, record, **_kwargs: (True, record))

    methods = UserTaskMethods(with_lock_cache(directus))
    await methods.create_task(
        "user-1",
        task_payload(
            key_wrappers=[
                {"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 100},
                {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_task_key": "cipher-chat", "created_at": 100},
                {
                    "key_type": "project",
                    "hashed_project_id": hash_id("project-1"),
                    "encrypted_task_key": "cipher-project",
                    "created_at": 100,
                },
            ]
        ),
    )

    task_collection, task_record = directus.create_item.await_args_list[0].args
    wrapper_collection, wrapper_record = directus.create_item.await_args_list[1].args
    assert task_collection == "user_tasks"
    assert "key_wrappers" not in task_record
    assert wrapper_collection == "user_task_key_wrappers"
    assert directus.create_item.await_args_list[1].kwargs == {"admin_required": True}
    assert wrapper_record["hashed_task_id"] == hash_id("task-1")
    assert wrapper_record["hashed_user_id"] == hash_id("user-1")
    assert wrapper_record["key_type"] == "master"


@pytest.mark.asyncio
async def test_create_task_rolls_back_row_and_wrappers_when_wrapper_write_fails() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=[
        (True, {"id": "task-row", **task_payload()}),
        (True, {"id": "wrapper-row", "key_type": "master"}),
        (False, {"error": "wrapper failed"}),
    ])
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserTaskMethods(with_lock_cache(directus))
    created = await methods.create_task(
        "user-1",
        task_payload(
            key_wrappers=[
                {"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 100},
                {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_task_key": "cipher-chat", "created_at": 100},
                {"key_type": "project", "hashed_project_id": hash_id("project-1"), "encrypted_task_key": "cipher-project", "created_at": 100},
            ]
        ),
    )

    assert created is None
    assert directus.delete_item.await_args_list[0].args == ("user_task_key_wrappers", "wrapper-row")
    assert directus.delete_item.await_args_list[1].args == ("user_tasks", "task-row")


@pytest.mark.asyncio
async def test_create_task_rejects_raw_project_id_in_key_wrapper_hash_field() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=[(True, {"id": "task-row", **task_payload()})])
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserTaskMethods(directus)
    created = await methods.create_task(
        "user-1",
        task_payload(
            key_wrappers=[
                {"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 100},
                {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_task_key": "cipher-chat", "created_at": 100},
                {"key_type": "project", "hashed_project_id": "project-1", "encrypted_task_key": "cipher-project", "created_at": 100},
            ]
        ),
    )

    assert created is None
    directus.create_item.assert_not_awaited()
    directus.delete_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_task_key_wrappers_creates_new_set_then_deletes_old_wrappers() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[{"id": "task-row", "task_id": "task-1", "version": 1}], [{"id": "old-wrapper"}]])
    directus.create_item = AsyncMock(return_value=(True, {"id": "new-wrapper", "key_type": "master"}))
    directus.update_item_if_version = AsyncMock(return_value={"id": "task-row", "version": 2})
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserTaskMethods(with_lock_cache(directus))
    created = await methods.replace_task_key_wrappers(
        "user-1",
        "task-1",
        [{"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 100}],
        1,
    )

    assert created == [{"id": "new-wrapper", "key_type": "master"}]
    directus.update_item_if_version.assert_awaited_once_with(
        "user_tasks",
        "task-row",
        {"version": 2},
        1,
        owner_hash_field="hashed_user_id",
        owner_hash=hash_id("user-1"),
    )
    directus.delete_item.assert_awaited_once_with("user_task_key_wrappers", "old-wrapper", admin_required=True)


@pytest.mark.asyncio
async def test_replace_task_key_wrappers_rejects_stale_version() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "task-row", "task_id": "task-1", "version": 2}])
    directus.update_item_if_version = AsyncMock()
    directus.create_item = AsyncMock()
    directus.delete_item = AsyncMock()

    methods = UserTaskMethods(with_lock_cache(directus))
    created = await methods.replace_task_key_wrappers(
        "user-1",
        "task-1",
        [{"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 100}],
        1,
    )

    assert created is None
    directus.update_item_if_version.assert_not_awaited()
    directus.create_item.assert_not_awaited()
    directus.delete_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_task_key_wrappers_restores_old_wrappers_when_version_advance_fails() -> None:
    existing = {"id": "task-row", "version": 2, "task_id": "task-1"}
    old_wrapper = {"id": "old-wrapper", "key_type": "master", "encrypted_task_key": "cipher-old", "created_at": 100}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[existing], [old_wrapper]])
    directus.create_item = AsyncMock(side_effect=[(True, {"id": "new-wrapper"}), (True, {"id": "restored-wrapper"})])
    directus.delete_item = AsyncMock(return_value=True)
    directus.update_item_if_version = AsyncMock(return_value=None)

    methods = UserTaskMethods(with_lock_cache(directus))

    with pytest.raises(RuntimeError, match="Failed to advance task version"):
        await methods.replace_task_key_wrappers(
            "user-1",
            "task-1",
            [{"key_type": "master", "encrypted_task_key": "cipher-new", "created_at": 200}],
            expected_version=2,
        )

    assert directus.delete_item.await_args_list[0].args == ("user_task_key_wrappers", "old-wrapper")
    assert directus.delete_item.await_args_list[1].args == ("user_task_key_wrappers", "new-wrapper")
    assert directus.create_item.await_args_list[-1].args[1]["encrypted_task_key"] == "cipher-old"


@pytest.mark.asyncio
async def test_delete_task_rejects_stale_version_and_uses_lock() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "task-row", "task_id": "task-1", "version": 2}])
    directus.delete_item = AsyncMock()

    methods = UserTaskMethods(with_lock_cache(directus))
    deleted = await methods.delete_task("task-1", "user-1", 1)

    assert deleted is False
    directus.delete_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_task_deletes_when_expected_version_matches() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "task-row", "task_id": "task-1", "version": 2}])
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserTaskMethods(with_lock_cache(directus))
    deleted = await methods.delete_task("task-1", "user-1", 2)

    assert deleted is True
    directus.delete_item.assert_awaited_once_with("user_tasks", "task-row")


@pytest.mark.asyncio
async def test_update_task_fails_closed_when_lock_backend_is_unavailable() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "row-1", "version": 1, "task_id": "task-1"}])
    directus.update_item = AsyncMock()

    methods = UserTaskMethods(directus)

    with pytest.raises(RuntimeError, match="Task lock backend is unavailable"):
        await methods.update_task("task-1", "user-1", {"status": "done"})

    directus.get_items.assert_not_awaited()
    directus.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_tasks_filters_by_chat_and_project_hashes() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    methods = UserTaskMethods(directus)
    await methods.list_tasks("user-1", chat_id="chat-1", project_id="project-1", status="todo")

    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[hashed_user_id][_eq]"] == hash_id("user-1")
    assert params["filter[hashed_primary_chat_id][_eq]"] == hash_id("chat-1")
    assert params["filter[linked_project_hashes][_contains]"] == hash_id("project-1")
    assert params["filter[status][_eq]"] == "todo"


@pytest.mark.asyncio
async def test_update_rejects_stale_client_version() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "row-1", "version": 3, "task_id": "task-1"}])
    directus.update_item_if_version = AsyncMock(return_value={"id": "row-1", "version": 4, "task_id": "task-1"})

    service = UserTaskService(UserTaskMethods(with_lock_cache(directus)))

    with pytest.raises(UserTaskConflictError):
        await service.update_task("task-1", "user-1", {"status": "done", "version": 2})

    directus.update_item_if_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_task_replaces_wrappers_with_project_hash_update() -> None:
    existing = {"id": "task-row", "version": 2, "task_id": "task-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[existing], [{"id": "old-wrapper"}]])
    directus.create_item = AsyncMock(return_value=(True, {"id": "new-wrapper", "key_type": "project"}))
    directus.update_item_if_version = AsyncMock(return_value={"id": "task-row", "version": 3})
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserTaskMethods(with_lock_cache(directus))
    updated = await methods.update_task(
        "task-1",
        "user-1",
        {
            "version": 2,
            "linked_project_ids": ["project-2"],
            "encrypted_linked_project_ids": "cipher-linked-project-ids-v2",
            "key_wrappers": [
                {"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 200},
                {"key_type": "project", "hashed_project_id": hash_id("project-2"), "encrypted_task_key": "cipher-project", "created_at": 200},
            ],
        },
    )

    assert updated == {"id": "task-row", "version": 3}
    _, _, patch, expected_version = directus.update_item_if_version.await_args.args
    assert expected_version == 2
    assert patch["linked_project_hashes"] == [hash_id("project-2")]
    assert patch["encrypted_linked_project_ids"] == "cipher-linked-project-ids-v2"
    assert patch["version"] == 3
    assert "linked_project_ids" not in patch
    assert "key_wrappers" not in patch
    directus.delete_item.assert_awaited_once_with("user_task_key_wrappers", "old-wrapper", admin_required=True)


@pytest.mark.asyncio
async def test_update_task_accepts_empty_conditional_update_response_when_version_committed() -> None:
    existing = {"id": "task-row", "version": 2, "task_id": "task-1", "status": "todo"}
    committed = {"id": "task-row", "version": 3, "task_id": "task-1", "status": "done"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[existing], [committed]])
    directus.update_item_if_version = AsyncMock(return_value=None)

    methods = UserTaskMethods(with_lock_cache(directus))

    updated = await methods.update_task("task-1", "user-1", {"version": 2, "status": "done"})

    assert updated is not None
    assert updated["version"] == committed["version"]
    assert updated["status"] == committed["status"]


@pytest.mark.asyncio
async def test_update_task_fails_visibly_when_old_wrapper_delete_fails() -> None:
    existing = {"id": "task-row", "version": 2, "task_id": "task-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[existing], [{"id": "old-wrapper"}]])
    directus.create_item = AsyncMock(return_value=(True, {"id": "new-wrapper", "key_type": "master"}))
    directus.update_item_if_version = AsyncMock(return_value={"id": "task-row", "version": 3})
    directus.delete_item = AsyncMock(side_effect=[False, True, True])

    methods = UserTaskMethods(with_lock_cache(directus))

    with pytest.raises(RuntimeError, match="Failed to delete old user task key wrappers"):
        await methods.update_task(
            "task-1",
            "user-1",
            {
                "linked_project_ids": ["project-2"],
                "encrypted_linked_project_ids": "cipher-linked-project-ids-v2",
                "version": 2,
                "key_wrappers": [
                    {"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 200},
                    {"key_type": "project", "hashed_project_id": hash_id("project-2"), "encrypted_task_key": "cipher-project", "created_at": 200},
                ],
            },
        )

    directus.update_item_if_version.assert_not_awaited()
    assert directus.delete_item.await_args_list[0].args == ("user_task_key_wrappers", "old-wrapper")
    assert directus.delete_item.await_args_list[0].kwargs == {"admin_required": True}


@pytest.mark.asyncio
async def test_update_task_rejects_project_relink_without_replacement_wrappers() -> None:
    existing = {"id": "task-row", "version": 2, "task_id": "task-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item_if_version = AsyncMock()

    service = UserTaskService(UserTaskMethods(with_lock_cache(directus)))

    with pytest.raises(ValueError, match="Failed to update task"):
        await service.update_task(
            "task-1",
            "user-1",
            {"version": 2, "linked_project_ids": ["project-2"], "encrypted_linked_project_ids": "cipher-linked-project-ids-v2"},
        )

    directus.update_item_if_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_task_rejects_project_relink_with_empty_replacement_wrappers() -> None:
    existing = {"id": "task-row", "version": 2, "task_id": "task-1"}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item_if_version = AsyncMock()

    service = UserTaskService(UserTaskMethods(with_lock_cache(directus)))

    with pytest.raises(ValueError, match="Failed to update task"):
        await service.update_task(
            "task-1",
            "user-1",
            {
                "version": 2,
                "linked_project_ids": ["project-2"],
                "encrypted_linked_project_ids": "cipher-linked-project-ids-v2",
                "key_wrappers": [],
            },
        )

    directus.update_item_if_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_task_without_due_date_starts_immediately() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.create_item = AsyncMock(side_effect=lambda _collection, record: (True, record))

    service = UserTaskService(UserTaskMethods(directus))
    created = await service.create_task("user-1", task_payload(assignee_type="ai", due_at=None))

    assert created["status"] == "in_progress"
    assert created["ai_execution_state"] == "queued"
    assert created["started_at"] == 100


@pytest.mark.asyncio
async def test_second_ai_task_without_due_date_waits_for_active_chat_task() -> None:
    active_other = {"id": "row-2", "version": 1, **task_payload(task_id="task-2", status="in_progress", assignee_type="ai")}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[active_other])
    directus.create_item = AsyncMock(side_effect=lambda _collection, record: (True, record))

    service = UserTaskService(UserTaskMethods(directus))
    created = await service.create_task("user-1", task_payload(assignee_type="ai", due_at=None))

    assert created["status"] == "todo"
    assert created["ai_execution_state"] == "waiting_for_previous_task"
    assert "started_at" not in created


@pytest.mark.asyncio
async def test_product_task_helpers_do_not_use_celery_tasks_collection() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    methods = UserTaskMethods(directus)
    await methods.list_tasks("user-1")

    collection = directus.get_items.await_args.args[0]
    assert collection == "user_tasks"
    assert collection != "tasks"


@pytest.mark.asyncio
async def test_start_ai_dispatches_transient_plaintext_without_persisting() -> None:
    existing = {**task_payload(), "id": "row-1", "version": 2}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item_if_version = AsyncMock(side_effect=lambda _collection, _row_id, patch, _expected_version, **_kwargs: {**existing, **patch})
    cache = SimpleNamespace(set_active_ai_task=AsyncMock())
    dispatched: dict[str, object] = {}

    async def fake_dispatcher(app_id: str, skill_id: str, payload: dict[str, object]) -> dict[str, str]:
        dispatched.update({"app_id": app_id, "skill_id": skill_id, "payload": payload})
        return {"task_id": "ai-task-1"}

    service = UserTaskService(
        UserTaskMethods(with_lock_cache(directus)),
        cache_service=cache,
        ai_dispatcher=fake_dispatcher,
    )

    updated = await service.start_ai(
        "task-1",
        "user-1",
        {
            "version": 2,
            "primary_chat_id": "chat-1",
            "plaintext_title": "Draft the launch plan",
            "plaintext_description": "Use the current project context.",
            "plaintext_project_context": "Linked projects: project-1",
            "updated_at": 200,
        },
    )

    persisted_patch = directus.update_item_if_version.await_args_list[0].args[2]
    assert updated["ai_execution_state"] == "queued"
    assert persisted_patch["status"] == "in_progress"
    assert "plaintext_title" not in persisted_patch
    assert "plaintext_description" not in persisted_patch

    payload = dispatched["payload"]
    assert dispatched["app_id"] == "ai"
    assert dispatched["skill_id"] == "ask"
    assert isinstance(payload, dict)
    assert payload["user_task_id"] == "task-1"
    assert payload["chat_id"] == "chat-1"
    assert "Draft the launch plan" in str(payload["current_user_content"])
    assert "Use the current project context." in str(payload["current_user_content"])
    assert "Linked projects: project-1" in str(payload["current_user_content"])
    cache.set_active_ai_task.assert_awaited_once_with("chat-1", "ai-task-1")


@pytest.mark.asyncio
async def test_start_ai_rejects_second_active_task_in_same_chat() -> None:
    existing = {"id": "row-1", "version": 2, **task_payload(task_id="task-1")}
    active_other = {"id": "row-2", "version": 1, **task_payload(task_id="task-2", status="in_progress", assignee_type="ai")}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[existing], [active_other]])
    directus.update_item_if_version = AsyncMock()

    service = UserTaskService(UserTaskMethods(with_lock_cache(directus)))

    with pytest.raises(UserTaskConflictError):
        await service.start_ai(
            "task-1",
            "user-1",
            {
                "version": 2,
                "primary_chat_id": "chat-1",
                "plaintext_title": "Do this after the active task",
                "updated_at": 200,
            },
        )

    directus.update_item_if_version.assert_not_awaited()
