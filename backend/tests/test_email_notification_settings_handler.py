"""Tests for durable, sparse email-notification settings updates."""

import asyncio
import copy
import sys
import types
from unittest.mock import AsyncMock, Mock

import pytest


_type_only_modules: dict[str, types.ModuleType] = {}


def _install_type_only_module(name: str, symbol: str) -> None:
    module = types.ModuleType(name)
    setattr(module, symbol, type(symbol, (), {}))
    if name not in sys.modules:
        sys.modules[name] = module
        _type_only_modules[name] = module


_install_type_only_module("backend.core.api.app.services.cache", "CacheService")
_install_type_only_module(
    "backend.core.api.app.services.directus.directus", "DirectusService"
)
_install_type_only_module("backend.core.api.app.utils.encryption", "EncryptionService")
_install_type_only_module(
    "backend.core.api.app.routes.connection_manager", "ConnectionManager"
)

try:
    from backend.core.api.app.routes.handlers.websocket_handlers.email_notification_settings_handler import (  # noqa: E402
        handle_email_notification_settings,
        handle_email_notification_settings_get,
    )
finally:
    # Type-only imports support lightweight handler tests without poisoning
    # subsequent real service imports during combined test collection.
    for _name, _module in _type_only_modules.items():
        if sys.modules.get(_name) is _module:
            del sys.modules[_name]


class _AwaitableClient:
    def __init__(self, client: object) -> None:
        self.client = client

    def __await__(self):
        async def get_client():
            return self.client
        return get_client().__await__()


def _cache_with_lock(lock: AsyncMock | None = None, client: Mock | None = None) -> AsyncMock:
    cache = AsyncMock()
    lock = lock or AsyncMock()
    lock.acquire.return_value = True
    lock.extend.return_value = True
    redis = client or Mock()
    if client is None:
        redis.lock.return_value = lock
    cache.client = _AwaitableClient(redis)
    return cache


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted
async def test_snapshot_reads_fresh_settings_without_recording_choices() -> None:
    manager = AsyncMock()
    directus = AsyncMock()
    directus.get_user_fields_direct.return_value = {
        "id": "user-123", "email_notifications_enabled": True,
        "email_notification_preferences": {"aiResponses": True, "workflowRuns": False, "backupReminder": False},
        "email_notification_preference_choices": {
            "workflowRuns": {"source": "user", "value": False, "updated_at": "2026-01-01T00:00:00Z"}
        },
        "backup_reminder_interval_days": 60,
    }

    await handle_email_notification_settings_get(
        manager=manager, directus_service=directus, user_id="user-123",
        device_fingerprint_hash="device-123", payload={"request_id": "snapshot-request"},
    )

    directus.get_user_fields_direct.assert_awaited_once()
    directus.update_user.assert_not_awaited()
    manager.broadcast_to_user.assert_not_awaited()
    snapshot = manager.send_personal_message.await_args.kwargs["message"]
    assert snapshot == {
        "type": "email_notification_settings_snapshot",
        "payload": {
            "enabled": True,
            "preferences": {"aiResponses": True, "workflowRuns": False, "backupReminder": False},
            "choices": {"workflowRuns": {"source": "user", "value": False, "updated_at": "2026-01-01T00:00:00Z"}},
            "backup_reminder_interval_days": 60,
            "request_id": "snapshot-request",
        },
    }


# contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted
@pytest.mark.asyncio
async def test_settings_ack_correlates_origin_and_does_not_correlate_broadcast() -> None:
    manager = AsyncMock()
    cache = _cache_with_lock()
    cache.update_user.return_value = True
    directus = AsyncMock()
    directus.get_user_fields_direct.return_value = {
        "id": "user-123", "email_notifications_enabled": True,
        "email_notification_preferences": {"aiResponses": True, "workflowRuns": True},
    }
    directus.update_user.return_value = True
    await handle_email_notification_settings(
        websocket=AsyncMock(), manager=manager, cache_service=cache,
        directus_service=directus, encryption_service=AsyncMock(),
        user_id="user-123", device_fingerprint_hash="device-123",
        payload={"enabled": False, "request_id": "own-request"},
    )
    ack = manager.send_personal_message.await_args.kwargs["message"]
    assert ack["type"] == "email_notification_settings_ack"
    assert ack["payload"]["request_id"] == "own-request"
    assert "request_id" not in directus.update_user.await_args.args[1]
    assert "request_id" not in manager.broadcast_to_user.await_args.kwargs["message"]["payload"]

# contract-test: direct surface=rest_api assertions=notifications.settings.ack-persisted,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_enable_email_notifications_reads_verified_address_on_cold_cache() -> None:
    manager = AsyncMock()
    cache_service = _cache_with_lock()
    cache_service.update_user.return_value = True
    directus_service = AsyncMock()
    directus_service.get_user_fields_direct.return_value = {
        "id": "user-123", "vault_key_id": "vault-key-123", "hashed_email": "hash-123",
        "email_notifications_enabled": False,
        "email_notification_preferences": {"aiResponses": False, "webhookChats": False},
        "email_notification_preference_choices": {},
    }
    directus_service.get_items.side_effect = [[{
        "user_id": "user-123", "hashed_email": "hash-123", "purpose": "account_lifecycle",
        "verified_at": "2026-01-01T00:00:00Z", "encrypted_email_address": "contact-ciphertext",
    }], []]
    directus_service.update_user.return_value = True
    encryption_service = AsyncMock()
    encryption_service.decrypt_account_contact_email.return_value = "person@example.test"
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
            "preferences": {"workflowRuns": True},
        },
    )

    directus_service.get_user_fields_direct.assert_awaited_once()
    directus_service.update_user.assert_awaited_once()
    saved = directus_service.update_user.await_args.args[1]
    assert saved["email_notification_preferences"] == {
        "aiResponses": False, "webhookChats": False, "workflowRuns": True,
    }
    assert saved["email_notification_preference_choices"]["workflowRuns"]["source"] == "user"
    assert saved["email_notification_preference_choices"]["enabled"]["value"] is True
    encryption_service.encrypt_with_user_key.assert_awaited_once_with(
        plaintext="person@example.test",
        key_id="vault-key-123",
    )
    assert any(
        call.kwargs["message"]["type"] == "email_notification_settings_ack"
        for call in manager.send_personal_message.await_args_list
    )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_rejected_durable_write_does_not_ack_or_update_cache() -> None:
    manager = AsyncMock()
    cache_service = _cache_with_lock()
    directus_service = AsyncMock()
    directus_service.get_user_fields_direct.return_value = {
        "id": "user-123", "email_notifications_enabled": False,
        "email_notification_preferences": {"aiResponses": False},
    }
    directus_service.update_user.return_value = False

    await handle_email_notification_settings(
        websocket=AsyncMock(), manager=manager, cache_service=cache_service,
        directus_service=directus_service, encryption_service=AsyncMock(),
        user_id="user-123", device_fingerprint_hash="device-123",
        payload={"preferences": {"aiResponses": True}},
    )

    cache_service.update_user.assert_not_awaited()
    assert all(
        call.kwargs["message"]["type"] != "email_notification_settings_ack"
        for call in manager.send_personal_message.await_args_list
    )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_unverified_notification_address_is_rejected() -> None:
    manager = AsyncMock()
    directus_service = AsyncMock()
    directus_service.get_user_fields_direct.return_value = {
        "id": "user-123", "hashed_email": "hash-123", "vault_key_id": "vault-key-123",
        "email_notifications_enabled": False,
    }
    directus_service.get_items.return_value = []

    await handle_email_notification_settings(
        websocket=AsyncMock(), manager=manager, cache_service=_cache_with_lock(),
        directus_service=directus_service, encryption_service=AsyncMock(),
        user_id="user-123", device_fingerprint_hash="device-123",
        payload={"enabled": True, "email": "unverified@example.test"},
    )

    directus_service.update_user.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_legacy_account_without_verified_contact_can_opt_out_category() -> None:
    manager = AsyncMock()
    directus_service = AsyncMock()
    directus_service.get_user_fields_direct.return_value = {
        "id": "user-123", "hashed_email": "hash-123",
        "email_notifications_enabled": True,
        "email_notification_preferences": {"aiResponses": True},
        "encrypted_notification_email": "old-unverified-ciphertext",
    }
    directus_service.get_items.return_value = []
    directus_service.update_user.return_value = True

    await handle_email_notification_settings(
        websocket=AsyncMock(), manager=manager, cache_service=_cache_with_lock(),
        directus_service=directus_service, encryption_service=AsyncMock(),
        user_id="user-123", device_fingerprint_hash="device-123",
        payload={"preferences": {"aiResponses": False}},
    )

    saved = directus_service.update_user.await_args.args[1]
    assert saved["email_notification_preferences"]["aiResponses"] is False
    assert saved["encrypted_notification_email"] is None
    assert any(
        call.kwargs["message"]["type"] == "email_notification_settings_ack"
        for call in manager.send_personal_message.await_args_list
    )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_cold_cache_after_durable_opt_out_is_evicted_before_ack() -> None:
    manager = AsyncMock()
    cache = _cache_with_lock()
    cache.update_user.return_value = False
    directus = AsyncMock()
    directus.get_user_fields_direct.return_value = {
        "id": "user-123", "email_notifications_enabled": True,
        "email_notification_preferences": {"aiResponses": True},
    }
    directus.update_user.return_value = True

    await handle_email_notification_settings(
        websocket=AsyncMock(), manager=manager, cache_service=cache,
        directus_service=directus, encryption_service=AsyncMock(),
        user_id="user-123", device_fingerprint_hash="device-123",
        payload={"enabled": False},
    )

    cache.delete_user_cache.assert_awaited_once_with("user-123")
    assert directus.update_user.await_args.args[1]["email_notifications_enabled"] is False
    assert any(
        call.kwargs["message"]["type"] == "email_notification_settings_ack"
        for call in manager.send_personal_message.await_args_list
    )


# contract-test: direct surface=rest_api assertions=notifications.settings.ack-persisted
@pytest.mark.asyncio
async def test_concurrent_device_opt_outs_preserve_both_categories_and_choices() -> None:
    gate = asyncio.Lock()

    class Lease:
        async def acquire(self, *, blocking: bool, blocking_timeout: int) -> bool:
            assert blocking is True and blocking_timeout == 10
            await gate.acquire()
            return True

        async def extend(self, seconds: int, *, replace_ttl: bool) -> bool:
            assert seconds == 120 and replace_ttl is True
            return gate.locked()

        async def release(self) -> None:
            gate.release()

    redis = Mock()
    redis.lock.side_effect = lambda key, timeout: Lease()
    caches = [_cache_with_lock(client=redis), _cache_with_lock(client=redis)]
    directus = AsyncMock()
    profile = {
        "id": "user-123", "email_notifications_enabled": True,
        "email_notification_preferences": {"aiResponses": True, "workflowRuns": True},
        "email_notification_preference_choices": {},
    }

    async def read_user(user_id: str, fields: list[str], *, no_cache=False) -> dict:
        assert user_id == "user-123" and "email_notification_preferences" in fields
        await asyncio.sleep(0)
        return copy.deepcopy(profile)

    async def update_user(user_id: str, patch: dict) -> bool:
        assert user_id == "user-123"
        await asyncio.sleep(0)
        profile.update(copy.deepcopy(patch))
        return True

    directus.get_user_fields_direct.side_effect = read_user
    directus.update_user.side_effect = update_user
    managers = [AsyncMock(), AsyncMock()]

    await asyncio.gather(*(
        handle_email_notification_settings(
            websocket=AsyncMock(), manager=managers[index], cache_service=caches[index],
            directus_service=directus, encryption_service=AsyncMock(),
            user_id="user-123", device_fingerprint_hash=f"device-{index}",
            payload={"preferences": {category: False}},
        )
        for index, category in enumerate(("aiResponses", "workflowRuns"))
    ))

    assert profile["email_notification_preferences"] == {"aiResponses": False, "workflowRuns": False}
    assert profile["email_notification_preference_choices"]["aiResponses"]["source"] == "user"
    assert profile["email_notification_preference_choices"]["workflowRuns"]["source"] == "user"
    assert directus.update_user.await_count == 2
    assert all(any(
        call.kwargs["message"]["type"] == "email_notification_settings_ack"
        for call in manager.send_personal_message.await_args_list
    ) for manager in managers)
    assert all(call.kwargs["timeout"] == 120 for call in redis.lock.call_args_list)


# contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["busy", "lost"])
async def test_lock_failure_never_writes_or_acknowledges(failure: str) -> None:
    lock = AsyncMock()
    cache = _cache_with_lock(lock)
    lock.acquire.return_value = failure != "busy"
    lock.extend.return_value = failure != "lost"
    directus = AsyncMock()
    directus.get_user_fields_direct.return_value = {
        "id": "user-123", "email_notifications_enabled": False,
        "email_notification_preferences": {"aiResponses": True},
    }
    manager = AsyncMock()

    await handle_email_notification_settings(
        websocket=AsyncMock(), manager=manager, cache_service=cache,
        directus_service=directus, encryption_service=AsyncMock(),
        user_id="user-123", device_fingerprint_hash="device-123",
        payload={"preferences": {"aiResponses": False}},
    )

    directus.update_user.assert_not_awaited()
    assert all(
        call.kwargs["message"]["type"] != "email_notification_settings_ack"
        for call in manager.send_personal_message.await_args_list
    )
