"""Session-bound verification before sensitive account actions."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from collections.abc import Mapping

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_cache_service, get_current_user, get_directus_service, get_encryption_service,
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
from backend.core.api.app.routes.auth_routes.auth_common import set_session_security_country
from backend.core.api.app.services.credential_verification import typed_lookup_method
from backend.core.api.app.services.password_v2 import (
    has_password_v2_record, issue_challenge, verify_challenge_proof,
)
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.session_security_state import (
    claim_totp_step, get_session_state_cached, mark_recent_strong_proof, token_hash,
)
from backend.core.api.app.utils.newsletter_utils import hash_email
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash
from backend.shared.python_utils.security_random import generate_digit_code

class SafeSensitiveRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, "Invalid verification request") from None

        return safe_handler


def _allow_risk_verification(request: Request) -> None:
    # This route may resolve a pending device challenge. The challenge itself
    # still rejects all purposes except device_approval until verified.
    request.state.allow_session_risk = True


router = APIRouter(prefix="/sensitive", dependencies=[
    Depends(verify_allowed_origin), Depends(_allow_risk_verification),
],
                   route_class=SafeSensitiveRoute)
CODE_TTL = 600
PURPOSES = frozenset({
    "api_key_manage", "pair_approval", "credential_change", "factor_change",
    "backup_codes", "recovery_key_change", "contact_change",
    "delete_account", "device_approval",
})
_CLAIM = """
local raw = redis.call('GET', KEYS[1])
if not raw then return -1 end
local record = cjson.decode(raw)
if record.digest == ARGV[1] then
    redis.call('DEL', KEYS[1])
    return 1
end
record.attempts = (record.attempts or 0) + 1
if record.attempts >= 5 then
    redis.call('DEL', KEYS[1])
else
    redis.call('SET', KEYS[1], cjson.encode(record), 'KEEPTTL')
end
return 0
"""


class EmailCodeRequest(BaseModel):
    purpose: str
    email: str = Field(min_length=3, max_length=254)
    session_id: str | None = Field(default=None, min_length=8, max_length=256)


class EmailCodeVerify(BaseModel):
    purpose: str
    challenge_id: str = Field(min_length=32, max_length=64)
    code: str = Field(pattern=r"^[0-9]{6}$")
    hashed_email: str
    lookup_hash: str | None = None
    session_id: str | None = Field(default=None, min_length=8, max_length=256)
    password_challenge_id: str | None = None
    password_proof: str | None = None


class TotpVerify(BaseModel):
    purpose: str
    code: str = Field(pattern=r"^[0-9]{6}$")
    session_id: str | None = Field(default=None, min_length=8, max_length=256)


def _purpose(value: str) -> str:
    if value not in PURPOSES:
        raise HTTPException(400, "Unsupported verification purpose")
    return value


def _challenge_key(challenge_id: str) -> str:
    return f"auth:sensitive-code:{challenge_id}"


def _code_digest(secret: str, *, challenge_id: str, user_id: str,
                 session_id: str, purpose: str, code: str) -> str:
    payload = "\0".join((challenge_id, user_id, session_id, purpose, code))
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


async def _session(directus, cache, token: str | None, user_id: str,
                   *, allow_risk: bool = False) -> dict:
    if not token:
        raise HTTPException(401, "Current session required")
    row = await get_session_state_cached(
        directus, cache, token_hash(token), user_id=user_id, allow_risk=allow_risk,
    )
    if not row or not row.get("logical_session_id"):
        raise HTTPException(401, "New login required for verification")
    return row


async def _complete_device_approval(request: Request, directus, cache,
                                    token: str, user_id: str,
                                    session_id: str | None) -> None:
    if not session_id:
        raise HTTPException(400, "Session ID required for device approval")
    try:
        device_hash, _, _, country, _, _, _, _ = generate_device_fingerprint_hash(
            request, user_id, session_id,
        )
        updated, _ = await directus.add_user_device_hash(user_id, device_hash)
        if not updated:
            raise RuntimeError("Device registration failed")
        await set_session_security_country(cache, user_id, token, country)
    except Exception as exc:
        raise HTTPException(503, "Device approval temporarily unavailable") from exc


def _secret() -> str:
    secret = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not secret:
        raise HTTPException(503, "Verification temporarily unavailable")
    return secret


@router.post("/email/request")
@limiter.limit("3/minute")
async def request_email_code(
    request: Request, body: EmailCodeRequest,
    user: User = Depends(get_current_user),
    cache=Depends(get_cache_service), directus=Depends(get_directus_service),
    refresh_token: str | None = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    purpose = _purpose(body.purpose)
    session = await _session(directus, cache, refresh_token, user.id,
                             allow_risk=purpose == "device_approval")
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(400, "Invalid email address")
    fields = await directus.get_user_fields_direct(user.id, [
        "hashed_email", "encrypted_tfa_secret", "language", "darkmode",
    ])
    if not isinstance(fields, dict) or not fields.get("hashed_email"):
        raise HTTPException(503, "Account verification unavailable")
    if not hmac.compare_digest(hash_email(email), str(fields["hashed_email"])):
        raise HTTPException(401, "Email does not match this account")
    # An enrolled TOTP is mandatory when present. A passkey may be bound to a
    # different device, so typed password plus email remains available while
    # the UI presents passkey as the preferred verification method.
    if fields.get("encrypted_tfa_secret"):
        raise HTTPException(403, "Use your enrolled authenticator")

    secret = _secret()
    client = await cache.client
    if client is None:
        raise HTTPException(503, "Verification temporarily unavailable")
    challenge_id = secrets.token_urlsafe(24)
    code = generate_digit_code()
    digest = _code_digest(secret, challenge_id=challenge_id, user_id=user.id,
                          session_id=session["logical_session_id"], purpose=purpose, code=code)
    key = _challenge_key(challenge_id)
    if not await client.set(key, json.dumps({"digest": digest, "attempts": 0}), nx=True, ex=CODE_TTL):
        raise HTTPException(503, "Verification temporarily unavailable")
    try:
        from backend.core.api.app.tasks.celery_config import app as celery_app
        celery_app.send_task(
            name="app.tasks.email_tasks.action_verification_email_task.generate_and_send_action_verification_email",
            kwargs={"user_id": user.id, "email": email, "action": purpose,
                    "language": fields.get("language") or "en",
                    "darkmode": bool(fields.get("darkmode")),
                    "verification_code": code}, queue="email",
        )
    except Exception as exc:
        await client.delete(key)
        raise HTTPException(503, "Verification delivery unavailable") from exc
    result = {"success": True, "challenge_id": challenge_id, "expires_in": CODE_TTL}
    if body.session_id:
        password_challenge = await issue_challenge(
            cache, hashed_email=str(fields["hashed_email"]),
            session_id=body.session_id, purpose=f"sensitive:{purpose}",
        )
        result["password_challenge_id"] = password_challenge["challenge_id"]
        result["password_nonce"] = password_challenge["nonce"]
    return result


@router.post("/email/verify")
@limiter.limit("5/minute")
async def verify_email_code(
    request: Request, body: EmailCodeVerify,
    user: User = Depends(get_current_user),
    cache=Depends(get_cache_service), directus=Depends(get_directus_service),
    encryption=Depends(get_encryption_service),
    refresh_token: str | None = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    purpose = _purpose(body.purpose)
    session = await _session(directus, cache, refresh_token, user.id,
                             allow_risk=purpose == "device_approval")
    secret = _secret()
    expected = _code_digest(secret, challenge_id=body.challenge_id, user_id=user.id,
                            session_id=session["logical_session_id"], purpose=purpose, code=body.code)
    client = await cache.client
    if client is None:
        raise HTTPException(503, "Verification temporarily unavailable")
    claimed = await client.eval(_CLAIM, 1, _challenge_key(body.challenge_id), expected)
    if claimed != 1:
        raise HTTPException(401, "Invalid or expired verification code")

    fields = await directus.get_user_fields_direct(user.id, [
        "hashed_email", "lookup_hashes", "credential_lookup_hashes", "encrypted_tfa_secret", "vault_key_id",
    ])
    if not isinstance(fields, dict) or not hmac.compare_digest(
        str(fields.get("hashed_email") or ""), body.hashed_email,
    ):
        raise HTTPException(401, "Invalid password proof")
    record = fields.get("credential_lookup_hashes")
    if has_password_v2_record(record):
        if not body.session_id or not body.password_challenge_id or not body.password_proof:
            raise HTTPException(401, "Invalid password proof")
        valid = await verify_challenge_proof(
            cache, encryption, challenge_id=body.password_challenge_id,
            password_proof=body.password_proof, hashed_email=body.hashed_email,
            session_id=body.session_id, purpose=f"sensitive:{purpose}",
            record=record, vault_key_id=fields.get("vault_key_id"),
        )
        if not valid:
            raise HTTPException(401, "Invalid password proof")
        method = "password_v2_email"
    else:
        method = None
    hashes = fields.get("lookup_hashes")
    if isinstance(hashes, str):
        try:
            hashes = json.loads(hashes)
        except ValueError:
            hashes = None
    if method is None and (not isinstance(hashes, list) or not body.lookup_hash or body.lookup_hash not in hashes):
        raise HTTPException(401, "Invalid password proof")
    if isinstance(record, str):
        if not record.strip():
            record = None
        else:
            try:
                record = json.loads(record)
            except ValueError as exc:
                raise HTTPException(401, "Invalid password proof") from exc
    if record is not None and not isinstance(record, Mapping):
        raise HTTPException(401, "Invalid password proof")
    if isinstance(record, Mapping) and method is None:
        for key, value in record.items():
            if not isinstance(key, str) or not key:
                raise HTTPException(401, "Invalid password proof")
            if isinstance(value, str):
                if not value:
                    raise HTTPException(401, "Invalid password proof")
            elif isinstance(value, Mapping):
                if (not set(value).issubset({"lookup_hash", "wrapper_method"})
                        or not isinstance(value.get("lookup_hash"), str)
                        or not value["lookup_hash"]
                        or ("wrapper_method" in value and (
                            not isinstance(value["wrapper_method"], str)
                            or not value["wrapper_method"]
                        ))):
                    raise HTTPException(401, "Invalid password proof")
            else:
                raise HTTPException(401, "Invalid password proof")
    if method is not None:
        pass
    elif isinstance(record, Mapping) and "password" in record:
        if typed_lookup_method(record, body.lookup_hash) != "password":
            raise HTTPException(401, "Invalid password proof")
        method = "typed_password_email"
    else:
        # Other typed methods may have been enrolled while the old account
        # secret remains untyped. Never relabel a hash bound to another method
        # as that secret, including when duplicate bindings make the typed
        # lookup resolver return no unique method.
        if isinstance(record, Mapping) and any(
            value == body.lookup_hash if isinstance(value, str)
            else value.get("lookup_hash") == body.lookup_hash
            for value in record.values()
        ):
            raise HTTPException(401, "Invalid password proof")
        # Temporary migration exception: an accepted untyped account secret
        # requires the one-use email code and retains distinct provenance.
        method = "legacy_account_secret_email"
    if fields.get("encrypted_tfa_secret"):
        raise HTTPException(403, "Use your enrolled authenticator")
    if purpose == "device_approval":
        await _complete_device_approval(
            request, directus, cache, refresh_token, user.id, body.session_id,
        )
    proof_kwargs = {"clear_risk": True} if purpose == "device_approval" else {}
    await mark_recent_strong_proof(directus, cache, refresh_token, user.id,
                                   method=method, **proof_kwargs)
    return {"success": True, "expires_in": 300}


@router.post("/totp/verify")
@limiter.limit("5/minute")
async def verify_totp(
    request: Request, body: TotpVerify,
    user: User = Depends(get_current_user),
    cache=Depends(get_cache_service), directus=Depends(get_directus_service),
    encryption=Depends(get_encryption_service),
    refresh_token: str | None = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    purpose = _purpose(body.purpose)
    await _session(directus, cache, refresh_token, user.id,
                   allow_risk=purpose == "device_approval")
    fields = await directus.get_user_fields_direct(user.id, ["encrypted_tfa_secret", "vault_key_id"])
    if not isinstance(fields, dict) or not fields.get("encrypted_tfa_secret") or not fields.get("vault_key_id"):
        raise HTTPException(401, "Authenticator unavailable")
    try:
        secret = await encryption.decrypt_with_user_key(fields["encrypted_tfa_secret"], fields["vault_key_id"])
        if not isinstance(secret, str) or not secret:
            raise ValueError("Authenticator secret unavailable")
    except Exception as exc:
        raise HTTPException(503, "Authenticator verification unavailable") from exc
    if not await claim_totp_step(cache, user.id, secret, body.code):
        raise HTTPException(401, "Invalid or reused authenticator code")
    if purpose == "device_approval":
        await _complete_device_approval(
            request, directus, cache, refresh_token, user.id, body.session_id,
        )
    proof_kwargs = {"clear_risk": True} if purpose == "device_approval" else {}
    await mark_recent_strong_proof(directus, cache, refresh_token, user.id,
                                   method="totp", **proof_kwargs)
    return {"success": True, "expires_in": 300}
