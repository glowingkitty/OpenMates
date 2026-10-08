# backend/tests/test_auth_session_security_isolation.py
# Contract tests for logical-session security isolation.
# These tests keep country risk state separate from account profile data and
# prove refresh rotation, encrypted display metadata, and device identity do
# not leak authentication effects across sibling sessions.

import asyncio
import hashlib
import copy
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, Response

from backend.core.api.app.routes.auth_routes import auth_common
from backend.core.api.app.routes.auth_routes import auth_session
from backend.core.api.app.utils import device_fingerprint
from backend.core.api.app.services import session_security_state


class FakeCache:
    def __init__(self, values):
        self.values = values

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True


class FakeRequest:
    headers = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/140.0"}
    client = None


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


# contract-test: direct surface=rest_api assertions=auth.session.isolation,auth.session.risk-reauth
def test_country_risk_uses_only_the_current_logical_session():
    cache = FakeCache({
        "user_tokens:user-1": {
            token_hash("browser-token"): {"security_country_code": "DE"},
            token_hash("cli-token"): {"security_country_code": "FI"},
        },
    })

    browser = asyncio.run(auth_common.get_session_security_country(cache, "user-1", "browser-token"))
    cli = asyncio.run(auth_common.get_session_security_country(cache, "user-1", "cli-token"))

    assert browser == "DE"
    assert cli == "FI"
    assert auth_common.session_country_changed(cli, "FI") is False
    assert auth_common.session_country_changed(cli, "US") is True


# contract-test: direct surface=rest_api assertions=auth.session.isolation,auth.session.risk-reauth
def test_country_update_mutates_only_the_target_session_and_preserves_encrypted_meta():
    browser_hash = token_hash("browser-token")
    cli_hash = token_hash("cli-token")
    cache = FakeCache({
        "user_tokens:user-1": {
            browser_hash: {"security_country_code": "DE", "encrypted_meta": "opaque-browser"},
            cli_hash: {"security_country_code": "FI", "encrypted_meta": "opaque-cli"},
        },
    })

    updated = asyncio.run(
        auth_common.set_session_security_country(cache, "user-1", "cli-token", "US")
    )

    assert updated is True
    assert cache.values["user_tokens:user-1"][browser_hash] == {
        "security_country_code": "DE",
        "encrypted_meta": "opaque-browser",
    }
    assert cache.values["user_tokens:user-1"][cli_hash] == {
        "security_country_code": "US",
        "encrypted_meta": "opaque-cli",
    }


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation
def test_refresh_rotation_preserves_session_security_metadata():
    old_hash = token_hash("old-token")
    new_hash = token_hash("new-token")
    cache = FakeCache({
        "user_tokens:user-1": {
            old_hash: {
                "created_at": 123,
                "stay_logged_in": True,
                "security_country_code": "FI",
                "encrypted_meta": "opaque",
            },
        },
    })

    user_data = {"stay_logged_in": False}
    asyncio.run(
        auth_common.preserve_rotated_session_metadata(
            cache,
            user_id="user-1",
            old_refresh_token="old-token",
            new_refresh_token="new-token",
            user_data=user_data,
        )
    )

    assert old_hash not in cache.values["user_tokens:user-1"]
    assert cache.values["user_tokens:user-1"][new_hash]["security_country_code"] == "FI"
    assert cache.values["user_tokens:user-1"][new_hash]["encrypted_meta"] == "opaque"
    assert user_data["stay_logged_in"] is True


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth
def test_device_identity_is_independent_from_country(monkeypatch):
    countries = iter(("DE", "FI"))

    def geo(_ip):
        return {
            "country_code": next(countries),
            "region": None,
            "city": None,
            "latitude": None,
            "longitude": None,
        }

    monkeypatch.setattr(device_fingerprint, "get_geo_data_from_ip", geo)

    first = device_fingerprint.generate_device_fingerprint_hash(FakeRequest(), "user-1", "tab-1")
    second = device_fingerprint.generate_device_fingerprint_hash(FakeRequest(), "user-1", "tab-1")

    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[3] == "DE"
    assert second[3] == "FI"


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth
def test_legacy_device_hash_remains_available_for_migration():
    expected = hashlib.sha256("Linux:FI:user-1".encode()).hexdigest()

    assert (
        device_fingerprint.generate_legacy_device_fingerprint_hash(
            "Linux", "FI", "user-1"
        )
        == expected
    )


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth,auth.keys.independent-unlock
def test_passkey_risk_challenge_offers_email_fallback_only_with_password_wrapper():
    assert not auth_session._has_password_wrapper([{"login_method": "passkey_v2_abc"}])
    assert auth_session._has_password_wrapper([{"login_method": "passkey_v2_abc"}, {"login_method": "password"}])
    assert auth_session._has_password_wrapper([{"login_method": "password_v2_xyz"}])


@pytest.fixture
def durable_session(monkeypatch):
    """Exercise the route with synthetic services and the real durable reader."""
    rows = {
        token_hash(token): {
            "id": token, "user_id": owner, "token_hash": token_hash(token),
            "logical_session_id": token, "expires_at": int(time.time()) + 3600,
            "revoked": False, "retired": False, "risk_pending": pending,
            "strong_verified_at": None, "proof_method": None,
        }
        for token, owner, pending in (
            ("pending-token", "user-1", True),
            ("sibling-token", "user-1", False),
            ("other-account-token", "user-2", True),
        )
    }
    user = {"user_id": "user-1", "username": "synthetic-user", "tfa_enabled": True,
            "token_expiry": int(time.time()) + 3600}
    cache = FakeCache({
        "user_tokens:user-1": {
            token_hash(token): {"security_country_code": "DE", "encrypted_meta": token}
            for token in ("pending-token", "sibling-token")
        },
        "user_tokens:user-2": {
            token_hash("other-account-token"): {"security_country_code": "FI"}
        },
    })
    cache.SESSION_TTL = 86400
    cache.update_user = AsyncMock(return_value=True)
    cache.set_user = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=True)

    async def get_items(collection, params=None, **kwargs):
        if collection == session_security_state.COLLECTION:
            row = rows.get(params["filter"]["token_hash"]["_eq"])
            return [dict(row)] if row else []
        assert collection == "encryption_keys"
        return [{"login_method": "passkey_v2_test"}]

    async def update_item(collection, item_id, changes, **kwargs):
        assert collection == session_security_state.COLLECTION
        rows[token_hash(item_id)].update(changes)
        return True

    directus = SimpleNamespace(
        get_items=AsyncMock(side_effect=get_items),
        _update_item=AsyncMock(side_effect=update_item),
        get_user_device_hashes=AsyncMock(return_value=["known-device"]),
        get_user_passkeys=AsyncMock(return_value=[{"id": "passkey"}]),
        add_user_device_hash=AsyncMock(), update_user=AsyncMock(),
    )

    async def verify(request, *_args, **_kwargs):
        return True, dict(user), request.cookies["auth_refresh_token"], None

    monkeypatch.setattr(auth_session, "verify_authenticated_user", verify)
    monkeypatch.setattr(auth_session, "get_signup_requirements", AsyncMock(return_value=(False, None, None)))
    monkeypatch.setattr(auth_session, "generate_device_fingerprint_hash", Mock(
        return_value=("known-device", "connection", "Linux", "DE", None, None, None, None)))
    monkeypatch.setattr(auth_session, "_has_free_testing_credits_grant", AsyncMock(return_value=False))
    ws_tokens = Mock(return_value="synthetic-ws-token")
    monkeypatch.setattr(auth_session, "create_ws_token", ws_tokens)

    async def call(token="pending-token"):
        request = SimpleNamespace(
            cookies={"auth_refresh_token": token}, headers=FakeRequest.headers,
            client=None, json=AsyncMock(return_value={"session_id": "installed-device"}),
        )
        return await auth_session.get_session(request, Response(), directus, cache, token)

    return SimpleNamespace(rows=rows, user=user, cache=cache,
                           directus=directus, call=call, ws_tokens=ws_tokens)


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth,auth.session.isolation
@pytest.mark.parametrize("factor,expected_challenge", [("totp", "2fa"), ("passkey", "passkey"), ("none", None)])
def test_durable_pending_risk_survives_unchanged_device_and_country(durable_session, factor, expected_challenge):
    state = durable_session
    state.user["tfa_enabled"] = factor == "totp"
    state.directus.get_user_passkeys.return_value = [{"id": "passkey"}] if factor == "passkey" else []
    original_rows = copy.deepcopy(state.rows)
    original_cache = copy.deepcopy(state.cache.values)

    # Returning to a trusted location repeatedly cannot approve the challenge.
    for _ in range(2):
        result = asyncio.run(state.call())
        assert result.success is False
        assert result.re_auth_required == expected_challenge
        assert result.re_auth_reason == "session_verification"
        assert result.ws_token is None
        assert result.user is None or result.user.id == "user-1"
    assert state.rows == original_rows
    assert state.cache.values == original_cache
    state.ws_tokens.assert_not_called()
    state.directus._update_item.assert_not_awaited()
    state.directus.add_user_device_hash.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth,auth.session.isolation
def test_pending_risk_leaves_sibling_authorized_and_only_verified_session_resumes(durable_session):
    state = durable_session
    original_rows = copy.deepcopy(state.rows)
    other_metadata = copy.deepcopy(state.cache.values["user_tokens:user-2"])

    sibling = asyncio.run(state.call("sibling-token"))
    assert sibling.success is True
    assert sibling.ws_token == "synthetic-ws-token"
    assert state.rows == original_rows
    state.ws_tokens.reset_mock()

    # The existing server-verified proof transition approves only this token.
    asyncio.run(session_security_state.mark_recent_strong_proof(
        state.directus, state.cache, "pending-token", "user-1",
        method="totp", clear_risk=True,
    ))
    resumed = asyncio.run(state.call())
    assert resumed.success is True
    assert resumed.re_auth_required is None
    assert resumed.ws_token == "synthetic-ws-token"
    state.ws_tokens.assert_called_once_with("pending-token")
    assert state.rows[token_hash("pending-token")]["risk_pending"] is False
    assert state.rows[token_hash("sibling-token")] == original_rows[token_hash("sibling-token")]
    assert state.rows[token_hash("other-account-token")] == original_rows[token_hash("other-account-token")]
    assert state.cache.values["user_tokens:user-2"] == other_metadata


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth,auth.session.isolation
def test_session_risk_state_must_belong_to_authenticated_user(durable_session):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(durable_session.call("other-account-token"))
    assert exc.value.status_code == 401
    durable_session.ws_tokens.assert_not_called()
    durable_session.directus._update_item.assert_not_awaited()
