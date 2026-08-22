"""
Reminder email notification worker tests.

These tests cover the server-side delivery gate that runs after a scheduled
reminder fires. The worker must trust Directus-persisted notification settings,
not a stale profile cache, before queueing an email task for an offline user.
"""

import importlib.util
import sys
import types
from unittest.mock import MagicMock

import pytest

if importlib.util.find_spec("celery") is None:
    tasks_stub = types.ModuleType("backend.core.api.app.tasks")
    tasks_stub.__path__ = []
    celery_config_stub = types.ModuleType("backend.core.api.app.tasks.celery_config")
    base_task_stub = types.ModuleType("backend.core.api.app.tasks.base_task")

    class _CeleryAppStub:
        def send_task(self, *_args, **_kwargs):
            return None

        def task(self, *_args, **_kwargs):
            return lambda func: func

    class _BaseServiceTaskStub:
        pass

    celery_config_stub.app = _CeleryAppStub()
    base_task_stub.BaseServiceTask = _BaseServiceTaskStub
    sys.modules.setdefault("backend.core.api.app.tasks", tasks_stub)
    sys.modules.setdefault("backend.core.api.app.tasks.celery_config", celery_config_stub)
    sys.modules.setdefault("backend.core.api.app.tasks.base_task", base_task_stub)

from backend.apps.reminder import tasks as reminder_tasks


class _FreshNotificationDirectus:
    def __init__(self) -> None:
        self.requested_fields: list[str] = []
        self.get_user_profile_called = False

    async def get_user_profile(self, _user_id: str):
        self.get_user_profile_called = True
        raise AssertionError("reminder email dispatch must bypass cached get_user_profile")

    async def get_user_fields_direct(self, _user_id: str, fields: list[str]):
        self.requested_fields = fields
        return {
            "email_notifications_enabled": True,
            "email_notification_preferences": {"backupReminder": True},
            "encrypted_notification_email": "encrypted@example",
            "vault_key_id": "vault-key",
            "language": "en",
            "darkmode": False,
        }


class _PreferenceDisabledDirectus(_FreshNotificationDirectus):
    async def get_user_fields_direct(self, _user_id: str, fields: list[str]):
        data = await super().get_user_fields_direct(_user_id, fields)
        data["email_notification_preferences"] = {"backupReminder": False}
        return data


class _NotificationEncryption:
    async def decrypt_with_user_key(self, ciphertext: str, vault_key_id: str) -> str:
        assert ciphertext == "encrypted@example"
        assert vault_key_id == "vault-key"
        return "user@example.test"


# contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_reminder_email_notification_uses_fresh_directus_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    directus = _FreshNotificationDirectus()
    send_task = MagicMock()
    monkeypatch.setattr(reminder_tasks.app, "send_task", send_task)

    sent = await reminder_tasks._send_reminder_email_notification(
        user_id="user-12345678",
        reminder_prompt="Check the test results.",
        trigger_time="Aug 11, 2026 at 03:00 AM",
        chat_id="chat-1",
        chat_title="Reminder test",
        is_new_chat=False,
        directus_service=directus,
        encryption_service=_NotificationEncryption(),
    )

    assert sent is True
    assert directus.get_user_profile_called is False
    assert directus.requested_fields == reminder_tasks.REMINDER_NOTIFICATION_PROFILE_FIELDS
    send_task.assert_called_once()
    assert send_task.call_args.kwargs["queue"] == "email"
    assert send_task.call_args.kwargs["kwargs"]["recipient_email"] == "user@example.test"


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_reminder_email_notification_respects_backup_reminder_preference(monkeypatch: pytest.MonkeyPatch) -> None:
    send_task = MagicMock()
    monkeypatch.setattr(reminder_tasks.app, "send_task", send_task)

    sent = await reminder_tasks._send_reminder_email_notification(
        user_id="user-12345678",
        reminder_prompt="Check the test results.",
        trigger_time="Aug 11, 2026 at 03:00 AM",
        chat_id="chat-1",
        chat_title="Reminder test",
        is_new_chat=False,
        directus_service=_PreferenceDisabledDirectus(),
        encryption_service=_NotificationEncryption(),
    )

    assert sent is False
    send_task.assert_not_called()
