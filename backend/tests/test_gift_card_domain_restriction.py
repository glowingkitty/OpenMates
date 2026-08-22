"""
backend/tests/test_gift_card_domain_restriction.py

Unit tests for the OPE-76 reusable + mailbox-bound gift card extension:

1. Regression guard: single-use cards still get deleted on redemption
2. Reusable cards are NOT deleted (the row survives)
3. Identity-bound cards reject a different mailbox with a clear error
4. Identity-bound cards reject users without an email
5. Gmail run aliases resolve to the configured mailbox identity
6. Legacy domain-bound cards fail closed until migrated

These tests mock the Directus HTTP layer entirely (via a fake DirectusService
shell) and only exercise the pure Python logic in
`backend/core/api/app/services/directus/gift_card_methods.py`.

Bug history this test suite guards against:
- OPE-76: without an identity restriction, the hourly prod smoke test gift card
  could in principle be redeemed by any authenticated user who learned the
  code. This suite locks in exact mailbox-identity enforcement as a
  security invariant.
"""
from __future__ import annotations

import types
from typing import Any, Dict, List, Optional, Tuple

import pytest

# contract-test-file: tooling

from backend.core.api.app.services.directus.gift_card_methods import (
    GiftCardIdentityMismatchError,
    GiftCardEmailRequiredError,
    GiftCardRestrictionConfigurationError,
    _email_identity_hash,
    _enforce_gift_card_identity,
    create_gift_card,
    get_gift_card_by_code,
    redeem_gift_card,
)


class _FakeResponse:
    def __init__(self, status_code: int, json_data: Optional[Dict[str, Any]] = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self) -> Dict[str, Any]:
        return self._json


class _FakeCache:
    def __init__(self) -> None:
        self.store: Dict[str, Any] = {}
        self.deleted: List[str] = []

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.store.pop(key, None)


class _FakeDirectus:
    """Minimal shell that satisfies the instance-method signature expected by
    the functions under test. Because the real `DirectusService` assembles
    methods from many mixin files at runtime, we manually bind the two module
    functions we need (`get_gift_card_by_code`, `redeem_gift_card`) onto each
    fake instance so the internal `self.get_gift_card_by_code(...)` call
    inside `redeem_gift_card` resolves correctly."""

    def __init__(self, gift_card_row: Optional[Dict[str, Any]]):
        self.base_url = "http://fake-directus:8055"
        self.cache = _FakeCache()
        self.cache_ttl = 60
        self._gift_card_row = gift_card_row
        self.delete_called_for: List[str] = []
        # Bind the real module functions as instance methods so that the
        # `self.get_gift_card_by_code(code)` call inside `redeem_gift_card`
        # resolves to the real implementation (which then calls back into
        # our fake HTTP layer below).
        self.get_gift_card_by_code = types.MethodType(get_gift_card_by_code, self)

    async def _make_api_request(self, method: str, url: str, params: Any = None) -> _FakeResponse:
        if method == "GET":
            items = [self._gift_card_row] if self._gift_card_row else []
            return _FakeResponse(200, {"data": items})
        if method == "DELETE":
            self.delete_called_for.append(url)
            return _FakeResponse(204)
        raise AssertionError(f"Unexpected HTTP method: {method}")

    async def create_item(self, collection: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        return True, {"id": "fake-id", **data}


class TestEnforceGiftCardIdentity:
    def test_gmail_aliases_share_one_mailbox_identity(self) -> None:
        expected_hash = _email_identity_hash("openmates.e2e@gmail.com")

        _enforce_gift_card_identity(
            allowed_email_identity_hash=expected_hash,
            legacy_allowed_email_domain=None,
            user_email="openmatese2e+run-123@googlemail.com",
        )

    def test_different_gmail_mailbox_is_rejected(self) -> None:
        expected_hash = _email_identity_hash("openmates.e2e@gmail.com")

        with pytest.raises(GiftCardIdentityMismatchError):
            _enforce_gift_card_identity(
                allowed_email_identity_hash=expected_hash,
                legacy_allowed_email_domain=None,
                user_email="attacker@gmail.com",
            )

    def test_legacy_domain_restriction_fails_closed(self) -> None:
        with pytest.raises(GiftCardRestrictionConfigurationError):
            _enforce_gift_card_identity(
                allowed_email_identity_hash=None,
                legacy_allowed_email_domain="legacy.test.example",
                user_email="smoke@legacy.test.example",
            )

# ----------------------------- redeem_gift_card ---------------------------------


@pytest.mark.asyncio
async def test_single_use_card_is_deleted_on_redemption() -> None:
    """Regression: default single-use behavior must remain unchanged."""
    row = {
        "id": "single-use-1",
        "code": "ABCD-EFGH-IJKL",
        "credits_value": 100,
        "is_reusable": False,
    }
    fake = _FakeDirectus(gift_card_row=row)
    fake.cache.store["gift_card:ABCD-EFGH-IJKL"] = row  # prime cache

    ok = await redeem_gift_card(fake, "ABCD-EFGH-IJKL", "user-1")

    assert ok is True
    assert len(fake.delete_called_for) == 1, "single-use card must be DELETEd"
    assert "gift_card:ABCD-EFGH-IJKL" in fake.cache.deleted


@pytest.mark.asyncio
async def test_reusable_card_is_not_deleted_on_redemption() -> None:
    """Reusable cards must survive redemption so the prod smoke test can
    redeem the same code every hour."""
    row = {
        "id": "reusable-1",
        "code": "SMOKE-TEST-CODE",
        "credits_value": 500,
        "is_reusable": True,
    }
    fake = _FakeDirectus(gift_card_row=row)
    fake.cache.store["gift_card:SMOKE-TEST-CODE"] = row

    ok = await redeem_gift_card(fake, "SMOKE-TEST-CODE", "user-1")

    assert ok is True
    assert fake.delete_called_for == [], "reusable card must NOT be DELETEd"
    # Cache IS still invalidated so any admin-side metadata changes are re-read.
    assert "gift_card:SMOKE-TEST-CODE" in fake.cache.deleted


@pytest.mark.asyncio
async def test_domain_bound_card_rejects_mismatched_email() -> None:
    row = {
        "id": "domain-bound-1",
        "code": "SMOKE-TEST-CODE",
        "credits_value": 500,
        "is_reusable": True,
        "allowed_email_identity_hash": _email_identity_hash("smoke@example.com"),
    }
    fake = _FakeDirectus(gift_card_row=row)

    with pytest.raises(GiftCardIdentityMismatchError):
        await redeem_gift_card(
            fake,
            "SMOKE-TEST-CODE",
            "user-1",
            user_email="attacker@example.com",
        )
    # No Directus mutation should have happened
    assert fake.delete_called_for == []


@pytest.mark.asyncio
async def test_domain_bound_card_accepts_matching_email() -> None:
    row = {
        "id": "domain-bound-2",
        "code": "SMOKE-TEST-CODE",
        "credits_value": 500,
        "is_reusable": True,
        "allowed_email_identity_hash": _email_identity_hash("smoke@example.com"),
    }
    fake = _FakeDirectus(gift_card_row=row)

    ok = await redeem_gift_card(
        fake,
        "SMOKE-TEST-CODE",
        "user-1",
        user_email="smoke@example.com",
    )
    assert ok is True
    assert fake.delete_called_for == []  # still reusable


@pytest.mark.asyncio
async def test_domain_bound_card_without_email_raises() -> None:
    row = {
        "id": "domain-bound-3",
        "code": "SMOKE-TEST-CODE",
        "credits_value": 500,
        "is_reusable": True,
        "allowed_email_identity_hash": _email_identity_hash("smoke@example.com"),
    }
    fake = _FakeDirectus(gift_card_row=row)

    with pytest.raises(GiftCardEmailRequiredError):
        await redeem_gift_card(fake, "SMOKE-TEST-CODE", "user-1", user_email=None)
    assert fake.delete_called_for == []


@pytest.mark.asyncio
async def test_unrestricted_reusable_ignores_email() -> None:
    """A reusable card without an identity restriction must not require an email
    (no reason to — there's no check to run)."""
    row = {
        "id": "reusable-unrestricted",
        "code": "FREEBIE-CODE",
        "credits_value": 10,
        "is_reusable": True,
    }
    fake = _FakeDirectus(gift_card_row=row)

    ok = await redeem_gift_card(fake, "FREEBIE-CODE", "user-1", user_email=None)
    assert ok is True


@pytest.mark.asyncio
async def test_identity_bound_card_accepts_gmail_run_alias() -> None:
    row = {
        "id": "identity-bound-1",
        "code": "SMOKE-TEST-CODE",
        "credits_value": 500,
        "is_reusable": True,
        "allowed_email_identity_hash": _email_identity_hash("openmates.e2e@gmail.com"),
    }
    fake = _FakeDirectus(gift_card_row=row)

    ok = await redeem_gift_card(
        fake,
        "SMOKE-TEST-CODE",
        "user-1",
        user_email="openmatese2e+run-123@gmail.com",
    )

    assert ok is True
    assert fake.delete_called_for == []


# ------------------------------ create_gift_card --------------------------------


@pytest.mark.asyncio
async def test_create_gift_card_defaults_preserve_legacy_behavior() -> None:
    """Creating a card with only the legacy arguments must not emit the new
    fields in the Directus payload. This keeps the user-buy and admin-UI
    flows byte-for-byte compatible."""
    fake = _FakeDirectus(gift_card_row=None)
    captured: Dict[str, Any] = {}

    async def capturing_create_item(collection: str, data: Dict[str, Any]):
        captured.update(data)
        return True, {"id": "x", **data}

    fake.create_item = capturing_create_item  # type: ignore[assignment]

    result = await create_gift_card(fake, code="NEW-CODE", credits_value=50)

    assert result is not None
    assert captured.get("code") == "NEW-CODE"
    assert "is_reusable" not in captured, "defaults must not leak into payload"
    assert "allowed_email_identity_hash" not in captured


@pytest.mark.asyncio
async def test_create_gift_card_stores_allowed_identity_hash() -> None:
    fake = _FakeDirectus(gift_card_row=None)
    captured: Dict[str, Any] = {}

    async def capturing_create_item(collection: str, data: Dict[str, Any]):
        captured.update(data)
        return True, {"id": "x", **data}

    fake.create_item = capturing_create_item  # type: ignore[assignment]

    await create_gift_card(
        fake,
        code="REUSABLE-CODE",
        credits_value=500,
        is_reusable=True,
        allowed_email_identity_hash="  identity-hash  ",
    )

    assert captured.get("is_reusable") is True
    assert captured.get("allowed_email_identity_hash") == "identity-hash"
