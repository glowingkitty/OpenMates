# contract-test-file: infrastructure
"""A due reminder must not fire after its Directus owner disappears."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.reminder import tasks as reminder_tasks


USER_ID = "11111111-1111-4111-8111-111111111111"
REMINDER_ID = "22222222-2222-4222-8222-222222222222"


def _worker(*, owner_rows=None, owner_error=None, retire=True, user_id=USER_ID):
    reminder = {
        "id": REMINDER_ID,
        "encrypted_user_id": "encrypted-user-id",
        "encrypted_prompt": "encrypted-prompt",
        "vault_key_id": "test-vault-key",
        "target_type": "new_chat",
        "response_type": "simple",
        "trigger_at": 999,
        "created_at": 900,
        "status": "pending",
        "repeat_config": {"type": "daily", "interval": 1},
    }
    cache = SimpleNamespace(
        get_due_reminders=AsyncMock(return_value=[reminder]),
        claim_due_reminder=AsyncMock(return_value=True),
        reschedule_reminder_in_cache=AsyncMock(return_value=True),
        remove_reminder_from_cache=AsyncMock(return_value=True),
        add_pending_reminder_delivery=AsyncMock(return_value=True),
    )
    directus = SimpleNamespace(
        get_items=AsyncMock(side_effect=owner_error) if owner_error else AsyncMock(return_value=owner_rows),
        reminder=SimpleNamespace(update_reminder=AsyncMock(return_value=retire)),
        chat=SimpleNamespace(create_chat_in_directus=AsyncMock(return_value=({"id": "chat"}, False))),
    )
    encryption = SimpleNamespace(
        decrypt_with_user_key=AsyncMock(side_effect=[user_id, "test reminder prompt"]),
    )
    task = SimpleNamespace(
        initialize_services=AsyncMock(),
        cleanup_services=AsyncMock(),
        publish_websocket_event=AsyncMock(),
        _cache_service=cache,
        _directus_service=directus,
        _encryption_service=encryption,
    )
    return task, reminder


def _assert_no_delivery(task, email, ai):
    task._directus_service.chat.create_chat_in_directus.assert_not_awaited()
    task.publish_websocket_event.assert_not_awaited()
    task._cache_service.add_pending_reminder_delivery.assert_not_awaited()
    email.assert_not_awaited()
    ai.assert_not_awaited()


@pytest.mark.asyncio
async def test_absent_reminder_owner_is_cancelled_before_any_delivery(monkeypatch):
    task, _ = _worker(owner_rows=[])
    email = AsyncMock()
    ai = AsyncMock()
    monkeypatch.setattr(reminder_tasks, "_send_reminder_email_notification", email)
    monkeypatch.setattr(reminder_tasks, "_dispatch_reminder_ai_request", ai)
    monkeypatch.setattr(reminder_tasks.time, "time", lambda: 1000)

    result = await reminder_tasks._process_due_reminders_async(task)

    assert result == {"success": True, "processed": 0, "errors": 0}
    task._directus_service.get_items.assert_awaited_once_with(
        "users",
        params={"filter[id][_eq]": USER_ID, "fields": "id", "limit": 1},
        admin_required=True, no_cache=True, raise_on_error=True,
    )
    task._directus_service.reminder.update_reminder.assert_awaited_once_with(
        REMINDER_ID, {"status": "cancelled"},
    )
    task._cache_service.claim_due_reminder.assert_not_awaited()
    task._cache_service.remove_reminder_from_cache.assert_awaited_once_with(REMINDER_ID)
    task._cache_service.reschedule_reminder_in_cache.assert_not_awaited()
    assert task._encryption_service.decrypt_with_user_key.await_count == 1
    _assert_no_delivery(task, email, ai)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_rows", "owner_error", "user_id"),
    [
        (None, RuntimeError("Directus denied access to users"), USER_ID),
        (None, RuntimeError("Directus request failed for users"), USER_ID),
        (None, None, USER_ID),
        ([{"id": "33333333-3333-4333-8333-333333333333"}], None, USER_ID),
        ([], None, "malformed-user-id"),
    ],
)
async def test_uncertain_owner_lookup_leaves_due_reminder_unclaimed(
    monkeypatch, owner_rows, owner_error, user_id,
):
    task, _ = _worker(owner_rows=owner_rows, owner_error=owner_error, user_id=user_id)
    email = AsyncMock()
    ai = AsyncMock()
    monkeypatch.setattr(reminder_tasks, "_send_reminder_email_notification", email)
    monkeypatch.setattr(reminder_tasks, "_dispatch_reminder_ai_request", ai)
    monkeypatch.setattr(reminder_tasks.time, "time", lambda: 1000)

    result = await reminder_tasks._process_due_reminders_async(task)

    assert result == {"success": True, "processed": 0, "errors": 1}
    task._directus_service.reminder.update_reminder.assert_not_awaited()
    task._cache_service.claim_due_reminder.assert_not_awaited()
    task._cache_service.reschedule_reminder_in_cache.assert_not_awaited()
    task._cache_service.remove_reminder_from_cache.assert_not_awaited()
    _assert_no_delivery(task, email, ai)


@pytest.mark.asyncio
async def test_failed_orphan_retirement_leaves_due_reminder_unclaimed(monkeypatch):
    task, _ = _worker(owner_rows=[], retire=False)
    email = AsyncMock()
    ai = AsyncMock()
    monkeypatch.setattr(reminder_tasks, "_send_reminder_email_notification", email)
    monkeypatch.setattr(reminder_tasks, "_dispatch_reminder_ai_request", ai)
    monkeypatch.setattr(reminder_tasks.time, "time", lambda: 1000)

    result = await reminder_tasks._process_due_reminders_async(task)

    assert result == {"success": True, "processed": 0, "errors": 1}
    task._directus_service.reminder.update_reminder.assert_awaited_once_with(
        REMINDER_ID, {"status": "cancelled"},
    )
    task._cache_service.claim_due_reminder.assert_not_awaited()
    task._cache_service.reschedule_reminder_in_cache.assert_not_awaited()
    task._cache_service.remove_reminder_from_cache.assert_not_awaited()
    _assert_no_delivery(task, email, ai)


@pytest.mark.asyncio
async def test_existing_reminder_owner_continues_normal_fire(monkeypatch):
    task, _ = _worker(owner_rows=[{"id": USER_ID}])
    task._cache_service.get_due_reminders.return_value[0]["repeat_config"] = None
    email = AsyncMock(return_value=False)
    ai = AsyncMock()
    monkeypatch.setattr(reminder_tasks, "_send_reminder_email_notification", email)
    monkeypatch.setattr(reminder_tasks, "_dispatch_reminder_ai_request", ai)
    monkeypatch.setattr(reminder_tasks.time, "time", lambda: 1000)

    result = await reminder_tasks._process_due_reminders_async(task)

    assert result == {"success": True, "processed": 1, "errors": 0}
    task._cache_service.claim_due_reminder.assert_awaited_once_with(REMINDER_ID)
    assert task._encryption_service.decrypt_with_user_key.await_count == 2
    task._directus_service.chat.create_chat_in_directus.assert_awaited_once()
    task.publish_websocket_event.assert_awaited_once()
    task._cache_service.add_pending_reminder_delivery.assert_awaited_once()
    email.assert_awaited_once()
    ai.assert_not_awaited()
    task._directus_service.reminder.update_reminder.assert_awaited_once_with(
        REMINDER_ID, {"status": "fired", "occurrence_count": 1},
    )
    task._cache_service.remove_reminder_from_cache.assert_awaited_once_with(REMINDER_ID)


@pytest.mark.asyncio
async def test_verified_owner_does_not_fire_when_another_worker_claimed_it(monkeypatch):
    task, _ = _worker(owner_rows=[{"id": USER_ID}])
    task._cache_service.claim_due_reminder.return_value = False
    email = AsyncMock()
    ai = AsyncMock()
    monkeypatch.setattr(reminder_tasks, "_send_reminder_email_notification", email)
    monkeypatch.setattr(reminder_tasks, "_dispatch_reminder_ai_request", ai)

    result = await reminder_tasks._process_due_reminders_async(task)

    assert result == {"success": True, "processed": 0, "errors": 0}
    task._cache_service.claim_due_reminder.assert_awaited_once_with(REMINDER_ID)
    task._directus_service.reminder.update_reminder.assert_not_awaited()
    assert task._encryption_service.decrypt_with_user_key.await_count == 1
    _assert_no_delivery(task, email, ai)


@pytest.mark.asyncio
async def test_missing_decrypted_user_retains_existing_failed_transition(monkeypatch):
    task, _ = _worker(user_id="")
    email = AsyncMock()
    ai = AsyncMock()
    monkeypatch.setattr(reminder_tasks, "_send_reminder_email_notification", email)
    monkeypatch.setattr(reminder_tasks, "_dispatch_reminder_ai_request", ai)

    result = await reminder_tasks._process_due_reminders_async(task)

    assert result == {"success": True, "processed": 0, "errors": 1}
    task._cache_service.claim_due_reminder.assert_awaited_once_with(REMINDER_ID)
    task._directus_service.get_items.assert_not_awaited()
    task._directus_service.reminder.update_reminder.assert_awaited_once_with(
        REMINDER_ID, {"status": "failed"},
    )
    _assert_no_delivery(task, email, ai)
