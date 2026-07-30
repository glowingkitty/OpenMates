"""
Billing processing admin notification tests.

These tests cover the July 2026 billing incident guardrail: billing task
failures must notify the configured server admin with sanitized context, and
alert delivery problems must never hide the original invoice-processing error.
External services are replaced with small fakes so the checks stay local.
"""

from datetime import datetime, timezone

import pytest

from backend.core.api.app.tasks.email_tasks import purchase_confirmation_email_task as billing_task


class RecordingEmailService:
    def __init__(self):
        self.sent = []

    async def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return True


class FailingEmailService:
    async def send_email(self, **kwargs):
        raise RuntimeError("admin transport unavailable")


class FakeTask:
    def __init__(self, email_service):
        self.email_template_service = email_service
        self.initialize_calls = 0
        self.cleaned_up = False

    async def initialize_services(self):
        self.initialize_calls += 1

    async def cleanup_services(self):
        self.cleaned_up = True


class FailingInvoiceTask(FakeTask):
    def __init__(self):
        super().__init__(email_service=None)

    async def initialize_services(self):
        raise RuntimeError("payment lookup failed for buyer@example.com")


def test_invoice_datetime_prefers_explicit_backfill_payment_date():
    resolved = billing_task._resolve_invoice_datetime(
        explicit_invoice_date="2026-06-04T16:30:00Z",
        payment_order_details={"payment_created": "2026-07-30T00:00:00Z"},
    )

    assert resolved.isoformat() == "2026-06-04T16:30:00+00:00"


def test_invoice_datetime_uses_provider_payment_created_before_now():
    resolved = billing_task._resolve_invoice_datetime(
        explicit_invoice_date=None,
        payment_order_details={"payment_created": int(datetime(2026, 7, 4, tzinfo=timezone.utc).timestamp())},
    )

    assert resolved.date().isoformat() == "2026-07-04"


@pytest.mark.asyncio
async def test_billing_admin_notification_sanitizes_context(monkeypatch):
    monkeypatch.setenv("ADMIN_NOTIFY_EMAIL", "admin@example.com")
    email_service = RecordingEmailService()
    task = FakeTask(email_service=email_service)

    sent = await billing_task._notify_billing_processing_error(
        task=task,
        stage="<script>invoice</script>",
        order_id="ord_<b>1</b>",
        user_id="user-secret-id",
        credits_purchased=1000,
        provider="stripe",
        provider_order_id="pi_123",
        send_email=True,
        error=RuntimeError("Failed for buyer@example.com with <script>alert(1)</script> Bearer supersecret"),
    )

    assert sent is True
    assert task.initialize_calls == 0
    assert len(email_service.sent) == 1

    message = email_service.sent[0]
    assert message["template"] == billing_task.BILLING_ADMIN_ERROR_TEMPLATE
    assert message["recipient_email"] == "admin@example.com"
    assert "Billing processing error" in message["subject"]

    context = message["context"]
    assert context["stage"] == "&lt;script&gt;invoice&lt;/script&gt;"
    assert context["order_id"] == "ord_&lt;b&gt;1&lt;/b&gt;"
    assert context["user_id_hash"] != "user-secret-id"
    assert "buyer@example.com" not in context["error_message"]
    assert "supersecret" not in context["error_message"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in context["error_message"]


@pytest.mark.asyncio
async def test_billing_admin_notification_is_best_effort(monkeypatch):
    monkeypatch.setenv("ADMIN_NOTIFY_EMAIL", "admin@example.com")
    task = FakeTask(email_service=FailingEmailService())

    sent = await billing_task._notify_billing_processing_error(
        task=task,
        stage="email_delivery",
        order_id="ord_123",
        user_id="user-123",
        credits_purchased=1000,
        provider="stripe",
        provider_order_id="pi_123",
        send_email=True,
        error=RuntimeError("purchase confirmation delivery failed"),
    )

    assert sent is False


@pytest.mark.asyncio
async def test_invoice_processing_preserves_original_error_when_admin_alert_fails(monkeypatch):
    calls = []

    async def fail_admin_alert(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("admin alert failed")

    monkeypatch.setattr(billing_task, "_notify_billing_processing_error", fail_admin_alert)

    task = FailingInvoiceTask()
    with pytest.raises(RuntimeError, match="payment lookup failed"):
        await billing_task._async_process_invoice_and_send_email(
            task=task,
            order_id="ord_123",
            user_id="user-123",
            credits_purchased=1000,
            sender_addressline1="",
            sender_addressline2="",
            sender_addressline3="",
            sender_country="",
            sender_email="support@example.com",
            sender_vat="",
            provider="stripe",
            provider_order_id="pi_123",
        )

    assert calls[0]["stage"] == "invoice_processing"
    assert task.cleaned_up is True
