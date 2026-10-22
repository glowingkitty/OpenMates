"""Reminder activation prompts use durable settings and preserve creation on errors."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.reminder.skills.set_reminder_skill import SetReminderSkill


USER_ID = "11111111-1111-4111-8111-111111111111"


def services(settings, *, cached_enabled=False, prompted=False, error=None):
    directus = SimpleNamespace(
        get_user_profile=AsyncMock(return_value=(True, {
            "email_notifications_enabled": cached_enabled,
            "vault_key_id": "test-vault-key",
        }, "cached")),
        get_user_fields_direct=AsyncMock(return_value=settings, side_effect=error),
        reminder=SimpleNamespace(
            get_user_reminders=AsyncMock(return_value=[]),
            create_reminder=AsyncMock(return_value=True),
        ),
    )
    cache = SimpleNamespace(
        get_user_vault_key_id=AsyncMock(return_value="test-vault-key"),
        load_reminder_into_cache=AsyncMock(),
        get=AsyncMock(return_value="1" if prompted else None),
        set=AsyncMock(),
        publish_event=AsyncMock(),
    )
    encryption = SimpleNamespace(
        encrypt_with_user_key=AsyncMock(return_value=("encrypted-test-value", "test-vault-key")),
    )
    return directus, cache, encryption


async def create_reminder(monkeypatch, directus, cache, encryption):
    monkeypatch.setattr("backend.apps.reminder.skills.set_reminder_skill.time.time", lambda: 1800000000)
    skill = SetReminderSkill(
        app=None, app_id="reminder", skill_id="set-reminder",
        skill_name="Set reminder", skill_description="Test reminder",
    )
    result = await skill.execute(
        prompt="Check the notification setup", trigger_type="specific", timezone="UTC",
        trigger_datetime="2027-01-17T12:00:00", user_id=USER_ID,
        directus_service=directus, cache_service=cache, encryption_service=encryption,
    )
    assert result.success is True
    directus.reminder.create_reminder.assert_awaited_once()
    directus.get_user_profile.assert_not_awaited()
    directus.get_user_fields_direct.assert_awaited_once_with(
        USER_ID, ["email_notifications_enabled"], no_cache=True,
    )
    return result


# contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted
@pytest.mark.asyncio
async def test_enabled_persisted_settings_override_disabled_cached_profile(monkeypatch):
    directus, cache, encryption = services({"email_notifications_enabled": True})
    result = await create_reminder(monkeypatch, directus, cache, encryption)
    assert result.email_notification_warning is None
    cache.get.assert_not_awaited()
    cache.set.assert_not_awaited()
    cache.publish_event.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted
@pytest.mark.asyncio
async def test_disabled_persisted_settings_prompt_with_current_settings_route(monkeypatch):
    directus, cache, encryption = services({"email_notifications_enabled": False}, cached_enabled=True)
    result = await create_reminder(monkeypatch, directus, cache, encryption)
    assert result.email_notification_warning
    cache.publish_event.assert_awaited_once()
    channel, event = cache.publish_event.call_args.args
    assert channel == f"websocket:user:{USER_ID}"
    assert event["event"] == "user_notification"
    assert event["payload"]["action_deep_link"] == "notifications/chat"
    assert event["payload"]["dedupe_key"] == "activate-email-notifications"
    cache.set.assert_awaited_once_with(
        f"reminder:email_prompt:{hashlib.sha256(USER_ID.encode()).hexdigest()}", "1", ttl=300,
    )


# contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted
@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [
    None, {}, {"email_notifications_enabled": None},
    {"email_notifications_enabled": "false"}, {"email_notifications_enabled": 0},
])
async def test_unknown_notification_state_does_not_claim_disabled(monkeypatch, settings):
    directus, cache, encryption = services(settings)
    result = await create_reminder(monkeypatch, directus, cache, encryption)
    assert result.email_notification_warning is None
    cache.get.assert_not_awaited()
    cache.publish_event.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted
@pytest.mark.asyncio
async def test_settings_lookup_failure_does_not_fail_reminder_or_claim_disabled(monkeypatch):
    directus, cache, encryption = services(None, error=RuntimeError("Settings unavailable"))
    result = await create_reminder(monkeypatch, directus, cache, encryption)
    assert result.email_notification_warning is None
    cache.get.assert_not_awaited()
    cache.publish_event.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted
@pytest.mark.asyncio
async def test_disabled_notification_prompt_remains_deduplicated(monkeypatch):
    directus, cache, encryption = services({"email_notifications_enabled": False}, prompted=True)
    result = await create_reminder(monkeypatch, directus, cache, encryption)
    assert result.email_notification_warning is None
    cache.set.assert_not_awaited()
    cache.publish_event.assert_not_awaited()
