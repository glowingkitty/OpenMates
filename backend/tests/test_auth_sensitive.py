"""Sensitive-action email challenges bind to account, session and purpose."""
import asyncio
import importlib
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pyotp
from fastapi import HTTPException
from backend.core.api.app.utils.newsletter_utils import hash_email

limiter_module = ModuleType("backend.core.api.app.services.limiter")
limiter_module.limiter = SimpleNamespace(limit=lambda _value: lambda function: function)
sys.modules.setdefault(limiter_module.__name__, limiter_module)
auth_utils_module = ModuleType("backend.core.api.app.routes.auth_routes.auth_utils")
auth_utils_module.verify_allowed_origin = lambda: None
sys.modules.setdefault(auth_utils_module.__name__, auth_utils_module)

sensitive = importlib.import_module("backend.core.api.app.routes.auth_routes.auth_sensitive")

# Keep the import-time dependency stubs local to this module. Other auth tests
# must import their real router helpers during combined pytest collection.
if sys.modules.get(limiter_module.__name__) is limiter_module:
    sys.modules.pop(limiter_module.__name__)
if sys.modules.get(auth_utils_module.__name__) is auth_utils_module:
    sys.modules.pop(auth_utils_module.__name__)


class Redis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, *, nx, ex):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, _script, _count, key, digest):
        raw = self.values.get(key)
        if raw is None:
            return -1
        record = json.loads(raw)
        if record["digest"] == digest:
            del self.values[key]
            return 1
        record["attempts"] += 1
        if record["attempts"] >= 5:
            del self.values[key]
        else:
            self.values[key] = json.dumps(record)
        return 0

    async def delete(self, key):
        self.values.pop(key, None)


class Cache:
    def __init__(self):
        self.redis = Redis()

    @property
    async def client(self):
        return self.redis


class Directus:
    def __init__(self):
        self.fields = {
            "hashed_email": hash_email("person@example.com"),
            "lookup_hashes": ["password-lookup"],
            "credential_lookup_hashes": {"password": "password-lookup"},
            "encrypted_tfa_secret": None,
        }

    async def get_user_fields_direct(self, user_id, field_names):
        return {key: self.fields.get(key) for key in field_names}

    async def get_items(self, *_args, **_kwargs):
        return []


# contract-test: direct surface=rest_api assertions=auth.sensitive-actions.recent-verification,auth.proofs.single-use
def test_email_challenge_consumes_once_and_requires_typed_password_same_session(monkeypatch):
    async def run():
        monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-only-secret")
        monkeypatch.setattr(sensitive, "generate_digit_code", lambda: "123456")
        session = {"logical_session_id": "session-a"}
        monkeypatch.setattr(sensitive, "_session", AsyncMock(return_value=session))
        mark = AsyncMock()
        monkeypatch.setattr(sensitive, "mark_recent_strong_proof", mark)
        fake_celery = ModuleType("backend.core.api.app.tasks.celery_config")
        fake_celery.app = SimpleNamespace(send_task=lambda **_kwargs: None)
        monkeypatch.setitem(sys.modules, fake_celery.__name__, fake_celery)

        directus, cache = Directus(), Cache()
        user = SimpleNamespace(id="account-a")
        request = SimpleNamespace()
        issued = await sensitive.request_email_code(
            request, sensitive.EmailCodeRequest(purpose="api_key_manage", email="PERSON@example.com "),
            user=user, cache=cache, directus=directus, refresh_token="token-a",
        )
        assert issued["expires_in"] == 600
        body = sensitive.EmailCodeVerify(
            purpose="api_key_manage", challenge_id=issued["challenge_id"],
            code="123456", hashed_email=directus.fields["hashed_email"],
            lookup_hash="password-lookup",
        )
        session["logical_session_id"] = "session-b"
        with pytest.raises(HTTPException) as wrong_session:
            await sensitive.verify_email_code(
                request, body, user=user, cache=cache, directus=directus,
                refresh_token="token-b",
            )
        assert wrong_session.value.status_code == 401
        session["logical_session_id"] = "session-a"
        assert (await sensitive.verify_email_code(
            request, body, user=user, cache=cache, directus=directus,
            refresh_token="token-a",
        ))["success"] is True
        mark.assert_awaited_once_with(
            directus, cache, "token-a", "account-a", method="typed_password_email",
        )
        with pytest.raises(HTTPException) as replay:
            await sensitive.verify_email_code(
                request, body, user=user, cache=cache, directus=directus,
                refresh_token="token-a",
            )
        assert replay.value.status_code == 401

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.proofs.single-use,auth.sensitive-actions.recent-verification
def test_totp_step_is_consumed_once_across_actions(monkeypatch):
    async def run():
        monkeypatch.setattr(sensitive, "_session", AsyncMock(return_value={"logical_session_id": "s1"}))
        mark = AsyncMock()
        monkeypatch.setattr(sensitive, "mark_recent_strong_proof", mark)
        secret = pyotp.random_base32()
        directus, cache = Directus(), Cache()
        directus.fields.update(encrypted_tfa_secret="ciphertext", vault_key_id="key-id")
        encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(return_value=secret))
        code = pyotp.TOTP(secret).now()
        user = SimpleNamespace(id="u1")
        result = await sensitive.verify_totp(
            SimpleNamespace(), sensitive.TotpVerify(purpose="api_key_manage", code=code),
            user=user, cache=cache, directus=directus, encryption=encryption,
            refresh_token="token",
        )
        assert result["expires_in"] == 300
        with pytest.raises(HTTPException) as replay:
            await sensitive.verify_totp(
                SimpleNamespace(), sensitive.TotpVerify(purpose="pair_approval", code=code),
                user=user, cache=cache, directus=directus, encryption=encryption,
                refresh_token="token",
            )
        assert replay.value.status_code == 401
        mark.assert_awaited_once_with(directus, cache, "token", "u1", method="totp")

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.proofs.single-use
def test_email_challenge_wrong_purpose_and_untyped_password_never_mark_proof(monkeypatch):
    async def run():
        monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-only-secret")
        monkeypatch.setattr(sensitive, "generate_digit_code", lambda: "123456")
        monkeypatch.setattr(sensitive, "_session", AsyncMock(return_value={"logical_session_id": "s1"}))
        mark = AsyncMock()
        monkeypatch.setattr(sensitive, "mark_recent_strong_proof", mark)
        fake_celery = ModuleType("backend.core.api.app.tasks.celery_config")
        fake_celery.app = SimpleNamespace(send_task=lambda **_kwargs: None)
        monkeypatch.setitem(sys.modules, fake_celery.__name__, fake_celery)
        directus, cache = Directus(), Cache()
        user = SimpleNamespace(id="u1")
        issued = await sensitive.request_email_code(
            SimpleNamespace(), sensitive.EmailCodeRequest(purpose="api_key_manage", email="person@example.com"),
            user=user, cache=cache, directus=directus, refresh_token="token",
        )
        body = sensitive.EmailCodeVerify(
            purpose="pair_approval", challenge_id=issued["challenge_id"], code="123456",
            hashed_email=directus.fields["hashed_email"], lookup_hash="password-lookup",
        )
        with pytest.raises(HTTPException):
            await sensitive.verify_email_code(
                SimpleNamespace(), body, user=user, cache=cache, directus=directus,
                refresh_token="token",
            )
        body.purpose = "api_key_manage"
        directus.fields["credential_lookup_hashes"] = {"recovery_key": "password-lookup"}
        with pytest.raises(HTTPException):
            await sensitive.verify_email_code(
                SimpleNamespace(), body, user=user, cache=cache, directus=directus,
                refresh_token="token",
            )
        mark.assert_not_awaited()

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.sensitive-actions.recent-verification,auth.proofs.single-use
def test_legacy_account_secret_email_has_distinct_provenance_and_rejects_mismatch(monkeypatch):
    async def run():
        monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-only-secret")
        monkeypatch.setattr(sensitive, "generate_digit_code", lambda: "123456")
        monkeypatch.setattr(sensitive, "_session", AsyncMock(return_value={"logical_session_id": "s1"}))
        mark = AsyncMock()
        monkeypatch.setattr(sensitive, "mark_recent_strong_proof", mark)
        fake_celery = ModuleType("backend.core.api.app.tasks.celery_config")
        fake_celery.app = SimpleNamespace(send_task=lambda **_kwargs: None)
        monkeypatch.setitem(sys.modules, fake_celery.__name__, fake_celery)
        directus, cache = Directus(), Cache()
        directus.fields["credential_lookup_hashes"] = None
        user = SimpleNamespace(id="u1")
        request = SimpleNamespace()
        wrong = await sensitive.request_email_code(
            request, sensitive.EmailCodeRequest(purpose="pair_approval", email="person@example.com"),
            user=user, cache=cache, directus=directus, refresh_token="token",
        )
        bad = sensitive.EmailCodeVerify(
            purpose="pair_approval", challenge_id=wrong["challenge_id"], code="123456",
            hashed_email=directus.fields["hashed_email"], lookup_hash="wrong-secret",
        )
        with pytest.raises(HTTPException):
            await sensitive.verify_email_code(
                request, bad, user=user, cache=cache, directus=directus,
                refresh_token="token",
            )
        mark.assert_not_awaited()
        with pytest.raises(HTTPException):
            await sensitive.verify_email_code(
                request, bad, user=user, cache=cache, directus=directus,
                refresh_token="token",
            )
        good = await sensitive.request_email_code(
            request, sensitive.EmailCodeRequest(purpose="pair_approval", email="person@example.com"),
            user=user, cache=cache, directus=directus, refresh_token="token",
        )
        body = sensitive.EmailCodeVerify(
            purpose="pair_approval", challenge_id=good["challenge_id"], code="123456",
            hashed_email=directus.fields["hashed_email"], lookup_hash="password-lookup",
        )
        assert (await sensitive.verify_email_code(
            request, body, user=user, cache=cache, directus=directus,
            refresh_token="token",
        ))["success"] is True
        mark.assert_awaited_once_with(
            directus, cache, "token", "u1", method="legacy_account_secret_email",
        )

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.sensitive-actions.recent-verification,auth.login.verified-method
def test_mixed_typed_methods_preserve_only_untyped_legacy_sensitive_fallback(monkeypatch):
    async def run():
        monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-only-secret")
        monkeypatch.setattr(sensitive, "generate_digit_code", lambda: "123456")
        monkeypatch.setattr(sensitive, "_session", AsyncMock(return_value={"logical_session_id": "s1"}))
        mark = AsyncMock()
        monkeypatch.setattr(sensitive, "mark_recent_strong_proof", mark)
        fake_celery = ModuleType("backend.core.api.app.tasks.celery_config")
        fake_celery.app = SimpleNamespace(send_task=lambda **_kwargs: None)
        monkeypatch.setitem(sys.modules, fake_celery.__name__, fake_celery)
        directus, cache = Directus(), Cache()
        directus.fields["lookup_hashes"] = ["old-untyped", "typed-recovery"]
        directus.fields["credential_lookup_hashes"] = {
            "recovery_key": {"lookup_hash": "typed-recovery", "wrapper_method": "recovery_key"},
        }
        user = SimpleNamespace(id="u1")
        request = SimpleNamespace()

        async def verify(lookup_hash):
            issued = await sensitive.request_email_code(
                request, sensitive.EmailCodeRequest(purpose="pair_approval", email="person@example.com"),
                user=user, cache=cache, directus=directus, refresh_token="token",
            )
            return await sensitive.verify_email_code(
                request, sensitive.EmailCodeVerify(
                    purpose="pair_approval", challenge_id=issued["challenge_id"],
                    code="123456", hashed_email=directus.fields["hashed_email"],
                    lookup_hash=lookup_hash,
                ), user=user, cache=cache, directus=directus, refresh_token="token",
            )

        assert (await verify("old-untyped"))["success"] is True
        mark.assert_awaited_once_with(
            directus, cache, "token", "u1", method="legacy_account_secret_email",
        )
        with pytest.raises(HTTPException) as typed_recovery:
            await verify("typed-recovery")
        assert typed_recovery.value.status_code == 401
        assert mark.await_count == 1

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.password.versioned-protection,auth.sensitive-actions.recent-verification
def test_v2_sensitive_email_never_falls_back_to_lookup_hash(monkeypatch):
    async def run():
        monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-only-secret")
        monkeypatch.setattr(sensitive, "generate_digit_code", lambda: "123456")
        monkeypatch.setattr(sensitive, "_session", AsyncMock(return_value={"logical_session_id": "s1"}))
        mark = AsyncMock()
        monkeypatch.setattr(sensitive, "mark_recent_strong_proof", mark)
        verify = AsyncMock(return_value=False)
        monkeypatch.setattr(sensitive, "verify_challenge_proof", verify)
        fake_celery = ModuleType("backend.core.api.app.tasks.celery_config")
        fake_celery.app = SimpleNamespace(send_task=lambda **_kwargs: None)
        monkeypatch.setitem(sys.modules, fake_celery.__name__, fake_celery)
        directus, cache = Directus(), Cache()
        directus.fields["credential_lookup_hashes"] = {
            "password": {"version": 2, "kdf": "argon2id-hkdf-sha256-v1",
                         "sealed_auth_key": "vault:v1:sealed", "wrapper_method": "password_v2_new"},
        }
        directus.fields["vault_key_id"] = "user-key"
        user = SimpleNamespace(id="u1")
        issued = await sensitive.request_email_code(
            SimpleNamespace(), sensitive.EmailCodeRequest(purpose="credential_change", email="person@example.com"),
            user=user, cache=cache, directus=directus, refresh_token="token",
        )
        body = sensitive.EmailCodeVerify(
            purpose="credential_change", challenge_id=issued["challenge_id"], code="123456",
            hashed_email=directus.fields["hashed_email"], lookup_hash="password-lookup",
            session_id="session-123", password_challenge_id="challenge-123", password_proof="proof-123",
        )
        with pytest.raises(HTTPException) as denied:
            await sensitive.verify_email_code(
                SimpleNamespace(), body, user=user, cache=cache, directus=directus,
                encryption=SimpleNamespace(), refresh_token="token",
            )
        assert denied.value.status_code == 401
        mark.assert_not_awaited()
        assert verify.await_args.kwargs["purpose"] == "sensitive:credential_change"

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.sensitive-actions.recent-verification,auth.login.verified-method
def test_rotated_typed_password_mapping_can_prove_but_malformed_mapping_cannot(monkeypatch):
    async def run():
        monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-only-secret")
        monkeypatch.setattr(sensitive, "generate_digit_code", lambda: "123456")
        monkeypatch.setattr(sensitive, "_session", AsyncMock(return_value={"logical_session_id": "s1"}))
        mark = AsyncMock()
        monkeypatch.setattr(sensitive, "mark_recent_strong_proof", mark)
        fake_celery = ModuleType("backend.core.api.app.tasks.celery_config")
        fake_celery.app = SimpleNamespace(send_task=lambda **_kwargs: None)
        monkeypatch.setitem(sys.modules, fake_celery.__name__, fake_celery)
        directus, cache = Directus(), Cache()
        directus.fields["credential_lookup_hashes"] = {
            "password": {"lookup_hash": "password-lookup", "wrapper_method": "password_v2"},
        }
        user = SimpleNamespace(id="u1")
        request = SimpleNamespace()

        async def attempt():
            issued = await sensitive.request_email_code(
                request, sensitive.EmailCodeRequest(purpose="credential_change", email="person@example.com"),
                user=user, cache=cache, directus=directus, refresh_token="token",
            )
            return await sensitive.verify_email_code(
                request, sensitive.EmailCodeVerify(
                    purpose="credential_change", challenge_id=issued["challenge_id"],
                    code="123456", hashed_email=directus.fields["hashed_email"],
                    lookup_hash="password-lookup",
                ), user=user, cache=cache, directus=directus, refresh_token="token",
            )

        assert (await attempt())["success"] is True
        mark.assert_awaited_once_with(
            directus, cache, "token", "u1", method="typed_password_email",
        )
        directus.fields["credential_lookup_hashes"] = {
            "password": {"lookup_hash": "password-lookup", "wrapper_method": 123},
        }
        with pytest.raises(HTTPException) as malformed:
            await attempt()
        assert malformed.value.status_code == 401
        assert mark.await_count == 1

    asyncio.run(run())
