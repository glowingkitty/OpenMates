"""Pair v2 rejects legacy credentials and requires session-bound strong proof."""
import base64
import hashlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from backend.core.api.app.routes.auth_routes import auth_pair, auth_pair_v2
from backend.core.api.app.middleware.logging_middleware import LoggingMiddleware
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_cache_service, get_compliance_service, get_current_user, get_directus_service, get_encryption_service,
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_auth_client


class Cache:
    def __init__(self, values):
        self.values = values

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True


def receiver_capability():
    raw = bytes(range(32))
    return base64.urlsafe_b64encode(raw).decode().rstrip("="), hashlib.sha256(raw).hexdigest()


# contract-test: direct surface=rest_api assertions=auth.pair-login.single-use-zk
def test_pair_v2_rejects_pin_fields_and_hashes_raw_receiver_capability():
    cap, digest = receiver_capability()
    assert auth_pair_v2._receiver_hash(cap) == digest
    with pytest.raises(ValidationError):
        auth_pair_v2.Authorize(encrypted_bundle="ciphertext", iv="nonce", grant_hash="a" * 64, pin="123456")
    with pytest.raises(ValidationError):
        auth_pair_v2.Message(stage="request", message="x" * 16385)
    with pytest.raises(HTTPException):
        auth_pair_v2._receiver_hash("not-a-capability")


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.lifecycle
async def test_legacy_pair_route_returns_update_required_without_reading_body():
    class Request:
        async def body(self):
            raise AssertionError("legacy PIN body must never be parsed")

    with pytest.raises(HTTPException) as error:
        await auth_pair.retired_pair_protocol(Request(), "complete/TOKEN")
    assert error.value.status_code == 426


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.approval-assurance
async def test_pair_stepup_password_requires_enrolled_totp_and_same_session_binding(monkeypatch):
    import pyotp

    token = "sender-refresh-token"
    binding = "b" * 64
    cache = Cache({"user_tokens:user-1": {hashlib.sha256(token.encode()).hexdigest(): {"pair_auth_binding": binding}}})
    request = SimpleNamespace(cookies={"auth_refresh_token": token})
    user = SimpleNamespace(id="user-1")

    class Directus:
        async def get_user_fields_direct(self, user_id, fields):
            assert user_id == "user-1"
            if fields == ["hashed_email", "lookup_hashes", "credential_lookup_hashes"]:
                return {"hashed_email": "email-hash", "lookup_hashes": ["lookup-hash"],
                        "credential_lookup_hashes": {"password": "lookup-hash"}}
            if fields == ["encrypted_tfa_secret"]:
                return {"encrypted_tfa_secret": "opaque"}
            return {"encrypted_tfa_secret": "opaque", "vault_key_id": "vault-key"}

    encryption = SimpleNamespace(decrypt_with_user_key=lambda *_: None)
    body = auth_pair_v2.StepUp(auth_method="password", hashed_email="email-hash", lookup_hash="lookup-hash")
    with pytest.raises(HTTPException) as error:
        await auth_pair_v2.step_up(request, body, user, cache, Directus(), encryption)
    assert error.value.status_code == 401
    assert cache.values.get(f"pair:stepup:{binding}") is None

    class Encryption:
        async def decrypt_with_user_key(self, *_):
            return "JBSWY3DPEHPK3PXP"

    marked = []
    async def mark(*args, **kwargs):
        marked.append(kwargs["method"])
    monkeypatch.setattr(auth_pair_v2, "mark_recent_strong_proof", mark)
    claim = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(auth_pair_v2, "claim_totp_step", claim)
    body.auth_code = pyotp.TOTP("JBSWY3DPEHPK3PXP").now()
    response = await auth_pair_v2.step_up(request, body, user, cache, Directus(), Encryption())
    assert response == {"success": True, "expires_in": 300}
    assert cache.values[f"pair:stepup:{binding}"] == "verified"
    assert marked == ["totp"]
    with pytest.raises(HTTPException) as replay:
        await auth_pair_v2.step_up(request, body, user, cache, Directus(), Encryption())
    assert replay.value.status_code == 401
    assert claim.await_count == 2
    claim.assert_awaited_with(cache, "user-1", "JBSWY3DPEHPK3PXP", body.auth_code)
    assert marked == ["totp"]

    other_request = SimpleNamespace(cookies={"auth_refresh_token": "other-session"})
    with pytest.raises(HTTPException):
        await auth_pair_v2._binding(other_request, cache, user)


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.approval-assurance
async def test_untyped_lookup_hash_cannot_step_up_without_enrolled_factor():
    cap, digest = receiver_capability()
    token = "sender-refresh-token"
    binding = "a" * 64
    cache = Cache({"user_tokens:user-1": {hashlib.sha256(token.encode()).hexdigest(): {"pair_auth_binding": binding}}})
    request = SimpleNamespace(cookies={"auth_refresh_token": token})
    user = SimpleNamespace(id="user-1")

    class Directus:
        async def get_user_fields_direct(self, _user_id, fields):
            if fields == ["hashed_email", "lookup_hashes", "credential_lookup_hashes"]:
                return {"hashed_email": "email-hash", "lookup_hashes": ["recovery-or-passkey-hash"]}
            return {"encrypted_tfa_secret": None}

    body = auth_pair_v2.StepUp(auth_method="password", hashed_email="email-hash", lookup_hash="recovery-or-passkey-hash")
    with pytest.raises(HTTPException) as error:
        await auth_pair_v2.step_up(request, body, user, cache, Directus(), None)
    assert error.value.status_code == 401
    assert f"pair:stepup:{binding}" not in cache.values


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.approval-assurance
async def test_mixed_typed_record_keeps_legacy_secret_eligible_only_with_totp(monkeypatch):
    token = "sender-refresh-token"
    binding = "c" * 64
    cache = Cache({"user_tokens:user-1": {hashlib.sha256(token.encode()).hexdigest(): {"pair_auth_binding": binding}}})
    request = SimpleNamespace(cookies={"auth_refresh_token": token})
    user = SimpleNamespace(id="user-1")
    record = {"passkey": "passkey-hash", "recovery": {"lookup_hash": "recovery-hash"}}

    class Directus:
        async def get_user_fields_direct(self, _user_id, fields):
            if fields == ["hashed_email", "lookup_hashes", "credential_lookup_hashes"]:
                return {"hashed_email": "email-hash", "lookup_hashes": ["legacy-secret", "passkey-hash", "recovery-hash"],
                        "credential_lookup_hashes": record}
            if fields == ["encrypted_tfa_secret"]:
                return {"encrypted_tfa_secret": "opaque"}
            return {"encrypted_tfa_secret": "opaque", "vault_key_id": "vault-key"}

    class Encryption:
        async def decrypt_with_user_key(self, *_):
            return "totp-secret"

    marked = []
    monkeypatch.setattr(auth_pair_v2, "mark_recent_strong_proof", AsyncMock(side_effect=lambda *args, **kwargs: marked.append(kwargs["method"])))
    monkeypatch.setattr(auth_pair_v2, "claim_totp_step", AsyncMock(return_value=True))
    body = auth_pair_v2.StepUp(auth_method="password", hashed_email="email-hash", lookup_hash="legacy-secret", auth_code="123456")
    assert await auth_pair_v2.step_up(request, body, user, cache, Directus(), Encryption()) == {
        "success": True, "expires_in": 300,
    }
    assert marked == ["totp"]
    assert cache.values[f"pair:stepup:{binding}"] == "verified"

    for rejected_hash in ("passkey-hash", "recovery-hash"):
        body.lookup_hash = rejected_hash
        with pytest.raises(HTTPException) as error:
            await auth_pair_v2.step_up(request, body, user, cache, Directus(), Encryption())
        assert error.value.status_code == 401
    record["password"] = "new-password-hash"
    body.lookup_hash = "legacy-secret"
    with pytest.raises(HTTPException) as error:
        await auth_pair_v2.step_up(request, body, user, cache, Directus(), Encryption())
    assert error.value.status_code == 401


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.single-use-zk
async def test_account_check_returns_only_current_user_bound_encrypted_metadata():
    class Directus:
        async def get_user_fields_direct(self, user_id, fields):
            assert user_id == "user-1"
            assert fields == ["hashed_email", "encrypted_email_with_master_key", "user_email_salt"]
            return {"hashed_email": "hash", "encrypted_email_with_master_key": "ciphertext", "user_email_salt": "salt"}

    result = await auth_pair_v2.account_check(None, SimpleNamespace(id="user-1"), Directus())
    assert result == {"user_id": "user-1", "hashed_email": "hash", "encrypted_email_with_master_key": "ciphertext", "user_email_salt": "salt"}


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.single-use-zk
async def test_account_check_allows_legacy_account_without_server_email_envelope():
    class Directus:
        async def get_user_fields_direct(self, user_id, fields):
            assert user_id == "user-1"
            assert fields == ["hashed_email", "encrypted_email_with_master_key", "user_email_salt"]
            return {"hashed_email": "server-bound-hash", "user_email_salt": "server-bound-salt",
                    "encrypted_email_with_master_key": None}

    result = await auth_pair_v2.account_check(None, SimpleNamespace(id="user-1"), Directus())
    assert result == {"user_id": "user-1", "hashed_email": "server-bound-hash",
                      "user_email_salt": "server-bound-salt", "encrypted_email_with_master_key": None}


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.single-use-zk
async def test_account_check_rejects_missing_server_bound_identity_even_with_envelope():
    class Directus:
        async def get_user_fields_direct(self, _user_id, _fields):
            return {"hashed_email": None, "user_email_salt": "salt",
                    "encrypted_email_with_master_key": "ciphertext"}

    with pytest.raises(HTTPException) as error:
        await auth_pair_v2.account_check(None, SimpleNamespace(id="user-1"), Directus())
    assert error.value.status_code == 503


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.lifecycle
async def test_terminal_polls_wait_for_durable_ack_confirmation():
    receiver, receiver_hash = receiver_capability()
    sender_token = "sender-refresh-token"
    binding = "a" * 64
    state = {"status": "acknowledged", "expires_at": 2_000_000_000,
             "receiver_token_hash": receiver_hash, "authorizer_user_id": "user-1",
             "authorizer_binding": binding, "session_token_hash": "f" * 64,
             "authorizer_device_name": "Browser", "auto_logout_minutes": None, "session_id": "session-1"}
    cache = Cache({"pair:v2:ABCDEF": state,
                   "user_tokens:user-1": {hashlib.sha256(sender_token.encode()).hexdigest(): {"pair_auth_binding": binding}}})
    row = {"id": "row-1", "user_id": "user-1", "expires_at": None,
           "pending_ack": False, "relay_acknowledged": False, "retired": False}

    class Directus:
        async def get_items(self, *_args, **_kwargs):
            return [row]

    sender_request = SimpleNamespace(cookies={"auth_refresh_token": sender_token})
    receiver_waiting = await auth_pair_v2.receiver_poll(None, "ABCDEF", receiver, cache, Directus())
    sender_waiting = await auth_pair_v2.authorizer_poll(sender_request, "ABCDEF", SimpleNamespace(id="user-1"), cache, Directus())
    assert receiver_waiting["status"] == sender_waiting["status"] == "acknowledging"

    row["relay_acknowledged"] = True
    receiver_done = await auth_pair_v2.receiver_poll(None, "ABCDEF", receiver, cache, Directus())
    sender_done = await auth_pair_v2.authorizer_poll(sender_request, "ABCDEF", SimpleNamespace(id="user-1"), cache, Directus())
    assert receiver_done["status"] == sender_done["status"] == "acknowledged"


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.single-use-zk
async def test_v2_validation_never_echoes_secret_inputs_to_response_or_error_log(caplog):
    app = FastAPI()
    # Match production's nested auth_pair router inclusion, which must retain
    # PairValidationRoute rather than FastAPI's default validation renderer.
    app.include_router(auth_pair.router)
    app.add_middleware(LoggingMiddleware)
    app.state.metrics_service = SimpleNamespace(track_api_request=lambda *_: None, track_request_duration=lambda *_: None)
    for dependency in (get_cache_service, get_compliance_service, get_directus_service, get_encryption_service):
        app.dependency_overrides[dependency] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[verify_auth_client] = lambda: True

    marker = "PAIR_SECRET_MARKER_5f3c"
    requests = [
        ("/pair/v2/complete/ABCDEF", {"grant_secret": marker}),
        ("/pair/v2/step-up", {"auth_method": "password", "lookup_hash": marker * 20}),
        ("/pair/v2/authorize/ABCDEF", {"encrypted_bundle": "ciphertext", "iv": "nonce", "grant_hash": "a" * 64, "pin": marker}),
    ]
    with caplog.at_level(logging.WARNING, logger="backend.core.api.app.middleware.logging_middleware"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for path, body in requests:
                response = await client.post(path, json=body)
                assert response.status_code == 422
                assert response.json() == {"detail": "Invalid pairing request"}
                assert marker not in response.text
    assert marker not in caplog.text
