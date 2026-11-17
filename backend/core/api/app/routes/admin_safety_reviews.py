"""
Admin review of safety-suspended accounts (strike 3 waits here).

Surface: first-party client only (web admin settings), session auth plus require_admin,
no developer-API access; not on Caddy's public allowlist.

An admin lists the accounts pending review and then restores (lifts the
suspension, clears strikes, sends an apology email) or deletes (queues the regular
deletion with refunds). Deletion happens only through this admin decision.
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.admin import require_admin
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_cache_service
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.shared.python_utils.image_safety import safety_review
from backend.shared.python_utils.image_safety.account_suspension import (
    STATE_PENDING_REVIEW,
    delete_suspended_account_by_admin,
    list_pending_reviews,
    restore_suspended_account,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/safety-reviews", tags=["Admin"])

async def _require_pending_review(directus_service: DirectusService, user_id: str) -> None:
    success, profile, _ = await directus_service.get_user_profile(user_id)
    if not success or not profile:
        raise HTTPException(status_code=404, detail="User not found")
    if profile.get("safety_suspension_state") != STATE_PENDING_REVIEW:
        raise HTTPException(status_code=409, detail="Account is not pending a safety review")

@router.get("")
async def list_reviews(
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, List[Dict[str, Any]]]:
    """Accounts waiting for an admin decision with check, scores, plan, age and appeals.

    Request text appears only for appeals whose user consented to share it.
    """
    pending = await list_pending_reviews(directus_service)
    return {"pending": [await safety_review.review_detail(directus_service, user) for user in pending]}


class AskUserRequest(BaseModel):
    """Admin question to the user (sent by email)."""

    question: str = Field(..., min_length=1, max_length=1000)


@router.post("/{user_id}/ask")
async def ask(
    user_id: str,
    body: AskUserRequest,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, str]:
    """Ask the user for more information; the user is emailed and can answer in the appeal."""
    await _require_pending_review(directus_service, user_id)
    try:
        await safety_review.ask_user(directus_service=directus_service, user_id=user_id, question=body.question)
    except safety_review.AppealError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    logger.warning(f"[SafetyReview] admin {admin_user.id[:8]} asked user {user_id[:8]} for information")
    return {"result": "question_sent"}

@router.post("/{user_id}/restore")
async def restore(
    user_id: str,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, str]:
    """Lift the suspension, clear the strikes and send the apology email."""
    await _require_pending_review(directus_service, user_id)
    await restore_suspended_account(user_id=user_id, directus_service=directus_service, cache_service=cache_service)
    logger.warning(f"[SafetyReview] admin {admin_user.id[:8]} restored user {user_id[:8]}")
    return {"result": "restored"}

@router.post("/{user_id}/delete")
async def delete(
    user_id: str,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, str]:
    """Queue the regular account deletion with refunds (admin decision)."""
    await _require_pending_review(directus_service, user_id)
    await delete_suspended_account_by_admin(
        user_id=user_id, reason="admin_safety_review", directus_service=directus_service
    )
    logger.warning(f"[SafetyReview] admin {admin_user.id[:8]} deleted user {user_id[:8]}")
    return {"result": "deletion_queued"}
