"""First-party, client-to-client PAKE pairing relay.

The API never receives the PIN, PAKE registration record, or account key in cleartext.
All state transitions use one Redis script so two workers cannot consume a grant twice.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from collections.abc import Mapping
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_cache_service, get_compliance_service, get_current_user, get_current_user_optional,
    get_directus_service, get_encryption_service,
)
from backend.core.api.app.routes.auth_routes.auth_login import PairingSessionContext, finalize_login_session
from backend.core.api.app.routes.auth_routes.auth_utils import verify_auth_client
from backend.core.api.app.schemas.auth import LoginResponse
from backend.core.api.app.schemas.user import UserResponse
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.device_fingerprint import _extract_client_ip, derive_device_name, generate_device_fingerprint_hash, get_geo_data_from_ip, truncate_ip
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.ws_token import create_ws_token
from backend.core.api.app.services.pair_session_deadline import register_pair_session, activate_pair_session, confirm_pair_session, is_pair_session_confirmed
from backend.core.api.app.services.credential_verification import typed_lookup_method
from backend.core.api.app.services.session_security_state import claim_totp_step, mark_recent_strong_proof, require_recent_strong_proof

class PairValidationRoute(APIRoute):
    """Keep PAKE fields out of FastAPI's 422 response and error logging."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(status_code=422, detail="Invalid pairing request") from None

        return safe_handler


router = APIRouter(prefix="/pair/v2", dependencies=[Depends(verify_auth_client)], route_class=PairValidationRoute)

PAIR_TTL = 300
MAX_GRANT_ATTEMPTS = 5
_TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRTUVWXY3468"
_TOKEN_RE = re.compile(r"^[ABCDEFGHJKLMNPQRTUVWXY3468]{6}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_B64_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")

# Redis Lua is the authority for all state changes. Inputs are JSON data with
# server-verified role identity. Only approved fields are written by Python.
_TRANSITION = r"""
local raw = redis.call('GET', KEYS[1])
if not raw then return cjson.encode({error='expired'}) end
local s = cjson.decode(raw)
local p = cjson.decode(ARGV[2])
local op = ARGV[1]
local function deny(reason) return cjson.encode({error=reason}) end
local function receiver() return p.receiver_hash and p.receiver_hash == s.receiver_token_hash end
local function authorizer() return p.user_id and p.user_id == s.authorizer_user_id and p.binding and p.binding == s.authorizer_binding end
if op == 'approve' then
  if s.status ~= 'waiting' then return deny('conflict') end
  s.authorizer_user_id=p.user_id; s.authorizer_binding=p.binding
  s.authorizer_device_name=p.device_name; s.auto_logout_minutes=p.auto_logout_minutes
  s.status='approved'
elseif op == 'request' then
  if not receiver() then return deny('forbidden') end
  if s.status ~= 'approved' then return deny('conflict') end
  s.receiver_request=p.message; s.status='request'
elseif op == 'response' then
  if not authorizer() then return deny('forbidden') end
  if s.status ~= 'request' then return deny('conflict') end
  s.authorizer_response=p.message; s.status='response'
elseif op == 'finish' then
  if not receiver() then return deny('forbidden') end
  if s.status ~= 'response' then return deny('conflict') end
  s.receiver_finish=p.message; s.status='finish'
elseif op == 'authorize' then
  if not authorizer() then return deny('forbidden') end
  if s.status ~= 'finish' then return deny('conflict') end
  s.encrypted_bundle=p.encrypted_bundle; s.iv=p.iv; s.grant_hash=p.grant_hash
  s.status='ready'
elseif op == 'claim' then
  if not receiver() then return deny('forbidden') end
  if s.status ~= 'ready' then return deny('conflict') end
  if p.grant_hash ~= s.grant_hash then
    s.attempts=(s.attempts or 0)+1
    if s.attempts >= tonumber(ARGV[3]) then s.status='failed' end
    redis.call('SET', KEYS[1], cjson.encode(s), 'KEEPTTL')
    return deny(s.status == 'failed' and 'too_many_attempts' or 'invalid_grant')
  end
  s.status='claimed'; s.encrypted_bundle=nil; s.iv=nil; s.grant_hash=nil
elseif op == 'complete' then
  if s.status ~= 'claimed' then return deny('conflict') end
  s.session_token_hash=p.session_token_hash; s.status='completed'
elseif op == 'fail' then
  if s.status ~= 'claimed' then return deny('conflict') end
  s.status='failed'
elseif op == 'ack_begin' then
  if not receiver() then return deny('forbidden') end
  if s.status ~= 'completed' and s.status ~= 'acknowledging' and s.status ~= 'acknowledged' then return deny('conflict') end
  if s.status ~= 'acknowledged' then s.status='acknowledging' end
elseif op == 'ack_finish' then
  if not receiver() then return deny('forbidden') end
  if s.status ~= 'acknowledging' and s.status ~= 'acknowledged' then return deny('conflict') end
  s.status='acknowledged'
elseif op == 'cancel' then
  if not receiver() and not authorizer() then return deny('forbidden') end
  if s.status == 'acknowledged' or s.status == 'acknowledging' or s.status == 'failed' or s.status == 'cancelled' then return deny('conflict') end
  s.status='cancelled'; s.encrypted_bundle=nil; s.iv=nil; s.grant_hash=nil
else return deny('invalid_operation') end
redis.call('SET', KEYS[1], cjson.encode(s), 'KEEPTTL')
return cjson.encode(s)
"""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Initiate(StrictModel):
    receiver_token_hash: str = Field(min_length=64, max_length=64)
    session_id: str = Field(min_length=1, max_length=128)
    device_hint: str | None = Field(default=None, max_length=80)

    @field_validator("receiver_token_hash")
    @classmethod
    def hash_format(cls, value: str) -> str:
        if not _HASH_RE.fullmatch(value):
            raise ValueError("Expected lowercase SHA-256 hex")
        return value


class Approve(StrictModel):
    authorizer_device_name: str | None = Field(default=None, max_length=80)
    auto_logout_minutes: Literal[30, 60, 240, 480, 1440] | None = None


class Message(StrictModel):
    stage: Literal["request", "response", "finish"]
    message: str = Field(min_length=1, max_length=16384)


class Authorize(StrictModel):
    encrypted_bundle: str = Field(min_length=1, max_length=65536)
    iv: str = Field(min_length=1, max_length=64)
    grant_hash: str = Field(min_length=64, max_length=64)

    @field_validator("grant_hash")
    @classmethod
    def hash_format(cls, value: str) -> str:
        if not _HASH_RE.fullmatch(value):
            raise ValueError("Expected lowercase SHA-256 hex")
        return value


class Complete(StrictModel):
    grant_secret: str = Field(min_length=43, max_length=43)


class StepUp(StrictModel):
    auth_method: Literal["password", "2fa_otp"]
    hashed_email: str | None = Field(default=None, min_length=1, max_length=256)
    lookup_hash: str | None = Field(default=None, min_length=1, max_length=256)
    auth_code: str | None = Field(default=None, min_length=6, max_length=12)


def _key(token: str) -> str:
    token = token.upper()
    if not _TOKEN_RE.fullmatch(token):
        raise HTTPException(404, "Pair token not found")
    return f"pair:v2:{token}"


def _decode_secret(value: str) -> bytes:
    if not _B64_RE.fullmatch(value):
        raise HTTPException(400, "Invalid pairing capability")
    try:
        raw = base64.urlsafe_b64decode(value + "=")
    except Exception as exc:
        raise HTTPException(400, "Invalid pairing capability") from exc
    if len(raw) != 32:
        raise HTTPException(400, "Invalid pairing capability")
    return raw


def _receiver_hash(value: str | None) -> str:
    if not value:
        raise HTTPException(401, "Receiver capability required")
    return hashlib.sha256(_decode_secret(value)).hexdigest()


async def _state(cache: CacheService, token: str) -> dict:
    value = await cache.get(_key(token))
    if not isinstance(value, dict):
        raise HTTPException(404, "Pair token expired")
    return value


async def _change(cache: CacheService, token: str, operation: str, payload: dict) -> dict:
    client = await cache.client
    if client is None:
        raise HTTPException(503, "Pairing temporarily unavailable")
    raw = await client.eval(_TRANSITION, 1, _key(token), operation, json.dumps(payload), MAX_GRANT_ATTEMPTS)
    result = json.loads(raw)
    error = result.get("error")
    if error:
        raise HTTPException({"expired": 404, "forbidden": 403, "invalid_grant": 401,
                             "too_many_attempts": 429}.get(error, 409), error)
    return result


async def _binding(request: Request, cache: CacheService, user: User) -> str:
    token = request.cookies.get("auth_refresh_token")
    if not token:
        raise HTTPException(401, "Session required")
    tokens = await cache.get(f"user_tokens:{user.id}")
    metadata = tokens.get(hashlib.sha256(token.encode()).hexdigest()) if isinstance(tokens, dict) else None
    binding = metadata.get("pair_auth_binding") if isinstance(metadata, dict) else None
    if not isinstance(binding, str) or len(binding) != 64:
        raise HTTPException(401, "Current session verification required")
    return binding


def _proof_key(binding: str) -> str:
    return f"pair:stepup:{binding}"


async def _require_stepup(cache: CacheService, binding: str) -> None:
    if await cache.get(_proof_key(binding)) != "verified":
        raise HTTPException(401, "Recent authentication required")


@router.post("/initiate")
@limiter.limit("10/hour")
async def initiate(request: Request, body: Initiate, cache: CacheService = Depends(get_cache_service)):
    client = await cache.client
    if client is None:
        raise HTTPException(503, "Pairing temporarily unavailable")
    ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
    geo = get_geo_data_from_ip(ip)
    for _ in range(5):
        token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(6))
        state = {"status": "waiting", "protocol_version": 2, "receiver_token_hash": body.receiver_token_hash,
                 "session_id": body.session_id, "device_name": body.device_hint or derive_device_name(request.headers.get("user-agent", "")),
                 "ip_truncated": truncate_ip(ip), "country_code": geo.get("country_code"), "city": geo.get("city"),
                 "created_at": int(time.time()), "expires_at": int(time.time()) + PAIR_TTL, "attempts": 0}
        if await client.set(_key(token), json.dumps(state), nx=True, ex=PAIR_TTL):
            return {"protocol_version": 2, "token": token, "expires_at": state["expires_at"]}
    raise HTTPException(503, "Pair token allocation unavailable")


@router.get("/info/{token}")
@limiter.limit("30/minute")
async def info(request: Request, token: str, user: User = Depends(get_current_user), cache: CacheService = Depends(get_cache_service)):
    state = await _state(cache, token)
    if state["status"] != "waiting":
        raise HTTPException(409, "Pair token unavailable")
    return {key: state.get(key) for key in ("protocol_version", "session_id", "receiver_token_hash", "device_name", "ip_truncated", "country_code", "city", "created_at", "expires_at")}


@router.get("/account-check")
@limiter.limit("20/minute")
async def account_check(request: Request, user: User = Depends(get_current_user),
                        directus: DirectusService = Depends(get_directus_service)):
    """Give an approver server-bound public/encrypted account metadata for local key matching."""
    fields = await directus.get_user_fields_direct(user.id, [
        "hashed_email", "encrypted_email_with_master_key", "user_email_salt",
    ])
    if not isinstance(fields, dict) or any(not fields.get(field) for field in (
        "hashed_email", "user_email_salt",
    )):
        raise HTTPException(503, "Pair account verification unavailable")
    # Older password accounts have no server-stored master-key email envelope.
    # The approver can use its own locally encrypted copy, but must compare its
    # decrypted email against this server-bound hash before exporting the key.
    return {"user_id": user.id, "hashed_email": fields["hashed_email"],
            "encrypted_email_with_master_key": fields.get("encrypted_email_with_master_key"),
            "user_email_salt": fields["user_email_salt"]}


@router.post("/step-up")
@limiter.limit("5/minute")
async def step_up(request: Request, body: StepUp, user: User = Depends(get_current_user),
                  cache: CacheService = Depends(get_cache_service), directus: DirectusService = Depends(get_directus_service),
                  encryption: EncryptionService = Depends(get_encryption_service)):
    binding = await _binding(request, cache, user)
    if body.auth_method == "password":
        if not body.hashed_email or not body.lookup_hash:
            raise HTTPException(400, "Password proof required")
        fields = await directus.get_user_fields_direct(user.id, ["hashed_email", "lookup_hashes", "credential_lookup_hashes"])
        hashes = fields.get("lookup_hashes") if fields else None
        if isinstance(hashes, str):
            try:
                hashes = json.loads(hashes)
            except ValueError:
                hashes = []
        typed = fields.get("credential_lookup_hashes") if fields else None
        if isinstance(typed, str):
            try:
                typed = json.loads(typed)
            except ValueError:
                typed = False
        typed_method = typed_lookup_method(typed, body.lookup_hash)
        # An account may have a typed passkey or recovery lookup while its
        # accepted password remains untyped. Allow that legacy secret only
        # with the enrolled TOTP proof below. A bound non-password hash (or
        # an ambiguous duplicate binding) must never be treated as password.
        bound_elsewhere = isinstance(typed, Mapping) and any(
            value == body.lookup_hash if isinstance(value, str)
            else isinstance(value, Mapping) and value.get("lookup_hash") == body.lookup_hash
            for value in typed.values()
        )
        password_proof = typed_method == "password" or (
            (typed is None or isinstance(typed, Mapping) and "password" not in typed)
            and not bound_elsewhere
        )
        if (not fields or fields.get("hashed_email") != body.hashed_email
                or body.lookup_hash not in (hashes or [])
                or not password_proof):
            raise HTTPException(401, "Invalid authentication proof")
        enrolled = await directus.get_user_fields_direct(user.id, ["encrypted_tfa_secret"])
        if enrolled is None:
            raise HTTPException(503, "Authentication verification unavailable")
        if not enrolled.get("encrypted_tfa_secret"):
            # Lookup hashes contain password and recovery entries with no
            # server-side type binding, so a bare hash cannot prove password.
            raise HTTPException(401, "Verified second factor required")
        if not body.auth_code:
            raise HTTPException(401, "TOTP proof required")
    if body.auth_method == "2fa_otp" or body.auth_code:
        if not body.auth_code:
            raise HTTPException(400, "TOTP proof required")
        fields = await directus.get_user_fields_direct(user.id, ["encrypted_tfa_secret", "vault_key_id"])
        if not fields or not fields.get("encrypted_tfa_secret") or not fields.get("vault_key_id"):
            raise HTTPException(401, "Invalid authentication proof")
        try:
            secret = await encryption.decrypt_with_user_key(fields["encrypted_tfa_secret"], fields["vault_key_id"])
            valid = bool(secret and await claim_totp_step(cache, user.id, secret, body.auth_code))
        except Exception:
            valid = False
        if not valid:
            raise HTTPException(401, "Invalid authentication proof")
    await mark_recent_strong_proof(directus, cache, request.cookies["auth_refresh_token"], user.id, method="totp")
    if not await cache.set(_proof_key(binding), "verified", ttl=300):
        raise HTTPException(503, "Authentication proof unavailable")
    return {"success": True, "expires_in": 300}


@router.post("/approve/{token}")
@limiter.limit("10/hour")
async def approve(request: Request, token: str, body: Approve, user: User = Depends(get_current_user), cache: CacheService = Depends(get_cache_service), directus: DirectusService = Depends(get_directus_service)):
    binding = await _binding(request, cache, user)
    await require_recent_strong_proof(directus, cache, request.cookies["auth_refresh_token"], user.id)
    state = await _change(cache, token, "approve", {"user_id": user.id, "binding": binding,
        "device_name": body.authorizer_device_name or derive_device_name(request.headers.get("user-agent", "")),
        "auto_logout_minutes": body.auto_logout_minutes})
    return {"success": True, "protocol_version": 2, "token": token.upper(), "session_id": state["session_id"],
            "receiver_token_hash": state["receiver_token_hash"], "authorizer_user_id": user.id,
            "auto_logout_minutes": body.auto_logout_minutes, "expires_at": state["expires_at"]}


@router.get("/receiver/{token}")
@limiter.limit("60/minute")
async def receiver_poll(request: Request, token: str, receiver: str | None = Header(default=None, alias="X-OpenMates-Pair-Receiver"), cache: CacheService = Depends(get_cache_service), directus: DirectusService = Depends(get_directus_service)):
    state = await _state(cache, token)
    if not secrets.compare_digest(_receiver_hash(receiver), state["receiver_token_hash"]):
        raise HTTPException(403, "Receiver capability mismatch")
    status = state["status"]
    if status == "acknowledged" and not await is_pair_session_confirmed(directus, state["session_token_hash"], state["authorizer_user_id"]):
        status = "acknowledging"
    result = {"status": status, "expires_at": state["expires_at"]}
    if state["status"] in ("approved", "request", "response", "finish", "ready", "claimed", "completed", "acknowledged"):
        result.update({"authorizer_user_id": state["authorizer_user_id"], "authorizer_device_name": state["authorizer_device_name"],
                       "auto_logout_minutes": state.get("auto_logout_minutes"), "session_id": state["session_id"],
                       "receiver_token_hash": state["receiver_token_hash"]})
    if state["status"] == "response":
        result["message"] = state["authorizer_response"]
    if state["status"] == "ready":
        result["encrypted_bundle"] = state["encrypted_bundle"]
        result["iv"] = state["iv"]
    return result


@router.get("/authorizer/{token}")
@limiter.limit("60/minute")
async def authorizer_poll(request: Request, token: str, user: User = Depends(get_current_user), cache: CacheService = Depends(get_cache_service), directus: DirectusService = Depends(get_directus_service)):
    binding = await _binding(request, cache, user)
    state = await _state(cache, token)
    if state.get("authorizer_user_id") != user.id or state.get("authorizer_binding") != binding:
        raise HTTPException(403, "Not the approving session")
    status = state["status"]
    if status == "acknowledged" and not await is_pair_session_confirmed(directus, state["session_token_hash"], state["authorizer_user_id"]):
        status = "acknowledging"
    result = {"status": status, "expires_at": state["expires_at"]}
    if state["status"] in ("request", "response", "finish", "ready"):
        result["receiver_request"] = state.get("receiver_request")
    if state["status"] in ("finish", "ready"):
        result["receiver_finish"] = state.get("receiver_finish")
    return result


@router.post("/receiver/{token}/message")
@limiter.limit("30/minute")
async def receiver_message(request: Request, token: str, body: Message, receiver: str | None = Header(default=None, alias="X-OpenMates-Pair-Receiver"), cache: CacheService = Depends(get_cache_service)):
    if body.stage not in ("request", "finish"):
        raise HTTPException(400, "Invalid receiver stage")
    await _change(cache, token, body.stage, {"receiver_hash": _receiver_hash(receiver), "message": body.message})
    return {"success": True}


@router.post("/authorizer/{token}/message")
@limiter.limit("30/minute")
async def authorizer_message(request: Request, token: str, body: Message, user: User = Depends(get_current_user), cache: CacheService = Depends(get_cache_service)):
    if body.stage != "response":
        raise HTTPException(400, "Invalid authorizer stage")
    await _change(cache, token, "response", {"user_id": user.id, "binding": await _binding(request, cache, user), "message": body.message})
    return {"success": True}


@router.post("/authorize/{token}")
@limiter.limit("10/hour")
async def authorize(request: Request, token: str, body: Authorize, user: User = Depends(get_current_user), cache: CacheService = Depends(get_cache_service)):
    await _change(cache, token, "authorize", {"user_id": user.id, "binding": await _binding(request, cache, user),
        "encrypted_bundle": body.encrypted_bundle, "iv": body.iv, "grant_hash": body.grant_hash})
    return {"success": True}


@router.post("/complete/{token}", response_model=LoginResponse)
@limiter.limit("10/minute")
async def complete(request: Request, response: Response, token: str, body: Complete,
                   receiver: str | None = Header(default=None, alias="X-OpenMates-Pair-Receiver"),
                   cache: CacheService = Depends(get_cache_service), directus: DirectusService = Depends(get_directus_service),
                   compliance: ComplianceService = Depends(get_compliance_service), encryption: EncryptionService = Depends(get_encryption_service)):
    grant_hash = hashlib.sha256(_decode_secret(body.grant_secret)).hexdigest()
    state = await _change(cache, token, "claim", {"receiver_hash": _receiver_hash(receiver), "grant_hash": grant_hash})
    issued_token = None
    try:
        user_id = state["authorizer_user_id"]
        auth_ok, auth_data, _ = await directus.create_trusted_user_session(user_id)
        if not auth_ok or not auth_data or auth_data.get("user", {}).get("id") != user_id:
            raise RuntimeError("Trusted session mint failed")
        user = auth_data["user"]
        profile_ok, profile, _ = await directus.get_user_profile(user_id)
        if not profile_ok or not profile:
            raise RuntimeError("Pair profile unavailable")
        user.update(profile)
        session_id = state["session_id"]
        device_hash, connection_hash, _, country, city, _, latitude, longitude = generate_device_fingerprint_hash(request, user_id, session_id)
        ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
        minutes = state.get("auto_logout_minutes")
        deadline = int(time.time()) + minutes * 60 if minutes is not None else None
        login_data = PairingSessionContext(session_id=session_id)
        issued_token = await finalize_login_session(request, response, user, auth_data, cache, compliance, directus,
            device_hash, connection_hash, ip, encryption, f"{city}, {country}" if city and country else country or "Unknown",
            latitude, longitude, login_data, country)
        if not issued_token:
            raise RuntimeError("Pair session cookie unavailable")
        await register_pair_session(directus, cache, issued_token, user_id, deadline)
        if deadline is not None:
            # A paired cookie must not outlive the selected absolute deadline.
            from backend.core.api.app.routes.auth_routes.auth_utils import get_cookie_domain
            cookie = {"key": "auth_refresh_token", "value": issued_token, "httponly": True, "secure": True,
                      "samesite": "lax", "max_age": max(1, deadline - int(time.time())), "path": "/"}
            domain = get_cookie_domain(request)
            if domain:
                cookie["domain"] = domain
            response.set_cookie(**cookie)
        result_user = UserResponse(
            id=user_id, account_id=user.get("account_id"), username=user["username"],
            is_admin=bool(user.get("is_admin")), credits=int(user.get("credits") or 0),
            profile_image_url=user.get("profile_image_url"), last_opened=user.get("last_opened"),
            tfa_app_name=user.get("tfa_app_name"), tfa_enabled=bool(user.get("tfa_enabled")),
            language=user.get("language", "en"), darkmode=bool(user.get("darkmode")),
            user_email_salt=user.get("user_email_salt"),
        )
        result = LoginResponse(success=True, message="Login successful", user=result_user,
            ws_token=create_ws_token(issued_token) if issued_token else None, pair_expires_at=deadline)
        await _change(cache, token, "complete", {"session_token_hash": hashlib.sha256(issued_token.encode()).hexdigest()})
        return result
    except Exception:
        if issued_token:
            await directus.logout_user(issued_token)
        await _change(cache, token, "fail", {})
        raise HTTPException(503, "Pair completion failed; start a new pairing")


@router.post("/acknowledge/{token}")
@limiter.limit("10/minute")
async def acknowledge(request: Request, token: str, receiver: str | None = Header(default=None, alias="X-OpenMates-Pair-Receiver"),
                      cache: CacheService = Depends(get_cache_service), directus: DirectusService = Depends(get_directus_service)):
    receiver_hash = _receiver_hash(receiver)
    state = await _change(cache, token, "ack_begin", {"receiver_hash": receiver_hash})
    await activate_pair_session(directus, cache, state["session_token_hash"], state["authorizer_user_id"])
    await _change(cache, token, "ack_finish", {"receiver_hash": receiver_hash})
    await confirm_pair_session(directus, cache, state["session_token_hash"], state["authorizer_user_id"])
    return {"success": True}


@router.delete("/{token}")
@limiter.limit("10/minute")
async def cancel(request: Request, token: str, receiver: str | None = Header(default=None, alias="X-OpenMates-Pair-Receiver"),
                 cache: CacheService = Depends(get_cache_service), user: User | None = Depends(get_current_user_optional)):
    if not receiver and not user:
        raise HTTPException(401, "Pairing role required")
    payload = {"receiver_hash": _receiver_hash(receiver)} if receiver else {"user_id": user.id, "binding": await _binding(request, cache, user)}
    await _change(cache, token, "cancel", payload)
    return {"success": True}
