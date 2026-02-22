# backend/core/api/app/routes/daily_inspirations_api.py
#
# Authenticated REST endpoints for user daily inspiration persistence.
#
# These endpoints are used by the web app client to:
#   1. POST /v1/daily-inspirations - Persist received inspirations (encrypted) to Directus
#   2. GET  /v1/daily-inspirations - Fetch persisted inspirations on login (sync)
#   3. POST /v1/daily-inspirations/{id}/opened - Mark an inspiration as opened
#
# Architecture:
#   - All content fields are encrypted client-side before reaching this API
#   - The server only stores opaque encrypted blobs and hashed identifiers
#   - Used to solve "vanished on reload" and "re-login hours later" problems
#   - Video embeds are stored in the standard embeds collection separately
#   - This collection tracks metadata needed to restore the carousel on login
#
# Authentication: required (session cookie)
#
# See: docs/architecture/daily_inspiration_persistence.md

import logging
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1",
    tags=["Daily Inspirations"],
)


# ─── Service dependencies ─────────────────────────────────────────────────────

def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, "directus_service"):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


# ─── Request/Response models ──────────────────────────────────────────────────

class DailyInspirationSyncItem(BaseModel):
    """A single encrypted daily inspiration to persist."""

    daily_inspiration_id: str = Field(..., description="Client-generated UUID for this inspiration")
    embed_id: Optional[str] = Field(None, description="UUID of the associated embed (video), if any")
    encrypted_phrase: str = Field(..., description="Inspiration phrase encrypted with master key")
    encrypted_assistant_response: str = Field(
        ..., description="First assistant message content encrypted with master key"
    )
    encrypted_title: str = Field(..., description="Chat title encrypted with master key")
    encrypted_category: str = Field(..., description="Category name encrypted with master key")
    encrypted_icon: Optional[str] = Field(None, description="Icon name encrypted with master key")
    is_opened: bool = Field(False, description="Whether user has started a chat from this inspiration")
    opened_chat_id: Optional[str] = Field(None, description="Hashed chat ID created from this inspiration")
    generated_at: int = Field(..., description="Unix timestamp when the inspiration was generated")
    content_type: str = Field("video", description="Content type (currently always 'video')")


class SyncInspirationsRequest(BaseModel):
    """Request body for POST /v1/daily-inspirations."""

    inspirations: List[DailyInspirationSyncItem] = Field(
        ..., description="List of inspirations to upsert (1-3)"
    )


class MarkOpenedRequest(BaseModel):
    """Request body for POST /v1/daily-inspirations/{id}/opened."""

    opened_chat_id: Optional[str] = Field(
        None, description="Hashed chat ID created from this inspiration"
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/daily-inspirations")
@limiter.limit("30/minute")
async def sync_daily_inspirations(
    request: Request,
    body: SyncInspirationsRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """
    Persist one or more encrypted daily inspirations to Directus.

    Called by the client immediately after receiving a `daily_inspiration` WebSocket event.
    Uses upsert semantics — safe to call multiple times with the same inspiration_ids.

    Returns the count of successfully stored inspirations.
    """
    if not body.inspirations:
        raise HTTPException(status_code=400, detail="No inspirations provided")

    if len(body.inspirations) > 3:
        raise HTTPException(status_code=400, detail="At most 3 inspirations per batch")

    user_id = current_user.id
    stored_count = 0

    for item in body.inspirations:
        result = await directus_service.user_daily_inspiration.upsert_inspiration(
            user_id=user_id,
            inspiration=item.model_dump(),
        )
        if result is not None:
            stored_count += 1
        else:
            logger.warning(
                "[daily_inspirations_api] Failed to upsert inspiration %s for user %s…",
                item.daily_inspiration_id,
                user_id[:8],
            )

    logger.info(
        "[daily_inspirations_api] Stored %d/%d inspirations for user %s…",
        stored_count,
        len(body.inspirations),
        user_id[:8],
    )

    return {"stored": stored_count, "total": len(body.inspirations)}


@router.get("/daily-inspirations")
@limiter.limit("60/minute")
async def get_daily_inspirations(
    request: Request,
    since: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """
    Fetch persisted daily inspirations for the authenticated user.

    Called during login sync (phased sync) to restore the carousel state.
    The client uses this to populate the store from Directus when no
    personalized inspirations are in IndexedDB (e.g. first time on a device).

    Query params:
      since (optional): Unix timestamp — only return inspirations generated at or after this time.

    Returns a list of inspiration records (encrypted content included).
    """
    user_id = current_user.id
    inspirations = await directus_service.user_daily_inspiration.get_user_inspirations(
        user_id=user_id,
        since_timestamp=since,
        limit=10,  # Max 10 (3 per day × ~3 days)
    )

    logger.debug(
        "[daily_inspirations_api] Returning %d inspirations for user %s…",
        len(inspirations),
        user_id[:8],
    )

    return {"inspirations": inspirations}


@router.post("/daily-inspirations/{daily_inspiration_id}/opened")
@limiter.limit("30/minute")
async def mark_inspiration_opened(
    request: Request,
    daily_inspiration_id: str,
    body: MarkOpenedRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """
    Mark a daily inspiration as opened (user has started a chat from it).

    Called when the user clicks the banner and a chat is created.
    The inspiration remains visible in the carousel but the next unopened one
    becomes the default.
    """
    user_id = current_user.id
    success = await directus_service.user_daily_inspiration.mark_opened(
        user_id=user_id,
        daily_inspiration_id=daily_inspiration_id,
        opened_chat_id=body.opened_chat_id,
    )

    if not success:
        logger.warning(
            "[daily_inspirations_api] mark_opened failed for inspiration %s, user %s…",
            daily_inspiration_id,
            user_id[:8],
        )
        # Return 200 anyway — client can ignore sync failures (local state is the truth)

    return {"success": success, "daily_inspiration_id": daily_inspiration_id}
