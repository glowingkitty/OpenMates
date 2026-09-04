"""Tests for privacy-preserving user task backend helpers.

User-facing tasks are distinct from Celery task polling. These tests focus on
the Directus/service contract so they run without a live CMS or FastAPI app.
"""

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


class _FakeLimiter:
    def limit(self, _rate: str):
        def decorator(func):
            return func

        return decorator


limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _FakeLimiter()
sys.modules.setdefault("backend.core.api.app.services.limiter", limiter_stub)

from backend.core.api.app.routes import user_tasks  # noqa: E402
from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods, derive_task_short_id, hash_id  # noqa: E402
from backend.core.api.app.services.user_task_service import UserTaskConflictError, UserTaskService  # noqa: E402


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


LABEL_HASH_A = "a" * 64
LABEL_HASH_B = "b" * 64


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


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted,tasks.project-links.encrypted
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


# contract-test: direct surface=rest_api assertions=tasks.assignment.identity-separated
def test_assignment_type_and_identity_combinations_are_validated() -> None:
    openmates = user_tasks.UserTaskCreateRequest(**task_payload(
        assignee_type="openmates",
        assignee_identity="openmates",
        assignee_hash=None,
    ))
    opencode = user_tasks.UserTaskCreateRequest(**task_payload(
        primary_chat_id=None,
        assignee_type="external_ai",
        assignee_identity="opencode",
        assignee_hash=None,
        external_chat_provider="opencode",
        external_chat_lookup_hash="c" * 64,
        encrypted_external_chat_id="cipher-session-id",
    ))

    assert openmates.assignee_identity == "openmates"
    assert opencode.assignee_identity == "opencode"

    with pytest.raises(ValidationError):
        user_tasks.UserTaskCreateRequest(**task_payload(
            assignee_type="external_ai",
            assignee_identity="openmates",
            assignee_hash=None,
        ))

    with pytest.raises(ValidationError):
        user_tasks.UserTaskCreateRequest(**task_payload(
            assignee_type="user",
            assignee_identity="opencode",
        ))


# contract-test: direct surface=rest_api assertions=tasks.assignment.identity-separated
@pytest.mark.asyncio
async def test_create_task_persists_named_external_ai_identity() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1"}))
    methods = UserTaskMethods(with_lock_cache(directus))

    await methods.create_task("user-1", task_payload(
        primary_chat_id=None,
        assignee_type="external_ai",
        assignee_identity="opencode",
        assignee_hash=None,
        external_chat_provider="opencode",
        external_chat_lookup_hash="c" * 64,
        encrypted_external_chat_id="cipher-session-id",
    ))

    _collection, record = directus.create_item.await_args_list[0].args
    assert record["assignee_type"] == "external_ai"
    assert record["assignee_identity"] == "opencode"
    assert record["assignee_hash"] is None


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted
@pytest.mark.asyncio
async def test_create_task_persists_label_hashes_and_priority_metadata() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1", **task_payload()}))

    methods = UserTaskMethods(with_lock_cache(directus))
    await methods.create_task("user-1", task_payload(label_hashes=[LABEL_HASH_A, LABEL_HASH_B], priority=4))

    _collection, record = directus.create_item.await_args.args
    assert record["label_hashes"] == [LABEL_HASH_A, LABEL_HASH_B]
    assert record["priority"] == 4
    assert "labels" not in record


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted,tasks.external-chat.encrypted-context
@pytest.mark.asyncio
async def test_create_external_chat_task_persists_only_encrypted_context_and_blind_index() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1", **task_payload(primary_chat_id=None)}))
    external_lookup_hash = "c" * 64

    methods = UserTaskMethods(with_lock_cache(directus))
    await methods.create_task("user-1", task_payload(
        primary_chat_id=None,
        external_chat_provider="opencode",
        external_chat_lookup_hash=external_lookup_hash,
        encrypted_external_chat_id="cipher-session-id",
        encrypted_external_chat_title="cipher-session-title",
    ))

    _collection, record = directus.create_item.await_args.args
    assert record["primary_chat_id"] is None
    assert record["hashed_primary_chat_id"] is None
    assert record["external_chat_provider"] == "opencode"
    assert record["external_chat_lookup_hash"] == external_lookup_hash
    assert record["encrypted_external_chat_id"] == "cipher-session-id"
    assert record["encrypted_external_chat_title"] == "cipher-session-title"
    assert "external_chat_id" not in record
    assert "external_chat_title" not in record


# contract-test: direct surface=rest_api assertions=tasks.external-chat.encrypted-context
@pytest.mark.asyncio
async def test_create_task_rejects_native_and_external_chat_context_together() -> None:
    methods = UserTaskMethods(with_lock_cache(SimpleNamespace()))

    with pytest.raises(ValueError, match="native or external chat"):
        await methods.create_task("user-1", task_payload(
            external_chat_provider="opencode",
            external_chat_lookup_hash="c" * 64,
            encrypted_external_chat_id="cipher-session-id",
        ))


# contract-test: direct surface=rest_api assertions=tasks.external-chat.encrypted-context
@pytest.mark.asyncio
async def test_list_tasks_filters_external_chat_provider_and_blind_index() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    methods = UserTaskMethods(with_lock_cache(directus))

    await methods.list_tasks(
        "user-1",
        external_chat_provider="opencode",
        external_chat_lookup_hash="c" * 64,
    )

    filter_terms = directus.get_items.await_args.kwargs["params"]["filter"]["_and"]
    assert {"external_chat_provider": {"_eq": "opencode"}} in filter_terms
    assert {"external_chat_lookup_hash": {"_eq": "c" * 64}} in filter_terms


# contract-test: supporting surface=rest_api assertions=tasks.external-chat.encrypted-context
def test_user_task_external_chat_index_is_owner_scoped() -> None:
    migration = Path(__file__).parents[1] / "core/directus/setup/migrate_user_task_indexes.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE INDEX IF NOT EXISTS user_tasks_owner_external_chat_idx" in sql
    assert "ON user_tasks (hashed_user_id, external_chat_provider, external_chat_lookup_hash, position, created_at)" in sql
    assert "WHERE hashed_team_id IS NULL" in sql


# contract-test: direct surface=rest_api assertions=tasks.external-chat.encrypted-context
@pytest.mark.asyncio
async def test_update_task_rejects_incomplete_or_native_external_chat_context() -> None:
    existing = {
        "id": "task-row",
        **task_payload(primary_chat_id=None),
        "external_chat_provider": "opencode",
        "external_chat_lookup_hash": "c" * 64,
        "encrypted_external_chat_id": "cipher-session-id",
    }
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item_if_version = AsyncMock()
    methods = UserTaskMethods(with_lock_cache(directus))

    with pytest.raises(ValueError, match="native or external chat"):
        await methods.update_task("task-1", "user-1", {"version": 1, "primary_chat_id": "chat-1"})

    with pytest.raises(ValueError, match="requires an encrypted external id"):
        await methods.update_task("task-1", "user-1", {"version": 1, "encrypted_external_chat_id": None})

    directus.update_item_if_version.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.blocking.encrypted-reason
@pytest.mark.asyncio
async def test_directus_task_updates_preserve_legacy_and_runtime_blocked_reason_codes() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "task-row", "task_id": "task-1", "version": 1}])
    directus.update_item_if_version = AsyncMock(return_value={"id": "task-row", "task_id": "task-1", "version": 2})
    methods = UserTaskMethods(with_lock_cache(directus))

    updated = await methods.update_task("task-1", "user-1", {"version": 1, "blocked_reason_code": "ai_dispatch_failed"})

    assert updated is not None
    assert directus.update_item_if_version.await_args.args[2]["blocked_reason_code"] == "ai_dispatch_failed"


# contract-test: direct surface=rest_api assertions=tasks.blocking.encrypted-reason
def test_task_request_models_reject_unapproved_blocked_reason_codes() -> None:
    with pytest.raises(ValueError, match="needs_user_input"):
        user_tasks.UserTaskUpdateRequest(version=1, blocked_reason_code="needs_input")

    assert user_tasks.UserTaskActionRequest(version=1, blocked_reason_code="missing_credentials").blocked_reason_code == "missing_credentials"


# contract-test: direct surface=rest_api assertions=tasks.external-chat.encrypted-context
@pytest.mark.asyncio
async def test_list_route_returns_bad_request_for_partial_external_chat_filter(monkeypatch) -> None:
    async def current_user(_request, _response):
        return SimpleNamespace(id="user-1")

    monkeypatch.setattr(user_tasks, "_current_user", current_user)
    service = SimpleNamespace(list_tasks=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(HTTPException) as exc_info:
        await user_tasks.list_user_tasks(
            request,
            SimpleNamespace(),
            external_chat_provider="opencode",
            service=service,
            workflow_projection_service=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Task external chat filters require both provider and lookup hash"
    service.list_tasks.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.external-chat.encrypted-context,tasks.key-wrappers.context-scoped
@pytest.mark.asyncio
async def test_external_chat_task_allows_master_wrapper_but_rejects_chat_wrapper() -> None:
    external_task = task_payload(
        primary_chat_id=None,
        linked_project_ids=[],
        encrypted_linked_project_ids=None,
        external_chat_provider="opencode",
        external_chat_lookup_hash="c" * 64,
        encrypted_external_chat_id="cipher-session-id",
    )
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=lambda _collection, record, **_kwargs: (True, {"id": "row", **record}))
    methods = UserTaskMethods(with_lock_cache(directus))

    created = await methods.create_task(
        "user-1",
        {**external_task, "key_wrappers": [{"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 100}]},
    )

    assert created is not None

    invalid_directus = SimpleNamespace()
    invalid_directus.create_item = AsyncMock()
    invalid_methods = UserTaskMethods(with_lock_cache(invalid_directus))
    rejected = await invalid_methods.create_task(
        "user-1",
        {
            **external_task,
            "key_wrappers": [
                {"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 100},
                {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_task_key": "cipher-chat", "created_at": 100},
            ],
        },
    )

    assert rejected is None
    invalid_directus.create_item.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.external-chat.encrypted-context,tasks.key-wrappers.context-scoped
@pytest.mark.asyncio
async def test_update_task_can_switch_external_context_to_native_when_all_external_fields_are_cleared() -> None:
    existing = {
        "id": "task-row",
        **task_payload(primary_chat_id=None),
        "external_chat_provider": "opencode",
        "external_chat_lookup_hash": "c" * 64,
        "encrypted_external_chat_id": "cipher-session-id",
        "encrypted_external_chat_title": "cipher-session-title",
        "linked_project_hashes": [hash_id("project-1")],
    }
    wrappers = [{"id": "old-master", "key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 100}]
    replacement_wrappers = [
        {"key_type": "master", "encrypted_task_key": "cipher-master-v2", "created_at": 200},
        {"key_type": "chat", "hashed_chat_id": hash_id("chat-1"), "encrypted_task_key": "cipher-chat", "created_at": 200},
        {"key_type": "project", "hashed_project_id": hash_id("project-1"), "encrypted_task_key": "cipher-project", "created_at": 200},
    ]
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[[existing], wrappers])
    directus.create_item = AsyncMock(side_effect=lambda _collection, record, **_kwargs: (True, {"id": "new-wrapper", **record}))
    directus.delete_item = AsyncMock(return_value=True)
    directus.update_item_if_version = AsyncMock(return_value={"id": "task-row", "task_id": "task-1", "version": 2})
    methods = UserTaskMethods(with_lock_cache(directus))

    updated = await methods.update_task(
        "task-1",
        "user-1",
        {
            "version": 1,
            "primary_chat_id": "chat-1",
            "external_chat_provider": None,
            "external_chat_lookup_hash": None,
            "encrypted_external_chat_id": None,
            "encrypted_external_chat_title": None,
            "key_wrappers": replacement_wrappers,
        },
    )

    assert updated is not None
    persisted = directus.update_item_if_version.await_args.args[2]
    assert persisted["hashed_primary_chat_id"] == hash_id("chat-1")
    assert persisted["external_chat_provider"] is None
    assert persisted["external_chat_lookup_hash"] is None
    assert persisted["encrypted_external_chat_id"] is None
    assert persisted["encrypted_external_chat_title"] is None


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted,tasks.surface.semantic-parity
@pytest.mark.asyncio
async def test_list_tasks_filters_labels_with_and_semantics_and_priority() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    methods = UserTaskMethods(with_lock_cache(directus))
    await methods.list_tasks("user-1", label_hashes=[LABEL_HASH_A, LABEL_HASH_B], priority=3)

    params = directus.get_items.await_args.kwargs["params"]
    filter_terms = params["filter"]["_and"]
    assert {"label_hashes": {"_contains": LABEL_HASH_A}} in filter_terms
    assert {"label_hashes": {"_contains": LABEL_HASH_B}} in filter_terms
    assert {"priority": {"_eq": 3}} in filter_terms


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted
@pytest.mark.asyncio
async def test_task_label_hashes_must_be_valid_blind_indexes() -> None:
    methods = UserTaskMethods(with_lock_cache(SimpleNamespace()))

    with pytest.raises(ValueError, match="label hashes"):
        await methods.list_tasks("user-1", label_hashes=["not-a-hash"])


# contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
def test_task_short_id_matches_cli_derivation() -> None:
    task = {"task_id": "123e4567-e89b-12d3-a456-426614174000"}

    assert derive_task_short_id(task) == "TASK-9020"


# contract-test: direct surface=rest_api assertions=tasks.surface.semantic-parity
@pytest.mark.asyncio
async def test_task_short_id_lookup_rejects_ambiguous_collisions() -> None:
    methods = UserTaskMethods(SimpleNamespace())
    methods.list_tasks = AsyncMock(return_value=[
        {"task_id": "task-1", "short_id": "TASK-1234"},
        {"task_id": "task-2", "short_id": "TASK-1234"},
    ])

    assert await methods.get_task_by_short_id("TASK-1234", "user-1") is None


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible
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


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted,tasks.lifecycle.visible
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


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.project-links.encrypted,tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.project-links.encrypted,tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.project-links.encrypted,tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_delete_task_rejects_stale_version_and_uses_lock() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "task-row", "task_id": "task-1", "version": 2}])
    directus.delete_item = AsyncMock()

    methods = UserTaskMethods(with_lock_cache(directus))
    deleted = await methods.delete_task("task-1", "user-1", 1)

    assert deleted is False
    directus.delete_item.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_delete_task_deletes_when_expected_version_matches() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "task-row", "task_id": "task-1", "version": 2}])
    directus.delete_item = AsyncMock(return_value=True)

    methods = UserTaskMethods(with_lock_cache(directus))
    deleted = await methods.delete_task("task-1", "user-1", 2)

    assert deleted is True
    directus.delete_item.assert_awaited_once_with("user_tasks", "task-row")


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible
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


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted,tasks.project-links.encrypted,tasks.surface.semantic-parity
@pytest.mark.asyncio
async def test_list_tasks_filters_by_chat_and_project_hashes() -> None:
    project_hash = hash_id("project-1")
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[
        {"task_id": "task-1", "linked_project_hashes": [project_hash]},
        {"task_id": "task-2", "linked_project_hashes": [hash_id("project-2")]},
    ])

    methods = UserTaskMethods(directus)
    tasks = await methods.list_tasks("user-1", chat_id="chat-1", project_id="project-1", status="todo")

    params = directus.get_items.await_args.kwargs["params"]
    filter_terms = params["filter"]["_and"]
    assert {"hashed_user_id": {"_eq": hash_id("user-1")}} in filter_terms
    assert {"hashed_primary_chat_id": {"_eq": hash_id("chat-1")}} in filter_terms
    assert {"linked_project_hashes": {"_contains": project_hash}} not in filter_terms
    assert {"status": {"_eq": "todo"}} in filter_terms
    assert params["limit"] == -1
    assert [task["task_id"] for task in tasks] == ["task-1"]


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_update_rejects_stale_client_version() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "row-1", "version": 3, "task_id": "task-1"}])
    directus.update_item_if_version = AsyncMock(return_value={"id": "row-1", "version": 4, "task_id": "task-1"})

    service = UserTaskService(UserTaskMethods(with_lock_cache(directus)))

    with pytest.raises(UserTaskConflictError):
        await service.update_task("task-1", "user-1", {"status": "done", "version": 2})

    directus.update_item_if_version.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.project-links.encrypted,tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible
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


# contract-test: direct surface=rest_api assertions=tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.project-links.encrypted,tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.project-links.encrypted,tasks.key-wrappers.context-scoped
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


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_ai_task_without_execution_context_waits_without_consuming_capacity() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.create_item = AsyncMock(side_effect=lambda _collection, record: (True, record))

    admission = AsyncMock()
    service = UserTaskService(UserTaskMethods(directus), admission_service=admission)
    created = await service.create_task("user-1", task_payload(assignee_type="openmates", assignee_identity="openmates", due_at=None))

    assert created["status"] == "todo"
    assert created["ai_execution_state"] == "waiting_for_capacity"
    admission.admit_available.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted,tasks.lifecycle.visible,tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_ai_task_create_with_transient_context_claims_and_dispatches() -> None:
    created = {**task_payload(assignee_type="openmates", assignee_identity="openmates"), "id": "row-1", "version": 1}
    queued = {**created, "status": "todo", "queue_state": "waiting", "ai_execution_state": "waiting_for_capacity", "version": 2}
    admitted = {**queued, "status": "in_progress", "queue_state": "active", "ai_execution_state": "queued", "version": 3}
    methods = AsyncMock()
    methods.create_task.return_value = created
    methods.get_task.return_value = created
    methods.update_task_if_version.return_value = queued
    admission = AsyncMock()
    admission.admit_available.return_value = {"admitted_tasks": [admitted]}
    dispatcher = AsyncMock(return_value={"task_id": "ai-run-1"})
    cache = SimpleNamespace(set_active_ai_task=AsyncMock())
    service = UserTaskService(methods, admission_service=admission, ai_dispatcher=dispatcher, cache_service=cache)

    result = await service.create_task(
        "user-1",
        task_payload(assignee_type="openmates", assignee_identity="openmates", plaintext_title="Draft launch plan"),
    )

    assert result["status"] == "in_progress"
    assert "plaintext_title" not in methods.create_task.await_args.args[1]
    dispatcher.assert_awaited_once()
    cache.set_active_ai_task.assert_awaited_once_with("chat-1", "ai-run-1")


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_second_ai_task_without_due_date_waits_for_active_chat_task() -> None:
    active_other = {"id": "row-2", "version": 1, **task_payload(task_id="task-2", status="in_progress", assignee_type="openmates", assignee_identity="openmates")}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[active_other])
    directus.create_item = AsyncMock(side_effect=lambda _collection, record: (True, record))

    admission = AsyncMock()
    admission.admit_available.return_value = {"admitted_tasks": []}
    service = UserTaskService(UserTaskMethods(directus), admission_service=admission)
    created = await service.create_task("user-1", task_payload(assignee_type="openmates", assignee_identity="openmates", due_at=None))

    assert created["status"] == "todo"
    assert created["ai_execution_state"] == "waiting_for_capacity"
    assert "started_at" not in created


# contract-test: direct surface=rest_api assertions=tasks.surface.semantic-parity
@pytest.mark.asyncio
async def test_product_task_helpers_do_not_use_celery_tasks_collection() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    methods = UserTaskMethods(directus)
    await methods.list_tasks("user-1")

    collection = directus.get_items.await_args.args[0]
    assert collection == "user_tasks"
    assert collection != "tasks"


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted,tasks.lifecycle.visible
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
        admission_service=AsyncMock(),
    )
    service.admission_service.admit_available.return_value = {
        "admitted_tasks": [{**existing, "status": "in_progress", "ai_execution_state": "queued", "version": 4}]
    }

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
    assert persisted_patch["status"] == "todo"
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


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_start_ai_waits_when_another_task_is_active_in_same_chat() -> None:
    existing = {**task_payload(task_id="task-1"), "id": "row-1", "version": 2}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item_if_version = AsyncMock(
        side_effect=lambda _collection, _row_id, patch, _expected_version, **_kwargs: {**existing, **patch, "version": 3}
    )

    admission = AsyncMock()
    admission.admit_available.return_value = {"admitted_tasks": []}
    service = UserTaskService(UserTaskMethods(with_lock_cache(directus)), admission_service=admission)

    waiting = await service.start_ai(
        "task-1",
        "user-1",
        {
            "version": 2,
            "primary_chat_id": "chat-1",
            "plaintext_title": "Do this after the active task",
            "updated_at": 200,
        },
    )

    assert waiting["status"] == "todo"
    assert waiting["ai_execution_state"] == "waiting_for_capacity"
    directus.update_item_if_version.assert_awaited_once()


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_team_start_ai_scopes_update_admission_and_dispatch_payload() -> None:
    team_id = "team-1"
    existing = {
        **task_payload(task_id="team-task"),
        "id": "row-1",
        "version": 2,
        "hashed_team_id": hash_id(team_id),
    }
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item_if_version = AsyncMock(
        side_effect=lambda _collection, _row_id, patch, _expected_version, **_kwargs: {**existing, **patch, "version": 3}
    )
    dispatched: dict[str, object] = {}

    async def fake_dispatcher(app_id: str, skill_id: str, payload: dict[str, object]) -> dict[str, str]:
        dispatched.update({"app_id": app_id, "skill_id": skill_id, "payload": payload})
        return {"task_id": "ai-team-run-1"}

    admission = AsyncMock()
    admission.admit_available.return_value = {
        "admitted_tasks": [{**existing, "status": "in_progress", "ai_execution_state": "queued", "version": 4}]
    }
    service = UserTaskService(
        UserTaskMethods(with_lock_cache(directus)),
        ai_dispatcher=fake_dispatcher,
        admission_service=admission,
    )

    await service.start_ai(
        "team-task",
        "actor-1",
        {
            "version": 2,
            "primary_chat_id": "chat-1",
            "plaintext_title": "Run Team task",
            "updated_at": 200,
        },
        team_id=team_id,
    )

    assert directus.update_item_if_version.await_args.kwargs == {
        "owner_hash_field": "hashed_team_id",
        "owner_hash": hash_id(team_id),
    }
    admission.admit_available.assert_awaited_once_with(
        "actor-1",
        team_id=team_id,
        now=200,
        preferred_chat_id="chat-1",
    )
    payload = dispatched["payload"]
    assert isinstance(payload, dict)
    assert payload["team_id"] == team_id
    assert payload["team_id_hash"] == hash_id(team_id)


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_team_task_updates_share_one_team_scoped_write_lock() -> None:
    methods = UserTaskMethods(SimpleNamespace())
    methods._acquire_task_lock = AsyncMock(return_value="lock-token")
    methods._release_task_lock = AsyncMock()
    methods.get_task = AsyncMock(return_value={"task_id": "team-task", "version": 1})
    methods._update_task_unlocked = AsyncMock(return_value={"task_id": "team-task", "version": 2})

    await methods.update_task_if_version("team-task", "member-1", {"status": "done"}, 1, team_id="team-1")
    await methods.update_task_if_version("team-task", "member-2", {"status": "done"}, 1, team_id="team-1")

    lock_keys = [call.args[0] for call in methods._acquire_task_lock.await_args_list]
    assert lock_keys == [lock_keys[0], lock_keys[0]]
    assert hash_id("team-1") in lock_keys[0]


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.content.client-encrypted
@pytest.mark.asyncio
async def test_start_ai_stages_execution_context_before_becoming_admission_eligible() -> None:
    existing = {**task_payload(task_id="task-1"), "version": 2}
    events: list[str] = []
    methods = AsyncMock()
    methods.get_task.return_value = existing

    async def update_side_effect(_task_id, _user_id, patch, _version, **_kwargs):
        events.append(str(patch["queue_state"]))
        return {**existing, **patch, "version": 3 if patch["queue_state"] == "staging" else 4}

    methods.update_task_if_version.side_effect = update_side_effect
    methods.create_task_execution_context.side_effect = lambda **_kwargs: events.append("context_staged") or {"id": "context-1"}
    encryption = AsyncMock()
    encryption.encrypt.return_value = ("vault:v1:ciphertext", "v1")
    admission = AsyncMock()

    async def admit_side_effect(*_args, **_kwargs):
        events.append("admission")
        return {"admitted_tasks": []}

    admission.admit_available.side_effect = admit_side_effect
    service = UserTaskService(methods, encryption_service=encryption, admission_service=admission)

    await service.start_ai(
        "task-1",
        "user-1",
        {"version": 2, "primary_chat_id": "chat-1", "plaintext_title": "Do the work", "updated_at": 200},
    )

    assert events == ["staging", "context_staged", "waiting", "admission"]


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_start_ai_staging_failure_moves_task_to_visible_blocked_state() -> None:
    existing = {**task_payload(task_id="task-1"), "version": 2}
    staging = {**existing, "queue_state": "staging", "ai_execution_state": "preparing_execution_context", "version": 3}
    methods = AsyncMock()
    methods.get_task.side_effect = [existing, staging]
    methods.update_task_if_version.side_effect = [staging, {**staging, "status": "blocked", "version": 4}]
    methods.create_task_execution_context.side_effect = RuntimeError("context store unavailable")
    encryption = AsyncMock()
    encryption.encrypt.return_value = ("vault:v1:ciphertext", "v1")
    service = UserTaskService(methods, encryption_service=encryption, admission_service=AsyncMock())

    with pytest.raises(RuntimeError, match="context store unavailable"):
        await service.start_ai(
            "task-1",
            "user-1",
            {"version": 2, "primary_chat_id": "chat-1", "plaintext_title": "Do the work", "updated_at": 200},
        )

    failure_patch = methods.update_task_if_version.await_args_list[-1].args[2]
    assert failure_patch["status"] == "blocked"
    assert failure_patch["blocked_reason_code"] == "execution_context_staging_failed"
