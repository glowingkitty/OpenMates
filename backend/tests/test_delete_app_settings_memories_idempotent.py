"""Deleting an app settings/memories entry that is already gone is not an error."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from backend.core.api.app.routes.handlers.websocket_handlers.delete_app_settings_memories_handler import (
    handle_delete_app_settings_memories_entry,
)


def _run(existing):
    manager = MagicMock()
    manager.send_personal_message = AsyncMock()
    manager.broadcast_to_user = AsyncMock()
    directus = MagicMock()
    directus.get_items = AsyncMock(return_value=existing)
    directus.delete_item = AsyncMock()
    asyncio.run(handle_delete_app_settings_memories_entry(
        MagicMock(), manager, MagicMock(), directus, "user-one", "device-one", {"entry_id": "entry-one"},
    ))
    return manager, directus


# contract-test: supporting surface=rest_api assertions=app-memories.migration.client-auto
def test_missing_entry_is_acknowledged_without_delete_error_or_broadcast():
    manager, directus = _run([])
    directus.delete_item.assert_not_awaited()
    manager.broadcast_to_user.assert_not_awaited()
    message = manager.send_personal_message.await_args.args[0]
    assert message["type"] == "app_settings_memories_entry_deleted"
    assert message["payload"] == {
        "entry_id": "entry-one", "app_id": None, "item_type": None, "success": True, "already_deleted": True,
    }


# contract-test: supporting surface=rest_api assertions=app-memories.migration.client-auto
def test_owned_entry_is_deleted_acknowledged_and_broadcast():
    manager, directus = _run([{"id": "entry-one", "app_id": "code", "item_type": "preferred_tech"}])
    directus.delete_item.assert_awaited_once_with("user_app_settings_and_memories", "entry-one")
    assert manager.send_personal_message.await_args.args[0]["payload"]["success"] is True
    manager.broadcast_to_user.assert_awaited_once()
