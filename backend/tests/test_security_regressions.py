# backend/tests/test_security_regressions.py
#
# Focused regression tests for merge-blocking security fixes.

import hashlib
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pyotp
import pytest
from fastapi import HTTPException, Request


_FAKE_WS_MANAGER = MagicMock(name="fake_ws_manager")


def _force_stub_leaf_module(dotted_name: str, **attrs) -> None:
    parent_name, _, leaf = dotted_name.rpartition(".")
    if parent_name not in sys.modules:
        __import__(parent_name)
    parent = sys.modules[parent_name]
    stub = types.ModuleType(dotted_name)
    for key, value in attrs.items():
        setattr(stub, key, value)
    sys.modules[dotted_name] = stub
    setattr(parent, leaf, stub)


_force_stub_leaf_module(
    "backend.core.api.app.routes.websockets",
    manager=_FAKE_WS_MANAGER,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _DomainSecurityService:
    config_loaded = True

    def validate_email_domain(self, _email: str):
        return True, None


@pytest.mark.anyio
async def test_email_change_password_reauth_does_not_create_login_session():
    from backend.core.api.app.routes import settings

    directus_service = AsyncMock()
    directus_service.get_user_fields_direct = AsyncMock(return_value={
        "hashed_email": "hashed-email",
        "lookup_hashes": ["lookup-hash"],
    })
    directus_service.login_user_with_lookup_hash = AsyncMock()

    await settings._verify_email_change_password(
        user_id="user-1",
        hashed_email="hashed-email",
        lookup_hash="lookup-hash",
        directus_service=directus_service,
    )

    directus_service.login_user_with_lookup_hash.assert_not_called()


@pytest.mark.anyio
async def test_email_change_2fa_reauth_verifies_totp_without_trusting_device():
    from backend.core.api.app.routes import settings

    user_id = "user-1"
    tfa_secret = "JBSWY3DPEHPK3PXP"
    directus_service = AsyncMock()
    directus_service.get_user_fields_direct = AsyncMock(return_value={
        "encrypted_tfa_secret": "encrypted-secret",
        "vault_key_id": "vault-key",
    })
    directus_service.add_user_device_hash = AsyncMock()
    cache_service = AsyncMock()
    cache_service.get = AsyncMock(return_value=None)
    cache_service.set = AsyncMock(return_value=True)
    encryption_service = AsyncMock()
    encryption_service.decrypt_with_user_key = AsyncMock(return_value=tfa_secret)

    await settings._verify_email_change_2fa(
        user_id=user_id,
        auth_code=pyotp.TOTP(tfa_secret).now(),
        directus_service=directus_service,
        cache_service=cache_service,
        encryption_service=encryption_service,
    )

    directus_service.add_user_device_hash.assert_not_called()


@pytest.mark.anyio
async def test_confirm_email_change_rejects_without_recent_reauth(monkeypatch):
    from backend.core.api.app.routes import settings
    from backend.core.api.app.models.user import User
    from backend.core.api.app.utils.newsletter_utils import hash_email

    async def mock_signup_requirements(*_args, **_kwargs):
        return False, False, []

    monkeypatch.setattr(settings, "get_signup_requirements", mock_signup_requirements)

    user_id = "test-user-id"
    new_email = "new@example.com"
    hashed_new_email = hash_email(new_email)

    cache_service = AsyncMock()
    cache_service.get.side_effect = lambda key: (
        "verified" if key.startswith("email_change_verified:") else None
    )

    directus_service = AsyncMock()
    directus_service.get_user_by_hashed_email = AsyncMock(return_value=(False, None, "User not found"))
    directus_service.update_user = AsyncMock(return_value=True)

    app = SimpleNamespace(state=SimpleNamespace(domain_security_service=_DomainSecurityService()))
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/user/email/confirm-change",
            "headers": [],
            "app": app,
            "client": ("127.0.0.1", 12345),
        }
    )
    body = settings.ConfirmEmailChangeRequest(
        new_email=new_email,
        hashed_email=hashed_new_email,
        encrypted_email_address="encrypted-email-address",
        encrypted_email_with_master_key="encrypted-email-master-key",
        auth_method="password",
    )
    current_user = User(id=user_id, username="testuser", vault_key_id="vault-key")

    with pytest.raises(HTTPException) as exc_info:
        await settings.confirm_email_change(
            request=request,
            body=body,
            current_user=current_user,
            directus_service=directus_service,
            cache_service=cache_service,
            compliance_service=AsyncMock(),
            encryption_service=AsyncMock(),
        )

    assert exc_info.value.status_code == 401
    directus_service.update_user.assert_not_called()


@pytest.mark.anyio
async def test_apple_iap_transaction_reservation_reports_existing_duplicate():
    from backend.core.api.app.services.directus.apple_iap_transaction_methods import (
        AppleIAPTransactionMethods,
    )

    existing = {"transaction_id": "tx-123", "credits": 1000, "user_id": "user-1"}
    directus = AsyncMock()
    directus.create_item = AsyncMock(return_value=(False, {"status_code": 400}))
    directus.get_items = AsyncMock(return_value=[existing])

    methods = AppleIAPTransactionMethods(directus)
    reserved, row = await methods.reserve_processed_transaction(
        transaction_id="tx-123",
        original_transaction_id="orig-123",
        user_id="user-1",
        product_id="org.openmates.credits.1000",
        credits=1000,
        environment="Sandbox",
    )

    assert reserved is False
    assert row == existing
    directus.create_item.assert_called_once()


@pytest.mark.anyio
async def test_store_account_lifecycle_contact_email_uses_vault_encryption():
    from backend.core.api.app.routes.auth_routes.auth_utils import store_account_lifecycle_contact_email

    directus_service = AsyncMock()
    directus_service.get_items = AsyncMock(return_value=[])
    directus_service.create_item = AsyncMock(return_value=(True, {"id": "bed33190-7517-5958-9b7f-bc9fd4e7cb2a"}))
    directus_service.update_item = AsyncMock()
    encryption_service = AsyncMock()
    encryption_service.encrypt_account_contact_email = AsyncMock(return_value="vault:v1:encrypted-email")

    stored = await store_account_lifecycle_contact_email(
        directus_service,
        encryption_service,
        user_id="user-1",
        hashed_email="hashed-email",
        email="user@example.com",
        verified_at=1234567890,
    )

    assert stored is True
    encryption_service.encrypt_account_contact_email.assert_awaited_once_with("user@example.com")
    collection, payload = directus_service.create_item.call_args.args[:2]
    assert collection == "account_contact_emails"
    assert payload["id"] == "bed33190-7517-5958-9b7f-bc9fd4e7cb2a"
    assert payload["user_id"] == "user-1"
    assert payload["hashed_email"] == "hashed-email"
    assert payload["encrypted_email_address"] == "vault:v1:encrypted-email"
    assert payload["purpose"] == "account_lifecycle"
    assert payload["source"] == "signup"
    assert payload["verified_at"] == 1234567890
    assert directus_service.create_item.call_args.kwargs["admin_required"] is True
    directus_service.update_item.assert_not_called()


@pytest.mark.anyio
async def test_store_account_lifecycle_contact_email_updates_existing_record():
    from backend.core.api.app.routes.auth_routes.auth_utils import store_account_lifecycle_contact_email

    directus_service = AsyncMock()
    directus_service.get_items = AsyncMock(return_value=[{"id": "bed33190-7517-5958-9b7f-bc9fd4e7cb2a"}])
    directus_service.create_item = AsyncMock()
    directus_service.update_item = AsyncMock(return_value={"id": "bed33190-7517-5958-9b7f-bc9fd4e7cb2a"})
    encryption_service = AsyncMock()
    encryption_service.encrypt_account_contact_email = AsyncMock(return_value="vault:v1:new-email")

    stored = await store_account_lifecycle_contact_email(
        directus_service,
        encryption_service,
        user_id="user-1",
        hashed_email="new-hashed-email",
        email="new@example.com",
        verified_at=1234567890,
    )

    assert stored is True
    directus_service.create_item.assert_not_called()
    collection, item_id, payload = directus_service.update_item.call_args.args[:3]
    assert collection == "account_contact_emails"
    assert item_id == "bed33190-7517-5958-9b7f-bc9fd4e7cb2a"
    assert payload["hashed_email"] == "new-hashed-email"
    assert payload["encrypted_email_address"] == "vault:v1:new-email"
    assert directus_service.update_item.call_args.kwargs["admin_required"] is True


@pytest.mark.anyio
async def test_store_account_lifecycle_contact_email_updates_after_duplicate_create():
    from backend.core.api.app.routes.auth_routes.auth_utils import store_account_lifecycle_contact_email

    directus_service = AsyncMock()
    directus_service.get_items = AsyncMock(return_value=[])
    directus_service.create_item = AsyncMock(return_value=(False, {"status_code": 400, "text": "RECORD_NOT_UNIQUE"}))
    directus_service.update_item = AsyncMock(return_value={"id": "bed33190-7517-5958-9b7f-bc9fd4e7cb2a"})
    encryption_service = AsyncMock()
    encryption_service.encrypt_account_contact_email = AsyncMock(return_value="vault:v1:race-email")

    stored = await store_account_lifecycle_contact_email(
        directus_service,
        encryption_service,
        user_id="user-1",
        hashed_email="race-hashed-email",
        email="race@example.com",
        verified_at=1234567890,
    )

    assert stored is True
    directus_service.create_item.assert_awaited_once()
    directus_service.update_item.assert_awaited_once()


@pytest.mark.anyio
async def test_incomplete_signup_deletion_requires_account_contact_email():
    from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import _decrypt_email_and_username

    task = SimpleNamespace(
        directus_service=AsyncMock(),
        encryption_service=AsyncMock(),
    )
    task.directus_service.get_items = AsyncMock(return_value=[])

    email, username = await _decrypt_email_and_username(
        task,
        {
            "id": "user-1",
            "vault_key_id": "user-vault-key",
            "encrypted_email_address": "client-side-encrypted-email",
            "encrypted_username": "encrypted-username",
        },
    )

    assert email is None
    assert username == ""
    task.encryption_service.decrypt_with_user_key.assert_not_called()


@pytest.mark.anyio
async def test_incomplete_signup_completion_requires_invoice_or_gift_card():
    from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import _has_completed_credit_source

    user_id = "user-1"
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    task = SimpleNamespace(directus_service=AsyncMock())
    task.directus_service.get_items = AsyncMock(side_effect=[[], [], []])

    assert await _has_completed_credit_source(task, user_id) is False

    invoice_call, gift_card_call = task.directus_service.get_items.call_args_list
    assert invoice_call.args[0] == "invoices"
    assert invoice_call.kwargs["params"]["filter"] == {"user_id_hash": {"_eq": user_id_hash}}
    assert gift_card_call.args[0] == "redeemed_gift_cards"
    assert gift_card_call.kwargs["params"]["filter"] == {"user_id_hash": {"_eq": user_id_hash}}


@pytest.mark.anyio
async def test_incomplete_signup_completion_accepts_redeemed_gift_card():
    from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import _has_completed_credit_source

    task = SimpleNamespace(directus_service=AsyncMock())
    task.directus_service.get_items = AsyncMock(side_effect=[[], [{"id": "redemption-1"}]])

    assert await _has_completed_credit_source(task, "user-1") is True


@pytest.mark.anyio
async def test_incomplete_signup_protection_accepts_stripe_payment_intent(monkeypatch):
    from backend.core.api.app.tasks.email_tasks import incomplete_signup_deletion_task as deletion_task

    class FakePaymentIntentList:
        def auto_paging_iter(self):
            return iter([
                SimpleNamespace(status="requires_payment_method", metadata={"purchase_type": "credits"}),
                SimpleNamespace(status="succeeded", metadata={"purchase_type": "credits"}),
            ])

    monkeypatch.setattr(deletion_task.stripe.PaymentIntent, "list", MagicMock(return_value=FakePaymentIntentList()))
    monkeypatch.setattr(deletion_task.stripe, "api_key", None)

    task = SimpleNamespace(directus_service=AsyncMock(), secrets_manager=AsyncMock())
    task.directus_service.get_items = AsyncMock(side_effect=[[], [], []])
    task.secrets_manager.get_secret = AsyncMock(return_value="sk_test_123")

    source = await deletion_task._account_protection_source(
        task,
        {"id": "user-1", "stripe_customer_id": "cus_123"},
        "user@example.com",
        datetime.now(timezone.utc),
    )

    assert source == "stripe_payment_intent"
    deletion_task.stripe.PaymentIntent.list.assert_called_once_with(customer="cus_123", limit=100)


@pytest.mark.anyio
async def test_incomplete_signup_protection_accepts_recent_pending_bank_transfer():
    from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import _account_protection_source

    now = datetime.now(timezone.utc)
    task = SimpleNamespace(directus_service=AsyncMock())
    task.directus_service.get_items = AsyncMock(side_effect=[
        [],
        [],
        [{"created_at": now.isoformat(), "expires_at": (now + timedelta(days=6)).isoformat(), "status": "pending"}],
    ])

    source = await _account_protection_source(task, {"id": "user-1"}, "user@example.com", now)

    assert source == "pending_bank_transfer"


@pytest.mark.anyio
async def test_incomplete_signup_dry_run_details_show_due_delete_action():
    from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import _async_process_incomplete_signup_deletions

    now = datetime.now(timezone.utc)
    user = {
        "id": "user-1",
        "status": "active",
        "is_admin": False,
        "signup_completed": False,
        "last_access": (now - timedelta(days=30)).isoformat(),
        "account_id": "ABC123",
        "language": "en",
        "stripe_customer_id": None,
    }
    deliveries = [
        {"stage": "14d", "sent_at": (now - timedelta(days=15)).isoformat()},
        {"stage": "1d", "sent_at": (now - timedelta(days=2)).isoformat()},
    ]
    task = SimpleNamespace(
        directus_service=AsyncMock(),
        encryption_service=AsyncMock(),
        secrets_manager=AsyncMock(),
        initialize_services=AsyncMock(),
        cleanup_services=AsyncMock(),
    )
    task.directus_service.get_items = AsyncMock(side_effect=[
        [user],
        [],
        [],
        [],
        deliveries,
        [{"encrypted_email_address": "encrypted-email"}],
        [],
    ])
    task.encryption_service.decrypt_account_contact_email = AsyncMock(return_value="user@example.com")
    task.secrets_manager.get_secret = AsyncMock(return_value="sk_test_123")

    class EmptyStripeList:
        def auto_paging_iter(self):
            return iter([])

    from backend.core.api.app.tasks.email_tasks import incomplete_signup_deletion_task as deletion_task

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(deletion_task.stripe.Customer, "list", MagicMock(return_value=EmptyStripeList()))
    monkeypatch.setattr(deletion_task.stripe, "api_key", None)

    try:
        result = await _async_process_incomplete_signup_deletions(task, dry_run=True, include_details=True)
    finally:
        monkeypatch.undo()

    assert result["deleted"] == 1
    assert len(result["due_actions"]) == 1
    due_action = result["due_actions"][0]
    assert due_action["user_id"] == "user-1"
    assert due_action["account_id"] == "ABC123"
    assert due_action["action"] == "delete_account"
    assert due_action["existing_stages"] == ["14d", "1d"]


@pytest.mark.anyio
async def test_incomplete_signup_skips_due_action_when_stripe_safety_fails():
    from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import _async_process_incomplete_signup_deletions

    now = datetime.now(timezone.utc)
    user = {
        "id": "user-1",
        "status": "active",
        "is_admin": False,
        "signup_completed": False,
        "last_access": (now - timedelta(days=20)).isoformat(),
        "account_id": "ABC123",
        "language": "en",
        "stripe_customer_id": "cus_123",
    }
    task = SimpleNamespace(
        directus_service=AsyncMock(),
        encryption_service=AsyncMock(),
        secrets_manager=AsyncMock(),
        initialize_services=AsyncMock(),
        cleanup_services=AsyncMock(),
    )
    task.directus_service.get_items = AsyncMock(side_effect=[
        [user],
        [],
        [],
        [],
        [],
        [{"encrypted_email_address": "encrypted-email"}],
    ])
    task.encryption_service.decrypt_account_contact_email = AsyncMock(return_value="user@example.com")
    task.secrets_manager.get_secret = AsyncMock(side_effect=RuntimeError("vault unavailable"))

    result = await _async_process_incomplete_signup_deletions(task, dry_run=True, include_details=True)

    assert result["sent_14d"] == 0
    assert result["skipped_safety_unknown"] == 1
    assert result["safety_skips"][0]["reason"] == "stripe_lookup_failed"


def test_paid_credit_update_marks_signup_complete():
    from backend.core.api.app.routes.payments import _paid_signup_completion_update_payload

    payload = _paid_signup_completion_update_payload(encrypted_credit_balance="encrypted-credits")

    assert payload == {
        "encrypted_credit_balance": "encrypted-credits",
        "last_opened": "/chat/new",
        "signup_completed": True,
    }


def test_password_login_treats_legacy_signup_resume_paths_as_complete():
    from backend.core.api.app.routes.auth_routes.auth_login import _is_obsolete_signup_resume_path

    assert _is_obsolete_signup_resume_path("/signup/one_time_codes") is True
    assert _is_obsolete_signup_resume_path("/signup/recovery-key") is True
    assert _is_obsolete_signup_resume_path("#signup/credits") is True
    assert _is_obsolete_signup_resume_path("/chat/new") is False
    assert _is_obsolete_signup_resume_path("demo-for-everyone") is False


@pytest.mark.anyio
async def test_user_cache_does_not_regress_completed_signup_to_stale_signup_step():
    from backend.core.api.app.services.cache_user_mixin import UserCacheMixin

    class FakeCache(UserCacheMixin):
        USER_KEY_PREFIX = "user:"
        SESSION_KEY_PREFIX = "session:"
        USER_TTL = 3600
        SESSION_TTL = 3600

        def __init__(self):
            self.saved_user = None

        async def get(self, key):
            assert key == "user:user-1"
            return {
                "user_id": "user-1",
                "last_opened": "/chat/new",
                "signup_completed": True,
            }

        async def set(self, key, value, ttl=None):
            assert key == "user:user-1"
            self.saved_user = value
            return True

    cache = FakeCache()

    await cache.set_user({"user_id": "user-1", "last_opened": "/signup/one_time_codes", "signup_completed": False})

    assert cache.saved_user["last_opened"] == "/chat/new"
    assert cache.saved_user["signup_completed"] is True
