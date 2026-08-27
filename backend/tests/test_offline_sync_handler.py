"""Offline WebSocket sync handler regression tests.

These tests pin draft replay behavior for client-side encrypted draft payloads.
Offline replay must match the online draft handlers: local draft-only chats can
be initialized from encrypted draft changes, and draft deletion is a versioned
tombstone/idempotent cleanup instead of a user-visible sync error.
"""

from types import SimpleNamespace
import importlib
from pathlib import Path
import sys
import types

import pytest

if "backend.core.api.app.tasks.celery_config" not in sys.modules:
    tasks_package = types.ModuleType("backend.core.api.app.tasks")
    tasks_package.__path__ = [str(Path(__file__).resolve().parents[1] / "core" / "api" / "app" / "tasks")]

    class _CeleryAppStub:
        def send_task(self, *_args, **_kwargs):
            return None

        def task(self, *_args, **_kwargs):
            return lambda func: func

    celery_config_module = types.ModuleType("backend.core.api.app.tasks.celery_config")
    celery_config_module.app = _CeleryAppStub()
    sys.modules.setdefault("backend.core.api.app.tasks", tasks_package)
    sys.modules["backend.core.api.app.tasks.celery_config"] = celery_config_module
    setattr(tasks_package, "celery_config", celery_config_module)
    setattr(importlib.import_module("backend.core.api.app"), "tasks", tasks_package)

from backend.core.api.app.routes.handlers.websocket_handlers.offline_sync_handler import (  # noqa: E402
    handle_sync_offline_changes,
)


class _Manager:
    def __init__(self) -> None:
        self.sent = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.sent.append(message)

    async def broadcast_to_user(self, message=None, user_id=None, exclude_device_hash=None, message_content=None):
        self.broadcasts.append(message if message is not None else message_content)


class _WebSocket:
    async def send_json(self, message) -> None:
        pass


class _LocalDraftChat:
    async def check_chat_ownership(self, chat_id, user_id):
        return False

    async def get_chat_metadata(self, chat_id):
        return None


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
@pytest.mark.anyio
async def test_offline_draft_sync_initializes_missing_versions_for_local_draft_chat() -> None:
    manager = _Manager()
    cache_calls = []

    class Cache:
        async def get_chat_versions(self, user_id, chat_id):
            return None

        async def increment_user_draft_version(self, user_id, chat_id):
            cache_calls.append(("increment", user_id, chat_id))
            return 1

        async def update_user_draft_in_cache(self, user_id, chat_id, encrypted_md, draft_v, *, encrypted_draft_preview):
            cache_calls.append(("update", user_id, chat_id, encrypted_md, draft_v, encrypted_draft_preview))
            return True

        async def add_chat_to_ids_versions(self, user_id, chat_id, timestamp):
            cache_calls.append(("add", user_id, chat_id, timestamp))
            return True

        async def get_chat_last_edited_overall_timestamp(self, user_id, chat_id):
            return 1234

    await handle_sync_offline_changes(
        websocket=_WebSocket(),
        manager=manager,
        cache_service=Cache(),
        directus_service=SimpleNamespace(chat=_LocalDraftChat()),
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"changes": [{
            "chat_id": "22222222-2222-4222-8222-222222222222",
            "type": "draft",
            "value": "cipher-md",
            "encrypted_draft_preview": "cipher-preview",
            "version_before_edit": 0,
            "change_id": "change-1",
        }]},
    )

    assert cache_calls[0] == ("increment", "user-1", "22222222-2222-4222-8222-222222222222")
    assert cache_calls[1] == (
        "update",
        "user-1",
        "22222222-2222-4222-8222-222222222222",
        "cipher-md",
        1,
        "cipher-preview",
    )
    assert cache_calls[2][0:3] == ("add", "user-1", "22222222-2222-4222-8222-222222222222")
    assert manager.broadcasts[0]["event"] == "chat_draft_updated"
    assert manager.broadcasts[0]["data"] == {
        "encrypted_draft_md": "cipher-md",
        "encrypted_draft_preview": "cipher-preview",
    }
    assert manager.broadcasts[0]["versions"] == {"draft_v": 1}
    assert manager.sent[-1] == {
        "type": "offline_sync_complete",
        "payload": {"processed": 1, "conflicts": 0, "errors": 0},
    }


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_offline_delete_draft_missing_versions_is_idempotent_tombstone() -> None:
    manager = _Manager()
    tombstones = []
    removed = []

    class Cache:
        async def get_chat_versions(self, user_id, chat_id):
            return None

        async def increment_user_draft_version(self, user_id, chat_id):
            return 3

        async def tombstone_user_draft_in_cache(self, *, user_id, chat_id, draft_version):
            tombstones.append((user_id, chat_id, draft_version))
            return True

        async def remove_chat_from_ids_versions(self, user_id, chat_id):
            removed.append((user_id, chat_id))
            return False

    class Directus:
        chat = _LocalDraftChat()

        async def get_items(self, collection, params):
            return []

    await handle_sync_offline_changes(
        websocket=_WebSocket(),
        manager=manager,
        cache_service=Cache(),
        directus_service=Directus(),
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"changes": [{
            "chat_id": "33333333-3333-4333-8333-333333333333",
            "type": "delete_draft",
            "value": None,
            "version_before_edit": 2,
            "change_id": "change-1",
        }]},
    )

    assert tombstones == [("user-1", "33333333-3333-4333-8333-333333333333", 3)]
    assert removed == [("user-1", "33333333-3333-4333-8333-333333333333")]
    assert manager.broadcasts[-1] == {
        "type": "draft_deleted",
        "payload": {
            "chat_id": "33333333-3333-4333-8333-333333333333",
            "draft_v": 3,
        },
    }
    assert manager.sent[-1] == {
        "type": "offline_sync_complete",
        "payload": {"processed": 1, "conflicts": 0, "errors": 0},
    }
