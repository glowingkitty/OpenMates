"""Scoped bearer authentication for private control-plane clients.

Only SHA-256 token digests are configured in the service. Plaintext tokens stay
with their engineering client, identities carry explicit scopes, and rotation
is supported by temporarily configuring multiple independently named digests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from fastapi import Header, HTTPException

from backend.engineering_control_plane.config import Settings


VALID_SCOPES = frozenset({"read", "ingest", "coordinate", "admin"})


@dataclass(frozen=True, slots=True)
class Identity:
    identity_key: str
    scopes: frozenset[str]


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate_token(authorization: str | None, identities_json: str) -> Identity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_control_plane_identity")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="invalid_control_plane_identity")
    try:
        configured = json.loads(identities_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ENGINEERING_CONTROL_PLANE_IDENTITIES_JSON is invalid") from exc
    if not isinstance(configured, dict):
        raise RuntimeError("ENGINEERING_CONTROL_PLANE_IDENTITIES_JSON must be an object")
    presented_digest = token_digest(token)
    for identity_key, record in configured.items():
        if not isinstance(record, dict):
            continue
        expected_digest = str(record.get("token_sha256") or "")
        if expected_digest and hmac.compare_digest(expected_digest, presented_digest):
            scopes = frozenset(str(scope) for scope in record.get("scopes") or [])
            if not scopes <= VALID_SCOPES:
                raise RuntimeError(f"invalid scopes configured for identity {identity_key}")
            return Identity(str(identity_key), scopes)
    raise HTTPException(status_code=401, detail="invalid_control_plane_identity")


def request_identity(authorization: str | None = Header(default=None)) -> Identity:
    return authenticate_token(authorization, Settings.from_environment().identities_json)


def require_scope(identity: Identity, scope: str) -> None:
    if scope not in identity.scopes and "admin" not in identity.scopes:
        raise HTTPException(status_code=403, detail=f"control_plane_scope_required:{scope}")

