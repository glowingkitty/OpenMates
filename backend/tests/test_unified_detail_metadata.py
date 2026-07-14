"""Red contracts for unified detail-page metadata writes.

These tests keep metadata persistence in each owning domain while requiring one
shared security property: writes are owner-scoped and accepted updates receive
server-authoritative monotonic versions. Client-encrypted domains must persist
only ciphertext; Workflow metadata remains inside its Automation Vault boundary.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import (
    encrypted_chat_metadata_handler,
    title_update_handler,
)
from backend.core.api.app.routes.handlers.websocket_handlers.encrypted_chat_metadata_handler import (
    handle_encrypted_chat_metadata,
)
from backend.core.api.app.routes.handlers.websocket_handlers.title_update_handler import (
    handle_update_title,
)
from backend.core.api.app.tasks import persistence_tasks
from backend.core.api.app.services.directus.project_methods import ProjectMethods, hash_id
from backend.core.api.app.services.user_plan_service import UserPlanNotFoundError, UserPlanService
from backend.core.api.app.services.user_task_service import UserTaskNotFoundError, UserTaskService
from backend.core.api.app.services.workflow_service import WorkflowNotFoundError
from backend.tests.workflow_test_utils import workflow_service


class OwnerScopedMetadataMethods:
    """Minimal task/plan repository double that never invents server versions."""

    def __init__(self, item_id_field: str, item_id: str) -> None:
        self.item_id_field = item_id_field
        self.item_id = item_id
        self.record = {
            "id": "row-1",
            item_id_field: item_id,
            "version": 4,
            "updated_at": 900,
            "encrypted_title": "cipher-title-v4",
        }
        self.patches: list[dict[str, object]] = []

    async def _get(self, item_id: str, user_id: str) -> dict[str, object] | None:
        if item_id != self.item_id or user_id != "owner-1":
            return None
        return dict(self.record)

    async def get_task(self, task_id: str, user_id: str) -> dict[str, object] | None:
        return await self._get(task_id, user_id)

    async def get_plan(self, plan_id: str, user_id: str) -> dict[str, object] | None:
        return await self._get(plan_id, user_id)

    async def _update(self, item_id: str, user_id: str, patch: dict[str, object]) -> dict[str, object] | None:
        if item_id != self.item_id or user_id != "owner-1":
            return None
        self.patches.append(dict(patch))
        self.record.update(patch)
        return dict(self.record)

    async def update_task(self, task_id: str, user_id: str, patch: dict[str, object]) -> dict[str, object] | None:
        return await self._update(task_id, user_id, patch)

    async def update_plan(self, plan_id: str, user_id: str, patch: dict[str, object]) -> dict[str, object] | None:
        return await self._update(plan_id, user_id, patch)


class ChatMetadataManager:
    def __init__(self) -> None:
        self.personal_messages: list[tuple[dict, str, str]] = []
        self.broadcasts: list[tuple[dict, str, str | None]] = []

    async def send_personal_message(
        self, message: dict, user_id: str, device_hash: str
    ) -> None:
        self.personal_messages.append((message, user_id, device_hash))

    async def broadcast_to_user(
        self,
        message: dict,
        user_id: str,
        exclude_device_hash: str | None = None,
    ) -> None:
        self.broadcasts.append((message, user_id, exclude_device_hash))


class ChatMetadataDirectus:
    def __init__(self, *, is_owner: bool) -> None:
        self.chat = SimpleNamespace(
            check_chat_ownership=AsyncMock(return_value=is_owner),
            get_chat_metadata=AsyncMock(
                return_value={
                    "hashed_user_id": "different-owner-hash",
                    "messages_v": 12,
                    "title_v": 7,
                    "metadata_v": 4,
                    "encrypted_title": "cipher-title-v7",
                    "encrypted_chat_summary": "cipher-summary-v4",
                }
            ),
        )


class ChatMetadataCache:
    async def get_chat_list_item_data(self, _user_id: str, _chat_id: str):
        return None


class TitleUpdateCache:
    def __init__(self) -> None:
        self.fields: list[tuple[str, str, str, str]] = []

    async def update_chat_list_item_field(
        self,
        user_id: str,
        chat_id: str,
        field: str,
        value: str,
    ) -> bool:
        self.fields.append((user_id, chat_id, field, value))
        return True


class TitleUpdateDirectus:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(
            get_chat_metadata=AsyncMock(
                return_value={
                    "messages_v": 3,
                    "title_v": 4,
                    "metadata_v": 4,
                }
            )
        )


def chat_metadata_payload(**overrides: object) -> dict[str, object]:
    return {
        "chat_id": "chat-1",
        "versions": {"metadata_v": 4, "title_v": 7, "messages_v": 12},
        **overrides,
    }


async def send_chat_metadata(
    payload: dict[str, object],
    *,
    is_owner: bool,
) -> ChatMetadataManager:
    manager = ChatMetadataManager()
    await handle_encrypted_chat_metadata(
        websocket=None,
        manager=manager,
        cache_service=ChatMetadataCache(),
        directus_service=ChatMetadataDirectus(is_owner=is_owner),
        encryption_service=None,
        user_id="owner-1" if is_owner else "read-only-user",
        user_id_hash="owner-hash",
        device_fingerprint_hash="device-1",
        payload=payload,
    )
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service_type", "methods_id_field", "item_id", "update_name", "not_found_error", "encrypted_description_field"),
    [
        (UserTaskService, "task_id", "task-1", "update_task", UserTaskNotFoundError, "encrypted_description"),
        (UserPlanService, "plan_id", "plan-1", "update_plan", UserPlanNotFoundError, "encrypted_summary"),
    ],
)
async def test_task_and_plan_metadata_versions_are_owner_scoped_and_server_monotonic(
    service_type,
    methods_id_field: str,
    item_id: str,
    update_name: str,
    not_found_error,
    encrypted_description_field: str,
) -> None:
    methods = OwnerScopedMetadataMethods(methods_id_field, item_id)
    service = service_type(methods)
    update = getattr(service, update_name)

    with pytest.raises(not_found_error):
        await update(item_id, "read-only-user", {"version": 4, "encrypted_title": "forged-ciphertext"})

    first = await update(
        item_id,
        "owner-1",
        {
            "version": 4,
            "updated_at": 100,
            "encrypted_title": "cipher-title-v5",
            encrypted_description_field: "cipher-description-v5",
        },
    )
    second = await update(
        item_id,
        "owner-1",
        {
            "version": 5,
            "updated_at": 50,
            "encrypted_title": "cipher-title-v6",
        },
    )

    assert first["version"] == 5
    assert second["version"] == 6
    assert methods.patches[0]["version"] == 5
    assert methods.patches[1]["version"] == 6
    assert methods.record["encrypted_title"] == "cipher-title-v6"
    assert "title" not in methods.record
    assert "description" not in methods.record
    assert "summary" not in methods.record


@pytest.mark.asyncio
async def test_project_metadata_version_is_owner_scoped_and_ignores_client_clock_ordering() -> None:
    owner_hash = hash_id("owner-1")
    record = {
        "id": "row-1",
        "project_id": "project-1",
        "hashed_user_id": owner_hash,
        "version": 4,
        "updated_at": 900,
        "encrypted_name": "cipher-name-v4",
    }

    async def get_items(_collection, *, params, **_kwargs):
        if params.get("filter[hashed_user_id][_eq]") != owner_hash:
            return []
        return [dict(record)]

    async def update_item(_collection, _row_id, patch):
        record.update(patch)
        return dict(record)

    directus = SimpleNamespace(
        get_items=AsyncMock(side_effect=get_items),
        update_item=AsyncMock(side_effect=update_item),
    )
    methods = ProjectMethods(directus)

    assert await methods.update_project("project-1", "read-only-user", {"encrypted_name": "forged"}) is None
    updated = await methods.update_project(
        "project-1",
        "owner-1",
        {
            "version": 4,
            "updated_at": 100,
            "encrypted_name": "cipher-name-v5",
            "encrypted_description": "cipher-description-v5",
        },
    )

    assert updated is not None
    assert updated["version"] == 5
    persisted_patch = directus.update_item.await_args.args[2]
    assert persisted_patch["version"] == 5
    assert persisted_patch["encrypted_name"] == "cipher-name-v5"
    assert "name" not in persisted_patch
    assert "description" not in persisted_patch


@pytest.mark.parametrize(
    "mutation",
    [
        {"encrypted_title": "cipher-title-v8"},
        {"encrypted_chat_summary": "cipher-summary-v5"},
    ],
)
def test_chat_title_and_summary_mutations_are_owner_only(
    monkeypatch,
    mutation: dict[str, str],
) -> None:
    queued_tasks: list[tuple[str, list, str | None]] = []
    monkeypatch.setattr(
        encrypted_chat_metadata_handler.celery_app,
        "send_task",
        lambda name, args=None, queue=None: queued_tasks.append((name, args or [], queue)),
    )

    manager = asyncio.run(
        send_chat_metadata(chat_metadata_payload(**mutation), is_owner=False)
    )

    assert queued_tasks == []
    assert manager.broadcasts == []
    assert manager.personal_messages[0][0]["type"] == "error"


@pytest.mark.parametrize(
    ("mutation", "expected_title_v"),
    [
        (
            {
                "encrypted_title": "cipher-title-v8",
                "encrypted_chat_summary": "cipher-summary-v5",
                "title": "plaintext title must be ignored",
                "chat_summary": "plaintext summary must be ignored",
            },
            8,
        ),
        (
            {
                "encrypted_chat_summary": "cipher-summary-v5",
                "chat_summary": "plaintext summary must be ignored",
            },
            7,
        ),
    ],
)
def test_chat_metadata_acceptance_is_server_versioned_ciphertext_only_and_broadcast(
    monkeypatch,
    mutation: dict[str, str],
    expected_title_v: int,
) -> None:
    queued_tasks: list[tuple[str, list, str | None]] = []

    def queue_task(name: str, args=None, queue: str | None = None):
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="task-1")

    monkeypatch.setattr(encrypted_chat_metadata_handler.celery_app, "send_task", queue_task)

    manager = asyncio.run(
        send_chat_metadata(chat_metadata_payload(**mutation), is_owner=True)
    )

    assert len(queued_tasks) == 1
    task_name, task_args, queue = queued_tasks[0]
    assert task_name == "app.tasks.persistence_tasks.persist_encrypted_chat_metadata"
    assert queue == "persistence"
    persisted = task_args[1]
    assert persisted["metadata_v"] == 5
    assert persisted["title_v"] == expected_title_v
    assert persisted["messages_v"] == 12
    assert persisted.get("encrypted_title") == mutation.get("encrypted_title")
    assert persisted["encrypted_chat_summary"] == mutation["encrypted_chat_summary"]
    assert "title" not in persisted
    assert "summary" not in persisted
    assert "chat_summary" not in persisted

    assert len(manager.broadcasts) == 1
    broadcast, user_id, excluded_device = manager.broadcasts[0]
    assert user_id == "owner-1"
    assert excluded_device == "device-1"
    assert broadcast["payload"]["versions"] == {
        "metadata_v": 5,
        "title_v": expected_title_v,
        "messages_v": 12,
    }
    assert broadcast["payload"].get("encrypted_title") == mutation.get("encrypted_title")
    assert broadcast["payload"]["encrypted_chat_summary"] == mutation["encrypted_chat_summary"]
    assert "title" not in broadcast["payload"]
    assert "summary" not in broadcast["payload"]
    assert "chat_summary" not in broadcast["payload"]


def test_chat_title_update_broadcasts_server_versions(monkeypatch) -> None:
    queued_tasks: list[tuple[str, dict, str | None]] = []

    def queue_task(name: str, kwargs=None, queue: str | None = None):
        queued_tasks.append((name, kwargs or {}, queue))
        return SimpleNamespace(id="task-1")

    monkeypatch.setattr(title_update_handler.celery_app_instance, "send_task", queue_task)

    manager = ChatMetadataManager()
    cache = TitleUpdateCache()
    asyncio.run(
        handle_update_title(
            websocket=None,
            manager=manager,
            cache_service=cache,
            directus_service=TitleUpdateDirectus(),
            encryption_service=None,
            user_id="owner-1",
            device_fingerprint_hash="device-1",
            payload={
                "chat_id": "chat-1",
                "encrypted_title": "cipher-title-v5",
                "encrypted_chat_key": "cipher-key",
            },
        )
    )

    assert cache.fields == [("owner-1", "chat-1", "title", "cipher-title-v5")]
    assert queued_tasks == [
        (
            "app.tasks.persistence_tasks.persist_chat_title",
            {
                "chat_id": "chat-1",
                "encrypted_title": "cipher-title-v5",
                "title_v": 5,
                "metadata_v": 5,
                "encrypted_chat_key": "cipher-key",
            },
            "persistence",
        )
    ]
    assert len(manager.broadcasts) == 1
    broadcast, user_id, excluded_device = manager.broadcasts[0]
    assert user_id == "owner-1"
    assert excluded_device is None
    assert broadcast == {
        "event": "chat_title_updated",
        "chat_id": "chat-1",
        "data": {"encrypted_title": "cipher-title-v5"},
        "versions": {"messages_v": 3, "title_v": 5, "metadata_v": 5},
    }


def test_metadata_persistence_writes_reserved_cache_version_to_directus(monkeypatch) -> None:
    record = {
        "id": "chat-1",
        "messages_v": 12,
        "title_v": 7,
        "metadata_v": 4,
        "encrypted_title": "cipher-title-v7",
        "encrypted_chat_summary": "cipher-summary-v4",
    }
    updates: list[dict[str, object]] = []

    class DirectusDouble:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                get_chat_metadata=AsyncMock(side_effect=lambda _chat_id: dict(record)),
                update_chat_fields_in_directus=AsyncMock(side_effect=self.update_chat),
            )

        async def ensure_auth_token(self) -> None:
            return None

        async def update_chat(self, chat_id: str, fields_to_update: dict[str, object]) -> dict[str, object]:
            assert chat_id == "chat-1"
            updates.append(dict(fields_to_update))
            record.update(fields_to_update)
            return dict(record)

    class CacheDouble:
        async def get_chat_versions(self, _user_id: str, _chat_id: str) -> SimpleNamespace:
            return SimpleNamespace(messages_v=12, title_v=7, metadata_v=5)

        async def get_chat_list_item_data(self, _user_id: str, _chat_id: str) -> None:
            return None

        async def set_chat_list_item_data(self, _user_id: str, _chat_id: str, _cache_data) -> bool:
            return True

        async def set_chat_versions(self, _user_id: str, _chat_id: str, _versions) -> bool:
            return True

        async def close(self) -> None:
            return None

    monkeypatch.setattr(persistence_tasks, "DirectusService", DirectusDouble)
    monkeypatch.setattr(persistence_tasks, "CacheService", CacheDouble)

    asyncio.run(
        persistence_tasks._async_persist_encrypted_chat_metadata(
            "chat-1",
            {
                "encrypted_chat_summary": "cipher-summary-v5",
                "messages_v": 12,
                "title_v": 7,
                "metadata_v": 5,
                "updated_at": 1000,
            },
            "task-1",
            hashed_user_id="owner-hash",
            user_id="owner-1",
        )
    )

    assert updates
    assert updates[0]["metadata_v"] == 5
    assert updates[0]["encrypted_chat_summary"] == "cipher-summary-v5"


def test_workflow_metadata_version_is_owner_scoped_and_vault_backed() -> None:
    service = workflow_service()
    workflow = service.create_workflow(
        "owner-1",
        "Workflow title v1",
        {
            "version": 1,
            "trigger_node_id": "manual",
            "nodes": [{"id": "manual", "type": "manual_trigger", "title": "Manual", "config": {}}],
            "edges": [],
        },
        description="Workflow description v1",
    )

    with pytest.raises(WorkflowNotFoundError):
        service.update_workflow(workflow.id, "read-only-user", title="Forged title")

    updated = service.update_workflow(
        workflow.id,
        "owner-1",
        title="Workflow title v2",
        description="Workflow description v2",
    )
    record = service.repository.get_workflow(workflow.id, "owner-1")

    assert updated.version == 2
    assert record["version"] == 2
    assert "title" not in record
    assert "description" not in record
    assert record["encrypted_title_ref"]
    assert record["encrypted_description_ref"]
