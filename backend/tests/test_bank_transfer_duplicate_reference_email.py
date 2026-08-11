"""
Bank Transfer Duplicate Reference Email Contract Tests
=====================================================

Static contract coverage for the duplicate completed-reference bank-transfer
email path. These tests keep the lightweight local suite focused on task
registration, email copy, and the operator test-send script without contacting
Brevo, Directus, or Revolut.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent
EMAIL_TASK_INIT_PATH = REPO_ROOT / "backend/core/api/app/tasks/email_tasks/__init__.py"
EMAIL_TEMPLATE_SERVICE_PATH = REPO_ROOT / "backend/core/api/app/services/email_template.py"
CELERY_CONFIG_PATH = REPO_ROOT / "backend/core/api/app/tasks/celery_config.py"
EMAIL_TEMPLATE_PATH = REPO_ROOT / "backend/core/api/templates/email/bank-transfer-duplicate-reference.mjml"
EMAIL_TASK_PATH = REPO_ROOT / "backend/core/api/app/tasks/email_tasks/bank_transfer_duplicate_reference_email_task.py"
AMOUNT_NOTICE_TEMPLATE_PATH = REPO_ROOT / "backend/core/api/templates/email/bank-transfer-amount-notice.mjml"
AMOUNT_NOTICE_TASK_PATH = REPO_ROOT / "backend/core/api/app/tasks/email_tasks/bank_transfer_amount_notice_email_task.py"
REMINDER_TASK_PATH = REPO_ROOT / "backend/core/api/app/tasks/email_tasks/bank_transfer_reminder_email_task.py"
TEST_SEND_SCRIPT_PATH = REPO_ROOT / "backend/scripts/send_bank_transfer_duplicate_reference_email_test.py"
EMAIL_TRANSLATIONS_PATH = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/email/main.yml"
BILLING_TRANSLATIONS_PATH = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/settings/billing.yml"


# contract-test: supporting surface=rest_api assertions=billing.purchase.provider-routing,notifications.delivery.email-enabled
def test_duplicate_reference_email_task_is_registered_and_transactional():
    email_task_init = EMAIL_TASK_INIT_PATH.read_text(encoding="utf-8")
    email_template_service = EMAIL_TEMPLATE_SERVICE_PATH.read_text(encoding="utf-8")
    celery_config = CELERY_CONFIG_PATH.read_text(encoding="utf-8")

    assert "from . import bank_transfer_reminder_email_task" in email_task_init
    assert "from . import bank_transfer_amount_notice_email_task" in email_task_init
    assert "from . import bank_transfer_duplicate_reference_email_task" in email_task_init
    assert "'bank_transfer_reminder_email_task'" in email_task_init
    assert "'bank_transfer_amount_notice_email_task'" in email_task_init
    assert "'bank_transfer_duplicate_reference_email_task'" in email_task_init
    assert "'bank-transfer-amount-notice'" in email_template_service
    assert "'bank-transfer-duplicate-reference'" in email_template_service
    assert "bank_transfer_reminder_email_task.send_bank_transfer_reminder\": \"email\"" in celery_config
    assert "bank_transfer_amount_notice_email_task.send_bank_transfer_amount_notice\": \"email\"" in celery_config
    assert "bank_transfer_duplicate_reference_email_task.send_bank_transfer_duplicate_reference\": \"email\"" in celery_config

    assert AMOUNT_NOTICE_TEMPLATE_PATH.exists()
    assert AMOUNT_NOTICE_TASK_PATH.exists()
    assert REMINDER_TASK_PATH.exists()


# contract-test: supporting surface=rest_api assertions=billing.bank-transfer.pending-visible,notifications.delivery.email-enabled
def test_duplicate_reference_template_offers_gift_card_or_refund_options():
    template = EMAIL_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "{{ reference }}" in template
    assert "{{ received_amount_eur }}" in template
    assert "single-use" in template
    assert "credits gift card" in template
    assert "IBAN" in template
    assert "account holder name" in template
    assert "{{ support_email }}" in template


# contract-test: supporting surface=rest_api assertions=billing.bank-transfer.pending-visible,notifications.delivery.email-enabled,notifications.delivery.idempotent
def test_duplicate_reference_email_task_uses_delivery_guard_and_order_email_key():
    task_source = EMAIL_TASK_PATH.read_text(encoding="utf-8")
    reminder_source = REMINDER_TASK_PATH.read_text(encoding="utf-8")

    assert "send_email_once" in task_source
    assert "email_type=\"bank_transfer_duplicate_reference\"" in task_source
    assert "campaign_key=transaction_id" in task_source
    assert "email_encryption_key" in task_source
    assert "decrypt_with_email_key" in task_source
    assert "get_user_profile" in reminder_source


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.purchase.provider-routing,notifications.delivery.email-enabled
async def test_bank_transfer_reminder_uses_directus_fallback_on_cache_miss(monkeypatch):
    celery_config_module = types.ModuleType("backend.core.api.app.tasks.celery_config")

    class FakeCeleryApp:
        def task(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

    celery_config_module.app = FakeCeleryApp()
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", celery_config_module)

    class FakeSecretsManager:
        async def initialize(self):
            return None

        async def get_secret(self, secret_path, secret_key):
            assert secret_key == "email"
            return "billing@example.test"

    class FakeCacheService:
        async def get_user_by_id(self, user_id):
            assert user_id == "user-123"
            return None

        async def close(self):
            return None

    class FakeDirectusService:
        profile_requests = []

        async def get_user_profile(self, user_id):
            self.profile_requests.append(user_id)
            return True, {
                "encrypted_email_address": "encrypted-email",
                "language": "en",
                "darkmode": True,
            }, "ok"

        async def close(self):
            return None

    class FakeEncryptionService:
        def __init__(self, _secrets_manager):
            pass

        async def decrypt_with_email_key(self, ciphertext, email_key):
            assert ciphertext == "encrypted-email"
            assert email_key == "email-key"
            return "buyer@example.test"

    class FakeEmailTemplateService:
        def __init__(self, _secrets_manager):
            pass

    sent_emails = []

    async def fake_send_email_once(**kwargs):
        sent_emails.append(kwargs)
        return True, "sent"

    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.cache",
        types.SimpleNamespace(CacheService=FakeCacheService),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.directus",
        types.SimpleNamespace(DirectusService=FakeDirectusService),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.email_delivery_guard",
        types.SimpleNamespace(send_email_once=fake_send_email_once),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.email_template",
        types.SimpleNamespace(EmailTemplateService=FakeEmailTemplateService),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.utils.encryption",
        types.SimpleNamespace(EncryptionService=FakeEncryptionService),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.utils.secrets_manager",
        types.SimpleNamespace(SecretsManager=FakeSecretsManager),
    )

    spec = importlib.util.spec_from_file_location(
        "bank_transfer_reminder_email_task_test",
        REMINDER_TASK_PATH,
    )
    assert spec and spec.loader
    reminder_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reminder_module)

    result = await reminder_module._async_send_bank_transfer_reminder(
        user_id="user-123",
        order_id="bt-reminder-1",
        email_encryption_key="email-key",
        iban="DE89370400440532013000",
        bic="COBADEFFXXX",
        account_holder_name="OpenMates GmbH",
        bank_name="Revolut Bank UAB",
        amount_eur="50.00",
        credits_amount=54000,
        reference="OM-USER-bt01",
        expires_at="2026-07-29T00:00:00+00:00",
    )

    assert result is True
    assert FakeDirectusService.profile_requests == ["user-123"]
    assert sent_emails[0]["template"] == "bank-transfer-reminder"
    assert sent_emails[0]["recipient_email"] == "buyer@example.test"
    assert sent_emails[0]["sender_email"] == "billing@example.test"
    assert sent_emails[0]["context"]["reference"] == "OM-USER-bt01"


# contract-test: tooling
def test_duplicate_reference_test_send_script_targets_testing_address():
    script = TEST_SEND_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "testing@openmates.org" in script
    assert "bank-transfer-duplicate-reference" in script
    assert "[TEST] Duplicate bank transfer reference received" in script


# contract-test: supporting surface=gui.web assertions=billing.bank-transfer.pending-visible,notifications.content.privacy-boundary
def test_bank_transfer_reference_copy_mentions_single_use_in_ui_and_email_sources():
    billing_source = BILLING_TRANSLATIONS_PATH.read_text(encoding="utf-8")
    email_source = EMAIL_TRANSLATIONS_PATH.read_text(encoding="utf-8")

    assert "single-use" in billing_source
    assert "create a new purchase" in billing_source
    assert "single-use" in email_source
    assert "create a new purchase" in email_source
