"""Keep nullable legacy email envelopes distinct from incomplete profile caches."""

import base64
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import Response

from backend.core.api.app.services.directus.user.user_profile import get_user_profile


class _Cache:
    def __init__(self, profile=None):
        self.values = {"user_profile:user-1": profile} if profile is not None else {}
        self.deleted = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True

    async def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)
        return True


def _profile(envelope_marker):
    profile = {
        "id": "user-1", "user_id": "user-1", "vault_key_id": "vault-1",
        "username": "Person", "hashed_email": "email-hash",
    }
    if envelope_marker is not ...:
        profile["encrypted_email_with_master_key"] = envelope_marker
    return profile


def _service(cache, source):
    raw = {
        "vault_key_id": "vault-1", "encrypted_username": "username-ciphertext",
        "hashed_email": "email-hash", **source,
    }
    service = SimpleNamespace(
        cache=cache, base_url="http://cms.test", cache_ttl=3600,
        encryption_service=SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value="Person")),
        _make_api_request=AsyncMock(return_value=httpx.Response(200, json={"data": raw})),
    )
    return service


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
async def test_explicit_null_envelope_is_reused_without_refetch_or_eviction():
    cache = _Cache(_profile(None))
    service = _service(cache, {"encrypted_email_with_master_key": None})

    success, profile, message = await get_user_profile(service, "user-1")

    assert success is True
    assert profile["encrypted_email_with_master_key"] is None
    assert message == "Profile retrieved from cache"
    assert cache.deleted == []
    service._make_api_request.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
async def test_omitted_envelope_in_partial_cache_forces_authoritative_refetch():
    cache = _Cache(_profile(...))
    service = _service(cache, {"encrypted_email_with_master_key": None})

    success, profile, _ = await get_user_profile(service, "user-1")

    assert success is True
    assert cache.deleted == ["user_profile:user-1"]
    service._make_api_request.assert_awaited_once()
    assert "encrypted_email_with_master_key" in profile
    assert profile["encrypted_email_with_master_key"] is None
    assert cache.values["user_profile:user-1"] == profile


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
async def test_missing_raw_column_is_not_synthesized_as_known_null():
    cache = _Cache()
    service = _service(cache, {})

    first_success, first_profile, _ = await get_user_profile(service, "user-1")
    second_success, second_profile, _ = await get_user_profile(service, "user-1")

    assert first_success and second_success
    assert "encrypted_email_with_master_key" not in first_profile
    assert "encrypted_email_with_master_key" not in second_profile
    assert "encrypted_email_with_master_key" not in cache.values["user_profile:user-1"]
    assert cache.deleted == ["user_profile:user-1"]
    assert service._make_api_request.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("envelope, expected_success", [(None, False), ("email-ciphertext", True)])
# contract-test: direct surface=rest_api assertions=auth.passkey.origin-prf-bound
async def test_passkey_assertion_still_requires_nonempty_envelope(monkeypatch, envelope, expected_success):
    from backend.core.api.app.routes.auth_routes import auth_passkey
    from backend.core.api.app.schemas.auth import PasskeyAssertionVerifyRequest

    user_id = "user-1"
    challenge = "Y2hhbGxlbmdl"
    client_data = base64.urlsafe_b64encode(json.dumps({
        "type": "webauthn.get", "challenge": challenge,
    }).encode()).decode().rstrip("=")
    credential = "Y3JlZGVudGlhbA"
    profile = _profile(envelope)
    profile["user_email_salt"] = "salt"
    directus = SimpleNamespace(
        get_passkey_by_credential_id=AsyncMock(return_value={
            "id": "passkey-1", "user_id": user_id,
            "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
            "sign_count": 0, "public_key_cose": "YQ",
        }),
        update_passkey_sign_count=AsyncMock(return_value=True),
        get_encryption_key=AsyncMock(return_value={
            "encrypted_key": "key-ciphertext", "key_iv": "iv", "salt": "salt",
        }),
        get_user_profile=AsyncMock(return_value=(True, profile, "ok")),
    )
    cache = SimpleNamespace(
        get=AsyncMock(return_value="challenge-ready"),
        set=AsyncMock(return_value=True),
        get_user_by_id=AsyncMock(return_value=dict(profile)),
        set_user=AsyncMock(return_value=True),
        cache=SimpleNamespace(delete=AsyncMock(return_value=True)),
    )
    monkeypatch.setattr(auth_passkey, "get_rp_id_from_request", lambda _request: "example.test")
    monkeypatch.setattr(auth_passkey, "verify_authentication_response",
                        lambda **_kwargs: SimpleNamespace(new_sign_count=1))
    request = SimpleNamespace(
        headers={"Origin": "https://example.test"},
        client=SimpleNamespace(host="127.0.0.1"), cookies={},
    )
    body = PasskeyAssertionVerifyRequest(
        credential_id=credential,
        assertion_response={"signature": "YQ"},
        client_data_json=client_data,
        authenticator_data="YQ",
    )

    result = await auth_passkey.passkey_assertion_verify(
        request, body, Response(), directus, cache, SimpleNamespace(),
        SimpleNamespace(log_auth_event=lambda **_kwargs: None), SimpleNamespace(),
    )

    assert result.success is expected_success
    assert result.encrypted_email == (envelope if expected_success else None)
    if not expected_success:
        assert "passkey needs to be updated" in result.message
        cache.cache.delete.assert_awaited_once()
        directus.get_user_profile.assert_awaited_once()
