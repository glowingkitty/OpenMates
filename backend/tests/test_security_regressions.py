# backend/tests/test_security_regressions.py
#
# Focused regression tests for merge-blocking security fixes.

import hashlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


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


class _DomainSecurityService:
    config_loaded = True

    def validate_email_domain(self, _email: str):
        return True, None


@pytest.mark.asyncio
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

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(domain_security_service=_DomainSecurityService()))
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
        await settings.confirm_email_change.__wrapped__(
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


@pytest.mark.asyncio
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
@pytest.mark.asyncio
async def test_store_account_lifecycle_contact_email_uses_vault_encryption():
    from backend.core.api.app.routes.auth_routes.auth_utils import store_account_lifecycle_contact_email

    directus_service = AsyncMock()
    directus_service.create_item = AsyncMock(return_value=(True, {"id": "bed33190-7517-5958-9b7f-bc9fd4e7cb2a"}))
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_incomplete_signup_completion_requires_invoice_or_gift_card():
    from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import _has_completed_credit_source

    user_id = "user-1"
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    task = SimpleNamespace(directus_service=AsyncMock())
    task.directus_service.get_items = AsyncMock(side_effect=[[], []])

    assert await _has_completed_credit_source(task, user_id) is False

    invoice_call, gift_card_call = task.directus_service.get_items.call_args_list
    assert invoice_call.args[0] == "invoices"
    assert invoice_call.kwargs["params"]["filter"] == {
        "user_id_hash": {"_eq": user_id_hash},
        "status": {"_eq": "completed"},
    }
    assert gift_card_call.args[0] == "redeemed_gift_cards"
    assert gift_card_call.kwargs["params"]["filter"] == {"user_id_hash": {"_eq": user_id_hash}}


@pytest.mark.asyncio
async def test_incomplete_signup_completion_accepts_redeemed_gift_card():
    from backend.core.api.app.tasks.email_tasks.incomplete_signup_deletion_task import _has_completed_credit_source

    task = SimpleNamespace(directus_service=AsyncMock())
    task.directus_service.get_items = AsyncMock(side_effect=[[], [{"id": "redemption-1"}]])

    assert await _has_completed_credit_source(task, "user-1") is True
