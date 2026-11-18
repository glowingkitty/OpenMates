"""
Appeal of a safety suspension by the suspended user.

Classification: first-party client surface only (web/CLI/SDK/native). A suspended user has no
session, so the routes accept the short-lived appeal token issued at login (credentials
verified) or in the 403 of a still valid session. The token names exactly one account, so a
user can only read and appeal their own case. Every route is rate limited. Not for the
developer API and not on Caddy's public allowlist.

The flagged requests are decrypted on the user's own device and submitted as plaintext only
with explicit consent; the server never decrypts chat content.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.shared.python_utils.image_safety import safety_review
from backend.shared.python_utils.image_safety.account_suspension import active_suspension, suspension_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/safety/appeal", tags=["Safety"])


class AppealRequest(BaseModel):
    """Appeal form: explanation plus consent to share only the flagged requests."""

    explanation: str = Field(..., min_length=1, max_length=safety_review.EXPLANATION_MAX_CHARS)
    consent_share_requests: bool
    flagged_requests: Optional[List[str]] = None
    attachment_data_url: Optional[str] = Field(None, max_length=8_000_000)


class ReplyRequest(BaseModel):
    """Answer to an admin question."""

    reply: str = Field(..., min_length=1, max_length=safety_review.EXPLANATION_MAX_CHARS)


async def appeal_user(
    authorization: Optional[str] = Header(None),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """The suspended user named by the bearer appeal token (own account only)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Appeal token required")
    try:
        user_id = safety_review.verify_appeal_token(authorization[7:].strip())
    except safety_review.AppealError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    success, profile, _ = await directus_service.get_user_profile(user_id)
    if not success or not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return {**profile, "id": user_id}


@router.get("")
@limiter.limit("30/minute")
async def appeal_status(
    request: Request,
    user: Dict[str, Any] = Depends(appeal_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Reason (category level), deadlines and the state of the user's appeal."""
    suspension = active_suspension(user)
    appeal = await safety_review.get_open_appeal(directus_service, user["id"])
    return {
        "suspended": suspension is not None,
        "state": suspension["state"] if suspension else "none",
        "category": user.get("safety_suspension_category"),
        "message": suspension_message(suspension, user.get("language")) if suspension else None,
        "started_at": user.get("safety_suspension_started_at"),
        "appeal_window_days": safety_review.APPEAL_WINDOW_DAYS,
        "flagged_message_ids": user.get("safety_flagged_message_ids") or [],
        "appeal": {
            "status": appeal.get("status"),
            "decision_due_at": appeal.get("decision_due_at"),
            "admin_question": appeal.get("admin_question"),
        } if appeal else None,
    }


@router.post("")
@limiter.limit("5/hour")
async def submit(
    request: Request,
    body: AppealRequest,
    user: Dict[str, Any] = Depends(appeal_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Submit the appeal; the flagged requests need explicit consent."""
    try:
        return await safety_review.submit_appeal(
            directus_service=directus_service, user=user, explanation=body.explanation,
            consent_share_requests=body.consent_share_requests, flagged_requests=body.flagged_requests,
            attachment_data_url=body.attachment_data_url,
        )
    except safety_review.AppealError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/reply")
@limiter.limit("10/hour")
async def reply(
    request: Request,
    body: ReplyRequest,
    user: Dict[str, Any] = Depends(appeal_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, str]:
    """Answer the admin's question."""
    try:
        await safety_review.reply_to_question(directus_service=directus_service, user_id=user["id"], reply=body.reply)
    except safety_review.AppealError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"result": "reply_stored"}
