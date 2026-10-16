"""First-party account key enrollment and client-encrypted Team direct chats.

The server stores public keys and opaque client-encrypted private backups.
Direct chats contain exactly two active Team participants and separate key
envelopes; each response exposes only the requesting participant's envelope.
The route never receives or decrypts raw chat or account private keys.
"""

import logging
import re
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.direct_chat_access import require_direct_chat_access
from backend.core.api.app.services.direct_chat_key_service import (
    KeyConflictError, KeyStoreError, get_account_key, get_account_key_by_hash,
    own_projection, public_projection, register_account_key,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.core.api.app.services.feature_availability_guards import ensure_teams_enabled
from backend.core.api.app.services.limiter import limiter

router = APIRouter(prefix="/v1", tags=["Team direct chats"], dependencies=[Depends(ensure_teams_enabled)])
logger = logging.getLogger(__name__)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
TEAM_ROLES = {"owner", "admin", "member", "viewer"}


class AccountChatKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_key: str = Field(min_length=43, max_length=43)
    encrypted_private_key: str = Field(min_length=1, max_length=8192)
    algorithm: str = Field(pattern=r"^x25519-xsalsa20poly1305$")
    version: int = Field(ge=1, le=1)


class ParticipantKeyEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    encrypted_chat_key: str = Field(min_length=22, max_length=2048, pattern=r"^OMDM1\.[A-Za-z0-9_-]{16,}$")


class DirectChatCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_id: UUID
    recipient_user_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    participant_key_envelopes: dict[str, ParticipantKeyEnvelope] = Field(min_length=2, max_length=2)
    encrypted_title: str | None = Field(default=None, min_length=1, max_length=4096)


async def _first_party_user(request: Request, response: Response) -> User:
    user = await get_current_user_or_api_key(
        request=request, response=response,
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=request.cookies.get("auth_refresh_token"),
    )
    auth = getattr(request.state, "auth_info", {}) or {}
    if auth.get("auth_source") != "session" and not (
        auth.get("auth_source") == "api_key" and auth.get("device_hash")
    ):
        raise HTTPException(status_code=403, detail="FIRST_PARTY_DEVICE_REQUIRED")
    return user


@router.get("/account/chat-encryption-key")
@limiter.limit("60/minute")
async def get_own_chat_encryption_key(request: Request, response: Response,
                                      user: User = Depends(_first_party_user)) -> dict[str, Any]:
    row = await get_account_key(request.app.state.directus_service, user.id)
    return {"key": own_projection(row) if row else None}


@router.put("/account/chat-encryption-key")
@limiter.limit("10/minute")
async def put_own_chat_encryption_key(body: AccountChatKeyRequest, request: Request, response: Response,
                                      user: User = Depends(_first_party_user)) -> dict[str, Any]:
    try:
        key = await register_account_key(
            request.app.state.directus_service, user.id,
            key_id=body.key_id, public_key=body.public_key,
            encrypted_private_key=body.encrypted_private_key,
        )
        return {"key": key}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _require_member(directus: Any, team_id: str, user_id: str) -> None:
    try:
        await directus.team.require_team_role(team_id, user_id, TEAM_ROLES)
    except TeamPermissionError as exc:
        raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc


async def _recipient_membership(directus: Any, team_id: str, member_hash: str) -> dict[str, Any]:
    if not HASH_RE.fullmatch(member_hash):
        raise HTTPException(status_code=404, detail="TEAM_MEMBER_NOT_FOUND")
    rows = await directus.get_items(
        "team_memberships",
        params={"filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[hashed_user_id][_eq]": member_hash,
                "filter[status][_eq]": "active", "fields": "user_id,hashed_user_id", "limit": 1},
        no_cache=True, admin_required=True,
    )
    if not isinstance(rows, list):
        raise HTTPException(status_code=503, detail="TEAM_MEMBERSHIP_UNAVAILABLE")
    if not rows:
        raise HTTPException(status_code=404, detail="TEAM_MEMBER_NOT_FOUND")
    return rows[0]


async def _recipient_user_id(directus: Any, team_id: str, member: dict[str, Any]) -> str | None:
    member_hash = member["hashed_user_id"]
    user_id = member.get("user_id")
    if isinstance(user_id, str) and hash_id(user_id) == member_hash:
        return user_id
    user_id = await directus.get_user_id_from_hashed_user_id(member_hash)
    if isinstance(user_id, str) and hash_id(user_id) == member_hash:
        return user_id
    # Legacy password-only memberships can lack user_id. Reuse the bounded
    # identity resolution already used by Team notification fanout.
    from backend.core.api.app.services.team_chat_notification_service import active_team_recipient_ids
    for user_id in await active_team_recipient_ids(directus, team_id, "", exclude_sender=False):
        if hash_id(user_id) == member_hash:
            return user_id
    return None


@router.get("/teams/{team_id}/members/{member_hash}/chat-encryption-key")
@limiter.limit("60/minute")
async def get_member_chat_encryption_key(team_id: str, member_hash: str, request: Request,
                                         response: Response, user: User = Depends(_first_party_user)) -> dict[str, str]:
    directus = request.app.state.directus_service
    await _require_member(directus, team_id, user.id)
    await _recipient_membership(directus, team_id, member_hash)
    key = await get_account_key_by_hash(directus, member_hash)
    if not key:
        raise HTTPException(status_code=404, detail="CHAT_ENCRYPTION_KEY_PENDING")
    return public_projection(key)


async def _chat_by_id(directus: Any, chat_id: str) -> dict[str, Any] | None:
    rows = await directus.get_items("chats", params={"filter[id][_eq]": chat_id, "limit": 1},
                                   no_cache=True, admin_required=True)
    if not isinstance(rows, list):
        raise HTTPException(status_code=503, detail="DIRECT_CHAT_UNAVAILABLE")
    return rows[0] if rows else None


def _same_creation(row: dict[str, Any], candidate: dict[str, Any]) -> bool:
    from backend.core.api.app.services.direct_chat_access import validate_direct_chat_metadata
    try:
        members, envelopes = validate_direct_chat_metadata(row)
    except ValueError:
        return False
    return (row.get("hashed_team_id") == candidate["hashed_team_id"]
            and set(members) == set(candidate["participant_user_hashes"])
            and envelopes == candidate["participant_key_envelopes"]
            and row.get("encrypted_title") == candidate.get("encrypted_title"))


@router.post("/teams/{team_id}/direct-chats")
@limiter.limit("20/minute")
async def create_direct_chat(team_id: str, body: DirectChatCreateRequest, request: Request,
                             response: Response, user: User = Depends(_first_party_user)) -> dict[str, Any]:
    directus = request.app.state.directus_service
    await _require_member(directus, team_id, user.id)
    own_hash = hash_id(user.id)
    recipient_hash = body.recipient_user_hash
    if recipient_hash == own_hash:
        raise HTTPException(status_code=400, detail="DIRECT_CHAT_REQUIRES_TWO_MEMBERS")
    envelopes = {member_hash: item.model_dump() for member_hash, item in body.participant_key_envelopes.items()}
    if set(envelopes) != {own_hash, recipient_hash}:
        raise HTTPException(status_code=400, detail="DIRECT_CHAT_ENVELOPES_INVALID")
    recipient = await _recipient_membership(directus, team_id, recipient_hash)
    recipient_id = await _recipient_user_id(directus, team_id, recipient)
    if not recipient_id:
        raise HTTPException(status_code=409, detail="TEAM_MEMBER_IDENTITY_PENDING")
    own_key = await get_account_key(directus, user.id)
    recipient_key = await get_account_key_by_hash(directus, recipient_hash)
    if not own_key or not recipient_key:
        raise HTTPException(status_code=409, detail="CHAT_ENCRYPTION_KEY_PENDING")
    if envelopes[own_hash]["key_id"] != own_key["key_id"] or envelopes[recipient_hash]["key_id"] != recipient_key["key_id"]:
        raise HTTPException(status_code=409, detail="CHAT_ENCRYPTION_KEY_CHANGED")
    chat_id = str(body.chat_id)
    candidate = {
        "id": chat_id, "hashed_user_id": own_hash, "hashed_team_id": hash_id(team_id),
        "chat_visibility": "direct", "participant_user_hashes": [own_hash, recipient_hash],
        "participant_key_envelopes": envelopes, "encrypted_chat_key": None,
        "encrypted_title": body.encrypted_title, "created_at": int(time.time()),
        "updated_at": int(time.time()), "messages_v": 0, "title_v": 0, "metadata_v": 0,
        "last_edited_overall_timestamp": int(time.time()),
    }
    existing = await _chat_by_id(directus, chat_id)
    created = False
    if existing is None:
        created, _ = await directus.create_item("chats", candidate, admin_required=True,
                                                expected_unique_conflict_field="id")
        existing = await _chat_by_id(directus, chat_id)
        if not existing:
            raise HTTPException(status_code=503, detail="DIRECT_CHAT_UNAVAILABLE")
    if not _same_creation(existing, candidate):
        raise HTTPException(status_code=409, detail="DIRECT_CHAT_ID_CONFLICT")
    try:
        projected = await require_direct_chat_access(directus, existing, user.id, team_id)
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="DIRECT_CHAT_ACCESS_DENIED") from exc
    projected["team_id"] = team_id
    if created:
        try:
            recipient_projected = await require_direct_chat_access(directus, existing, recipient_id, team_id)
            recipient_projected["team_id"] = team_id
            await _notify_recipient(request, recipient_id, team_id, chat_id, recipient_projected)
        except (PermissionError, ValueError) as exc:
            logger.warning("Direct chat recipient notification access check failed (%s)", type(exc).__name__)
    return {"chat": projected}


async def _notify_recipient(request: Request, recipient_id: str, team_id: str, chat_id: str,
                            recipient_chat: dict[str, Any]) -> None:
    """Best-effort content-free in-app delivery after the insert commits."""
    from backend.core.api.app.services.direct_chat_notification_service import notify_new_direct_chat
    try:
        await notify_new_direct_chat(
            request.app, recipient_id=recipient_id, team_id=team_id, chat_id=chat_id,
            recipient_chat=recipient_chat,
        )
    except Exception as exc:
        # Chat creation is committed; notification delivery is secondary.
        logger.warning("Direct chat notification dispatch failed (%s)", type(exc).__name__)
