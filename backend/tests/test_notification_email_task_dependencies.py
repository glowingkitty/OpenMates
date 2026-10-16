"""Notification delivery remains available when billing secrets are absent."""
# contract-test-file: infrastructure

import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services import chat_email_notification_service as delivery
from backend.core.api.app.services import email_delivery_guard
from backend.core.api.app.tasks.email_tasks import ai_response_notification_email_task as worker
from backend.core.api.app.tasks.email_tasks import daily_notification_dispatcher as daily


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_chat_email_dispatch_sends_without_billing_secrets(monkeypatch):
    user_id, chat_id, message_id = "user-a", "chat-a", "message-a"
    candidate = json.dumps({"source": "chat", "sender_name": "Mate", "not_before": time.time() - 1})
    redis = SimpleNamespace(get=AsyncMock(return_value=candidate))
    class Cache:
        @property
        async def client(self):
            return redis

    cache = Cache()
    user = {
        "id": user_id, "status": "active", "email_notifications_enabled": True,
        "email_notification_preferences": {"aiResponses": True, "includeContent": False},
        "email_notification_preference_choices": {}, "language": "en",
    }
    directus = SimpleNamespace(
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
            "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
        })),
        get_user_fields_direct=AsyncMock(return_value=user),
    )
    sent = []

    class EmailTemplate:
        def __init__(self, *, secrets_manager):
            self.secrets_manager = secrets_manager

        async def send_email(self, **kwargs):
            sent.append(kwargs)
            return True

    class Task:
        _email_template_service = None
        _secrets_manager = object()
        directus_service = directus
        cache_service = cache
        encryption_service = object()

        async def initialize_core_services(self):
            pass

        async def initialize_services(self):
            raise RuntimeError("Invoice Ninja URL secret unavailable")

        @property
        def email_template_service(self):
            return self._email_template_service

        async def cleanup_services(self):
            pass

    async def deliver_once(*, email_template_service, before_send, recipient_email, template, **kwargs):
        if not await before_send():
            return False, "disabled"
        return await email_template_service.send_email(template=template, recipient_email=recipient_email), "sent"

    monkeypatch.setattr(worker, "EmailTemplateService", EmailTemplate)
    monkeypatch.setattr(email_delivery_guard, "send_email_once", deliver_once)
    monkeypatch.setattr(delivery, "resolve_notification_email", AsyncMock(return_value="verified@example.test"))
    monkeypatch.setattr(delivery, "has_active_human", AsyncMock(return_value=False))
    monkeypatch.setattr(delivery, "is_message_viewed", AsyncMock(return_value=False))

    assert await worker._send(Task(), user_id=user_id, chat_id=chat_id, message_id=message_id) == "sent"
    assert sent == [{"template": "chat-message-notification", "recipient_email": "verified@example.test"}]


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,workflows.execution.lifecycle-visible
@pytest.mark.asyncio
async def test_daily_dispatch_reaches_digest_without_billing_secrets(monkeypatch):
    sent = []

    class EmailTemplate:
        def __init__(self, *, secrets_manager):
            pass

        async def send_email(self, **kwargs):
            sent.append(kwargs)
            return True

    class Directus:
        async def get_items(self, collection, *, params, admin_required, no_cache):
            assert no_cache is True
            if params["page"] == 1:
                return [{"id": "user-a", "email_notification_preferences": {"workflowRuns": True},
                         "email_notifications_enabled": True}]
            return []

    class Task:
        _email_template_service = None
        _secrets_manager = object()
        directus_service = Directus()

        async def initialize_core_services(self):
            pass

        async def initialize_services(self):
            raise RuntimeError("Invoice Ninja URL secret unavailable")

        @property
        def email_template_service(self):
            return self._email_template_service

        async def cleanup_services(self):
            pass

    async def digest(task, user_id, cutoff, *, require_current_cutoff):
        assert require_current_cutoff is True
        assert await task.email_template_service.send_email(
            template="workflow-run-digest", recipient_email="verified@example.test",
        )
        return "sent"

    monkeypatch.setattr(worker, "EmailTemplateService", EmailTemplate)
    monkeypatch.setattr(daily, "send_user_workflow_digest", digest)
    monkeypatch.setattr(daily, "HANDLERS", [])

    stats = await daily._async_run_daily_notifications(Task())
    assert stats["sent_workflowRuns"] == 1
    assert sent == [{"template": "workflow-run-digest", "recipient_email": "verified@example.test"}]
