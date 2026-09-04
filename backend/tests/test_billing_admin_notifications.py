"""
Billing processing admin notification tests.

These tests cover the July 2026 billing incident guardrail: billing task
failures must notify the configured server admin with sanitized context, and
alert delivery problems must never hide the original invoice-processing error.
External services are replaced with small fakes so the checks stay local.
"""

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.tests.runtime_import_stubs import install_code_route_import_stubs
from backend.tests.s3_service_test_support import ensure_s3_dependencies

ensure_s3_dependencies()
install_code_route_import_stubs()


REPO_ROOT = Path(__file__).parent.parent.parent
PURCHASE_CONFIRMATION_TASK_PATH = (
    REPO_ROOT
    / "backend/core/api/app/tasks/email_tasks/purchase_confirmation_email_task.py"
)


class _FakeCeleryTask:
    def __init__(self, func):
        self.run = types.MethodType(func, self)
        self.request = SimpleNamespace(kwargs={}, retries=0)

    def __call__(self, *args, **kwargs):
        return self.run(*args, **kwargs)

    def retry(self, **_kwargs):
        raise RuntimeError("retry not stubbed")


class _FakeCeleryApp:
    def task(self, *args, **_kwargs):
        if args and callable(args[0]):
            return _FakeCeleryTask(args[0])

        def decorator(func):
            return _FakeCeleryTask(func)

        return decorator


class _FakeBaseServiceTask:
    pass


tasks_module = types.ModuleType("backend.core.api.app.tasks")
tasks_module.__path__ = [str(REPO_ROOT / "backend/core/api/app/tasks")]
celery_config_module = types.ModuleType("backend.core.api.app.tasks.celery_config")
celery_config_module.app = _FakeCeleryApp()
base_task_module = types.ModuleType("backend.core.api.app.tasks.base_task")
base_task_module.BaseServiceTask = _FakeBaseServiceTask
sys.modules["backend.core.api.app.tasks"] = tasks_module
sys.modules["backend.core.api.app.tasks.celery_config"] = celery_config_module
sys.modules["backend.core.api.app.tasks.base_task"] = base_task_module


def _load_billing_task_module():
    module_name = "backend.tests._purchase_confirmation_email_task_under_test"
    spec = importlib.util.spec_from_file_location(module_name, PURCHASE_CONFIRMATION_TASK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load purchase confirmation task module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

from backend.core.api.app.services.s3 import service as s3_service  # noqa: E402
from botocore.exceptions import ClientError, EndpointConnectionError  # noqa: E402

billing_task = _load_billing_task_module()


def _endpoint_connection_error(endpoint_url: str) -> Exception:
    try:
        return EndpointConnectionError(endpoint_url=endpoint_url)
    except TypeError:
        return EndpointConnectionError(endpoint_url)


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


class ScheduledRetry(Exception):
    pass


# contract-test: supporting surface=rest_api assertions=billing.documents.visible-downloadable
def test_invoice_datetime_prefers_explicit_backfill_payment_date():
    resolved = billing_task._resolve_invoice_datetime(
        explicit_invoice_date="2026-06-04T16:30:00Z",
        payment_order_details={"payment_created": "2026-07-30T00:00:00Z"},
    )

    assert resolved.isoformat() == "2026-06-04T16:30:00+00:00"


# contract-test: supporting surface=rest_api assertions=billing.documents.visible-downloadable
def test_invoice_datetime_uses_provider_payment_created_before_now():
    resolved = billing_task._resolve_invoice_datetime(
        explicit_invoice_date=None,
        payment_order_details={"payment_created": int(datetime(2026, 7, 4, tzinfo=timezone.utc).timestamp())},
    )

    assert resolved.date().isoformat() == "2026-07-04"


# contract-test: direct surface=rest_api assertions=billing.documents.visible-downloadable,billing.credits.encrypted-authority-cache-projection
@pytest.mark.anyio
async def test_purchase_confirmation_profile_falls_back_to_directus_for_partial_cache():
    cache_service = AsyncMock()
    cache_service.get_user_by_id = AsyncMock(return_value={
        "id": "user-1",
        "language": "de",
    })
    cache_service.set_user = AsyncMock(return_value=True)

    task = FakeTask(email_service=RecordingEmailService())
    task.directus_service = AsyncMock()
    task.directus_service.get_user_profile = AsyncMock(side_effect=AssertionError("cache-backed profile lookup used"))
    task.directus_service.get_user_fields_direct = AsyncMock(return_value={
        "account_id": "acct-1",
        "vault_key_id": "vault-key",
        "encrypted_email_address": "enc-email",
        "encrypted_email_auto_topup": None,
        "encrypted_invoice_counter": "enc-counter",
        "encrypted_credit_balance": "enc-balance",
        "language": "de",
        "country_code": "DE",
        "darkmode": True,
    })
    task.encryption_service = AsyncMock()
    task.encryption_service.decrypt_with_user_key = AsyncMock(side_effect=["7", "250"])

    profile = await billing_task._get_purchase_confirmation_user_profile(
        task=task,
        cache_service=cache_service,
        user_id="user-1",
        order_id="pi_123",
    )

    assert profile["account_id"] == "acct-1"
    assert profile["vault_key_id"] == "vault-key"
    assert profile["encrypted_email_address"] == "enc-email"
    assert profile["language"] == "de"
    assert profile["country_code"] == "DE"
    assert profile["darkmode"] is True
    assert profile["invoice_counter"] == 7
    assert profile["credits"] == 250
    task.directus_service.get_user_fields_direct.assert_awaited_once_with(
        "user-1",
        billing_task._PURCHASE_CONFIRMATION_USER_FIELDS,
    )
    task.directus_service.get_user_profile.assert_not_called()
    cache_service.set_user.assert_awaited_once()


# contract-test: infrastructure
def test_billing_admin_notification_sanitizes_context(monkeypatch):
    monkeypatch.setenv("ADMIN_NOTIFY_EMAIL", "admin@example.com")
    email_service = RecordingEmailService()
    task = FakeTask(email_service=email_service)

    sent = asyncio.run(
        billing_task._notify_billing_processing_error(
            task=task,
            stage="<script>invoice</script>",
            order_id="ord_<b>1</b>",
            user_id="user-secret-id",
            credits_purchased=1000,
            provider="stripe",
            provider_order_id="pi_123",
            send_email=True,
            error=RuntimeError(
                "Failed for buyer@example.com with <script>alert(1)</script> Bearer supersecret"
            ),
        )
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


# contract-test: infrastructure
def test_billing_admin_notification_is_best_effort(monkeypatch):
    monkeypatch.setenv("ADMIN_NOTIFY_EMAIL", "admin@example.com")
    task = FakeTask(email_service=FailingEmailService())

    sent = asyncio.run(
        billing_task._notify_billing_processing_error(
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
    )

    assert sent is False


# contract-test: infrastructure
def test_invoice_processing_preserves_original_error_when_admin_alert_fails(monkeypatch):
    calls = []

    async def fail_admin_alert(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("admin alert failed")

    monkeypatch.setattr(billing_task, "_notify_billing_processing_error", fail_admin_alert)

    task = FailingInvoiceTask()
    with pytest.raises(RuntimeError, match="payment lookup failed"):
        asyncio.run(
            billing_task._async_process_invoice_and_send_email(
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
        )

    assert calls[0]["stage"] == "invoice_processing"
    assert task.cleaned_up is True


# contract-test: supporting surface=rest_api assertions=billing.documents.visible-downloadable
def test_invoice_processing_task_retries_invoice_record_creation_failure(monkeypatch):
    retry_calls = []

    async def fail_invoice_record_creation(*args, **kwargs):
        raise RuntimeError("Failed to create Directus invoice record")

    def fake_retry(**kwargs):
        retry_calls.append(kwargs)
        raise ScheduledRetry()

    monkeypatch.setattr(billing_task, "_async_process_invoice_and_send_email", fail_invoice_record_creation)
    monkeypatch.setattr(billing_task.process_invoice_and_send_email, "retry", fake_retry)

    with pytest.raises(ScheduledRetry):
        billing_task.process_invoice_and_send_email.run(
            order_id="ord_123",
            user_id="user-123",
            credits_purchased=1000,
            sender_addressline1="",
            sender_addressline2="",
            sender_addressline3="",
            sender_country="",
            sender_email="support@example.com",
            sender_vat="",
            provider="stripe_managed",
            provider_order_id="pi_123",
        )

    assert len(retry_calls) == 1
    assert retry_calls[0]["countdown"] > 0
    assert retry_calls[0]["max_retries"] > 0
    assert "Directus invoice record" in str(retry_calls[0]["exc"])


@pytest.mark.parametrize(
    "error",
    [
        _endpoint_connection_error("https://nbg1.your-objectstorage.com"),
        ClientError(
            {"Error": {"Code": "SlowDown", "Message": "slow"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
            "PutObject",
        ),
    ],
)
# contract-test: direct surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_hetzner_transient_upload_failures_are_provider_degradation(error):
    classified = s3_service.classify_hetzner_upload_error(error)

    assert classified.provider == "Hetzner Object Storage"
    assert classified.classification == "external_provider_degraded"
    assert classified.retryable is True
    assert "Hetzner Object Storage" in str(classified)


# contract-test: direct surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_hetzner_permission_failure_is_internal_configuration():
    error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
        "PutObject",
    )

    classified = s3_service.classify_hetzner_upload_error(error)

    assert classified.provider == "Hetzner Object Storage"
    assert classified.classification == "internal_storage_configuration"
    assert classified.retryable is False


# contract-test: direct surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_invoice_processing_task_retries_hetzner_degradation_for_24_hours(monkeypatch):
    retry_calls = []
    error = s3_service.HetznerObjectStorageError(
        classification="external_provider_degraded",
        retryable=True,
        reason="connection or timeout failure",
    )

    async def fail_upload(*args, **kwargs):
        raise error

    def fake_retry(**kwargs):
        retry_calls.append(kwargs)
        raise ScheduledRetry()

    monkeypatch.setattr(billing_task, "_async_process_invoice_and_send_email", fail_upload)
    monkeypatch.setattr(billing_task.process_invoice_and_send_email, "retry", fake_retry)

    with pytest.raises(ScheduledRetry):
        billing_task.process_invoice_and_send_email.run(
            order_id="ord_123",
            user_id="user-123",
            credits_purchased=1000,
            sender_addressline1="",
            sender_addressline2="",
            sender_addressline3="",
            sender_country="",
            sender_email="support@example.com",
            sender_vat="",
            provider="stripe_managed",
            provider_order_id="pi_123",
        )

    assert retry_calls == [
        {
            "exc": error,
            "countdown": 600,
            "max_retries": 144,
            "kwargs": {
                "storage_retry_count": 1,
                "invoice_record_retry_count": 0,
            },
        }
    ]


# contract-test: direct surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_storage_retry_budget_is_independent_from_prior_directus_retries(monkeypatch):
    retry_calls = []
    error = s3_service.HetznerObjectStorageError(
        classification="external_provider_degraded",
        retryable=True,
        reason="connection or timeout failure",
    )

    async def fail_upload(*args, **kwargs):
        raise error

    def fake_retry(**kwargs):
        retry_calls.append(kwargs)
        raise ScheduledRetry()

    monkeypatch.setattr(billing_task, "_async_process_invoice_and_send_email", fail_upload)
    monkeypatch.setattr(billing_task, "_task_retry_count", lambda task: 3)
    monkeypatch.setattr(billing_task.process_invoice_and_send_email, "retry", fake_retry)

    with pytest.raises(ScheduledRetry):
        billing_task.process_invoice_and_send_email.run(
            order_id="ord_123",
            user_id="user-123",
            credits_purchased=1000,
            sender_addressline1="",
            sender_addressline2="",
            sender_addressline3="",
            sender_country="",
            sender_email="support@example.com",
            sender_vat="",
            provider="stripe_managed",
            provider_order_id="pi_123",
            invoice_record_retry_count=3,
        )

    assert retry_calls[0]["max_retries"] == 147
    assert retry_calls[0]["kwargs"]["storage_retry_count"] == 1
    assert retry_calls[0]["kwargs"]["invoice_record_retry_count"] == 3


# contract-test: direct surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_invoice_processing_does_not_retry_storage_configuration_failure(monkeypatch):
    error = s3_service.HetznerObjectStorageError(
        classification="internal_storage_configuration",
        retryable=False,
        reason="authentication or permission failure",
    )

    async def fail_upload(*args, **kwargs):
        raise error

    def unexpected_retry(**kwargs):
        raise AssertionError(f"unexpected retry: {kwargs}")

    monkeypatch.setattr(billing_task, "_async_process_invoice_and_send_email", fail_upload)
    monkeypatch.setattr(billing_task.process_invoice_and_send_email, "retry", unexpected_retry)

    with pytest.raises(s3_service.HetznerObjectStorageError) as raised:
        billing_task.process_invoice_and_send_email.run(
            order_id="ord_123",
            user_id="user-123",
            credits_purchased=1000,
            sender_addressline1="",
            sender_addressline2="",
            sender_addressline3="",
            sender_country="",
            sender_email="support@example.com",
            sender_vat="",
            provider="stripe_managed",
            provider_order_id="pi_123",
        )

    assert raised.value is error


# contract-test: direct surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_invoice_processing_stops_after_24_hour_storage_retry_window(monkeypatch):
    error = s3_service.HetznerObjectStorageError(
        classification="external_provider_degraded",
        retryable=True,
        reason="service returned a server error",
    )

    async def fail_upload(*args, **kwargs):
        raise error

    def unexpected_retry(**kwargs):
        raise AssertionError(f"unexpected retry after exhaustion: {kwargs}")

    monkeypatch.setattr(billing_task, "_async_process_invoice_and_send_email", fail_upload)
    monkeypatch.setattr(billing_task.process_invoice_and_send_email, "retry", unexpected_retry)

    with pytest.raises(s3_service.HetznerObjectStorageError) as raised:
        billing_task.process_invoice_and_send_email.run(
            order_id="ord_123",
            user_id="user-123",
            credits_purchased=1000,
            sender_addressline1="",
            sender_addressline2="",
            sender_addressline3="",
            sender_country="",
            sender_email="support@example.com",
            sender_vat="",
            provider="stripe_managed",
            provider_order_id="pi_123",
            storage_retry_count=144,
        )

    assert raised.value is error


# contract-test: direct surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_hetzner_alert_lists_provider_classification_and_retry_state(monkeypatch):
    monkeypatch.setenv("ADMIN_NOTIFY_EMAIL", "admin@example.com")
    email_service = RecordingEmailService()
    task = FakeTask(email_service=email_service)

    sent = asyncio.run(
        billing_task._notify_billing_processing_error(
            task=task,
            stage="invoice_storage_upload",
            order_id="ord_123",
            user_id="user-123",
            credits_purchased=1000,
            provider="stripe_managed",
            provider_order_id="pi_123",
            send_email=True,
            error=s3_service.HetznerObjectStorageError(
                classification="external_provider_degraded",
                retryable=True,
                reason="connection or timeout failure",
            ),
            failure_provider="Hetzner Object Storage",
            failure_classification="external_provider_degraded",
            retryable=True,
            retry_delay_seconds=600,
            retry_attempt=1,
            max_retries=144,
            max_attempts=145,
            retries_exhausted=False,
        )
    )

    assert sent is True
    message = email_service.sent[0]
    assert "Hetzner Object Storage degraded" in message["subject"]
    expected_retry_context = {
        "failure_provider": "Hetzner Object Storage",
        "failure_classification": "external_provider_degraded",
        "retryable": "True",
        "retry_delay_seconds": "600",
        "retry_attempt": "1",
        "max_retries": "144",
        "max_attempts": "145",
        "retries_exhausted": "False",
    }
    assert {
        key: message["context"][key] for key in expected_retry_context
    } == expected_retry_context


# contract-test: supporting surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_storage_alert_policy_sends_only_initial_configuration_and_exhaustion_alerts():
    assert billing_task._should_notify_storage_failure(
        retryable=True, storage_retry_count=0
    )
    assert not billing_task._should_notify_storage_failure(
        retryable=True, storage_retry_count=1
    )
    assert not billing_task._should_notify_storage_failure(
        retryable=True, storage_retry_count=143
    )
    assert billing_task._should_notify_storage_failure(
        retryable=True, storage_retry_count=144
    )
    assert billing_task._should_notify_storage_failure(
        retryable=False, storage_retry_count=0
    )


# contract-test: supporting surface=rest_api assertions=billing.documents.storage-degradation-resilient
def test_payment_settlement_precedes_invoice_dispatch_and_is_absent_from_invoice_worker():
    repo_root = Path(__file__).resolve().parents[2]
    payments_source = (repo_root / "backend/core/api/app/routes/payments.py").read_text()
    invoice_task_source = (
        repo_root / "backend/core/api/app/tasks/email_tasks/purchase_confirmation_email_task.py"
    ).read_text()

    assert payments_source.index("await complete_purchase_settlement") < payments_source.index(
        "name='app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email'"
    )
    assert "begin_purchase_settlement" not in invoice_task_source
    assert "complete_purchase_settlement" not in invoice_task_source
