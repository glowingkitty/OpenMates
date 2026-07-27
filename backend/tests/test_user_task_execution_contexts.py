"""Tests for short-lived user task execution contexts.

Execution contexts are only a transient bridge for AI task queue continuation.
They must be owner/chat/task scoped by hashes and must not add durable plaintext
task titles, descriptions, instructions, or activity text to Directus.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods, hash_id


@pytest.mark.asyncio
async def test_create_task_execution_context_stores_hashes_and_encrypted_context_only() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"id": "ctx-1"}))

    created = await UserTaskMethods(directus).create_task_execution_context(
        user_id="user-1",
        task_id="task-1",
        chat_id="chat-1",
        encrypted_context="vault:ciphertext",
        created_at=100,
        expires_at=160,
    )

    assert created == {"id": "ctx-1"}
    collection, record = directus.create_item.await_args.args
    assert collection == "user_task_execution_contexts"
    assert directus.create_item.await_args.kwargs["admin_required"] is True
    assert record == {
        "hashed_user_id": hash_id("user-1"),
        "hashed_task_id": hash_id("task-1"),
        "hashed_chat_id": hash_id("chat-1"),
        "encrypted_context": "vault:ciphertext",
        "created_at": 100,
        "expires_at": 160,
    }
    assert "user-1" not in record.values()
    assert "chat-1" not in record.values()
    assert "task-1" not in record.values()


@pytest.mark.asyncio
async def test_get_task_execution_context_filters_by_owner_task_chat_and_expiry() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "ctx-1", "encrypted_context": "vault:ciphertext"}])

    context = await UserTaskMethods(directus).get_task_execution_context(
        user_id="user-1",
        task_id="task-1",
        chat_id="chat-1",
        now=120,
    )

    assert context == {"id": "ctx-1", "encrypted_context": "vault:ciphertext"}
    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[hashed_user_id][_eq]"] == hash_id("user-1")
    assert params["filter[hashed_task_id][_eq]"] == hash_id("task-1")
    assert params["filter[hashed_chat_id][_eq]"] == hash_id("chat-1")
    assert params["filter[expires_at][_gt]"] == 120
    assert params["sort"] == "-created_at"


@pytest.mark.asyncio
async def test_expired_task_execution_context_cleanup_deletes_limited_rows() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "ctx-1"}, {"id": "ctx-2"}])
    directus.delete_item = AsyncMock(return_value=True)

    deleted = await UserTaskMethods(directus).delete_expired_task_execution_contexts(200, limit=2)

    assert deleted == 2
    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[expires_at][_lte]"] == 200
    assert params["limit"] == 2
    assert [call.args for call in directus.delete_item.await_args_list] == [
        ("user_task_execution_contexts", "ctx-1"),
        ("user_task_execution_contexts", "ctx-2"),
    ]
    assert all(call.kwargs["admin_required"] is True for call in directus.delete_item.await_args_list)


@pytest.mark.asyncio
async def test_task_execution_context_rejects_non_expiring_payload() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock()

    with pytest.raises(ValueError, match="expire after creation"):
        await UserTaskMethods(directus).create_task_execution_context(
            user_id="user-1",
            task_id="task-1",
            chat_id="chat-1",
            encrypted_context="vault:ciphertext",
            created_at=100,
            expires_at=100,
        )

    directus.create_item.assert_not_awaited()
