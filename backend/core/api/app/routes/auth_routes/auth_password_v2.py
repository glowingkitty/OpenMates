"""First-party password v2 challenge and migration routes."""

from __future__ import annotations

import hashlib
import json
import secrets
import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_cache_service, get_current_user, get_directus_service, get_encryption_service,
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_auth_client
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.password_v2 import (
    KDF_ID, decode_key, has_password_v2_record, issue_challenge, password_v2_record,
    seal_auth_key, verify_challenge_proof,
)
from backend.core.api.app.services.credential_verification import (
    acquire_credential_change_lock, release_credential_change_lock, typed_lookup_method,
    typed_lookup_wrapper,
)
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.models.user import User
from backend.core.api.app.services.session_security_state import (
    get_session_state_cached, require_recent_strong_proof, token_hash,
)

router = APIRouter(prefix="/password-v2", tags=["Auth - Password V2"])


@router.get("/migration-capabilities", dependencies=[Depends(verify_auth_client)])
async def password_v2_migration_capabilities():
    return {"staged_protocol": 2, "confirm_required": True}


class PasswordV2ChallengeRequest(BaseModel):
    hashed_email: str = Field(min_length=16, max_length=256)
    session_id: str = Field(min_length=8, max_length=256)
    purpose: str = Field(default="login", pattern=r"^login$")


@router.post("/challenge", dependencies=[Depends(verify_auth_client)])
@limiter.limit("30/minute")
async def password_v2_challenge(
    request: Request, body: PasswordV2ChallengeRequest,
    cache_service: CacheService = Depends(get_cache_service),
):
    # Unauthenticated first-party REST surface. A challenge contains no
    # account-specific data and is issued uniformly for absent identities.
    return await issue_challenge(
        cache_service, hashed_email=body.hashed_email,
        session_id=body.session_id, purpose=body.purpose,
    )


class PasswordV2MigrationRequest(BaseModel):
    old_lookup_hash: str = Field(min_length=16, max_length=512)
    password_auth_key: SecretStr
    encrypted_master_key: str = Field(min_length=16)
    salt: str = Field(min_length=16)
    key_iv: str = Field(min_length=8)


def _typed_record(fields: dict) -> dict | None:
    typed = fields.get("credential_lookup_hashes")
    if isinstance(typed, str):
        try:
            typed = json.loads(typed)
        except ValueError:
            return None
    return typed if isinstance(typed, dict) else None


def _require_recent_password_login(session: dict, *, method: str, lookup_hash: str) -> None:
    try:
        verified_at = int(session["login_verified_at"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "Fresh password login required") from None
    now = int(time.time())
    if (session.get("verified_login_method") != method
            or session.get("verified_credential_version") != 1
            or session.get("verified_lookup_digest") != hashlib.sha256(lookup_hash.encode()).hexdigest()
            or verified_at > now or now - verified_at >= 300):
        raise HTTPException(401, "Fresh password login required")


async def _require_migration_assurance(directus, cache, token: str, user_id: str) -> None:
    try:
        await require_recent_strong_proof(directus, cache, token, user_id)
    except HTTPException as exc:
        if exc.status_code == 401 and exc.detail == "Recent verification required":
            raise HTTPException(428, {"error": "recent_verification_required"}) from None
        raise


async def _staged_account(directus, cache, token: str | None, user_id: str):
    if not token:
        raise HTTPException(401, "Current session required")
    session = await get_session_state_cached(directus, cache, token_hash(token), user_id=user_id)
    if not session or not session.get("logical_session_id"):
        raise HTTPException(401, "Current session required")
    fields = await directus.get_user_fields_direct(user_id, [
        "hashed_email", "vault_key_id", "credential_lookup_hashes", "lookup_hashes",
    ])
    typed = _typed_record(fields) if isinstance(fields, dict) else None
    v2 = password_v2_record(typed)
    if not fields or not v2 or not v2.get("pending_v1_lookup_hash"):
        raise HTTPException(409, "No pending password migration")
    _require_recent_password_login(session, method="password", lookup_hash=v2["pending_v1_lookup_hash"])
    return session, fields, typed, v2


def _confirmation_key(token: str) -> str:
    return f"auth:password-v2:confirm:{token_hash(token)}"


async def _safe_migration_request(request: Request) -> PasswordV2MigrationRequest:
    try:
        return PasswordV2MigrationRequest.model_validate(await request.json())
    except Exception:
        raise HTTPException(400, "Invalid password migration request") from None


@router.post("/migrate", dependencies=[Depends(verify_auth_client)])
@limiter.limit("5/minute")
async def migrate_password_v2(
    request: Request, body: PasswordV2MigrationRequest = Depends(_safe_migration_request),
    user: User = Depends(get_current_user),
    directus=Depends(get_directus_service),
    cache: CacheService = Depends(get_cache_service),
    encryption: EncryptionService = Depends(get_encryption_service),
):
    """Install a v2 wrapper after local unlock and a live legacy session.

    Only a typed v1 password binding permits retirement of its old lookup.
    Untyped mixed legacy lookups remain valid because their provenance cannot
    be inferred from a submitted accepted hash.
    """
    try:
        decode_key(body.password_auth_key.get_secret_value())
    except ValueError:
        raise HTTPException(400, "Invalid password migration request") from None
    lock = await acquire_credential_change_lock(cache, user.id, "password")
    wrapper_method = None
    committed = False
    try:
        fields = await directus.get_user_fields_direct(user.id, [
            "hashed_email", "user_email_salt", "vault_key_id", "lookup_hashes", "credential_lookup_hashes",
        ])
        if not isinstance(fields, dict) or body.salt != fields.get("user_email_salt"):
            raise HTTPException(401, "Invalid password migration request")
        hashes = fields.get("lookup_hashes")
        typed = fields.get("credential_lookup_hashes")
        if isinstance(hashes, str):
            try:
                hashes = json.loads(hashes)
            except ValueError:
                hashes = None
        if isinstance(typed, str):
            if not typed.strip():
                typed = {}
            else:
                try:
                    typed = json.loads(typed)
                except ValueError:
                    typed = None
        if typed is None:
            typed = {}
        if (not isinstance(hashes, list) or body.old_lookup_hash not in hashes
                or not isinstance(typed, dict) or has_password_v2_record(typed)):
            raise HTTPException(401, "Invalid password migration request")
        bound_method = typed_lookup_method(typed, body.old_lookup_hash)
        if (bound_method and bound_method != "password") or (
            "password" in typed and bound_method != "password"
        ):
            raise HTTPException(401, "Invalid password migration request")
        # Untyped mixed hashes may be recovery keys. Installing a v2 password
        # would remove their TOTP-bypass eligibility and could strand a user
        # who has lost their authenticator. Defer before sealing or writing.
        if bound_method != "password" or any(
            not isinstance(value, str) or typed_lookup_method(typed, value) is None
            for value in hashes
        ):
            raise HTTPException(409, {
                "error": "legacy_credential_binding_required",
                "migration_status": "deferred_legacy_credentials",
            })
        # Typed v1 remains active until v2 proof and client-side root equality.
        status = "pending_confirmation"
        token = request.cookies.get("auth_refresh_token") if hasattr(request, "cookies") else None
        if not token:
            raise HTTPException(401, "Fresh password login required")
        session = await get_session_state_cached(directus, cache, token_hash(token), user_id=user.id)
        if not session:
            raise HTTPException(401, "Fresh password login required")
        _require_recent_password_login(
            session, method="password",
            lookup_hash=body.old_lookup_hash,
        )
        # The legacy lookup may be disclosed to an authenticated client. A
        # stolen session must not be able to enroll an attacker-controlled v2
        # verifier and wrapper using that value alone.
        await _require_migration_assurance(directus, cache, token, user.id)
        legacy_retained = False
        vault_key_id = fields.get("vault_key_id")
        sealed_auth_key = await seal_auth_key(
            encryption, password_auth_key=body.password_auth_key.get_secret_value(),
            vault_key_id=vault_key_id,
        )
        wrapper_method = f"password_v2_{secrets.token_hex(16)}"
        hashed_user_id = hashlib.sha256(user.id.encode()).hexdigest()
        created = await directus.create_encryption_key(
            hashed_user_id=hashed_user_id, login_method=wrapper_method,
            encrypted_key=body.encrypted_master_key, salt=body.salt, key_iv=body.key_iv,
        )
        if not created:
            raise HTTPException(503, "Password migration unavailable")
        next_typed = dict(typed)
        next_typed["password"] = {
            "version": 2, "kdf": KDF_ID,
            "sealed_auth_key": sealed_auth_key, "wrapper_method": wrapper_method,
            "legacy_password_retained": legacy_retained,
        }
        if status == "pending_confirmation":
            next_typed["password"]["pending_v1_lookup_hash"] = body.old_lookup_hash
            next_typed["password"]["pending_v1_wrapper_method"] = (
                typed_lookup_wrapper(typed, "password", body.old_lookup_hash) or "password"
            )
        next_hashes = hashes
        committed = await directus.update_user(user.id, {
            "lookup_hashes": next_hashes, "credential_lookup_hashes": next_typed,
        })
        if not committed:
            raise HTTPException(503, "Password migration unavailable")
        await cache.delete(f"user_profile:{user.id}")
        await cache.delete(f"user:{hashed_user_id}:login_methods")
        await cache.delete(f"login_methods:{user.id}")
        return {"success": True, "migration_status": status,
                "legacy_password_retained": legacy_retained}
    except HTTPException:
        if wrapper_method and not committed:
            await directus.delete_encryption_key(hashlib.sha256(user.id.encode()).hexdigest(), wrapper_method)
        raise
    except Exception:
        if wrapper_method and not committed:
            await directus.delete_encryption_key(hashlib.sha256(user.id.encode()).hexdigest(), wrapper_method)
        raise HTTPException(503, "Password migration unavailable") from None
    finally:
        await release_credential_change_lock(lock)


@router.post("/staged-challenge", dependencies=[Depends(verify_auth_client)])
@limiter.limit("10/minute")
async def staged_password_challenge(
    request: Request, user: User = Depends(get_current_user),
    directus=Depends(get_directus_service), cache: CacheService = Depends(get_cache_service),
    refresh_token: str | None = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    session, fields, _typed, v2 = await _staged_account(directus, cache, refresh_token, user.id)
    return await issue_challenge(
        cache, hashed_email=fields["hashed_email"],
        session_id=session["logical_session_id"], purpose="migration",
        binding=v2["pending_v1_lookup_hash"],
    )


class StagedPasswordVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=32, max_length=64)
    password_proof: str = Field(min_length=43, max_length=43)


@router.post("/verify-staged", dependencies=[Depends(verify_auth_client)])
@limiter.limit("10/minute")
async def verify_staged_password(
    request: Request, body: StagedPasswordVerifyRequest,
    user: User = Depends(get_current_user),
    directus=Depends(get_directus_service), cache: CacheService = Depends(get_cache_service),
    encryption: EncryptionService = Depends(get_encryption_service),
    refresh_token: str | None = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    session, fields, typed, v2 = await _staged_account(directus, cache, refresh_token, user.id)
    verified = await verify_challenge_proof(
        cache, encryption, challenge_id=body.challenge_id, password_proof=body.password_proof,
        hashed_email=fields["hashed_email"], session_id=session["logical_session_id"],
        purpose="migration", binding=v2["pending_v1_lookup_hash"],
        record=typed, vault_key_id=fields["vault_key_id"],
    )
    if not verified:
        raise HTTPException(401, "Invalid password proof")
    wrapper = await directus.get_encryption_key(
        hashlib.sha256(user.id.encode()).hexdigest(), v2["wrapper_method"],
    )
    if not isinstance(wrapper, dict) or not all(wrapper.get(key) for key in ("encrypted_key", "salt", "key_iv")):
        raise HTTPException(503, "Password wrapper unavailable")
    marker = {"user_id": user.id, "session_id": session["logical_session_id"],
              "pending_v1_lookup_hash": v2["pending_v1_lookup_hash"],
              "wrapper_method": v2["wrapper_method"]}
    if not await cache.set(_confirmation_key(refresh_token), marker, ttl=300):
        raise HTTPException(503, "Password confirmation unavailable")
    return {"encrypted_key": wrapper["encrypted_key"], "salt": wrapper["salt"],
            "key_iv": wrapper["key_iv"], "credential_version": 2}


@router.post("/confirm-migration", dependencies=[Depends(verify_auth_client)])
@limiter.limit("10/minute")
async def confirm_password_migration(
    request: Request, user: User = Depends(get_current_user),
    directus=Depends(get_directus_service), cache: CacheService = Depends(get_cache_service),
    refresh_token: str | None = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    session, _fields, _typed, _v2 = await _staged_account(directus, cache, refresh_token, user.id)
    lock = await acquire_credential_change_lock(cache, user.id, "password")
    try:
        marker = await cache.get_and_delete(_confirmation_key(refresh_token))
        if not isinstance(marker, dict) or marker.get("user_id") != user.id or marker.get("session_id") != session["logical_session_id"]:
            raise HTTPException(401, "Password confirmation expired")
        _session, fields, typed, v2 = await _staged_account(directus, cache, refresh_token, user.id)
        old_hash = v2["pending_v1_lookup_hash"]
        if marker.get("pending_v1_lookup_hash") != old_hash or marker.get("wrapper_method") != v2["wrapper_method"]:
            raise HTTPException(409, "Password migration changed")
        hashes = fields.get("lookup_hashes")
        if isinstance(hashes, str):
            try:
                hashes = json.loads(hashes)
            except ValueError:
                hashes = None
        if not isinstance(hashes, list) or old_hash not in hashes:
            raise HTTPException(409, "Password migration changed")
        # Recheck at the irreversible retirement boundary. A staged wrapper or
        # one-use confirmation marker created before this policy was enforced
        # cannot authorize removal of the v1 credential on its own.
        await _require_migration_assurance(directus, cache, refresh_token, user.id)
        next_v2 = dict(v2)
        next_v2.pop("pending_v1_lookup_hash", None)
        next_v2.pop("pending_v1_wrapper_method", None)
        next_typed = dict(typed)
        next_typed["password"] = next_v2
        committed = await directus.update_user(user.id, {
            "lookup_hashes": [value for value in hashes if value != old_hash],
            "credential_lookup_hashes": next_typed,
        })
        if not committed:
            raise HTTPException(503, "Password confirmation unavailable")
        hashed_user_id = hashlib.sha256(user.id.encode()).hexdigest()
        await cache.delete(f"user_profile:{user.id}")
        await cache.delete(f"user:{hashed_user_id}:login_methods")
        await cache.delete(f"login_methods:{user.id}")
        return {"success": True, "migration_status": "typed_retired",
                "legacy_password_retained": bool(next_v2.get("legacy_password_retained"))}
    finally:
        await release_credential_change_lock(lock)
