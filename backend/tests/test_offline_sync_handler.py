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


@pytest.fixture(autouse=True)
def _recovery_exclusion_is_committed(monkeypatch):
    """draft_change_allowed commits a voice-call cleanup exclusion through the
    chat-recovery transaction before admitting a draft; these handler tests
    have no Directus extension behind it."""
    from backend.core.api.app.routes.handlers.websocket_handlers import draft_scope

    class _Recovery:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, payload):
            return {}

    monkeypatch.setattr(draft_scope, "ChatRecoveryService", _Recovery)


class _Manager:
    def __init__(self) -> None:
        self.sent = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.sent.append(message)

    async def broadcast_to_user(self, message: dict, user_id: str, exclude_device_hash: str = None):
        self.broadcasts.append(message)


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
@pytest.mark.parametrize("edit_count", [1, 3])
async def test_offline_draft_sync_initializes_missing_versions_for_local_draft_chat(edit_count: int) -> None:
    manager = _Manager()
    cache_calls = []
    draft_version = 0

    class Cache:
        async def get_chat_versions(self, user_id, chat_id):
            return None

        async def increment_user_draft_version(self, user_id, chat_id):
            nonlocal draft_version
            cache_calls.append(("increment", user_id, chat_id))
            draft_version += 1
            return draft_version

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
        payload={"batch_id": "offline-batch-1", "changes": [{
            "chat_id": "22222222-2222-4222-8222-222222222222",
            "type": "draft",
            "value": "cipher-md" if index == 0 else f"cipher-md-{index + 1}",
            "encrypted_draft_preview": "cipher-preview" if index == 0 else f"cipher-preview-{index + 1}",
            "version_before_edit": index,
            "change_id": f"change-{index + 1}",
        } for index in range(edit_count)]},
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
    assert len(manager.broadcasts) == edit_count
    assert manager.broadcasts[-1]["versions"] == {"draft_v": edit_count}
    assert manager.broadcasts[-1]["data"]["encrypted_draft_md"] == (
        "cipher-md" if edit_count == 1 else f"cipher-md-{edit_count}"
    )
    assert manager.broadcasts[-1]["data"]["encrypted_draft_preview"] == (
        "cipher-preview" if edit_count == 1 else f"cipher-preview-{edit_count}"
    )
    assert manager.sent[-1] == {
        "type": "offline_sync_complete",
        "payload": {
            "processed": edit_count, "conflicts": 0, "errors": 0,
            "batch_id": "offline-batch-1",
            "successful_change_ids": [f"change-{index + 1}" for index in range(edit_count)],
        },
    }


# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
@pytest.mark.anyio
async def test_offline_delete_draft_missing_versions_is_idempotent_tombstone(monkeypatch) -> None:
    from backend.core.api.app.routes.handlers.websocket_handlers import offline_sync_handler

    manager = _Manager()
    tombstones = []
    removed = []
    deletion_records = []

    async def _record_draft_deletion(cache_service, user_id, chat_id, draft_version):
        deletion_records.append((user_id, chat_id, draft_version))
        return True

    monkeypatch.setattr(offline_sync_handler, "record_draft_deletion", _record_draft_deletion)

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

        @property
        async def client(self):
            # No Redis: record_draft_deletion skips its probe marker.
            return None

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
    assert deletion_records == [("user-1", "33333333-3333-4333-8333-333333333333", 3)]
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



# contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,chats.offline-outbox.ordered-replay
@pytest.mark.anyio
async def test_offline_draft_replays_already_settled_on_server_are_acknowledged() -> None:
    """Prod issue 70f20bcf: a draft queued after its receipt was lost, or an older
    delete, replays behind the server's per-user draft_v. Reported as a conflict,
    the row stayed queued and 'Offline sync: N changes had conflicts' returned on
    every reconnect. Such replays change nothing, so they are acknowledged without
    a write. A draft with different ciphertext is still a genuine conflict."""
    manager = _Manager()
    writes = []

    class Cache:
        async def get_chat_versions(self, user_id, chat_id):
            return SimpleNamespace(title_v=4, model_extra={"user_draft_v:user-1": 5})

        async def get_user_draft_from_cache(self, user_id, chat_id, refresh_ttl=False):
            return ("cipher-already-saved", 5, "cipher-preview")

        async def increment_user_draft_version(self, user_id, chat_id):
            writes.append(("increment", chat_id))
            return 6

        async def update_user_draft_in_cache(self, *args, **kwargs):
            writes.append(("update", args, kwargs))
            return True

        async def tombstone_user_draft_in_cache(self, **kwargs):
            writes.append(("tombstone", kwargs))
            return True

    class Chat:
        async def check_chat_ownership(self, chat_id, user_id):
            return True

        async def get_chat_metadata(self, chat_id, admin_required=False):
            return {"id": chat_id}

    chat_id = "44444444-4444-4444-8444-444444444444"
    await handle_sync_offline_changes(
        websocket=_WebSocket(),
        manager=manager,
        cache_service=Cache(),
        directus_service=SimpleNamespace(chat=Chat()),
        encryption_service=None,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"batch_id": "offline-batch-2", "changes": [
            {"chat_id": chat_id, "type": "draft", "value": "cipher-already-saved",
             "encrypted_draft_preview": "cipher-preview", "version_before_edit": 4,
             "change_id": "lost-receipt-draft"},
            {"chat_id": chat_id, "type": "delete_draft", "value": None,
             "version_before_edit": 3, "change_id": "older-delete"},
            {"chat_id": chat_id, "type": "draft", "value": "cipher-other-offline-text",
             "encrypted_draft_preview": "cipher-other-preview", "version_before_edit": 4,
             "change_id": "genuine-conflict"},
            {"chat_id": chat_id, "type": "title", "value": "Offline title",
             "version_before_edit": 2, "change_id": "stale-title"},
        ]},
    )

    assert writes == []
    assert manager.broadcasts == []
    assert manager.sent[-1] == {
        "type": "offline_sync_complete",
        "payload": {
            "processed": 2, "conflicts": 2, "errors": 0,
            "batch_id": "offline-batch-2",
            "successful_change_ids": ["lost-receipt-draft", "older-delete"],
        },
    }
