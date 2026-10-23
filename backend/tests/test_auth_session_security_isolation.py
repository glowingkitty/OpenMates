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
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "synthetic-internal-token")
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

    async def call(token="pending-token", *, include_personal_memories=None, headers=None):
        request = SimpleNamespace(
            cookies={"auth_refresh_token": token}, headers=headers or FakeRequest.headers,
            client=None, json=AsyncMock(return_value={
                "session_id": "installed-device",
                **({"include_personal_memories": include_personal_memories}
                   if include_personal_memories is not None else {}),
            }),
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


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.risk-reauth
def test_session_independent_reads_start_together_and_finish_before_success(durable_session, monkeypatch):
    state = durable_session
    started = []

    async def scenario():
        all_started = asyncio.Event()

        async def read(name, value):
            started.append(name)
            if len(started) == 4:
                all_started.set()
            await all_started.wait()
            return value

        async def devices(*_args):
            return await read("devices", ["known-device"])

        monkeypatch.setattr(auth_session, "get_session_state_cached", lambda *_args, **_kwargs: read("ledger", state.rows[token_hash("sibling-token")]))
        state.directus.get_user_device_hashes.side_effect = devices
        monkeypatch.setattr(auth_session, "get_session_security_country", lambda *_args: read("country", "DE"))
        monkeypatch.setattr(auth_session, "_has_free_testing_credits_grant", lambda *_args: read("grant", True))
        return await asyncio.wait_for(state.call("sibling-token"), timeout=1)

    result = asyncio.run(scenario())
    assert set(started) == {"ledger", "devices", "country", "grant"}
    assert result.success is True
    assert result.user.has_free_testing_credits_grant is True
    state.directus.add_user_device_hash.assert_awaited_once()


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.risk-reauth
def test_session_rejects_failed_durable_read_after_parallel_reads(durable_session, monkeypatch):
    state = durable_session
    monkeypatch.setattr(auth_session, "get_session_state_cached", AsyncMock(side_effect=HTTPException(401, "Session revoked")))
    grant = AsyncMock(return_value=True)
    monkeypatch.setattr(auth_session, "_has_free_testing_credits_grant", grant)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(state.call("sibling-token"))

    assert exc.value.status_code == 401
    state.directus.get_user_device_hashes.assert_awaited_once()
    grant.assert_awaited_once()
    state.directus.add_user_device_hash.assert_not_awaited()
    state.directus.update_user.assert_not_awaited()
    state.ws_tokens.assert_not_called()


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth
@pytest.mark.parametrize("risk_source", ["new_device", "country_change"])
def test_parallel_reads_keep_new_device_and_country_challenges(durable_session, monkeypatch, risk_source):
    state = durable_session
    if risk_source == "new_device":
        state.directus.get_user_device_hashes.return_value = []
    else:
        monkeypatch.setattr(auth_session, "generate_device_fingerprint_hash", Mock(
            return_value=("known-device", "connection", "Linux", "FI", None, None, None, None)))
    grant = AsyncMock(return_value=True)
    monkeypatch.setattr(auth_session, "_has_free_testing_credits_grant", grant)

    result = asyncio.run(state.call("sibling-token"))

    assert result.success is False
    assert result.re_auth_required == "2fa"
    assert result.re_auth_reason == ("new_device" if risk_source == "new_device" else "location_change")
    assert result.ws_token is None
    assert state.rows[token_hash("sibling-token")]["risk_pending"] is True
    grant.assert_awaited_once()
    state.directus.add_user_device_hash.assert_not_awaited()
    state.directus.update_user.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle
def test_invalid_basic_auth_does_not_start_parallel_reads(durable_session, monkeypatch):
    state = durable_session
    monkeypatch.setattr(auth_session, "verify_authenticated_user", AsyncMock(return_value=(False, {}, None, "authentication_failed")))
    ledger = AsyncMock()
    grant = AsyncMock()
    monkeypatch.setattr(auth_session, "get_session_state_cached", ledger)
    monkeypatch.setattr(auth_session, "_has_free_testing_credits_grant", grant)

    result = asyncio.run(state.call("sibling-token"))

    assert result.success is False
    ledger.assert_not_awaited()
    grant.assert_not_awaited()
    state.directus.get_user_device_hashes.assert_not_awaited()
    state.ws_tokens.assert_not_called()


def _personal_memory_row(user_id="user-1", team_id=None):
    return {
        "id": "memory-1", "app_id": "openmates", "item_type": "memories",
        "item_key": "key-hash", "encrypted_item_json": "opaque-ciphertext",
        "item_version": 1, "created_at": 10, "updated_at": 20,
        "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
        "hashed_team_id": team_id,
    }


def _personal_settings_response(*, user_id="user-1", settings=None, include_settings=True):
    data = {"id": user_id}
    if include_settings:
        data["encrypted_settings"] = settings
    return SimpleNamespace(status_code=200, json=lambda: {"data": data})


def _legacy_personal_api(profile, status_code=200):
    """Model explicit endpoint non-support separately from legacy profile reads."""
    async def request(method, url, **kwargs):
        if url.endswith("/personal-privacy-snapshot"):
            assert method == "POST"
            return SimpleNamespace(status_code=status_code, json=lambda: {"data": {"supported": False}})
        assert method == "GET"
        return await profile(method, url, **kwargs)
    return request


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
def test_session_personal_batch_starts_fresh_reads_after_admission_and_preserves_receipt(durable_session, monkeypatch):
    state = durable_session
    events = []
    original_ledger = auth_session.get_session_state_cached
    original_items = state.directus.get_items.side_effect

    async def ledger(*args, **kwargs):
        events.append("ledger")
        return await original_ledger(*args, **kwargs)

    async def profile(*args, **kwargs):
        events.append("profile")
        return _personal_settings_response(settings="settings-ciphertext")

    async def items(collection, params=None, **kwargs):
        if collection == "user_app_settings_and_memories":
            events.append("memories")
            return [_personal_memory_row()]
        return await original_items(collection, params=params, **kwargs)

    monkeypatch.setattr(auth_session, "get_session_state_cached", ledger)
    state.directus.base_url = "http://cms.test"
    state.directus._make_api_request = AsyncMock(side_effect=_legacy_personal_api(profile))
    state.directus.get_items.side_effect = items

    result = asyncio.run(state.call("sibling-token", include_personal_memories=True))

    assert result.success is True
    assert result.ws_token == "synthetic-ws-token"
    state.ws_tokens.assert_called_once_with("sibling-token")
    assert events.index("ledger") < events.index("profile")
    assert events.index("ledger") < events.index("memories")
    profile_call = state.directus._make_api_request.await_args
    assert profile_call.args[0] == "GET"
    assert profile_call.args[1].startswith("http://cms.test/users/user-1?fields=id,encrypted_settings&_ts=")
    assert profile_call.kwargs == {"headers": {"Cache-Control": "no-store"}}
    memory_call = next(call for call in state.directus.get_items.await_args_list
                       if call.args[0] == "user_app_settings_and_memories")
    assert memory_call.kwargs["no_cache"] is True
    assert memory_call.kwargs["raise_on_error"] is True
    assert memory_call.kwargs["params"]["filter"] == {
        "hashed_user_id": {"_eq": hashlib.sha256(b"user-1").hexdigest()},
        "hashed_team_id": {"_null": True},
    }
    assert memory_call.kwargs["params"]["limit"] == -1
    assert memory_call.kwargs["params"]["sort"] == "-updated_at"
    payload = result.model_dump()
    assert payload["personal_memories"] == {
        "encrypted_settings": "settings-ciphertext",
        "memories": [{key: value for key, value in _personal_memory_row().items()
                      if key not in ("hashed_user_id", "hashed_team_id")}],
    }


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
def test_session_personal_batch_runs_independent_fresh_reads_together(durable_session):
    state = durable_session
    original_items = state.directus.get_items.side_effect

    async def scenario():
        started = set()
        both_started = asyncio.Event()

        async def read(name, result):
            started.add(name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            return result

        async def profile(*_args, **_kwargs):
            return await read("profile", _personal_settings_response(settings="ciphertext"))

        async def items(collection, params=None, **kwargs):
            if collection == "user_app_settings_and_memories":
                return await read("memories", [_personal_memory_row()])
            return await original_items(collection, params=params, **kwargs)

        state.directus.base_url = "http://cms.test"
        state.directus._make_api_request = AsyncMock(side_effect=_legacy_personal_api(profile))
        state.directus.get_items.side_effect = items
        result = await asyncio.wait_for(state.call("sibling-token", include_personal_memories=True), timeout=2)
        return started, result

    started, result = asyncio.run(scenario())
    assert started == {"profile", "memories"}
    assert result.success is True


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle
@pytest.mark.parametrize("legacy_row", [False, True])
@pytest.mark.parametrize("snapshot_status", [200, 404])
def test_session_personal_batch_accepts_null_settings_and_legacy_rows(durable_session, legacy_row, snapshot_status):
    state = durable_session
    original_items = state.directus.get_items.side_effect
    state.directus.base_url = "http://cms.test"
    state.directus._make_api_request = AsyncMock(side_effect=_legacy_personal_api(AsyncMock(return_value=_personal_settings_response()), snapshot_status))

    async def items(collection, params=None, **kwargs):
        if collection == "user_app_settings_and_memories":
            if not legacy_row:
                return []
            row = _personal_memory_row()
            row.update(encrypted_item_json=None, created_at=None, updated_at=None)
            return [row]
        return await original_items(collection, params=params, **kwargs)

    state.directus.get_items.side_effect = items
    result = asyncio.run(state.call("sibling-token", include_personal_memories=True))

    assert result.success is True
    assert result.personal_memories.encrypted_settings is None
    assert len(result.personal_memories.memories) == (1 if legacy_row else 0)
    if legacy_row:
        assert result.personal_memories.memories[0].encrypted_item_json is None
        assert result.personal_memories.memories[0].created_at is None


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
def test_session_personal_batch_uses_consistent_supported_snapshot(durable_session):
    state = durable_session
    state.directus.base_url = "http://cms.test"
    snapshot = {
        "encrypted_settings": "snapshot-ciphertext",
        "memories": [{key: value for key, value in _personal_memory_row().items()
                      if key not in ("hashed_user_id", "hashed_team_id")}],
    }
    state.directus._make_api_request = AsyncMock(return_value=SimpleNamespace(
        status_code=200, json=lambda: {"data": {
            "supported": True, "privacy_generation": "generation-1",
            "unchanged": False, "personal_memories": snapshot,
        }},
    ))

    result = asyncio.run(state.call("sibling-token", include_personal_memories=True))

    assert result.success is True
    assert result.personal_memories.model_dump() == snapshot
    state.directus._make_api_request.assert_awaited_once_with(
        "POST", "http://cms.test/personal-privacy-snapshot",
        json={"user_id": "user-1", "known_generation": None},
        headers={"x-internal-service-token": "synthetic-internal-token", "Cache-Control": "no-store"},
    )
    assert all(call.args[0] != "user_app_settings_and_memories"
               for call in state.directus.get_items.await_args_list)
    state.ws_tokens.assert_called_once_with("sibling-token")


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
@pytest.mark.parametrize("failure", [
    "transport", "unavailable", "invalid_json", "invalid_data", "legacy_profile",
    "missing_generation", "invalid_generation", "missing_unchanged", "unchanged",
    "missing_snapshot", "invalid_snapshot",
])
def test_session_personal_batch_rejects_supported_snapshot_errors_without_fallback(durable_session, failure):
    state = durable_session
    state.directus.base_url = "http://cms.test"
    data = {"supported": True, "privacy_generation": "generation-1", "unchanged": False,
            "personal_memories": {"encrypted_settings": None, "memories": []}}
    if failure == "invalid_data":
        data = None
    elif failure == "legacy_profile":
        data = {"id": "user-1", "encrypted_settings": "ciphertext"}
    elif failure == "missing_generation":
        data.pop("privacy_generation")
    elif failure == "invalid_generation":
        data["privacy_generation"] = ""
    elif failure == "missing_unchanged":
        data.pop("unchanged")
    elif failure == "unchanged":
        data["unchanged"] = True
    elif failure == "missing_snapshot":
        data.pop("personal_memories")
    elif failure == "invalid_snapshot":
        data["personal_memories"] = {"encrypted_settings": None, "memories": [{}]}
    json_response = Mock(return_value={"data": data})
    if failure == "invalid_json":
        json_response.side_effect = ValueError("private invalid JSON")
    state.directus._make_api_request = AsyncMock(
        side_effect=RuntimeError("private transport failure") if failure == "transport" else None,
        return_value=SimpleNamespace(status_code=503 if failure == "unavailable" else 200, json=json_response),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(state.call("sibling-token", include_personal_memories=True))

    assert error.value.status_code == 503
    assert error.value.detail == "Personal memory snapshot temporarily unavailable"
    state.directus._make_api_request.assert_awaited_once()
    assert all(call.args[0] != "user_app_settings_and_memories"
               for call in state.directus.get_items.await_args_list)
    state.ws_tokens.assert_not_called()


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle
# contract-test: supporting surface=gui.web assertions=chat-message-timeline.bookmarks
@pytest.mark.parametrize("flag", [None, False, "true", 1])
def test_session_legacy_request_does_not_read_or_serialize_personal_batch(durable_session, flag):
    state = durable_session
    state.user["encrypted_settings"] = "opaque-owner-account-settings"
    state.directus._make_api_request = AsyncMock()

    result = asyncio.run(state.call("sibling-token", include_personal_memories=flag))

    assert result.success is True
    assert result.model_dump()["user"]["encrypted_settings"] == "opaque-owner-account-settings"
    assert "personal_memories" not in result.model_dump()
    state.directus._make_api_request.assert_not_awaited()
    assert all(call.args[0] != "user_app_settings_and_memories"
               for call in state.directus.get_items.await_args_list)


# contract-test: supporting surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.access-and-lifecycle
def test_pending_verification_does_not_expose_encrypted_bookmark_settings(durable_session):
    durable_session.user["encrypted_settings"] = "opaque-owner-account-settings"
    result = asyncio.run(durable_session.call("pending-token"))
    assert result.success is False
    assert result.user is None or result.user.encrypted_settings is None
    assert "opaque-owner-account-settings" not in result.model_dump_json()


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
@pytest.mark.parametrize("failure", ["profile_exception", "memory_exception", "foreign_profile", "missing_settings", "team_row", "foreign_row"])
def test_session_personal_batch_fails_closed_on_partial_or_foreign_reads(durable_session, failure):
    state = durable_session
    original_items = state.directus.get_items.side_effect
    state.directus.base_url = "http://cms.test"
    state.directus._make_api_request = AsyncMock(side_effect=_legacy_personal_api(AsyncMock(
        side_effect=RuntimeError("private failure") if failure == "profile_exception" else None,
        return_value=_personal_settings_response(
            user_id="other-user" if failure == "foreign_profile" else "user-1",
            include_settings=failure != "missing_settings",
        ),
    )))

    async def items(collection, params=None, **kwargs):
        if collection == "user_app_settings_and_memories":
            if failure == "memory_exception":
                raise RuntimeError("private failure")
            if failure == "team_row":
                return [_personal_memory_row(team_id="team-hash")]
            if failure == "foreign_row":
                return [_personal_memory_row(user_id="other-user")]
            return [_personal_memory_row()]
        return await original_items(collection, params=params, **kwargs)

    state.directus.get_items.side_effect = items
    with pytest.raises(HTTPException) as error:
        asyncio.run(state.call("sibling-token", include_personal_memories=True))

    assert error.value.status_code == 503
    assert error.value.detail == "Personal memory snapshot temporarily unavailable"
    assert "private" not in error.value.detail
    state.ws_tokens.assert_not_called()


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
@pytest.mark.parametrize("auth_case", ["invalid_cookie", "api_key_only", "risk_pending"])
def test_session_personal_batch_never_reads_on_unsuccessful_auth(durable_session, monkeypatch, auth_case):
    state = durable_session
    state.directus._make_api_request = AsyncMock()
    if auth_case != "risk_pending":
        monkeypatch.setattr(auth_session, "verify_authenticated_user", AsyncMock(
            return_value=(False, {}, None, "authentication_failed")))
    else:
        state.rows[token_hash("sibling-token")]["risk_pending"] = True

    token = None if auth_case == "api_key_only" else "sibling-token"
    headers = {**FakeRequest.headers, "Authorization": "Bearer sdk-only"} if auth_case == "api_key_only" else None
    result = asyncio.run(state.call(token, include_personal_memories=True, headers=headers))

    assert result.success is False
    assert "personal_memories" not in result.model_dump()
    state.directus._make_api_request.assert_not_awaited()
    assert all(call.args[0] != "user_app_settings_and_memories"
               for call in state.directus.get_items.await_args_list)


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
@pytest.mark.parametrize("kind", ["default", "failed", "batched"])
def test_session_response_serialization_keeps_legacy_shape_and_complete_batch(kind):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import TypeAdapter
    from backend.core.api.app.schemas.auth import PersonalMemoriesSnapshot, PersonalMemoryRow, SessionResponse
    from backend.core.api.app.schemas.user import UserResponse

    if kind == "batched":
        response = SessionResponse(
            success=True, message="Session valid", ws_token="synthetic-ws-token",
            user=UserResponse(id="user-1", username="Person", is_admin=False, credits=0, tfa_enabled=False),
            personal_memories=PersonalMemoriesSnapshot(
                encrypted_settings=None,
                memories=[PersonalMemoryRow(
                    id="memory-1", app_id="openmates", item_type="memories", item_key="key-hash",
                    encrypted_item_json="opaque-ciphertext", item_version=1,
                    created_at=10, updated_at=20,
                )],
            ),
        )
    else:
        response = SessionResponse(success=kind == "default", message="Session valid" if kind == "default" else "Not logged in")

    adapter = TypeAdapter(SessionResponse)
    serialized = [
        response.model_dump(),
        json.loads(response.model_dump_json()),
        adapter.dump_python(response, mode="json"),
        json.loads(adapter.dump_json(response)),
    ]
    app = FastAPI()

    @app.get("/session", response_model=SessionResponse)
    async def session_response():
        return response

    with TestClient(app) as client:
        http_response = client.get("/session")
    assert http_response.status_code == 200
    serialized.append(http_response.json())

    assert all(payload == serialized[0] for payload in serialized)
    for payload in serialized:
        # Existing defaults and null fields remain serialized exactly as before.
        if kind == "batched":
            assert payload["user"]["id"] == "user-1"
        else:
            assert payload["user"] is None
        assert payload["re_auth_required"] is None
        assert payload["session_meta_registered"] is False
        if kind == "batched":
            assert payload["personal_memories"] == {
                "encrypted_settings": None,
                "memories": [{
                    "id": "memory-1", "app_id": "openmates", "item_type": "memories",
                    "item_key": "key-hash", "encrypted_item_json": "opaque-ciphertext",
                    "item_version": 1, "created_at": 10, "updated_at": 20,
                }],
            }
        else:
            assert "personal_memories" not in payload
