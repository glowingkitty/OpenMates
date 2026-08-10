"""Tests for encrypted user tasks in shared chat bundles.

Shared chats may include chat-primary task records, but the server never receives
URL-fragment key material and never creates persistent share-specific task key
wrappers. Only encrypted task fields and existing chat-scoped task key wrappers
are exposed for client-side decryption.
"""

import hashlib

import pytest

from backend.core.api.app.services.user_task_share_bundle import get_shared_chat_tasks


class FakeDirectusService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], bool]] = []
        self.created: list[tuple[str, dict[str, object]]] = []

    async def get_items(self, collection: str, *, params: dict[str, object], admin_required: bool = False, **_kwargs):
        self.calls.append((collection, params, admin_required))
        if collection == "user_tasks":
            return [
                {
                    "task_id": "task-chat",
                    "primary_chat_id": "chat-1",
                    "status": "todo",
                    "encrypted_title": "cipher-title",
                    "encrypted_description": "cipher-description",
                    "encrypted_tags": "cipher-tags",
                    "encrypted_linked_project_ids": "cipher-projects",
                }
            ]
        if collection == "user_task_key_wrappers":
            return [
                {
                    "hashed_task_id": hashlib.sha256("task-chat".encode()).hexdigest(),
                    "key_type": "chat",
                    "hashed_chat_id": hashlib.sha256("chat-1".encode()).hexdigest(),
                    "encrypted_task_key": "cipher-task-key-for-chat",
                    "created_at": 100,
                }
            ]
        return []

    async def create_item(self, collection: str, record: dict[str, object], **_kwargs):
        self.created.append((collection, record))
        return True, record


@pytest.mark.asyncio
async def test_shared_chat_tasks_include_encrypted_records_and_chat_key_wrappers_only() -> None:
    directus = FakeDirectusService()
    hashed_chat_id = hashlib.sha256("chat-1".encode()).hexdigest()

    payload = await get_shared_chat_tasks("chat-1", hashed_chat_id, directus)  # type: ignore[arg-type]

    assert payload["tasks"] == [
        {
            "task_id": "task-chat",
            "primary_chat_id": "chat-1",
            "status": "todo",
            "encrypted_title": "cipher-title",
            "encrypted_description": "cipher-description",
            "encrypted_tags": "cipher-tags",
            "encrypted_linked_project_ids": "cipher-projects",
        }
    ]
    assert payload["task_key_wrappers"] == [
        {
            "hashed_task_id": hashlib.sha256("task-chat".encode()).hexdigest(),
            "key_type": "chat",
            "hashed_chat_id": hashed_chat_id,
            "encrypted_task_key": "cipher-task-key-for-chat",
            "created_at": 100,
        }
    ]
    assert directus.created == []
    task_call = directus.calls[0]
    assert task_call[0] == "user_tasks"
    assert task_call[1]["filter[hashed_primary_chat_id][_eq]"] == hashed_chat_id
    assert "fragment" not in str(directus.calls).lower()
    wrapper_call = directus.calls[1]
    assert wrapper_call[0] == "user_task_key_wrappers"
    assert wrapper_call[1]["filter[key_type][_eq]"] == "chat"
    assert wrapper_call[1]["filter[hashed_chat_id][_eq]"] == hashed_chat_id
