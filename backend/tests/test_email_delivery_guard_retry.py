"""Bounded notification retry keeps the original delivery identity and start time."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.email_delivery_guard import (
    build_delivery_id, build_delivery_key, send_email_once,
)
from backend.core.api.app.services.email.brevo_provider import BrevoProvider
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.tasks.email_tasks import workflow_digest_email_task as digest_task


class FakeDirectus:
    base_url = "https://directus.example.test"

    def __init__(self):
        self.row = None

    async def login_admin(self):
        return "test-token"

    async def _make_api_request(self, method, url, **kwargs):
        assert method == "POST"
        if self.row is not None:
            return SimpleNamespace(status_code=409, text="duplicate")
        self.row = dict(kwargs["json"])
        return SimpleNamespace(status_code=200, text="ok")

    async def get_items(self, collection, *, params, admin_required):
        assert admin_required and collection == "email_deliveries"
        return [dict(self.row)] if self.row is not None else []

    async def update_item(self, collection, item_id, data, *, admin_required):
        assert admin_required and collection == "email_deliveries" and item_id == self.row["id"]
        self.row.update(data)


class FakeRedis:
    def __init__(self):
        self.locks = {}

    async def set(self, key, value, *, nx, ex):
        assert nx and ex == 120
        if key in self.locks:
            return False
        self.locks[key] = value
        return True

    async def eval(self, script, keys, key, token):
        assert keys == 1
        if self.locks.get(key) == token:
            del self.locks[key]
            return 1
        return 0


class FakeCache:
    def __init__(self):
        self.redis = FakeRedis()

    @property
    async def client(self):
        return self.redis


def send_args(directus, template, cache):
    template.selected_delivery_transport = lambda: "brevo"
    template.supports_delivery_idempotency = lambda: True
    return dict(
        directus=directus, email_template_service=template,
        email_type="daily_notification", campaign_key="workflowRuns",
        recipient_kind="directus_user", recipient_id="user-1",
        recipient_email="user@example.test", template="workflow-run-digest",
        context={}, stage="2026-10-01", retry_cache=cache,
    )


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_failed_send_retries_with_same_provider_key_and_original_start():
    directus, cache = FakeDirectus(), FakeCache()
    template = SimpleNamespace(send_email=AsyncMock(side_effect=[False, True]))
    args = send_args(directus, template, cache)
    assert await send_email_once(**args) == (False, "failed")
    first_start = directus.row["processing_started_at"]
    assert await send_email_once(**args) == (True, "sent")
    assert directus.row["processing_started_at"] == first_start
    expected = build_delivery_id(build_delivery_key(
        email_type="daily_notification", campaign_key="workflowRuns",
        recipient_kind="directus_user", recipient_id="user-1", stage="2026-10-01",
    ))
    assert [call.kwargs["delivery_idempotency_key"] for call in template.send_email.await_args_list] == [expected, expected]
    assert await send_email_once(**args) == (False, "already_reserved")
    assert template.send_email.await_count == 2


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.delivery.email-enabled
@pytest.mark.asyncio
@pytest.mark.parametrize("status,age,expected", [
    ("failed", 601, "retry_window_closed"),
    ("processing", 121, "retry_ready"),
    ("processing", 10, "retry_locked"),
    ("sent", 10, "already_reserved"),
    ("skipped", 10, "already_reserved"),
    ("mystery", 10, "already_reserved"),
])
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_retry_status_and_window_are_protected(status, age, expected):
    directus, cache = FakeDirectus(), FakeCache()
    template = SimpleNamespace(send_email=AsyncMock(return_value=True))
    args = send_args(directus, template, cache)
    assert await send_email_once(**args) == (True, "sent")
    directus.row.update({
        "status": status,
        "processing_started_at": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
    })
    result = await send_email_once(**args)
    assert result == ((True, "sent") if expected == "retry_ready" else (False, expected))
    assert template.send_email.await_count == (2 if expected == "retry_ready" else 1)


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_concurrent_attempt_cannot_send_while_first_holds_lock():
    directus, cache = FakeDirectus(), FakeCache()
    started = asyncio.Event()
    release = asyncio.Event()

    async def send_email(**kwargs):
        started.set()
        await release.wait()
        return True

    template = SimpleNamespace(send_email=AsyncMock(side_effect=send_email))
    args = send_args(directus, template, cache)
    first = asyncio.create_task(send_email_once(**args))
    await started.wait()
    assert await send_email_once(**args) == (False, "retry_locked")
    release.set()
    assert await first == (True, "sent")
    assert template.send_email.await_count == 1


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_existing_callers_keep_one_attempt_behavior():
    directus = FakeDirectus()
    template = SimpleNamespace(send_email=AsyncMock(return_value=False))
    args = send_args(directus, template, None)
    assert await send_email_once(**args) == (False, "failed")
    assert await send_email_once(**args) == (False, "already_reserved")
    assert "delivery_idempotency_key" not in template.send_email.await_args.kwargs


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.delivery.email-enabled
@pytest.mark.asyncio
@pytest.mark.parametrize("prior_status", ["failed", "processing"])
async def test_smtp_uncertain_delivery_is_never_reopened(prior_status):
    directus, cache = FakeDirectus(), FakeCache()
    template = SimpleNamespace(send_email=AsyncMock(side_effect=[False, True]))
    args = send_args(directus, template, cache)
    template.selected_delivery_transport = lambda: "ci_smtp"
    template.supports_delivery_idempotency = lambda: False
    assert await send_email_once(**args) == (False, "failed")
    assert directus.row["provider"] == "ci_smtp"
    assert "delivery_idempotency_key" not in template.send_email.await_args.kwargs
    directus.row["status"] = prior_status
    directus.row["processing_started_at"] = (datetime.now(timezone.utc) - timedelta(seconds=121)).isoformat()
    assert await send_email_once(**args) == (False, "retry_unsafe_transport")
    assert template.send_email.await_count == 1


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_provider_switch_does_not_replay_smtp_reservation():
    directus, cache = FakeDirectus(), FakeCache()
    template = SimpleNamespace(send_email=AsyncMock(side_effect=[False, True]))
    args = send_args(directus, template, cache)
    template.selected_delivery_transport = lambda: "ci_smtp"
    template.supports_delivery_idempotency = lambda: False
    assert await send_email_once(**args) == (False, "failed")
    template.selected_delivery_transport = lambda: "brevo"
    template.supports_delivery_idempotency = lambda: True
    assert await send_email_once(**args) == (False, "already_reserved")
    assert template.send_email.await_count == 1


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent
def test_actual_template_transport_capability_tracks_ci_smtp(monkeypatch):
    service = EmailTemplateService.__new__(EmailTemplateService)
    monkeypatch.setenv("OPENMATES_CI_MAIL_CAPTURE", "1")
    assert service.selected_delivery_transport() == "ci_smtp"
    assert not service.supports_delivery_idempotency()
    monkeypatch.delenv("OPENMATES_CI_MAIL_CAPTURE")
    assert service.selected_delivery_transport() == "brevo"
    assert service.supports_delivery_idempotency()


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_reserved_delivery_rechecks_consent_and_skip_is_terminal():
    directus, cache = FakeDirectus(), FakeCache()
    template = SimpleNamespace(send_email=AsyncMock(return_value=True))
    args = send_args(directus, template, cache)
    args["before_send"] = AsyncMock(return_value=False)
    assert await send_email_once(**args) == (False, "ineligible_at_dispatch")
    assert directus.row["status"] == "skipped"
    assert await send_email_once(**args) == (False, "already_reserved")
    template.send_email.assert_not_awaited()


def _transport_ready_template(monkeypatch, events, *, on_key_ready=None):
    monkeypatch.delenv("OPENMATES_CI_MAIL_CAPTURE", raising=False)

    class Secrets:
        async def get_secret(self, **kwargs):
            await asyncio.sleep(0)
            if on_key_ready is not None:
                on_key_ready()
            events.append("vault_key_ready")
            return "test-brevo-key"

    provider = SimpleNamespace(api_key="test-brevo-key", send_email=AsyncMock(return_value=True))
    template = EmailTemplateService.__new__(EmailTemplateService)
    template.secrets_manager = Secrets()
    template.default_sender_name = "OpenMates"
    template.default_sender_email = "noreply@openmates.org"
    template.translation_service = SimpleNamespace(get_translations=lambda *args, **kwargs: {})
    template.render_template = lambda name, context, lang, return_context: (
        f"<p>{context.get('response_preview', '')}</p>", context,
    )
    template._brevo_provider = provider
    template._ci_mail_provider = None
    return template, provider


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
@pytest.mark.asyncio
async def test_late_opt_out_during_key_lookup_skips_without_transport_or_retry(monkeypatch):
    directus, events = FakeDirectus(), []
    eligible = {"value": True}
    template, provider = _transport_ready_template(
        monkeypatch, events, on_key_ready=lambda: eligible.update(value=False),
    )

    async def before_send():
        events.append("eligibility_check")
        return eligible["value"]

    args = send_args(directus, template, None)
    args.update(before_send=before_send, subject="Original", context={"response_preview": "private"})
    assert await send_email_once(**args) == (False, "ineligible_at_dispatch")
    assert events == ["eligibility_check", "vault_key_ready", "eligibility_check"]
    assert directus.row["status"] == "skipped"
    assert await send_email_once(**args) == (False, "already_reserved")
    provider.send_email.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
@pytest.mark.asyncio
async def test_late_gate_updates_subject_and_content_before_render(monkeypatch):
    directus, events = FakeDirectus(), []
    template, provider = _transport_ready_template(monkeypatch, events)
    context = {"response_preview": "private preview"}
    options = {"subject": "Private subject"}

    async def before_send():
        events.append("eligibility_check")
        if "vault_key_ready" in events:
            context["response_preview"] = ""
            options["subject"] = "New message"
        return True

    args = send_args(directus, template, None)
    args.update(before_send=before_send, context=context, send_options=options)
    assert await send_email_once(**args) == (True, "sent")
    assert events == ["eligibility_check", "vault_key_ready", "eligibility_check"]
    assert provider.send_email.await_args.kwargs["subject"] == "New message"
    assert provider.send_email.await_args.kwargs["html_content"] == "<p></p>"


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.delivery.email-enabled
@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,expected", [
    (400, {"code": "duplicate_parameter", "message": "same key"}, True),
    (400, {"code": "invalid_parameter", "message": "bad address"}, False),
    (500, {"code": "duplicate_parameter", "message": "server error"}, False),
])
async def test_brevo_accepts_only_documented_duplicate_response(monkeypatch, status, body, expected):
    from backend.core.api.app.services.email import brevo_provider

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def text(self):
            return json.dumps(body)

    response = Response()
    response.status = status

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def post(self, url, *, headers, data):
            assert json.loads(data)["headers"]["idempotencyKey"] == "stable-uuid"
            return response

    monkeypatch.setattr(brevo_provider.aiohttp, "ClientSession", Session)
    provider = BrevoProvider(api_key="test-key")
    result = await provider.send_email(
        sender_name="Sender", sender_email="sender@example.test",
        recipient_email="user@example.test", recipient_name="User",
        subject="Summary", html_content="<p>Summary</p>", plain_text_content="Summary",
        email_headers={"idempotencyKey": "stable-uuid"}, attachments=None,
    )
    assert result is expected


# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,notifications.delivery.email-enabled
def test_digest_retry_uses_only_ids_and_fixed_backoff(monkeypatch):
    queued = []
    monkeypatch.setattr(digest_task.retry_workflow_digest, "apply_async", lambda **kwargs: queued.append(kwargs))
    assert digest_task.queue_workflow_digest_retry("user-1", 1790845200, 1)
    assert digest_task.queue_workflow_digest_retry("user-1", 1790845200, 2)
    assert digest_task.queue_workflow_digest_retry("user-1", 1790845200, 3)
    assert not digest_task.queue_workflow_digest_retry("user-1", 1790845200, 4)
    assert queued == [
        {"args": ["user-1", 1790845200, 1], "countdown": 30, "expires": 600},
        {"args": ["user-1", 1790845200, 2], "countdown": 90, "expires": 600},
        {"args": ["user-1", 1790845200, 3], "countdown": 180, "expires": 600},
    ]
