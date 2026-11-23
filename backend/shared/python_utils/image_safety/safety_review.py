"""
Appeals and the scheduled review rules for safety suspensions.

- A suspended user cannot hold a session, so the credentials verified at login (or the
  403 of a still valid session) yield a short-lived signed appeal token that opens only
  the appeal routes for that one account.
- An appeal carries an explanation (at most 1,000 characters) and, only with the user's
  consent, the plaintext of the flagged requests that the user's own device decrypted.
  The optional photo is deleted at the decision.
- Deadlines: 14 days to appeal, decision within 7 days of an appeal, a reminder to the
  admin after 48 hours of an undecided review, automatic restore of an unclear case
  (pending review) that was not appealed within 14 days.
- Retention: the strike and suspension record is purged 90 days after the case closes,
  appeals 6 months after the decision.
"""

import hashlib
import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

APPEAL_WINDOW_DAYS = 14
DECISION_DAYS = 7
REMINDER_AFTER_HOURS = 48
CASE_RETENTION_DAYS = 90
APPEAL_RETENTION_DAYS = 183
EXPLANATION_MAX_CHARS = 1000
APPEAL_TOKEN_TTL_SECONDS = 3600
APPEALS_COLLECTION = "safety_appeals"
STATUS_OPEN = "open"
STATUS_NEEDS_INFORMATION = "needs_information"
STATUS_DECIDED = "decided"
ASK_EMAIL_TASK = "app.tasks.email_tasks.safety_review_email_task.send_safety_more_information_email"
_PURPOSE = "safety_appeal"


class AppealError(Exception):
    """A rejected appeal action with an HTTP-style status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _secret() -> bytes:
    secret = os.getenv("INTERNAL_API_SHARED_TOKEN", "")
    if not secret:
        raise RuntimeError("INTERNAL_API_SHARED_TOKEN is not configured; appeal tokens cannot be signed")
    return secret.encode()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def create_appeal_token(user_id: str, now: Optional[float] = None) -> str:
    """Signed token "<user_id>:<expiry>:<sig>" that opens only this account's appeal routes."""
    expiry = int((now if now is not None else time.time()) + APPEAL_TOKEN_TTL_SECONDS)
    payload = f"{_PURPOSE}:{user_id}:{expiry}"
    return f"{user_id}:{expiry}:{_sign(payload)}"


def verify_appeal_token(token: str, now: Optional[float] = None) -> str:
    """The user id of a valid appeal token; raises AppealError(401) otherwise."""
    parts = (token or "").split(":")
    if len(parts) != 3 or not parts[1].isdigit():
        raise AppealError(401, "Invalid appeal token")
    user_id, expiry, signature = parts
    if not hmac.compare_digest(signature, _sign(f"{_PURPOSE}:{user_id}:{expiry}")):
        raise AppealError(401, "Invalid appeal token")
    if int(expiry) < (now if now is not None else time.time()):
        raise AppealError(401, "Appeal token expired")
    return user_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _appeals_for(directus_service: Any, user_id: str) -> List[Dict[str, Any]]:
    return await directus_service.get_items(APPEALS_COLLECTION, params={
        "filter[user_id][_eq]": user_id, "sort": "-created_at", "limit": -1,
    }, admin_required=True) or []


async def get_open_appeal(directus_service: Any, user_id: str) -> Optional[Dict[str, Any]]:
    """The latest appeal that has no decision yet, or None."""
    for appeal in await _appeals_for(directus_service, user_id):
        if appeal.get("status") != STATUS_DECIDED:
            return appeal
    return None


def validate_appeal_text(text: str) -> str:
    """Trimmed explanation; 1 to 1,000 characters."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise AppealError(422, "An explanation is required")
    if len(cleaned) > EXPLANATION_MAX_CHARS:
        raise AppealError(422, f"The explanation must be at most {EXPLANATION_MAX_CHARS} characters")
    return cleaned


async def submit_appeal(
    *, directus_service: Any, user: Dict[str, Any], explanation: str, consent_share_requests: bool,
    flagged_requests: Optional[List[str]], attachment_data_url: Optional[str],
) -> Dict[str, Any]:
    """Store an appeal for a suspended account inside the 14-day window."""
    from .account_suspension import STATE_NONE

    state = user.get("safety_suspension_state") or STATE_NONE
    if state == STATE_NONE:
        raise AppealError(409, "The account is not suspended")
    started = _parse(user.get("safety_suspension_started_at"))
    if started is not None and _now() > started + timedelta(days=APPEAL_WINDOW_DAYS):
        raise AppealError(409, "The 14-day appeal period has ended")
    if await get_open_appeal(directus_service, user["id"]) is not None:
        raise AppealError(409, "An appeal is already open")
    text = validate_appeal_text(explanation)
    if flagged_requests and not consent_share_requests:
        raise AppealError(422, "Consent is required to share the flagged requests")
    if attachment_data_url and not consent_share_requests:
        raise AppealError(422, "Consent is required to share the attached photo")
    if flagged_requests and len(flagged_requests) > 20:
        raise AppealError(422, "Too many flagged requests")
    now = _now()
    row = {
        "id": str(uuid.uuid4()), "user_id": user["id"], "status": STATUS_OPEN,
        "explanation": text, "consent_share_requests": bool(consent_share_requests),
        "flagged_requests": [r[:4000] for r in flagged_requests] if consent_share_requests and flagged_requests else None,
        "attachment_data_url": attachment_data_url if consent_share_requests else None,
        "created_at": now.isoformat(), "decision_due_at": (now + timedelta(days=DECISION_DAYS)).isoformat(),
    }
    created, _ = await directus_service.create_item(APPEALS_COLLECTION, row, admin_required=True)
    if not created:
        raise RuntimeError("Could not store the safety appeal")
    return {"id": row["id"], "status": row["status"], "decision_due_at": row["decision_due_at"]}


async def reply_to_question(*, directus_service: Any, user_id: str, reply: str) -> None:
    """The user's answer to the admin's question; reopens the appeal."""
    appeal = await get_open_appeal(directus_service, user_id)
    if appeal is None or appeal.get("status") != STATUS_NEEDS_INFORMATION:
        raise AppealError(409, "There is no open question")
    text = validate_appeal_text(reply)
    if not await directus_service.update_item(
        APPEALS_COLLECTION, appeal["id"], {"user_reply": text, "status": STATUS_OPEN}, admin_required=True
    ):
        raise RuntimeError("Could not store the reply")


async def ask_user(*, directus_service: Any, user_id: str, question: str) -> None:
    """Admin asks the user for more information; sends the user an email."""
    from backend.core.api.app.tasks.celery_config import app

    text = validate_appeal_text(question)
    appeal = await get_open_appeal(directus_service, user_id)
    if appeal is None:
        created, _ = await directus_service.create_item(APPEALS_COLLECTION, {
            "id": str(uuid.uuid4()), "user_id": user_id, "status": STATUS_NEEDS_INFORMATION,
            "explanation": "(opened by the admin question)", "consent_share_requests": False,
            "admin_question": text, "created_at": _now().isoformat(),
            "decision_due_at": (_now() + timedelta(days=DECISION_DAYS)).isoformat(),
        }, admin_required=True)
        if not created:
            raise RuntimeError("Could not store the admin question")
    elif not await directus_service.update_item(
        APPEALS_COLLECTION, appeal["id"], {"admin_question": text, "status": STATUS_NEEDS_INFORMATION}, admin_required=True
    ):
        raise RuntimeError("Could not store the admin question")
    app.send_task(name=ASK_EMAIL_TASK, kwargs={"user_id": user_id, "question": text}, queue="email")


async def close_appeals(directus_service: Any, user_id: str, decision: str) -> None:
    """Record the decision on open appeals and delete the attached photo; schedules the 6-month purge."""
    now = _now()
    for appeal in await _appeals_for(directus_service, user_id):
        if appeal.get("status") == STATUS_DECIDED:
            continue
        await directus_service.update_item(APPEALS_COLLECTION, appeal["id"], {
            "status": STATUS_DECIDED, "decision": decision, "decided_at": now.isoformat(),
            "attachment_data_url": None,
            "purge_after": (now + timedelta(days=APPEAL_RETENTION_DAYS)).isoformat(),
        }, admin_required=True)


async def review_detail(directus_service: Any, user: Dict[str, Any]) -> Dict[str, Any]:
    """Admin view of one case: check, scores, account facts and the appeal.

    Request text appears only when the user consented in an appeal; a photo only when the
    user attached it again.
    """
    appeals = await _appeals_for(directus_service, user["id"])
    shown = [{
        "id": a["id"], "status": a.get("status"), "explanation": a.get("explanation"),
        "consent_share_requests": bool(a.get("consent_share_requests")),
        "flagged_requests": a.get("flagged_requests") if a.get("consent_share_requests") else None,
        "attachment_data_url": a.get("attachment_data_url") if a.get("consent_share_requests") else None,
        "admin_question": a.get("admin_question"), "user_reply": a.get("user_reply"),
        "decision": a.get("decision"), "created_at": a.get("created_at"), "decision_due_at": a.get("decision_due_at"),
    } for a in appeals]
    decision = user.get("safety_decision") or {}
    return {
        "user_id": user["id"],
        "state": user.get("safety_suspension_state"),
        "category": user.get("safety_suspension_category"),
        "started_at": user.get("safety_suspension_started_at"),
        "check": {"stage": decision.get("stage"), "reason": decision.get("reason")},
        "scores": decision.get("scores") or {},
        "threshold": decision.get("threshold"),
        "purpose_verdict": decision.get("purpose_verdict"),
        "account_created": user.get("signup_started_at"),
        "plan": user.get("subscription_status") or "free",
        "earlier_strikes": decision.get("earlier_strikes"),
        "appeals": shown,
    }


async def remind_stale_reviews(directus_service: Any, alert: Any) -> int:
    """Remind the admin of reviews undecided for 48 hours; at most once per 48 hours per case."""
    from .account_suspension import list_pending_reviews

    reminded = 0
    cutoff = _now() - timedelta(hours=REMINDER_AFTER_HOURS)
    for user in await list_pending_reviews(directus_service):
        started = _parse(user.get("safety_suspension_started_at"))
        last = _parse(user.get("safety_review_reminded_at")) or started
        if last is None or last > cutoff:
            continue
        await alert(f"Safety review reminder: user {user['id'][:8]} ({user.get('safety_suspension_category')}) "
                    f"has waited more than {REMINDER_AFTER_HOURS} hours for a decision")
        await directus_service.update_user(user["id"], {"safety_review_reminded_at": _now().isoformat()})
        reminded += 1
    return reminded


async def auto_restore_unappealed(directus_service: Any, cache_service: Any) -> int:
    """Restore unclear cases (pending review) with no appeal 14 days after the suspension."""
    from .account_suspension import list_pending_reviews, restore_suspended_account

    restored = 0
    cutoff = _now() - timedelta(days=APPEAL_WINDOW_DAYS)
    for user in await list_pending_reviews(directus_service):
        started = _parse(user.get("safety_suspension_started_at"))
        if started is None or started > cutoff:
            continue
        if await _appeals_for(directus_service, user["id"]):
            continue
        await restore_suspended_account(user_id=user["id"], directus_service=directus_service, cache_service=cache_service)
        restored += 1
    return restored


async def purge_closed_cases(directus_service: Any) -> Dict[str, int]:
    """Delete decided appeals past their purge date and strike records 90 days after closing."""
    now = _now()
    appeals = await directus_service.get_items(APPEALS_COLLECTION, params={
        "filter[purge_after][_lt]": now.isoformat(), "fields": "id", "limit": -1,
    }, admin_required=True) or []
    for appeal in appeals:
        await directus_service.delete_item(APPEALS_COLLECTION, appeal["id"], admin_required=True)
    cutoff = (now - timedelta(days=CASE_RETENTION_DAYS)).isoformat()
    users = await directus_service.get_items("directus_users", params={
        "filter[safety_suspension_closed_at][_lt]": cutoff, "fields": "id", "limit": -1,
    }) or []
    for user in users:
        await directus_service.update_user(user["id"], {
            "safety_suspension_category": None, "safety_suspension_started_at": None,
            "safety_suspension_closed_at": None, "safety_decision": None,
            "safety_flagged_message_ids": None, "safety_review_reminded_at": None,
        })
    return {"appeals": len(appeals), "cases": len(users)}
