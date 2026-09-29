"""Typed lookup bindings and immutable wrapper switch behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.core.api.app.services.credential_verification import (
    acquire_credential_change_lock, replace_typed_lookup, typed_lookup_method,
    typed_lookup_wrapper,
)


# contract-test: direct surface=rest_api assertions=auth.login.verified-method
def test_untyped_legacy_lookup_never_gains_method_authority():
    assert typed_lookup_method(None, "legacy-hash") is None
    assert typed_lookup_method({"password": "other-hash"}, "legacy-hash") is None
    assert typed_lookup_method({"password": "same", "recovery_key": "same"}, "same") is None


# contract-test: direct surface=rest_api assertions=auth.credentials.atomic-replacement,auth.login.verified-method
def test_versioned_wrapper_binding_replaces_only_its_method():
    original = {"password": "old", "recovery_key": "recovery", "passkey_abc": "passkey"}
    updated = replace_typed_lookup(
        original, "password", "new", wrapper_method="password_v2_123")
    assert original["password"] == "old"
    assert updated["password"] == {"lookup_hash": "new", "wrapper_method": "password_v2_123"}
    assert updated["recovery_key"] == "recovery"
    assert updated["passkey_abc"] == "passkey"
    assert typed_lookup_method(updated, "old") is None
    assert typed_lookup_method(updated, "new") == "password"
    assert typed_lookup_wrapper(updated, "password", "new") == "password_v2_123"
    assert typed_lookup_wrapper(updated, "password", "old") is None


# contract-test: direct surface=rest_api assertions=auth.credentials.atomic-replacement
@pytest.mark.anyio
async def test_password_recovery_and_passkey_updates_share_account_lock():
    names = []
    redis = MagicMock()
    redis.lock.side_effect = lambda name, **kwargs: (
        names.append(name) or MagicMock(acquire=AsyncMock(return_value=True))
    )

    class Cache:
        @property
        def client(self):
            return asyncio.sleep(0, result=redis)

    for method in ("password", "recovery_key", "passkey"):
        await acquire_credential_change_lock(Cache(), "user-123", method)
    assert names == ["auth:credential-change:user-123"] * 3
