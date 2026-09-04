"""Red contracts for unified detail-page metadata writes.

These tests keep metadata persistence in each owning domain while requiring one
shared security property: writes are owner-scoped and accepted updates receive
server-authoritative monotonic versions. Client-encrypted domains must persist
only ciphertext; Workflow metadata remains inside its Automation Vault boundary.
"""

# contract-test-file: infrastructure

import asyncio
import importlib.machinery
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


if "redis.asyncio" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")
    redis_module.__spec__ = importlib.machinery.ModuleSpec("redis", loader=None)
    redis_asyncio_module.__spec__ = importlib.machinery.ModuleSpec("redis.asyncio", loader=None)

    class FakeRedis:
        pass

    redis_asyncio_module.Redis = FakeRedis
    redis_module.asyncio = redis_asyncio_module
    redis_module.exceptions = SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=Exception)
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

if "boto3" not in sys.modules:
    boto3_module = types.ModuleType("boto3")
    boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
    boto3_module.client = lambda *_args, **_kwargs: None
    sys.modules["boto3"] = boto3_module

if "botocore" not in sys.modules:
    botocore_module = types.ModuleType("botocore")
    botocore_config_module = types.ModuleType("botocore.config")
    botocore_exceptions_module = types.ModuleType("botocore.exceptions")
    botocore_module.__spec__ = importlib.machinery.ModuleSpec("botocore", loader=None)
    botocore_config_module.__spec__ = importlib.machinery.ModuleSpec("botocore.config", loader=None)
    botocore_exceptions_module.__spec__ = importlib.machinery.ModuleSpec("botocore.exceptions", loader=None)
    botocore_config_module.Config = lambda *_args, **_kwargs: None
    botocore_exceptions_module.ClientError = Exception
    botocore_exceptions_module.ReadTimeoutError = Exception
    botocore_exceptions_module.ConnectTimeoutError = Exception
    botocore_exceptions_module.EndpointConnectionError = Exception
    sys.modules["botocore"] = botocore_module
    sys.modules["botocore.config"] = botocore_config_module
    sys.modules["botocore.exceptions"] = botocore_exceptions_module

from backend.core.api.app.routes.handlers.websocket_handlers import (
    encrypted_chat_metadata_handler,
    post_processing_metadata_handler,
    title_update_handler,
)
from backend.core.api.app.routes.handlers.websocket_handlers.encrypted_chat_metadata_handler import (
    handle_encrypted_chat_metadata,
)
from backend.core.api.app.routes.handlers.websocket_handlers.post_processing_metadata_handler import (
    handle_post_processing_metadata,
)
from backend.core.api.app.routes.handlers.websocket_handlers.title_update_handler import (
    handle_update_title,
)
from backend.core.api.app.tasks import persistence_tasks, user_cache_tasks
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

    async def get_task(self, task_id: str, user_id: str, team_id: str | None = None) -> dict[str, object] | None:
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

    async def update_task_if_version(
        self,
        task_id: str,
        user_id: str,
        patch: dict[str, object],
        expected_version: int,
        **_kwargs: object,
    ) -> dict[str, object] | None:
        existing = await self.get_task(task_id, user_id)
        if not existing or int(existing.get("version") or 0) != expected_version:
            return None
        update = dict(patch)
        update["version"] = expected_version + 1
        return await self._update(task_id, user_id, update)

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
    def __init__(self, *, is_owner: bool, metadata_v: int = 4, title_v: int = 7) -> None:
        owner_hash = "4f031bbae19672579c80b55bc57d3a3d8a0644b35f4c4b5324680ece9bb50439"
        self.chat = SimpleNamespace(
            check_chat_ownership=AsyncMock(return_value=is_owner),
            get_chat_metadata=AsyncMock(
                return_value={
                    "hashed_user_id": owner_hash if is_owner else "different-owner-hash",
                    "messages_v": 12,
                    "title_v": title_v,
                    "metadata_v": metadata_v,
                    "encrypted_title": f"cipher-title-v{title_v}",
                    "encrypted_chat_summary": f"cipher-summary-v{metadata_v}",
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


class PostProcessingCache:
    def __init__(
        self,
        events: list[tuple],
        metadata_v: int = 4,
        *,
        cached_title: str | None = None,
        cached_summary: str | None = None,
    ) -> None:
        self.events = events
        self.metadata_v = metadata_v
        self.cached_title = cached_title
        self.cached_summary = cached_summary

    async def get_chat_versions(self, _user_id: str, _chat_id: str) -> SimpleNamespace:
        return SimpleNamespace(messages_v=12, title_v=7, metadata_v=self.metadata_v)

    async def set_chat_version_component(
        self, _user_id: str, _chat_id: str, component: str, value: int
    ) -> bool:
        if component == "metadata_v":
            self.metadata_v = value
        return True

    async def increment_chat_component_version(
        self, _user_id: str, _chat_id: str, component: str
    ) -> int:
        if component == "metadata_v":
            self.metadata_v += 1
            return self.metadata_v
        raise AssertionError(f"Unexpected component increment: {component}")

    async def update_chat_list_item_field(
        self,
        user_id: str,
        chat_id: str,
        field: str,
        value: str,
    ) -> bool:
        self.events.append(("cache", user_id, chat_id, field, value))
        return True

    async def get_chat_list_item_data(self, _user_id: str, _chat_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            title=self.cached_title,
            encrypted_chat_summary=self.cached_summary,
        )


class OrderedPostProcessingManager(ChatMetadataManager):
    def __init__(self, events: list[tuple]) -> None:
        super().__init__()
        self.events = events

    async def send_personal_message(
        self, message: dict, user_id: str, device_hash: str
    ) -> None:
        self.events.append(("personal", message["type"]))
        await super().send_personal_message(message, user_id, device_hash)

    async def broadcast_to_user(
        self,
        message: dict,
        user_id: str,
        exclude_device_hash: str | None = None,
    ) -> None:
        self.events.append(("broadcast", message["type"]))
        await super().broadcast_to_user(message, user_id, exclude_device_hash)


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
        (UserPlanService, "plan_id", "plan-1", "update_plan", UserPlanNotFoundError, "encrypted_goal"),
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
    persistence_calls: list[str] = []

    async def persist_metadata(chat_id: str, *args, **kwargs) -> bool:
        persistence_calls.append(chat_id)
        return True

    monkeypatch.setattr(
        encrypted_chat_metadata_handler,
        "_async_persist_encrypted_chat_metadata",
        persist_metadata,
    )

    manager = asyncio.run(
        send_chat_metadata(chat_metadata_payload(**mutation), is_owner=False)
    )

    assert persistence_calls == []
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
    persistence_calls: list[tuple[str, dict, str, str | None, str | None, str | None]] = []

    async def persist_metadata(
        chat_id: str,
        metadata: dict,
        task_id: str,
        hashed_user_id: str | None = None,
        user_id: str | None = None,
        hashed_team_id: str | None = None,
    ) -> bool:
        persistence_calls.append(
            (chat_id, metadata, task_id, hashed_user_id, user_id, hashed_team_id)
        )
        return True

    monkeypatch.setattr(
        encrypted_chat_metadata_handler,
        "_async_persist_encrypted_chat_metadata",
        persist_metadata,
        raising=False,
    )

    manager = asyncio.run(
        send_chat_metadata(chat_metadata_payload(**mutation), is_owner=True)
    )

    assert len(persistence_calls) == 1
    chat_id, persisted, task_id, hashed_user_id, user_id, hashed_team_id = persistence_calls[0]
    assert chat_id == "chat-1"
    assert task_id == "websocket-direct"
    assert hashed_user_id == "owner-hash"
    assert user_id == "owner-1"
    assert hashed_team_id is None
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


def test_post_processing_summary_updates_sync_cache_before_version_broadcast(monkeypatch) -> None:
    events: list[tuple] = []
    persistence_calls: list[tuple[str, dict, str, str | None, str | None, str | None]] = []

    async def persist_metadata(chat_id, metadata, task_id, hashed_user_id=None, user_id=None, hashed_team_id=None):
        persistence_calls.append((chat_id, metadata, task_id, hashed_user_id, user_id, hashed_team_id))
        events.append(("persist", chat_id))
        return True

    monkeypatch.setattr(post_processing_metadata_handler, "_async_persist_encrypted_chat_metadata", persist_metadata)

    manager = OrderedPostProcessingManager(events)
    asyncio.run(
        handle_post_processing_metadata(
            websocket=None,
            manager=manager,
            cache_service=PostProcessingCache(events),
            directus_service=ChatMetadataDirectus(is_owner=True),
            encryption_service=None,
            user_id="owner-1",
            user_id_hash="owner-hash",
            device_fingerprint_hash="device-1",
            payload=chat_metadata_payload(encrypted_chat_summary="cipher-summary-v5"),
        )
    )

    assert events[0] == ("persist", "chat-1")
    assert events[1] == (
        "cache",
        "owner-1",
        "chat-1",
        "encrypted_chat_summary",
        "cipher-summary-v5",
    )
    assert events[2:] == [
        ("personal", "post_processing_metadata_stored"),
        ("broadcast", "encrypted_chat_metadata"),
    ]
    chat_id, persisted, task_id, hashed_user_id, user_id, hashed_team_id = persistence_calls[0]
    assert chat_id == "chat-1"
    assert task_id == "websocket-direct"
    assert hashed_user_id == "owner-hash"
    assert user_id == "owner-1"
    assert hashed_team_id is None
    assert persisted["metadata_v"] == 5


def test_post_processing_does_not_ack_failed_persistence(monkeypatch) -> None:
    async def reject_persistence(*args, **kwargs) -> bool:
        return False

    monkeypatch.setattr(
        post_processing_metadata_handler,
        "_async_persist_encrypted_chat_metadata",
        reject_persistence,
    )
    manager = ChatMetadataManager()

    with pytest.raises(RuntimeError, match="was not persisted"):
        asyncio.run(
            handle_post_processing_metadata(
                websocket=None,
                manager=manager,
                cache_service=PostProcessingCache([]),
                directus_service=ChatMetadataDirectus(is_owner=True),
                encryption_service=None,
                user_id="owner-1",
                user_id_hash="owner-hash",
                device_fingerprint_hash="device-1",
                payload=chat_metadata_payload(
                    encrypted_quick_tip_slugs="cipher-quick-tips",
                    encrypted_chat_key="cipher-key",
                ),
            )
        )

    assert manager.personal_messages == []
    assert manager.broadcasts == []


def test_post_processing_keeps_new_chat_suggestions_on_persistence_queue(monkeypatch) -> None:
    queued_tasks: list[tuple[str, list, str | None]] = []

    def queue_task(name: str, args=None, queue: str | None = None):
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="task-1")

    async def persist_metadata(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(post_processing_metadata_handler.celery_app, "send_task", queue_task)
    monkeypatch.setattr(
        post_processing_metadata_handler,
        "_async_persist_encrypted_chat_metadata",
        persist_metadata,
    )

    asyncio.run(
        handle_post_processing_metadata(
            websocket=None,
            manager=ChatMetadataManager(),
            cache_service=PostProcessingCache([]),
            directus_service=ChatMetadataDirectus(is_owner=True),
            encryption_service=None,
            user_id="owner-1",
            user_id_hash="owner-hash",
            device_fingerprint_hash="device-1",
            payload=chat_metadata_payload(
                encrypted_new_chat_suggestions=["cipher-suggestion"],
                encrypted_quick_tip_slugs="cipher-quick-tips",
                encrypted_chat_key="cipher-key",
            ),
        )
    )

    assert queued_tasks == [
        (
            "app.tasks.persistence_tasks.persist_new_chat_suggestions",
            ["owner-hash", "chat-1", ["cipher-suggestion"]],
            "persistence",
        )
    ]


def test_post_processing_drops_stale_summary_without_blocking_other_metadata(monkeypatch) -> None:
    events: list[tuple] = []
    persistence_calls: list[tuple[str, dict, str, str | None, str | None, str | None]] = []

    async def persist_metadata(chat_id, metadata, task_id, hashed_user_id=None, user_id=None, hashed_team_id=None):
        persistence_calls.append((chat_id, metadata, task_id, hashed_user_id, user_id, hashed_team_id))
        return True

    monkeypatch.setattr(post_processing_metadata_handler, "_async_persist_encrypted_chat_metadata", persist_metadata)

    manager = OrderedPostProcessingManager(events)
    asyncio.run(
        handle_post_processing_metadata(
            websocket=None,
            manager=manager,
            cache_service=PostProcessingCache(events, metadata_v=8),
            directus_service=ChatMetadataDirectus(is_owner=True, metadata_v=8),
            encryption_service=None,
            user_id="owner-1",
            user_id_hash="owner-hash",
            device_fingerprint_hash="device-1",
            payload=chat_metadata_payload(
                versions={"metadata_v": 4, "title_v": 7, "messages_v": 12},
                encrypted_chat_summary="stale-generated-summary-v4",
                encrypted_chat_tags="fresh-tags-from-post-processing",
                encrypted_chat_key="cipher-key",
            ),
        )
    )

    assert events == [("personal", "post_processing_metadata_stored")]
    assert manager.broadcasts == []
    assert len(persistence_calls) == 1
    persisted = persistence_calls[0][1]
    assert persisted["encrypted_chat_tags"] == "fresh-tags-from-post-processing"
    assert persisted["encrypted_chat_key"] == "cipher-key"
    assert "encrypted_chat_summary" not in persisted
    assert "metadata_v" not in persisted


def test_generated_post_processing_without_baseline_preserves_existing_summary(monkeypatch) -> None:
    events: list[tuple] = []
    persistence_calls: list[tuple[str, dict, str, str | None, str | None, str | None]] = []

    async def persist_metadata(chat_id, metadata, task_id, hashed_user_id=None, user_id=None, hashed_team_id=None):
        persistence_calls.append((chat_id, metadata, task_id, hashed_user_id, user_id, hashed_team_id))
        return True

    monkeypatch.setattr(post_processing_metadata_handler, "_async_persist_encrypted_chat_metadata", persist_metadata)

    manager = OrderedPostProcessingManager(events)
    asyncio.run(
        handle_post_processing_metadata(
            websocket=None,
            manager=manager,
            cache_service=PostProcessingCache(
                events,
                metadata_v=8,
                cached_title="manual-title-v9",
                cached_summary="manual-summary-v9",
            ),
            directus_service=ChatMetadataDirectus(is_owner=True, metadata_v=8),
            encryption_service=None,
            user_id="owner-1",
            user_id_hash="owner-hash",
            device_fingerprint_hash="device-1",
            payload={
                "chat_id": "chat-1",
                "encrypted_title": "late-generated-title",
                "encrypted_chat_summary": "late-generated-summary",
                "encrypted_chat_tags": "fresh-generated-tags",
                "encrypted_chat_key": "cipher-key",
            },
        )
    )

    assert events == [("personal", "post_processing_metadata_stored")]
    assert manager.broadcasts == []
    assert len(persistence_calls) == 1
    persisted = persistence_calls[0][1]
    assert persisted["encrypted_chat_tags"] == "fresh-generated-tags"
    assert persisted["encrypted_chat_key"] == "cipher-key"
    assert "encrypted_title" not in persisted
    assert "encrypted_chat_summary" not in persisted
    assert "metadata_v" not in persisted


def test_post_processing_accepts_manual_summary_with_stale_local_baseline(monkeypatch) -> None:
    events: list[tuple] = []
    persistence_calls: list[tuple[str, dict, str, str | None, str | None, str | None]] = []

    async def persist_metadata(chat_id, metadata, task_id, hashed_user_id=None, user_id=None, hashed_team_id=None):
        persistence_calls.append((chat_id, metadata, task_id, hashed_user_id, user_id, hashed_team_id))
        return True

    monkeypatch.setattr(post_processing_metadata_handler, "_async_persist_encrypted_chat_metadata", persist_metadata)

    manager = OrderedPostProcessingManager(events)
    asyncio.run(
        handle_post_processing_metadata(
            websocket=None,
            manager=manager,
            cache_service=PostProcessingCache(events, metadata_v=8),
            directus_service=ChatMetadataDirectus(is_owner=True, metadata_v=8),
            encryption_service=None,
            user_id="owner-1",
            user_id_hash="owner-hash",
            device_fingerprint_hash="device-1",
            payload=chat_metadata_payload(
                versions={"metadata_v": 4, "title_v": 7, "messages_v": 12},
                encrypted_chat_summary="manual-summary-v9",
                encrypted_chat_key="cipher-key",
                manual_update=True,
            ),
        )
    )

    assert events[0] == (
        "cache",
        "owner-1",
        "chat-1",
        "encrypted_chat_summary",
        "manual-summary-v9",
    )
    assert events[1:] == [
        ("personal", "post_processing_metadata_stored"),
        ("broadcast", "encrypted_chat_metadata"),
    ]
    assert len(persistence_calls) == 1
    persisted = persistence_calls[0][1]
    assert persisted["encrypted_chat_summary"] == "manual-summary-v9"
    assert persisted["metadata_v"] == 9


def test_manual_summary_can_carry_current_title_without_bumping_title_version(monkeypatch) -> None:
    events: list[tuple] = []
    persistence_calls: list[tuple[str, dict, str, str | None, str | None, str | None]] = []

    async def persist_metadata(chat_id, metadata, task_id, hashed_user_id=None, user_id=None, hashed_team_id=None):
        persistence_calls.append((chat_id, metadata, task_id, hashed_user_id, user_id, hashed_team_id))
        return True

    monkeypatch.setattr(post_processing_metadata_handler, "_async_persist_encrypted_chat_metadata", persist_metadata)

    manager = OrderedPostProcessingManager(events)
    asyncio.run(
        handle_post_processing_metadata(
            websocket=None,
            manager=manager,
            cache_service=PostProcessingCache(events, metadata_v=8),
            directus_service=ChatMetadataDirectus(is_owner=True, metadata_v=8, title_v=7),
            encryption_service=None,
            user_id="owner-1",
            user_id_hash="owner-hash",
            device_fingerprint_hash="device-1",
            payload=chat_metadata_payload(
                versions={"metadata_v": 8, "title_v": 7, "messages_v": 12},
                encrypted_title="manual-title-carry-forward",
                encrypted_chat_summary="manual-summary-v9",
                encrypted_chat_key="cipher-key",
                manual_update=True,
                title_changed=False,
            ),
        )
    )

    assert len(persistence_calls) == 1
    persisted = persistence_calls[0][1]
    assert persisted["encrypted_title"] == "manual-title-carry-forward"
    assert persisted["encrypted_chat_summary"] == "manual-summary-v9"
    assert persisted["metadata_v"] == 9
    assert persisted["title_v"] == 7
    _, user_id, excluded_device = manager.broadcasts[0]
    assert user_id == "owner-1"
    assert excluded_device == "device-1"
    assert manager.broadcasts[0][0]["payload"]["versions"] == {
        "metadata_v": 9,
        "title_v": 7,
        "messages_v": 12,
    }


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
                "user_id": "owner-1",
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


def test_metadata_persistence_preserves_newer_cached_title_when_refreshing_cache(monkeypatch) -> None:
    record = {
        "id": "chat-1",
        "messages_v": 12,
        "title_v": 4,
        "metadata_v": 4,
        "encrypted_title": "cipher-title-v4",
        "encrypted_chat_summary": "cipher-summary-v4",
    }
    cached_items: list[object] = []
    cached_versions: list[object] = []

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
            record.update(fields_to_update)
            return dict(record)

    class CacheDouble:
        async def get_chat_versions(self, _user_id: str, _chat_id: str) -> SimpleNamespace:
            return SimpleNamespace(messages_v=12, title_v=5, metadata_v=5)

        async def get_chat_list_item_data(self, _user_id: str, _chat_id: str):
            return persistence_tasks.CachedChatListItemData(
                title="cipher-title-v5",
                encrypted_chat_summary="cipher-summary-v4",
            )

        async def set_chat_list_item_data(self, _user_id: str, _chat_id: str, cache_data) -> bool:
            cached_items.append(cache_data)
            return True

        async def set_chat_versions(self, _user_id: str, _chat_id: str, versions) -> bool:
            cached_versions.append(versions)
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
                "title_v": 4,
                "metadata_v": 5,
                "updated_at": 1000,
            },
            "task-1",
            hashed_user_id="owner-hash",
            user_id="owner-1",
        )
    )

    assert record["encrypted_chat_summary"] == "cipher-summary-v5"
    assert cached_items[0].title == "cipher-title-v5"
    assert cached_items[0].encrypted_chat_summary == "cipher-summary-v5"
    assert cached_versions[0].title_v == 5
    assert cached_versions[0].metadata_v == 5


def test_cache_refresh_preserves_newer_cached_title_and_summary_when_directus_lags() -> None:
    cache_data = persistence_tasks.CachedChatListItemData(
        title="cipher-title-v5",
        encrypted_chat_summary="cipher-summary-v6",
    )
    cache_versions = persistence_tasks.CachedChatVersions(
        messages_v=12,
        title_v=5,
        metadata_v=6,
    )

    merged = persistence_tasks._chat_list_cache_data_from_metadata(
        {
            "id": "chat-1",
            "messages_v": 12,
            "title_v": 5,
            "metadata_v": 4,
            "encrypted_title": "cipher-title-v4",
            "encrypted_chat_summary": None,
        },
        existing_cache_data=cache_data,
        cached_versions=cache_versions,
    )

    assert merged.title == "cipher-title-v5"
    assert merged.encrypted_chat_summary == "cipher-summary-v6"


def test_cache_warming_preserves_newer_cached_title_and_summary_when_directus_lags() -> None:
    cache_data = user_cache_tasks.CachedChatListItemData(
        title="cipher-title-v5",
        encrypted_chat_summary="cipher-summary-v6",
    )
    cache_versions = user_cache_tasks.CachedChatVersions(
        messages_v=12,
        title_v=5,
        metadata_v=6,
    )
    directus_chat = {
        "id": "chat-1",
        "messages_v": 12,
        "title_v": 5,
        "metadata_v": 4,
        "encrypted_title": "cipher-title-v4",
        "encrypted_chat_summary": None,
        "created_at": 100,
        "updated_at": 200,
    }

    merged = user_cache_tasks._cached_chat_list_item_from_details(
        directus_chat,
        "owner-1",
        "chat-1",
        existing_cache_data=cache_data,
        existing_versions=cache_versions,
    )
    versions = user_cache_tasks._cached_chat_versions_from_details(
        directus_chat,
        "owner-1",
        "chat-1",
        existing_versions=cache_versions,
    )

    assert merged.title == "cipher-title-v5"
    assert merged.encrypted_chat_summary == "cipher-summary-v6"
    assert versions.title_v == 5
    assert versions.metadata_v == 6


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
