"""
Account suspension for safety strikes: the one place that decides, stores and lifts it.

Accounts are never deleted automatically for safety strikes. The ladder shared by
every strike source (image generation, editing, video, uploaded images):

- strike 1: warning only;
- strike 2: suspension for 7 days, then the account is active again by itself;
- strike 3: suspension until an admin review, which ends in restore or deletion.

The suspension is stored on the Directus user record (safety_suspension_* fields)
and mirrored in the cached user record. Only an admin decision deletes an account
(`delete_suspended_account_by_admin`). Admin alerts carry the category, the
deciding check with its numeric scores, account age, plan and earlier strikes,
never the image and never the request text.
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .strike_counter import BAN_THRESHOLD, get_strike_counter

logger = logging.getLogger(__name__)

STATE_NONE = "none"
STATE_TEMPORARY = "temporary"
STATE_PENDING_REVIEW = "pending_review"
TEMPORARY_SUSPENSION_DAYS = 7
TEMPORARY_SUSPENSION_STRIKE = 2

ALERT_QUEUE = "email"
ALERT_TASK = "app.tasks.email_tasks.alert_notification_email_task.send_alert_notification"
SUSPENSION_EMAIL_TASK = "app.tasks.email_tasks.safety_review_email_task.send_safety_suspension_email"
RESTORE_EMAIL_TASK = "app.tasks.email_tasks.safety_account_restored_email_task.send_safety_account_restored_email"
_SAFE_REASON = re.compile(r"[^A-Za-z0-9_.=<>:,\- ]")

class AccountSuspendedError(Exception):
    """Raised when a suspended account tries to log in or use the API."""

    def __init__(
        self, state: str, until: Optional[datetime], message: str,
        user_id: Optional[str] = None, category: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.user_id = user_id
        self.category = category
        self.state = state
        self.until = until
        self.message = message

    def detail(self) -> Dict[str, Any]:
        """Structured API detail; the message is already in the user's language."""
        from .safety_review import create_appeal_token

        return {
            "code": "account_suspended",
            "state": self.state,
            "until": self.until.isoformat() if self.until else None,
            "message": self.message,
            "category": self.category,
            "appeal_token": create_appeal_token(self.user_id) if self.user_id else None,
        }

def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def active_suspension(user: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The suspension that currently blocks the account, or None.

    A temporary suspension whose end has passed no longer blocks, so the account
    is active again without any job having to run.
    """
    state = (user or {}).get("safety_suspension_state") or STATE_NONE
    if state == STATE_PENDING_REVIEW:
        return {"state": state, "until": None}
    if state == STATE_TEMPORARY:
        until = _parse_timestamp(user.get("safety_suspended_until"))
        if until is not None and until > (now or datetime.now(timezone.utc)):
            return {"state": state, "until": until}
    return None

def _translate(key: str, language: str) -> str:
    from .strike_policy import _translate as translate

    return translate(key, language)

def suspension_message(suspension: Dict[str, Any], language: Optional[str]) -> str:
    """Localized message for a suspended account; never the 'wrong login data' text."""
    lang = language or "en"
    if suspension["state"] == STATE_PENDING_REVIEW:
        return _translate("suspended_pending_review", lang)
    return _translate("suspended_until", lang).replace("{date}", suspension["until"].strftime("%Y-%m-%d"))

def raise_if_suspended(user: Optional[Dict[str, Any]]) -> None:
    """The shared check for login, API and WebSocket use; raises AccountSuspendedError."""
    suspension = active_suspension(user)
    if suspension is None:
        return
    raise AccountSuspendedError(
        suspension["state"], suspension["until"],
        suspension_message(suspension, (user or {}).get("language")),
        user_id=(user or {}).get("id"),
        category=(user or {}).get("safety_suspension_category"),
    )

def _flatten_numbers(prefix: str, value: Any, out: Dict[str, Any]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out[prefix] = value
    elif isinstance(value, dict):
        for key, inner in value.items():
            _flatten_numbers(f"{prefix}.{key}" if prefix else str(key), inner, out)

def rejection_decision(rejection: Any) -> Dict[str, Any]:
    """The deciding check of a SafetyRejection as stage, reason code and numeric scores only."""
    scores: Dict[str, Any] = {}
    _flatten_numbers("sightengine", rejection.sightengine_audit, scores)
    _flatten_numbers("vlm", rejection.vlm_audit, scores)
    return {"stage": rejection.stage, "reason": rejection.reason, "scores": scores}

async def _store(directus_service: Any, cache_service: Any, user_id: str, fields: Dict[str, Any]) -> None:
    if not await directus_service.update_user(user_id, fields):
        raise RuntimeError(f"Could not persist safety suspension fields for user {user_id[:8]}")
    await cache_service.delete(f"user_profile:{user_id}")

def _score_summary(decision: Optional[Dict[str, Any]]) -> str:
    """Numeric scores and the threshold of the deciding check; never free text."""
    if not decision:
        return "not available"
    parts = []
    for key in ("stage", "check"):
        if decision.get(key):
            parts.append(f"{key}={_SAFE_REASON.sub('', str(decision[key]))[:60]}")
    if decision.get("reason"):
        parts.append(f"reason={_SAFE_REASON.sub('', str(decision['reason']))[:200]}")
    scores = decision.get("scores") or {}
    numeric = {k: v for k, v in scores.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if numeric:
        parts.append("scores=" + ", ".join(f"{_SAFE_REASON.sub('', str(k))[:40]}={v}" for k, v in sorted(numeric.items())))
    if isinstance(decision.get("threshold"), (int, float)):
        parts.append(f"threshold={decision['threshold']}")
    return "; ".join(parts) or "not available"

def build_admin_alert(
    *, user_id: str, user: Dict[str, Any], state: str, category: str,
    strike_count: int, decision: Optional[Dict[str, Any]],
) -> str:
    """Alert text for the admin: no image, no request text."""
    created = user.get("date_created") or user.get("signup_started_at") or "unknown"
    return "\n".join([
        f"Safety suspension ({state}) for user {user_id[:8]}",
        f"Category: {_SAFE_REASON.sub('', category)[:80]}",
        f"Deciding check: {_score_summary(decision)}",
        f"Account created: {created}",
        f"Plan: {user.get('subscription_status') or 'free'}",
        f"Earlier strikes: {max(strike_count - 1, 0)}",
    ])

async def alert_admin(text: str) -> None:
    """Discord plus email to the admin; delivery problems are logged, never raised."""
    from backend.core.api.app.services.operational_monitoring import resolve_operations_discord_destination
    from backend.core.api.app.tasks.celery_config import app
    from backend.shared.python_utils.discord_webhook import post_discord_message

    environment = "production" if os.getenv("SERVER_ENVIRONMENT", "").strip().lower() == "production" else "development"
    destination = resolve_operations_discord_destination(environment, os.environ)
    if not await post_discord_message(destination["url"], content=text, username="Safety suspensions"):
        logger.error("[SafetyStrikes] Discord admin alert was not delivered")
    admin_email = os.getenv("SERVER_OWNER_EMAIL") or os.getenv("ADMIN_NOTIFY_EMAIL")
    if not admin_email:
        logger.error("[SafetyStrikes] No admin email configured; email alert skipped")
        return
    app.send_task(
        name=ALERT_TASK,
        kwargs={
            "admin_email": admin_email, "alertname": "SafetySuspension", "status": "firing",
            "severity": "warning", "summary": text.splitlines()[0],
            "starts_at": datetime.now(timezone.utc).isoformat(), "description": text,
        },
        queue=ALERT_QUEUE,
    )

async def end_all_sessions(*, user_id: str, directus_service: Any, cache_service: Any) -> None:
    """Sign the suspended account out everywhere, as logout-all does.

    Revokes every OpenMates session token, removes the Directus sessions and
    pushes ``force_logout`` so open clients leave at once instead of on their
    next token check. Signing in again then shows the suspension screen.
    """
    from backend.core.api.app.routes.auth_routes.auth_sessions import _broadcast_force_logout
    from backend.core.api.app.services.session_security_state import revoke_all_user_sessions

    revoked = await revoke_all_user_sessions(directus_service, cache_service, user_id)
    await directus_service.logout_all_sessions(user_id)
    await _broadcast_force_logout(cache_service, user_id, "account_suspended")
    logger.warning(f"[SafetyStrikes] user={user_id[:8]} signed out of {revoked} session(s)")


async def suspend_account_for_strikes(
    *, user_id: str, strike_count: int, category: str, directus_service: Any, cache_service: Any,
    decision: Optional[Dict[str, Any]] = None, flagged_message_ids: Optional[list] = None,
) -> Optional[Dict[str, Any]]:
    """Apply the ladder for a recorded strike; returns the suspension or None for strike 1."""
    if strike_count < TEMPORARY_SUSPENSION_STRIKE:
        return None
    from backend.core.api.app.tasks.celery_config import app

    now = datetime.now(timezone.utc)
    if strike_count >= BAN_THRESHOLD:
        state, until = STATE_PENDING_REVIEW, None
    else:
        state, until = STATE_TEMPORARY, now + timedelta(days=TEMPORARY_SUSPENSION_DAYS)
    fields = {
        "safety_suspension_state": state,
        "safety_suspended_until": until.isoformat() if until else None,
        "safety_suspension_category": category,
        "safety_suspension_started_at": now.isoformat(),
        "safety_suspension_closed_at": None,
        "safety_review_reminded_at": None,
        "safety_decision": decision,
        "safety_flagged_message_ids": [str(i) for i in (flagged_message_ids or [])],
    }
    logger.warning(f"[SafetyStrikes] user={user_id[:8]} strike {strike_count}; suspension={state}")
    await _store(directus_service, cache_service, user_id, fields)
    await end_all_sessions(user_id=user_id, directus_service=directus_service, cache_service=cache_service)
    user = await cache_service.get_user_by_id(user_id) or {}
    await alert_admin(build_admin_alert(
        user_id=user_id, user=user, state=state, category=category,
        strike_count=strike_count, decision=decision,
    ))
    app.send_task(
        name=SUSPENSION_EMAIL_TASK,
        kwargs={"user_id": user_id, "state": state, "until": until.isoformat() if until else None},
        queue=ALERT_QUEUE,
    )
    return {"state": state, "until": until}

# The service role may not read directus_users.date_created (Directus 403);
# signup_started_at is the readable account-creation time.
REVIEW_FIELDS = (
    "id,safety_suspension_category,safety_suspension_started_at,safety_decision,"
    "safety_review_reminded_at,signup_started_at,subscription_status"
)

async def list_pending_reviews(directus_service: Any) -> list:
    """Accounts waiting for an admin decision (state pending_review)."""
    return await directus_service.get_items("directus_users", params={
        "filter[safety_suspension_state][_eq]": STATE_PENDING_REVIEW,
        "fields": REVIEW_FIELDS,
        "limit": -1,
    })

async def restore_suspended_account(*, user_id: str, directus_service: Any, cache_service: Any) -> None:
    """Admin restore: lift the suspension, clear the strikes and send the apology email."""
    from backend.core.api.app.tasks.celery_config import app

    from .safety_review import close_appeals

    await _store(directus_service, cache_service, user_id, {
        "safety_suspension_state": STATE_NONE,
        "safety_suspended_until": None,
        "safety_suspension_closed_at": datetime.now(timezone.utc).isoformat(),
    })
    await close_appeals(directus_service, user_id, "restored")
    await get_strike_counter(cache_service).reset(user_id)
    app.send_task(name=RESTORE_EMAIL_TASK, kwargs={"user_id": user_id}, queue=ALERT_QUEUE)
    logger.warning(f"[SafetyStrikes] user={user_id[:8]} restored by admin decision")

async def delete_suspended_account_by_admin(
    *, user_id: str, reason: str, directus_service: Any = None
) -> None:
    """Admin deletion: the only way a safety strike can end in deletion, with refunds."""
    from backend.core.api.app.tasks.celery_config import app

    from .safety_review import close_appeals

    logger.warning(f"[SafetyStrikes] user={user_id[:8]} deletion decided by admin")
    if directus_service is not None:
        await directus_service.logout_all_sessions(user_id)
        await close_appeals(directus_service, user_id, "deleted")
    app.send_task(
        name="delete_user_account",
        kwargs={
            "user_id": user_id,
            "deletion_type": "policy_violation",
            "reason": reason,
            "ip_address": None,
            "device_fingerprint": None,
            "refund_invoices": True,
            "email_encryption_key": None,
        },
        queue="user_init",
    )
