"""Signed, request-bound admission for ephemeral AI outputs.

Incognito and authenticated stateless REST requests have no durable chat
preflight. Their authority crosses Celery as a short-lived internal signature;
it does not create a recovery record or authorize persistent chat output.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


MAIN_HEADER = "openmates_volatile_ai"
EMBED_HEADER = "openmates_volatile_embed"
VERSION = 1
MAX_AGE_SECONDS = 7200


@dataclass(frozen=True)
class AuthenticatedVolatileAI:
    owner_id: str
    owner_hash: str
    mode: str
    chat_id: str | None = None
    message_id: str | None = None
    session_nonce: str | None = None
    hashed_team_id: str | None = None


@dataclass(frozen=True)
class VolatileAIContext:
    owner_id: str
    owner_hash: str
    mode: str
    chat_id: str
    message_id: str
    main_task_id: str
    expires_at: int
    session_nonce: str | None = None
    hashed_team_id: str | None = None


active_authenticated_volatile_ai: ContextVar[AuthenticatedVolatileAI | None] = ContextVar(
    "active_authenticated_volatile_ai", default=None,
)
active_volatile_ai_context: ContextVar[VolatileAIContext | None] = ContextVar(
    "active_volatile_ai_context", default=None,
)


def _key() -> bytes:
    value = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not value or len(value) < 16:
        raise ValueError("internal_volatile_signing_key_unavailable")
    return value.encode("utf-8")


def _signature(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(_key(), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _wrap(payload: dict[str, Any]) -> dict[str, Any]:
    return {"payload": payload, "signature": _signature(payload)}


def _open(header: Any, *, kind: str, now: int | None = None) -> dict[str, Any]:
    if not isinstance(header, dict) or not isinstance(header.get("payload"), dict):
        raise ValueError("volatile_authority_missing")
    payload = header["payload"]
    if payload.get("version") != VERSION or payload.get("kind") != kind:
        raise ValueError("volatile_authority_version_invalid")
    signature = header.get("signature")
    if not isinstance(signature, str) or not hmac.compare_digest(signature, _signature(payload)):
        raise ValueError("volatile_authority_signature_invalid")
    current = int(time.time()) if now is None else now
    expires_at = payload.get("expires_at")
    if (type(expires_at) is not int or expires_at <= current
            or expires_at > current + MAX_AGE_SECONDS):
        raise ValueError("volatile_authority_expired")
    return payload


def make_main_header(
    principal: AuthenticatedVolatileAI, *, owner_id: str, owner_hash: str,
    chat_id: str, message_id: str, main_task_id: str,
    hashed_team_id: str | None = None,
    expires_at: int | None = None,
) -> dict[str, Any]:
    if (principal.owner_id != owner_id or principal.owner_hash != owner_hash
            or owner_hash != hashlib.sha256(owner_id.encode()).hexdigest()
            or principal.mode not in {"incognito", "external"}
            or principal.chat_id not in {None, chat_id}
            or principal.message_id not in {None, message_id}
            or principal.hashed_team_id != hashed_team_id
            or (principal.hashed_team_id is not None
                and (len(principal.hashed_team_id) != 64
                     or any(c not in "0123456789abcdef" for c in principal.hashed_team_id)))
            or (principal.mode == "incognito" and not principal.session_nonce)
            or (principal.mode == "external" and principal.session_nonce is not None)
            or not all((chat_id, message_id, main_task_id))):
        raise ValueError("volatile_request_identity_mismatch")
    return _wrap({
        "version": VERSION, "kind": "main", "mode": principal.mode,
        "owner_id": owner_id, "owner_hash": owner_hash,
        "chat_id": chat_id, "message_id": message_id,
        "main_task_id": main_task_id,
        "session_nonce": principal.session_nonce,
        "hashed_team_id": principal.hashed_team_id,
        "expires_at": expires_at or int(time.time()) + MAX_AGE_SECONDS,
    })


def verify_main_header(
    header: Any, *, owner_id: str, owner_hash: str,
    chat_id: str, message_id: str, main_task_id: str,
    hashed_team_id: str | None = None, now: int | None = None,
) -> VolatileAIContext:
    payload = _open(header, kind="main", now=now)
    if (payload.get("owner_id") != owner_id
            or payload.get("owner_hash") != owner_hash
            or owner_hash != hashlib.sha256(owner_id.encode()).hexdigest()
            or payload.get("chat_id") != chat_id or payload.get("message_id") != message_id
            or payload.get("main_task_id") != main_task_id
            or payload.get("hashed_team_id") != hashed_team_id
            or payload.get("mode") not in {"incognito", "external"}):
        raise ValueError("volatile_main_identity_mismatch")
    if (payload["mode"] == "incognito" and
            (not isinstance(payload.get("session_nonce"), str)
             or len(payload["session_nonce"]) < 32)):
        raise ValueError("incognito_live_session_missing")
    if payload["mode"] == "external" and payload.get("session_nonce") is not None:
        raise ValueError("external_session_scope_invalid")
    return VolatileAIContext(
        owner_id, owner_hash, payload["mode"], chat_id, message_id,
        main_task_id, payload["expires_at"], payload.get("session_nonce"),
        payload.get("hashed_team_id"),
    )


def make_embed_header(
    context: VolatileAIContext, *, task_uuid: str, task_name: str,
    kwargs_binding: str, owner_id: str, chat_id: str, message_id: str,
    embed_id: str,
) -> dict[str, Any]:
    if (context.owner_id != owner_id or context.chat_id != chat_id
            or context.message_id != message_id or not embed_id
            or context.expires_at <= int(time.time())):
        raise ValueError("volatile_embed_identity_mismatch")
    return _wrap({
        "version": VERSION, "kind": "embed", "mode": context.mode,
        "owner_id": owner_id, "owner_hash": context.owner_hash,
        "chat_id": chat_id, "message_id": message_id,
        "main_task_id": context.main_task_id, "task_uuid": task_uuid,
        "task_name": task_name, "kwargs_binding": kwargs_binding,
        "embed_id": embed_id, "expires_at": context.expires_at,
        "session_nonce": context.session_nonce,
        "hashed_team_id": context.hashed_team_id,
    })


def verify_embed_header(
    header: Any, *, task_uuid: str, task_name: str, kwargs_binding: str,
    owner_id: str, chat_id: str, message_id: str, embed_id: str,
    now: int | None = None,
) -> dict[str, Any]:
    payload = _open(header, kind="embed", now=now)
    expected = {
        "task_uuid": task_uuid, "task_name": task_name,
        "kwargs_binding": kwargs_binding, "owner_id": owner_id,
        "owner_hash": hashlib.sha256(owner_id.encode()).hexdigest(),
        "chat_id": chat_id, "message_id": message_id, "embed_id": embed_id,
    }
    if (any(payload.get(key) != value for key, value in expected.items())
            or payload.get("mode") not in {"incognito", "external"}
            or not isinstance(payload.get("main_task_id"), str)
            or not payload["main_task_id"]):
        raise ValueError("volatile_embed_identity_mismatch")
    if payload["mode"] == "incognito":
        if (not isinstance(payload.get("session_nonce"), str)
                or len(payload["session_nonce"]) < 32):
            raise ValueError("incognito_live_session_missing")
    elif payload.get("session_nonce") is not None:
        raise ValueError("external_session_scope_invalid")
    team_hash = payload.get("hashed_team_id")
    if team_hash is not None and (
        not isinstance(team_hash, str) or len(team_hash) != 64
        or any(c not in "0123456789abcdef" for c in team_hash)
    ):
        raise ValueError("volatile_team_scope_invalid")
    return payload


async def require_live_incognito_session(nonce: str, owner_hash: str) -> None:
    """Require a current authenticated socket lease before dependent work."""
    from backend.core.api.app.services.cache import CacheService

    cache = CacheService()
    try:
        client = await cache.client
        if client is None:
            raise ValueError("incognito_session_store_unavailable")
        value = await client.get(f"volatile_ai_live:v1:{nonce}")
        if isinstance(value, bytes):
            value = value.decode("ascii", errors="strict")
        if not isinstance(value, str) or not hmac.compare_digest(value, owner_hash):
            raise ValueError("incognito_session_closed")
    finally:
        await cache.close()
