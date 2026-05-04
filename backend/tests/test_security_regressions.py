# backend/tests/test_security_regressions.py
#
# Focused regression tests for merge-blocking security fixes.

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
