"""Chat sync feed routes (architecture.sync@2).

API surface classification:
- GET /v1/chats/changes: first-party client surface only. Session-cookie
  authentication (get_current_user, never API keys), owner/Team scoped with a
  live Team role check, rate limited, no credits. Caddy routes /v1/chats/* to
  FastAPI, which enforces session auth; developer API keys cannot reach it.
  Returns encrypted metadata only, never messages, embeds or plaintext.
- POST /internal/chat-sync/changed: internal-only (shared service token) hints
  from the chat-sync Directus extension; content-free scope/revision pairs.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.chat_sync_feed_service import (
    DEFAULT_LIMIT, MAX_CURSOR_LENGTH, MAX_LIMIT, ChatSyncFeedError, validate_request,
)
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.internal_auth import VerifiedInternalRequest

router = APIRouter(prefix="/v1", tags=["Chats"])
internal_router = APIRouter(prefix="/internal", tags=["Internal Services"], dependencies=[VerifiedInternalRequest])

_STATUS = {"team_access_revoked": 403, "invalid_team": 400, "invalid_cursor": 400, "invalid_limit": 400}
_HINT_SCOPE = re.compile(r"(?:personal|team|user):[0-9a-f]{64}")


def _feed(request: Request):
    service = getattr(request.app.state, "chat_sync_feed", None)
    if service is None:
        raise HTTPException(status_code=503, detail="chat_sync_unavailable")
    return service


@router.get("/chats/changes")
@limiter.limit("120/minute")
async def get_chat_changes(
    request: Request,
    cursor: str | None = Query(default=None, max_length=MAX_CURSOR_LENGTH),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    team_id: str | None = Query(default=None, max_length=128),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """One page of the caller's chat change feed after `cursor` (null cursor => reset)."""
    service = _feed(request)
    try:
        team, parsed_cursor, parsed_limit = validate_request({"team_id": team_id, "cursor": cursor, "limit": limit})
        page = await service.read_page(current_user.id, team, parsed_cursor, parsed_limit)
    except ChatSyncFeedError as exc:
        raise HTTPException(status_code=_STATUS.get(exc.code, 503), detail=exc.code) from exc
    return {**page, "team_id": team}


class ChatSyncHint(BaseModel):
    scope: str = Field(max_length=80)
    revision: str = Field(pattern=r"^\d{1,19}$")


class ChatSyncHints(BaseModel):
    hints: list[ChatSyncHint] = Field(min_length=1, max_length=500)


@internal_router.post("/chat-sync/changed")
async def chat_sync_changed(body: ChatSyncHints, request: Request) -> dict[str, bool]:
    """Coalesced commit hints from the chat-sync Directus listener; no content."""
    if any(not _HINT_SCOPE.fullmatch(hint.scope) for hint in body.hints):
        raise HTTPException(status_code=400, detail="invalid_chat_sync_scope")
    try:
        await _feed(request).publish_hints([{"scope": h.scope, "revision": int(h.revision)} for h in body.hints])
    except ChatSyncFeedError as exc:
        raise HTTPException(status_code=503, detail="chat_sync_hint_deferred") from exc
    return {"accepted": True}
