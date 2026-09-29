"""One-use v2 password proof and atomic migration boundaries."""

import hashlib
import hmac
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from backend.core.api.app.services.password_v2 import (
    KDF_ID, decode_key, encode_key, has_password_v2_record, issue_challenge,
    password_v2_record, proof_message, verify_challenge_proof,
)


class Cache:
    def __init__(self):
        self.values = {}
        self.delete = AsyncMock()

    async def set(self, key, value, ttl):
        self.values[key] = value
        return True

    async def get_and_delete(self, key):
        return self.values.pop(key, None)


def record():
    return {"password": {"version": 2, "kdf": KDF_ID,
                         "sealed_auth_key": "vault:v1:sealed",
                         "wrapper_method": "password_v2_wrapper"}}


# contract-test: direct surface=rest_api assertions=auth.password.versioned-protection
def test_canonical_key_and_malformed_v2_fail_closed():
    key = bytes(range(32))
    assert decode_key(encode_key(key)) == key
    with pytest.raises(ValueError):
        decode_key(encode_key(key) + "=")
    assert has_password_v2_record({"password": {"version": 2}})
    assert password_v2_record({"password": {"version": 2}}) is None
    assert password_v2_record(record()) is not None


# contract-test: direct surface=rest_api assertions=auth.proofs.single-use,auth.password.versioned-protection
@pytest.mark.anyio
async def test_challenge_is_bound_and_one_use():
    cache = Cache()
    auth_key = bytes(range(32))
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value=encode_key(auth_key)))
    issued = await issue_challenge(cache, hashed_email="email-hash", session_id="browser-session",
                                   purpose="login")
    nonce = decode_key(issued["nonce"])
    proof = encode_key(hmac.new(auth_key, proof_message("login", nonce), hashlib.sha256).digest())
    args = dict(challenge_id=issued["challenge_id"], password_proof=proof,
                hashed_email="email-hash", session_id="browser-session", purpose="login",
                record=record(), vault_key_id="user-key")
    assert not await verify_challenge_proof(cache, encryption, **{**args, "session_id": "other-session"})
    assert not await verify_challenge_proof(cache, encryption, **args)
    issued = await issue_challenge(cache, hashed_email="email-hash", session_id="browser-session",
                                   purpose="login")
    malformed = {**args, "challenge_id": issued["challenge_id"], "password_proof": "malformed"}
    assert not await verify_challenge_proof(cache, encryption, **malformed)
    assert not await verify_challenge_proof(cache, encryption, **{
        **malformed, "password_proof": encode_key(bytes(32)),
    })
    issued = await issue_challenge(cache, hashed_email="email-hash", session_id="browser-session",
                                   purpose="login")
    args["challenge_id"] = issued["challenge_id"]
    args["password_proof"] = encode_key(hmac.new(
        auth_key, proof_message("login", decode_key(issued["nonce"])), hashlib.sha256,
    ).digest())
    assert await verify_challenge_proof(cache, encryption, **args)
    assert not await verify_challenge_proof(cache, encryption, **args)
    issued = await issue_challenge(cache, hashed_email="email-hash", session_id="logical-session",
                                   purpose="migration", binding="old-hash")
    migration_proof = encode_key(hmac.new(
        auth_key, proof_message("migration", decode_key(issued["nonce"])), hashlib.sha256,
    ).digest())
    assert not await verify_challenge_proof(
        cache, encryption, challenge_id=issued["challenge_id"], password_proof=migration_proof,
        hashed_email="email-hash", session_id="logical-session", purpose="migration",
        binding="different-hash", record=record(), vault_key_id="user-key",
    )
    encryption.decrypt_with_user_key.assert_awaited()


# contract-test: direct surface=rest_api assertions=auth.password.versioned-protection,auth.credentials.atomic-replacement
@pytest.mark.anyio
async def test_migration_retirement_and_wrapper_rollback(monkeypatch):
    # Route dependencies are called directly: this checks the user-row commit
    # and wrapper cleanup, independent of the HTTP dependency framework.
    from backend.core.api.app.routes.auth_routes import auth_password_v2 as route

    class Lock:
        acquire = AsyncMock(return_value=True)
        release = AsyncMock()

    lock = Lock()
    monkeypatch.setattr(route, "acquire_credential_change_lock", AsyncMock(return_value=lock))
    monkeypatch.setattr(route, "release_credential_change_lock", AsyncMock())
    monkeypatch.setattr(route, "seal_auth_key", AsyncMock(return_value="vault:v1:sealed"))
    user = SimpleNamespace(id="user-1")
    fields = {"hashed_email": "email-hash", "user_email_salt": "salt-123456789012",
              "vault_key_id": "vault-key", "lookup_hashes": ["old", "recovery"],
              "credential_lookup_hashes": {"password": "old", "recovery_key": "recovery"}}
    directus = SimpleNamespace(get_user_fields_direct=AsyncMock(return_value=fields),
                              create_encryption_key=AsyncMock(return_value=True),
                              update_user=AsyncMock(return_value=True),
                              delete_encryption_key=AsyncMock())
    body = route.PasswordV2MigrationRequest(
        old_lookup_hash="old-lookup-hash-123", password_auth_key=SecretStr(encode_key(bytes(range(32)))),
        encrypted_master_key="encrypted-master-key", salt="salt-123456789012",
        key_iv="iv-12345678",
    )
    fields["lookup_hashes"][0] = body.old_lookup_hash
    fields["credential_lookup_hashes"]["password"] = body.old_lookup_hash
    session = {"verified_login_method": "password", "verified_credential_version": 1,
               "verified_lookup_digest": hashlib.sha256(body.old_lookup_hash.encode()).hexdigest(),
               "login_verified_at": int(time.time()),
               "strong_verified_at": int(time.time())}
    monkeypatch.setattr(route, "get_session_state_cached", AsyncMock(return_value=session))
    monkeypatch.setattr(route, "require_recent_strong_proof", AsyncMock())
    request = SimpleNamespace(cookies={"auth_refresh_token": "session-cookie"})
    result = await route.migrate_password_v2(request, body, user, directus, Cache(), SimpleNamespace())
    assert result["migration_status"] == "pending_confirmation"
    saved = directus.update_user.await_args.args[1]
    assert body.old_lookup_hash in saved["lookup_hashes"]
    assert saved["credential_lookup_hashes"]["recovery_key"] == "recovery"
    assert saved["credential_lookup_hashes"]["password"]["version"] == 2
    assert saved["credential_lookup_hashes"]["password"]["pending_v1_lookup_hash"] == body.old_lookup_hash

    directus.update_user.return_value = False
    with pytest.raises(HTTPException):
        await route.migrate_password_v2(request, body, user, directus, Cache(), SimpleNamespace())
    directus.delete_encryption_key.assert_awaited()

    directus.update_user.return_value = True
    fields["credential_lookup_hashes"] = None
    session["verified_login_method"] = "legacy_account_secret"
    directus.create_encryption_key.reset_mock()
    with pytest.raises(HTTPException) as legacy_deferred:
        await route.migrate_password_v2(request, body, user, directus, Cache(), SimpleNamespace())
    assert legacy_deferred.value.status_code == 409
    assert legacy_deferred.value.detail["migration_status"] == "deferred_legacy_credentials"
    directus.create_encryption_key.assert_not_awaited()

    fields["credential_lookup_hashes"] = {"password": body.old_lookup_hash}
    fields["lookup_hashes"].append("ambiguous-recovery")
    session["verified_login_method"] = "password"
    with pytest.raises(HTTPException) as mixed_deferred:
        await route.migrate_password_v2(request, body, user, directus, Cache(), SimpleNamespace())
    assert mixed_deferred.value.status_code == 409
    directus.create_encryption_key.assert_not_awaited()
    fields["lookup_hashes"].remove("ambiguous-recovery")

    fields["credential_lookup_hashes"] = {"password": "different-typed-password"}
    with pytest.raises(HTTPException) as wrong_binding:
        await route.migrate_password_v2(request, body, user, directus, Cache(), SimpleNamespace())
    assert wrong_binding.value.status_code == 401

    fields["credential_lookup_hashes"] = {"password": body.old_lookup_hash, "recovery_key": "recovery"}
    session["verified_login_method"] = "passkey"
    with pytest.raises(HTTPException) as passkey_bypass:
        await route.migrate_password_v2(request, body, user, directus, Cache(), SimpleNamespace())
    assert passkey_bypass.value.status_code == 401
    session["verified_login_method"] = "password"
    session["login_verified_at"] = int(time.time()) - 301
    with pytest.raises(HTTPException) as stale_cookie:
        await route.migrate_password_v2(request, body, user, directus, Cache(), SimpleNamespace())
    assert stale_cookie.value.status_code == 401


# contract-test: direct surface=rest_api assertions=auth.password.versioned-protection,auth.sensitive-actions.recent-verification
@pytest.mark.anyio
async def test_stolen_fresh_session_cannot_stage_password_migration(monkeypatch):
    from backend.core.api.app.routes.auth_routes import auth_password_v2 as route

    old_hash = "old-lookup-hash-123"
    fields = {"user_email_salt": "salt-123456789012", "lookup_hashes": [old_hash],
              "credential_lookup_hashes": {"password": old_hash}, "vault_key_id": "vault-key"}
    directus = SimpleNamespace(
        get_user_fields_direct=AsyncMock(return_value=fields),
        create_encryption_key=AsyncMock(return_value=True),
        update_user=AsyncMock(return_value=True),
    )
    session = {"verified_login_method": "password", "verified_credential_version": 1,
               "verified_lookup_digest": hashlib.sha256(old_hash.encode()).hexdigest(),
               "login_verified_at": int(time.time()), "strong_verified_at": None}
    monkeypatch.setattr(route, "get_session_state_cached", AsyncMock(return_value=session))
    from backend.core.api.app.services import session_security_state
    monkeypatch.setattr(session_security_state, "get_session_state_cached", AsyncMock(return_value=session))
    monkeypatch.setattr(route, "acquire_credential_change_lock", AsyncMock(return_value=object()))
    monkeypatch.setattr(route, "release_credential_change_lock", AsyncMock())
    body = route.PasswordV2MigrationRequest(
        old_lookup_hash=old_hash, password_auth_key=SecretStr(encode_key(bytes(range(32)))),
        encrypted_master_key="attacker-wrapped-root", salt=fields["user_email_salt"], key_iv="iv-12345678",
    )
    with pytest.raises(HTTPException) as denied:
        await route.migrate_password_v2(
            SimpleNamespace(cookies={"auth_refresh_token": "stolen-cookie"}),
            body, SimpleNamespace(id="user-1"), directus, Cache(), SimpleNamespace(),
        )
    assert denied.value.status_code == 428
    assert denied.value.detail == {"error": "recent_verification_required"}
    directus.create_encryption_key.assert_not_awaited()
    directus.update_user.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=auth.login.verified-method,auth.password.versioned-protection
@pytest.mark.anyio
async def test_committed_v2_rejects_legacy_password_lookup_even_when_retained(monkeypatch):
    from backend.core.api.app.services.directus.user.user_authentication import login_user_with_lookup_hash

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"data": [{
        "id": "user-1", "vault_key_id": "vault-key",
        "lookup_hashes": ["old-password-hash", "legacy-recovery-hash"],
        "credential_lookup_hashes": record(),
    }]}
    directus = SimpleNamespace(base_url="https://directus.example",
                              _make_api_request=AsyncMock(return_value=response),
                              encryption_service=SimpleNamespace())
    accepted, _auth, _message = await login_user_with_lookup_hash(
        directus, "hashed-email", "old-password-hash", login_method="password",
    )
    assert accepted is False

    class HttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            result = MagicMock()
            result.status_code = 200
            result.json.return_value = {"data": {"access_token": "directus-token"}}
            result.cookies = {}
            return result

        async def get(self, *_args, **_kwargs):
            result = MagicMock()
            result.status_code = 200
            result.json.return_value = {"data": {"id": "user-1"}}
            return result

    from backend.core.api.app.services.directus.user import user_authentication as auth_module
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", HttpClient)
    directus.encryption_service = SimpleNamespace(hash_email=AsyncMock(return_value="directus-password"))
    staged = record()
    staged["password"]["pending_v1_lookup_hash"] = "old-password-hash"
    staged["password"]["pending_v1_wrapper_method"] = "password"
    response.json.return_value["data"][0]["credential_lookup_hashes"] = staged
    accepted, auth, _message = await login_user_with_lookup_hash(
        directus, "hashed-email", "old-password-hash", login_method="password",
    )
    assert accepted is True
    assert auth["verified_wrapper_method"] == "password"
    response.json.return_value["data"][0]["credential_lookup_hashes"] = record()
    accepted, auth, _message = await login_user_with_lookup_hash(
        directus, "hashed-email", "old-password-hash", login_method="recovery_key",
    )
    assert accepted is True
    assert auth["verified_lookup_method"] is None
    assert auth["legacy_recovery_allowed"] is True
    # This is an explicit temporary compatibility exception: an untyped old
    # password hash could be relabeled as recovery. It grants no strong proof.
    directus.encryption_service = SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value=encode_key(bytes(range(32)))))
    accepted, _auth, _message = await login_user_with_lookup_hash(
        directus, "hashed-email", None, credential_version=2,
        challenge_id="absent-challenge", password_proof=encode_key(bytes(32)),
        session_id="browser-session", cache_service=Cache(),
    )
    assert accepted is False


# contract-test: direct surface=rest_api assertions=auth.password.versioned-protection,auth.proofs.single-use
@pytest.mark.anyio
async def test_staged_verify_and_confirmation_are_one_use(monkeypatch):
    from backend.core.api.app.routes.auth_routes import auth_password_v2 as route

    cache = Cache()
    user = SimpleNamespace(id="user-1")
    old_hash = "typed-v1-password-hash"
    typed = record()
    typed["password"]["pending_v1_lookup_hash"] = old_hash
    typed["password"]["pending_v1_wrapper_method"] = "password"
    fields = {"hashed_email": "email-hash", "vault_key_id": "vault-key",
              "lookup_hashes": [old_hash], "credential_lookup_hashes": typed}
    session = {"logical_session_id": "logical-session"}
    monkeypatch.setattr(route, "_staged_account", AsyncMock(return_value=(
        session, fields, typed, typed["password"],
    )))
    verifier = AsyncMock(return_value=False)
    monkeypatch.setattr(route, "verify_challenge_proof", verifier)
    directus = SimpleNamespace(
        get_encryption_key=AsyncMock(return_value={
            "encrypted_key": "encrypted-root", "salt": "salt", "key_iv": "iv",
        }),
        update_user=AsyncMock(return_value=True),
    )
    body = route.StagedPasswordVerifyRequest(
        challenge_id="challenge-id-12345678901234567890",
        password_proof=encode_key(bytes(32)),
    )
    with pytest.raises(HTTPException) as invalid:
        await route.verify_staged_password(SimpleNamespace(), body, user, directus, cache,
                                           SimpleNamespace(), "refresh-token")
    assert invalid.value.status_code == 401
    assert cache.values == {}
    verifier.return_value = True
    wrapper = await route.verify_staged_password(SimpleNamespace(), body, user, directus, cache,
                                                  SimpleNamespace(), "refresh-token")
    assert wrapper["encrypted_key"] == "encrypted-root"
    assert fields["lookup_hashes"] == [old_hash]  # Verification alone cannot retire v1.
    assert verifier.await_args.kwargs["binding"] == old_hash

    class Lock:
        release = AsyncMock()

    monkeypatch.setattr(route, "acquire_credential_change_lock", AsyncMock(return_value=Lock()))
    monkeypatch.setattr(route, "release_credential_change_lock", AsyncMock())
    assurance = AsyncMock()
    monkeypatch.setattr(route, "require_recent_strong_proof", assurance)
    result = await route.confirm_password_migration(SimpleNamespace(), user, directus, cache,
                                                     "refresh-token")
    assert result["migration_status"] == "typed_retired"
    assurance.assert_awaited_once_with(directus, cache, "refresh-token", user.id)
    saved = directus.update_user.await_args.args[1]
    assert old_hash not in saved["lookup_hashes"]
    assert "pending_v1_lookup_hash" not in saved["credential_lookup_hashes"]["password"]
    with pytest.raises(HTTPException) as replay:
        await route.confirm_password_migration(SimpleNamespace(), user, directus, cache,
                                                "refresh-token")
    assert replay.value.status_code == 401


# contract-test: direct surface=rest_api assertions=auth.password.versioned-protection,auth.sensitive-actions.recent-verification
@pytest.mark.anyio
async def test_pending_stage_and_one_use_marker_cannot_retire_without_fresh_assurance(monkeypatch):
    from backend.core.api.app.routes.auth_routes import auth_password_v2 as route

    cache = Cache()
    user = SimpleNamespace(id="user-1")
    old_hash = "old-lookup-hash-123"
    v2 = {**record()["password"], "pending_v1_lookup_hash": old_hash,
          "pending_v1_wrapper_method": "password"}
    typed = {"password": v2}
    fields = {"lookup_hashes": [old_hash], "credential_lookup_hashes": typed}
    session = {"logical_session_id": "logical-session"}
    monkeypatch.setattr(route, "_staged_account", AsyncMock(return_value=(session, fields, typed, v2)))
    monkeypatch.setattr(route, "acquire_credential_change_lock", AsyncMock(return_value=object()))
    monkeypatch.setattr(route, "release_credential_change_lock", AsyncMock())
    monkeypatch.setattr(route, "require_recent_strong_proof", AsyncMock(
        side_effect=HTTPException(401, "Recent verification required")))
    directus = SimpleNamespace(update_user=AsyncMock(return_value=True))
    await cache.set(route._confirmation_key("stolen-cookie"), {
        "user_id": user.id, "session_id": session["logical_session_id"],
        "pending_v1_lookup_hash": old_hash, "wrapper_method": v2["wrapper_method"],
    }, ttl=300)
    with pytest.raises(HTTPException) as denied:
        await route.confirm_password_migration(
            SimpleNamespace(), user, directus, cache, "stolen-cookie",
        )
    assert denied.value.status_code == 428
    assert denied.value.detail == {"error": "recent_verification_required"}
    directus.update_user.assert_not_awaited()
    assert fields["lookup_hashes"] == [old_hash]
