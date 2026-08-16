"""Tests for durable email-notification settings WebSocket updates.

The handler must recover encryption metadata from Directus when the cache is
cold, then backfill the cache before encrypting and persisting the setting.
These tests use async mocks only and do not open a real WebSocket connection.
"""

import sys
import types
from unittest.mock import AsyncMock

import pytest


def _install_type_only_module(name: str, symbol: str) -> None:
    module = types.ModuleType(name)
    setattr(module, symbol, type(symbol, (), {}))
    sys.modules.setdefault(name, module)


_install_type_only_module("backend.core.api.app.services.cache", "CacheService")
_install_type_only_module(
    "backend.core.api.app.services.directus.directus", "DirectusService"
)
_install_type_only_module("backend.core.api.app.utils.encryption", "EncryptionService")
_install_type_only_module(
    "backend.core.api.app.routes.connection_manager", "ConnectionManager"
)

from backend.core.api.app.routes.handlers.websocket_handlers.email_notification_settings_handler import (  # noqa: E402
    handle_email_notification_settings,
)

# contract-test: direct surface=rest_api assertions=notifications.settings.ack-persisted,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_enable_email_notifications_recovers_vault_key_from_directus() -> None:
    manager = AsyncMock()
    cache_service = AsyncMock()
    cache_service.get_user_vault_key_id.return_value = None
    cache_service.update_user.return_value = True
    directus_service = AsyncMock()
    directus_service.get_user_profile.return_value = (True, {"vault_key_id": "vault-key-123"})
    directus_service.update_user.return_value = True
    encryption_service = AsyncMock()
    encryption_service.encrypt_with_user_key.return_value = ("encrypted-email", "key-version")

    await handle_email_notification_settings(
        websocket=AsyncMock(),
        manager=manager,
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
        user_id="user-123",
        device_fingerprint_hash="device-123",
        payload={
            "enabled": True,
            "email": "person@example.test",
            "preferences": {"aiResponses": True},
        },
    )

    directus_service.get_user_profile.assert_awaited_once_with("user-123")
    cache_service.update_user.assert_any_await(
        "user-123", {"vault_key_id": "vault-key-123"}
    )
    encryption_service.encrypt_with_user_key.assert_awaited_once_with(
        plaintext="person@example.test",
        key_id="vault-key-123",
    )
    assert any(
        call.kwargs["message"]["type"] == "email_notification_settings_ack"
        for call in manager.send_personal_message.await_args_list
    )
