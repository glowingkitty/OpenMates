"""
Bank Transfer Duplicate Reference Email Contract Tests
=====================================================

Static contract coverage for the duplicate completed-reference bank-transfer
email path. These tests keep the lightweight local suite focused on task
registration, email copy, and the operator test-send script without contacting
Brevo, Directus, or Revolut.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.parent
EMAIL_TASK_INIT_PATH = REPO_ROOT / "backend/core/api/app/tasks/email_tasks/__init__.py"
EMAIL_TEMPLATE_SERVICE_PATH = REPO_ROOT / "backend/core/api/app/services/email_template.py"
EMAIL_TEMPLATE_PATH = REPO_ROOT / "backend/core/api/templates/email/bank-transfer-duplicate-reference.mjml"
EMAIL_TASK_PATH = REPO_ROOT / "backend/core/api/app/tasks/email_tasks/bank_transfer_duplicate_reference_email_task.py"
TEST_SEND_SCRIPT_PATH = REPO_ROOT / "backend/scripts/send_bank_transfer_duplicate_reference_email_test.py"
EMAIL_TRANSLATIONS_PATH = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/email/main.yml"
BILLING_TRANSLATIONS_PATH = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/settings/billing.yml"


def test_duplicate_reference_email_task_is_registered_and_transactional():
    email_task_init = EMAIL_TASK_INIT_PATH.read_text(encoding="utf-8")
    email_template_service = EMAIL_TEMPLATE_SERVICE_PATH.read_text(encoding="utf-8")

    assert "from . import bank_transfer_duplicate_reference_email_task" in email_task_init
    assert "'bank_transfer_duplicate_reference_email_task'" in email_task_init
    assert "'bank-transfer-duplicate-reference'" in email_template_service


def test_duplicate_reference_template_offers_gift_card_or_refund_options():
    template = EMAIL_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "{{ reference }}" in template
    assert "{{ received_amount_eur }}" in template
    assert "single-use" in template
    assert "credits gift card" in template
    assert "IBAN" in template
    assert "account holder name" in template
    assert "{{ support_email }}" in template


def test_duplicate_reference_email_task_uses_delivery_guard_and_order_email_key():
    task_source = EMAIL_TASK_PATH.read_text(encoding="utf-8")

    assert "send_email_once" in task_source
    assert "email_type=\"bank_transfer_duplicate_reference\"" in task_source
    assert "campaign_key=transaction_id" in task_source
    assert "email_encryption_key" in task_source
    assert "decrypt_with_email_key" in task_source


def test_duplicate_reference_test_send_script_targets_testing_address():
    script = TEST_SEND_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "testing@openmates.org" in script
    assert "bank-transfer-duplicate-reference" in script
    assert "[TEST] Duplicate bank transfer reference received" in script


def test_bank_transfer_reference_copy_mentions_single_use_in_ui_and_email_sources():
    billing_source = BILLING_TRANSLATIONS_PATH.read_text(encoding="utf-8")
    email_source = EMAIL_TRANSLATIONS_PATH.read_text(encoding="utf-8")

    assert "single-use" in billing_source
    assert "create a new purchase" in billing_source
    assert "single-use" in email_source
    assert "create a new purchase" in email_source
